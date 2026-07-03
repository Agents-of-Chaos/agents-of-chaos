# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch Coefficient Giving / Open Philanthropy grant data.

Two-pronged:
  a) Archived Open Phil grants DB: github.com/rufuspollock/open-philanthropy-grants
     - List repo files via GitHub API to find the CSV
     - Download CSV, filter to AI-safety focus areas
  b) Try https://coefficientgiving.org/funds with a real browser UA
     - If 403/blocked: note it and rely on archive
     - If it loads: capture fund names + staff as person records

Emits experiments/funding/raw/normalized_coefficient.json:
  - grant records: {funder_hint, grantee_name, amount_usd, year, program, source_url}
  - funder_total records: {funder_hint, year, amount_usd, method, source_url}
  - person records: {name, title, funder_hint, profile_url, source_url} (if CG site loads)

Run:  uv run experiments/funding/fetch_coefficient.py
"""
import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CACHE = RAW / "cache"
OUT = RAW / "normalized_coefficient.json"
RAW.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

GITHUB_API = "https://api.github.com"
REPO_OWNER = "rufuspollock"
REPO_NAME = "open-philanthropy-grants"
RAW_GH = "https://raw.githubusercontent.com"

CG_FUNDS_URL = "https://coefficientgiving.org/funds"

# AI-safety relevant focus area substrings (case-insensitive match)
AI_SAFETY_PROGRAMS = {
    "potential risks from advanced ai",
    "ai governance",
    "biosecurity",
    "biorisk",
    "global catastrophic risk",
    "ai safety",
    "ai alignment",
    "technical ai safety",
    "policy and strategy",  # when paired with AI context
    "global health and wellbeing",  # broad but included per plan
    "scientific research",  # included when co-occurring
}

# Programs to definitely exclude (too far from AI safety)
EXCLUDE_PROGRAMS = {
    "criminal justice reform",
    "farm animal welfare",
    "immigration policy",
    "housing policy",
    "economic empowerment",
    "tobacco",
    "land use reform",
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

GH_HEADERS = {
    "User-Agent": "funding-pipeline (alexloftus2004@gmail.com)",
    "Accept": "application/vnd.github.v3+json",
}


def cached_get(
    client: httpx.Client,
    url: str,
    cache_key: str,
    headers: dict | None = None,
) -> tuple[int, bytes]:
    """GET with disk cache + backoff. Returns (status_code, body_bytes).
    STALE fallback on repeated failure."""
    cache_file = CACHE / f"{cache_key}.bin"

    for attempt in range(6):
        try:
            r = client.get(url, headers=headers)
        except (httpx.HTTPError, httpx.TransportError):
            wait = 2.0 * (attempt + 1)
            print(f"  [network error on {url}, retry in {wait:.0f}s]")
            time.sleep(wait)
            continue
        if r.status_code == 200:
            cache_file.write_bytes(r.content)
            return 200, r.content
        if r.status_code == 429:
            wait = 4.0 * (attempt + 1)
            print(f"  [429 on {url}, retry in {wait:.0f}s]")
            time.sleep(wait)
            continue
        print(f"  [HTTP {r.status_code} on {url}]")
        return r.status_code, r.content

    if cache_file.exists():
        print(f"  [STALE] using cached response for {url}")
        return -1, cache_file.read_bytes()
    return -1, b""


# ---------------------------------------------------------------------------
# Part A: Open Philanthropy grants archive
# ---------------------------------------------------------------------------


def find_csv_url(client: httpx.Client) -> str | None:
    """Use GitHub API to find the CSV file in rufuspollock/open-philanthropy-grants."""
    api_url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/HEAD?recursive=1"
    status, body = cached_get(client, api_url, "gh_openphil_tree", headers=GH_HEADERS)
    if not body:
        return None

    try:
        tree_data = json.loads(body)
    except json.JSONDecodeError:
        print("  [GitHub API] failed to parse tree JSON")
        return None

    tree = tree_data.get("tree", [])
    csv_files = [item["path"] for item in tree if item["path"].endswith(".csv")]
    print(f"  [GitHub API] CSV files in repo: {csv_files}")

    if not csv_files:
        return None

    # Prefer the most likely main grants file
    priority = ["grants.csv", "data/grants.csv", "openphilanthropy-grants.csv"]
    for name in priority:
        if name in csv_files:
            return f"{RAW_GH}/{REPO_OWNER}/{REPO_NAME}/HEAD/{name}"

    # Fall back to first CSV found
    return f"{RAW_GH}/{REPO_OWNER}/{REPO_NAME}/HEAD/{csv_files[0]}"


def _is_ai_safety_program(program: str) -> bool:
    p = program.lower().strip()
    for excl in EXCLUDE_PROGRAMS:
        if excl in p:
            return False
    for incl in AI_SAFETY_PROGRAMS:
        if incl in p:
            return True
    return False


def _parse_amount(amount_str: str) -> float | None:
    if not amount_str:
        return None
    clean = re.sub(r"[,$\s]", "", str(amount_str))
    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def _parse_year(date_str: str) -> int | None:
    if not date_str:
        return None
    m = re.search(r"\b(19|20)(\d{2})\b", str(date_str))
    return int(m.group(0)) if m else None


def fetch_openphil_csv(client: httpx.Client) -> list[dict]:
    """Download + parse the Open Phil grants CSV, filter to AI-safety programs."""
    records = []

    csv_url = find_csv_url(client)
    if not csv_url:
        print("  [OpenPhil CSV] could not locate CSV in repo")
        return records

    print(f"  [OpenPhil CSV] fetching {csv_url}")
    status, body = cached_get(client, csv_url, "openphil_grants_csv")
    if not body:
        print("  [OpenPhil CSV] no response")
        return records

    text = body.decode("utf-8-sig", errors="replace")  # utf-8-sig strips BOM
    reader = csv.DictReader(io.StringIO(text))

    # Detect column names (the repo has used varying schemas)
    fieldnames = reader.fieldnames or []
    print(f"  [OpenPhil CSV] columns: {fieldnames}")

    # Map flexible column names
    col_map = _detect_columns(fieldnames)
    print(f"  [OpenPhil CSV] column mapping: {col_map}")

    all_rows = list(reader)
    print(f"  [OpenPhil CSV] total rows: {len(all_rows)}")

    ai_safety_rows = []
    for row in all_rows:
        program = row.get(col_map["program"], "") or ""
        if _is_ai_safety_program(program):
            ai_safety_rows.append(row)

    print(f"  [OpenPhil CSV] AI-safety rows: {len(ai_safety_rows)}")

    for row in ai_safety_rows:
        grantee = row.get(col_map["grantee"], "").strip()
        if not grantee:
            continue
        amount_str = row.get(col_map["amount"], "") or ""
        amount_usd = _parse_amount(amount_str)
        date_str = row.get(col_map["date"], "") or ""
        year = _parse_year(date_str)
        program = row.get(col_map["program"], "").strip()
        # source URL: use grant page URL column if present, else repo URL
        grant_url_col = col_map.get("grant_url")
        source_url = (row.get(grant_url_col, "") or "").strip() if grant_url_col else ""
        if not source_url:
            source_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"

        records.append(
            {
                "record_type": "grant",
                "funder_hint": "coefficient-giving",
                "grantee_name": grantee,
                "amount_usd": amount_usd,
                "year": year,
                "program": program,
                "source_url": source_url,
            }
        )

    # Compute funder_total for latest full year in archive
    years_with_amounts = [
        (r["year"], r["amount_usd"]) for r in records if r["year"] and r["amount_usd"]
    ]
    if years_with_amounts:
        all_years = sorted({y for y, _ in years_with_amounts})
        latest_year = all_years[-1]
        # Use second-latest if latest might be partial
        if len(all_years) >= 2:
            # count rows in latest year
            latest_count = sum(1 for y, _ in years_with_amounts if y == latest_year)
            prev_count = sum(1 for y, _ in years_with_amounts if y == all_years[-2])
            if latest_count < prev_count * 0.5:
                latest_year = all_years[-2]

        total_for_year = sum(a for y, a in years_with_amounts if y == latest_year)
        records.append(
            {
                "record_type": "funder_total",
                "funder_hint": "coefficient-giving",
                "year": latest_year,
                "amount_usd": total_for_year,
                "method": f"sum of AI-safety grants in archive for {latest_year}",
                "source_url": f"https://github.com/{REPO_OWNER}/{REPO_NAME}",
            }
        )
        print(f"  [OpenPhil CSV] funder_total: ${total_for_year:,.0f} in {latest_year}")

    return records


def _detect_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map logical field names to actual CSV column names."""
    fn_lower = {f.lower().strip(): f for f in fieldnames}

    def find(candidates: list[str]) -> str:
        for c in candidates:
            if c in fn_lower:
                return fn_lower[c]
        # fuzzy: any field containing the first candidate
        for c in candidates:
            for k, v in fn_lower.items():
                if c in k:
                    return v
        return candidates[0]  # fallback (will just miss)

    mapping = {
        "grantee": find(
            ["organization", "grantee", "recipient", "org name", "organization name"]
        ),
        "amount": find(["amount", "amount (usd)", "grant amount", "funding amount"]),
        "date": find(["date", "grant date", "year", "award date"]),
        "program": find(
            ["focus area", "program", "programme", "area", "topic", "category"]
        ),
    }

    # Optional: grant URL
    for k, v in fn_lower.items():
        if "url" in k or "link" in k or "page" in k:
            mapping["grant_url"] = v
            break

    return mapping


