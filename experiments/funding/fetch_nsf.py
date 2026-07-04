# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch NSF awards for AI safety-relevant programs, emit raw/normalized_nsf.json.

Queries (quoted-phrase search, field-relevant slice):
  1. "Safe Learning-Enabled Systems"   — SLES program awards (~7)
  2. "AI safety"                        — broad AI safety keyword (~25-100)
  3. "trustworthy artificial intelligence" — ~37 awards

All three are deduped by award id. Title/program keyword filter drops obvious
non-AI false positives (civil engineering, biology, etc.).
Program officers captured as person records (distinct poName).
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CACHE = RAW / "cache"
RAW.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)
OUT = RAW / "normalized_nsf.json"

NSF_API = "https://api.nsf.gov/services/v1/awards.json"
FUNDER_TOTAL_SOURCE = (
    "https://resources.research.gov/common/webapi/awardapisearch-v1.htm"
)

PRINT_FIELDS = ",".join(
    [
        "id",
        "title",
        "awardeeName",
        "fundsObligatedAmt",
        "estimatedTotalAmt",
        "startDate",
        "expDate",
        "poName",
        "fundProgramName",
    ]
)

QUERIES = [
    '"Safe Learning-Enabled Systems"',
    '"AI safety"',
    '"trustworthy artificial intelligence"',
]

# Title/program must contain at least one of these (case-insensitive) to pass the filter.
# Broad enough to keep genuine AI safety work; narrow enough to drop civil/bio/etc. false positives.
AI_KEYWORDS = [
    "artificial intelligence",
    "machine learning",
    "learning-enabled",
    "language model",
    "neural network",
    "deep learning",
    "trustworthy ai",
    "ai safety",
    "safe learning",
    "sles",
    "llm",
    " ai ",  # word-boundary AI (avoids matching "AISI", "rail", etc.)
]

HEADERS = {"User-Agent": "Mozilla/5.0 (funding-pipeline; alexloftus2004@gmail.com)"}
client = httpx.Client(timeout=30, headers=HEADERS)


def cached_get(url: str, key: str, params: dict | None = None) -> tuple[dict, bool]:
    """GET JSON with disk cache + 429/5xx backoff. Returns (parsed_json, cache_hit).
    On persistent failure uses stale cache with STALE warning; never crashes.
    """
    cache_path = CACHE / key
    if cache_path.exists():
        return json.loads(cache_path.read_bytes()), True

    last_err: Exception | None = None
    for attempt in range(6):
        try:
            r = client.get(url, params=params)
            if r.status_code == 200:
                cache_path.write_bytes(r.content)
                return r.json(), False
            if r.status_code in (429, 500, 502, 503):
                wait = 2.0 * (attempt + 1)
                print(
                    f"  [{r.status_code}] backing off {wait:.0f}s (attempt {attempt+1})",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            last_err = ValueError(f"HTTP {r.status_code}")
            break
        except httpx.HTTPError as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))

    stale = sorted(CACHE.glob(f"{key.rsplit('.', 1)[0]}*"))
    if stale:
        print(f"  STALE fallback: {stale[-1].name}", file=sys.stderr)
        return json.loads(stale[-1].read_bytes()), True

    raise RuntimeError(f"All retries failed for {url}: {last_err}")


def paginate_query(keyword: str) -> list[dict]:
    """Fetch all pages for one keyword query; returns raw award dicts."""
    awards: list[dict] = []
    offset = 1
    page = 0
    safe_key = keyword.replace('"', "").replace(" ", "_").lower()[:40]

    while True:
        key = f"nsf_{safe_key}_off{offset}.json"
        params = {
            "keyword": keyword,
            "printFields": PRINT_FIELDS,
            "offset": offset,
        }
        data, hit = cached_get(NSF_API, key, params=params)
        response = data.get("response", {})

        # Check for API error notifications
        if "serviceNotification" in response:
            for n in response["serviceNotification"]:
                if n.get("notificationType") == "ERROR":
                    raise RuntimeError(f"NSF API error: {n.get('notificationMessage')}")

        batch = response.get("award", [])
        meta = response.get("metadata", {})
        total = meta.get("totalCount", 0)

        if not batch:
            break

        awards.extend(batch)
        page += 1
        rpp = int(meta.get("rpp", 25))
        print(
            f"    page {page} offset={offset} → {len(batch)} awards "
            f"(total reported: {total}) {'(cache)' if hit else '(live)'}"
        )

        if len(batch) < rpp:
            break  # last page
        offset += rpp
        if not hit:
            time.sleep(0.3)  # polite delay on live fetch

    return awards


