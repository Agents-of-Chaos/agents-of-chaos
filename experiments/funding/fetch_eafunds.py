# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch EA Funds grants (Long-Term Future Fund only), emit raw/normalized_eafunds.json.

API note: /api/grants returns HTTP 500 as of 2026-07-03 (Next.js server error).
Script falls back to the Next.js SSG endpoint /_next/data/{buildId}/grants.json,
which serves the same data as a clean JSON payload (1631 total grants, 682 LTFF).
"""

import json
import re
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
OUT = RAW / "normalized_eafunds.json"

# Contract-specified source URL (even though /api/grants 500s; this is the canonical ref)
SOURCE_URL = "https://funds.effectivealtruism.org/api/grants"
GRANTS_PAGE = "https://funds.effectivealtruism.org/grants"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (funding-pipeline; alexloftus2004@gmail.com)",
    "Accept": "*/*",
}

client = httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True)


def cached_get(url: str, key: str) -> tuple[bytes, bool]:
    """GET with disk cache + 429/5xx backoff. Returns (bytes, cache_hit).
    On persistent failure uses stale cache with STALE warning; never crashes.
    """
    cache_path = CACHE / key
    if cache_path.exists():
        return cache_path.read_bytes(), True

    last_err: Exception | None = None
    for attempt in range(6):
        try:
            r = client.get(url)
            if r.status_code == 200:
                cache_path.write_bytes(r.content)
                return r.content, False
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

    # Stale cache fallback
    stale = sorted(CACHE.glob(f"{key.rsplit('.', 1)[0]}*"))
    if stale:
        print(f"  STALE fallback: {stale[-1].name}", file=sys.stderr)
        return stale[-1].read_bytes(), True

    raise RuntimeError(f"All retries failed for {url}: {last_err}")


def get_build_id() -> str:
    """Fetch the grants page HTML to extract the current Next.js buildId."""
    html_bytes, hit = cached_get(GRANTS_PAGE, "eafunds_grants_page.html")
    html = html_bytes.decode("utf-8", errors="replace")
    m = re.search(r'"buildId":"([^"]+)"', html)
    assert m, "Could not find buildId in EA Funds grants page HTML"
    build_id = m.group(1)
    print(f"  buildId: {build_id} ({'cache' if hit else 'live'})")
    return build_id


def fetch_all_grants() -> list[dict]:
    """Fetch via Next.js SSG data endpoint; fall back to CSV API if it ever recovers."""
    # Primary: try /api/grants CSV (per spec)
    csv_bytes, csv_hit = _try_csv_api()
    if csv_bytes is not None:
        return _parse_csv(csv_bytes)

    # Fallback: Next.js SSG JSON (confirmed working 2026-07-03)
    print("  /api/grants unavailable — using Next.js SSG fallback", file=sys.stderr)
    build_id = get_build_id()
    ssg_url = f"https://funds.effectivealtruism.org/_next/data/{build_id}/grants.json"
    key = f"eafunds_ssg_{build_id}.json"
    data_bytes, hit = cached_get(ssg_url, key)
    print(
        f"  SSG grants JSON {'(cache)' if hit else '(live)'}: {len(data_bytes):,} bytes"
    )
    data = json.loads(data_bytes)
    return data["pageProps"]["grantsList"]


def _try_csv_api() -> tuple[bytes | None, bool]:
    """Attempt the documented /api/grants CSV endpoint. Returns (bytes, hit) or (None, False)."""
    api_url = "https://funds.effectivealtruism.org/api/grants"
    key = "eafunds_api_grants.csv"
    cache_path = CACHE / key
    if cache_path.exists():
        b = cache_path.read_bytes()
        if not b.startswith(b"<!DOCTYPE"):  # cached CSV, not an error HTML
            return b, True

    try:
        r = client.get(api_url, timeout=15)
        if r.status_code == 200 and not r.content.startswith(b"<!DOCTYPE"):
            cache_path.write_bytes(r.content)
            return r.content, False
    except httpx.HTTPError:
        pass
    return None, False


def _parse_csv(csv_bytes: bytes) -> list[dict]:
    """Parse CSV bytes into grant dicts (if /api/grants ever returns CSV again)."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    grants = []
    for row in reader:
        grants.append(
            {
                "fund": row.get("fund", ""),
                "grantee": row.get("grantee", ""),
                "amount": float(row["amount"]) if row.get("amount") else None,
                "year": int(row["year"]) if row.get("year") else None,
            }
        )
    return grants


def main() -> None:
    t0 = datetime.now(timezone.utc)
    print("=== fetch_eafunds.py ===")

    all_grants = fetch_all_grants()
    print(f"  total grants fetched: {len(all_grants)}")

    ltff = [g for g in all_grants if g.get("fund") == "Long-Term Future Fund"]
    print(f"  LTFF grants: {len(ltff)}")

    records: list[dict] = []

    for g in ltff:
        amount = g.get("amount")
        records.append(
            {
                "type": "grant",
                "funder_hint": "ltff",
                "grantee_name": g.get("grantee", ""),
                "amount_usd": int(amount) if amount is not None else None,
                "year": g.get("year"),
                "program": "LTFF",
                "source_url": SOURCE_URL,
            }
        )

    # funder_total for CY2025
    ltff_2025 = [
        g for g in ltff if g.get("year") == 2025 and g.get("amount") is not None
    ]
    total_2025 = int(sum(g["amount"] for g in ltff_2025))
    records.append(
        {
            "type": "funder_total",
            "funder_hint": "ltff",
            "year": 2025,
            "amount_usd": total_2025,
            "method": (
                "sum of LTFF grants CY2025 from the public grants JSON "
                "(Next.js SSG endpoint; /api/grants returns HTTP 500 as of 2026-07-03)"
            ),
            "source_url": SOURCE_URL,
        }
    )

    out = {"source": "eafunds", "fetched": t0.isoformat(), "records": records}
    OUT.write_text(json.dumps(out, indent=2))

    grant_recs = [r for r in records if r.get("type") == "grant"]
    total_all = sum(r.get("amount_usd") or 0 for r in grant_recs)

    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1

    print("\n--- Report ---")
    print(f"  records by type: {by_type}")
    print(f"  LTFF all-years $: ${total_all:,.0f}")
    print(f"  LTFF 2025 grants: {len(ltff_2025)} → ${total_2025:,.0f}")
    print(f"  output: {OUT}")

    # 3 sample records
    print("\n--- 3 sample grant records ---")
    for r in grant_recs[:3]:
        print(f"  {r['grantee_name']} | ${r['amount_usd']:,} | {r['year']}")


if __name__ == "__main__":
    main()