# ---------------------------------------------------------------------------
# Part B: coefficientgiving.org/funds
# ---------------------------------------------------------------------------


def _parse_cg_funds_html(html: str) -> tuple[list[str], list[dict]]:
    """Extract fund names from H3 tags and staff from /team/ links on coefficientgiving.org/funds.

    Verified live (2026-07-03): fund names appear as bare <h3> tags (no special class needed).
    Staff links use /team/ paths, not /people/.
    Returns (fund_name_list, person_record_list).
    """
    funds: list[str] = []
    people: list[dict] = []

    # Fund names: <h3> tags with plain text (not containing nav/footer noise)
    h3_matches = re.findall(r"<h3[^>]*>(.*?)</h3>", html, re.S | re.I)
    nav_noise = {"follow us", "sign up for news about our grants, research, and more"}
    for raw in h3_matches:
        text = re.sub(r"<[^>]+>", "", raw).strip()
        text = re.sub(
            r"&#\d+;|&\w+;",
            lambda m: {"&#038;": "&", "&amp;": "&"}.get(m.group(0), m.group(0)),
            text,
        )
        if text and len(text) > 3 and text.lower() not in nav_noise:
            funds.append(text)

    # Staff: links with /team/ in href
    for m in re.finditer(
        r'<a[^>]+href="(https?://coefficientgiving\.org/team/[^"]+)"[^>]*>(.*?)</a>',
        html,
        re.S | re.I,
    ):
        href, inner = m.group(1), m.group(2)
        name = re.sub(r"<[^>]+>", "", inner).strip()
        if name and len(name) > 2:
            people.append(
                {
                    "record_type": "person",
                    "name": name,
                    "title": "Staff",
                    "funder_hint": "coefficient-giving",
                    "profile_url": href,
                    "source_url": CG_FUNDS_URL,
                }
            )

    return funds, people