def is_ai_safety_relevant(award: dict) -> bool:
    """Return True if the award is plausibly AI-safety relevant."""
    haystack = (
        (award.get("title") or "").lower()
        + " "
        + (award.get("fundProgramName") or "").lower()
    )
    return any(kw in haystack for kw in AI_KEYWORDS)


def parse_year(date_str: str | None) -> int | None:
    """Parse MM/DD/YYYY → year int."""
    if not date_str:
        return None
    parts = date_str.split("/")
    if len(parts) == 3:
        try:
            return int(parts[2])
        except ValueError:
            pass
    return None


def award_url(award_id: str) -> str:
    return f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={award_id}"


def main() -> None:
    t0 = datetime.now(timezone.utc)
    print("=== fetch_nsf.py ===")

    # Fetch all three keyword queries and dedupe by id
    raw_awards: dict[str, dict] = {}  # id → award
    query_counts: dict[str, int] = {}
    for kw in QUERIES:
        print(f"\n  Query: {kw}")
        batch = paginate_query(kw)
        new = 0
        for a in batch:
            if a["id"] not in raw_awards:
                raw_awards[a["id"]] = a
                new += 1
        query_counts[kw] = len(batch)
        print(
            f"  → {len(batch)} fetched, {new} new after dedup (total pool: {len(raw_awards)})"
        )

    print(f"\n  Pre-filter pool: {len(raw_awards)} unique awards")

    # Apply AI safety relevance filter
    kept = {aid: a for aid, a in raw_awards.items() if is_ai_safety_relevant(a)}
    dropped = len(raw_awards) - len(kept)
    print(f"  After AI-relevance filter: {len(kept)} kept, {dropped} dropped")

    records: list[dict] = []
    seen_po: dict[str, str] = {}  # poName → award_url

    for award in kept.values():
        aid = award["id"]
        aurl = award_url(aid)
        obligated = award.get("fundsObligatedAmt")
        amount = int(obligated) if obligated else None
        year = parse_year(award.get("startDate"))

        records.append(
            {
                "type": "grant",
                "funder_hint": "nsf",
                "grantee_name": award.get("awardeeName", ""),
                "amount_usd": amount,
                "year": year,
                "program": award.get("fundProgramName", ""),
                "source_url": aurl,
            }
        )

        po = (award.get("poName") or "").strip()
        if po and po not in seen_po:
            seen_po[po] = aurl

    # Person records for distinct program officers
    for po_name, src_url in seen_po.items():
        # Find the program for this PO from the first award that lists them
        program = next(
            (
                a.get("fundProgramName", "")
                for a in kept.values()
                if (a.get("poName") or "").strip() == po_name
            ),
            "",
        )
        records.append(
            {
                "type": "person",
                "name": po_name,
                "title": f"Program Officer, {program}",
                "funder_hint": "nsf",
                "profile_url": None,
                "source_url": src_url,
            }
        )

    # funder_total: sum obligated $ for CY2025 awards
    grants_2025 = [
        r
        for r in records
        if r["type"] == "grant"
        and r.get("year") == 2025
        and r.get("amount_usd") is not None
    ]
    total_2025 = sum(r["amount_usd"] for r in grants_2025)
    records.append(
        {
            "type": "funder_total",
            "funder_hint": "nsf",
            "year": 2025,
            "amount_usd": total_2025,
            "method": (
                "sum of AI-safety-relevant NSF awards obligated CY2025 "
                "(SLES + 'AI safety' + 'trustworthy artificial intelligence' keyword slice)"
            ),
            "source_url": FUNDER_TOTAL_SOURCE,
        }
    )

    out = {"source": "nsf", "fetched": t0.isoformat(), "records": records}
    OUT.write_text(json.dumps(out, indent=2))

    # Summary
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1

    grant_recs = [r for r in records if r["type"] == "grant"]
    total_all = sum(r.get("amount_usd") or 0 for r in grant_recs)

    print("\n--- Report ---")
    print(f"  records by type: {by_type}")
    print(f"  grants total $ (all years): ${total_all:,.0f}")
    print(f"  CY2025 grants: {len(grants_2025)} → ${total_2025:,.0f}")
    print(f"  unique program officers: {len(seen_po)}")
    print(f"  output: {OUT}")

    print("\n--- 3 sample grant records ---")
    for r in grant_recs[:3]:
        print(
            f"  {r['grantee_name'][:50]} | ${r['amount_usd']:,} | {r['year']} | {r['program'][:40]}"
        )


if __name__ == "__main__":
    main()