class CGFundsParser(HTMLParser):
    """Legacy HTML parser — kept but superseded by _parse_cg_funds_html regex approach."""

    def __init__(self):
        super().__init__()
        self.funds: list[str] = []
        self.people: list[dict] = []
        self._capture = False
        self._text_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href", "")
        if tag == "a" and "/team/" in href:
            self._capture = True
            self._text_buf = []
            self._current_href = href
        elif tag == "h3":
            self._capture = True
            self._text_buf = []
            self._current_href = ""

    def handle_endtag(self, tag):
        if self._capture and tag in ("a", "h3"):
            txt = " ".join(self._text_buf).strip()
            if txt and len(txt) > 2:
                href = getattr(self, "_current_href", "")
                if href and "/team/" in href:
                    base = "https://coefficientgiving.org"
                    self.people.append(
                        {
                            "record_type": "person",
                            "name": txt,
                            "title": "Staff",
                            "funder_hint": "coefficient-giving",
                            "profile_url": f"{base}{href}"
                            if href.startswith("/")
                            else href,
                            "source_url": CG_FUNDS_URL,
                        }
                    )
                elif txt.lower() not in ("home", "about", "contact", "funds", "grants"):
                    self.funds.append(txt)
            self._capture = False
            self._text_buf = []

    def handle_data(self, data):
        if self._capture and data.strip():
            self._text_buf.append(data.strip())


def fetch_cg_website(client: httpx.Client) -> list[dict]:
    """Try coefficientgiving.org/funds with a real browser UA. 403 expected but tried anyway."""
    records = []
    print(f"  [CG] trying {CG_FUNDS_URL}")
    status, body = cached_get(client, CG_FUNDS_URL, "cg_funds", headers=BROWSER_HEADERS)

    if status in (403, 429, -1) and not body:
        print(f"  [CG] blocked (HTTP {status}) — relying on archive only")
        return records

    if status not in (200, -1) or not body:
        print(f"  [CG] HTTP {status} — relying on archive only")
        return records

    html = body.decode("utf-8", errors="replace")
    if "<html" not in html.lower() and len(html) < 500:
        print(f"  [CG] response too short ({len(html)} bytes) — likely blocked")
        return records

    print(f"  [CG] loaded ({len(html)} chars) — parsing")
    # Use regex-based extractor (verified against live page structure)
    funds, people = _parse_cg_funds_html(html)
    print(f"  [CG] found {len(funds)} fund names, {len(people)} people")

    # AI-safety relevant CG fund names (from live page H3s)
    ai_safety_fund_keywords = {
        "navigating transformative ai",
        "biosecurity",
        "pandemic",
        "global catastrophic",
        "forecasting",
    }
    for fund_name in funds:
        if any(kw in fund_name.lower() for kw in ai_safety_fund_keywords):
            records.append(
                {
                    "record_type": "grant",
                    "funder_hint": "coefficient-giving",
                    "grantee_name": fund_name,
                    "amount_usd": None,
                    "year": None,
                    "program": "Coefficient Giving Fund",
                    "source_url": CG_FUNDS_URL,
                }
            )

    records.extend(people)
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=== fetch_coefficient.py ===")
    # Two separate clients: one for GitHub (JSON), one for browsers (HTML)
    gh_client = httpx.Client(timeout=30, headers=GH_HEADERS, follow_redirects=True)
    browser_client = httpx.Client(
        timeout=30, headers=BROWSER_HEADERS, follow_redirects=True
    )

    records: list[dict] = []

    print("\n-- Part A: Open Phil grants archive --")
    archive_records = fetch_openphil_csv(gh_client)
    records.extend(archive_records)

    print("\n-- Part B: coefficientgiving.org/funds --")
    cg_records = fetch_cg_website(browser_client)
    records.extend(cg_records)

    # Summary
    grants = [r for r in records if r.get("record_type") == "grant"]
    totals = [r for r in records if r.get("record_type") == "funder_total"]
    people = [r for r in records if r.get("record_type") == "person"]

    print(f"\ngrant records: {len(grants)}")
    print(f"funder_total records: {len(totals)}")
    print(f"person records: {len(people)}")

    # $ coverage
    grants_with_amounts = [g for g in grants if g.get("amount_usd")]
    if grants_with_amounts:
        total_usd = sum(g["amount_usd"] for g in grants_with_amounts)
        print(
            f"$ coverage: {len(grants_with_amounts)}/{len(grants)} grants → ${total_usd:,.0f} total"
        )

    # 3 samples each type
    print("\nSample grants:")
    for g in grants[:3]:
        print(
            f"  {g['grantee_name'][:50]!r} | ${g['amount_usd']:,.0f}"
            if g["amount_usd"]
            else f"  {g['grantee_name'][:50]!r} | $null"
            f" | {g['year']} | {g['program'][:40]}"
        )

    if totals:
        print("\nSample funder_total:")
        for t in totals[:2]:
            print(
                f"  {t['funder_hint']} | ${t['amount_usd']:,.0f} | {t['year']} | {t['method'][:60]}"
            )

    if people:
        print("\nSample persons:")
        for p in people[:3]:
            print(f"  {p['name']!r} | {p['title']} | {p['profile_url']}")

    output = {
        "source": "coefficient",
        "fetched": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    OUT.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {len(records)} records → {OUT}")


if __name__ == "__main__":
    main()
