# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch AI-safety grant data from manifund.org.

Strategy (tried in order):
  a) JSON API guess: GET /api/projects and siblings
  b) RSC (React Server Components) payload embedded in /projects page
     - Manifund uses Next.js App Router which streams project data as double-backslash-escaped
       JSON inside self.__next_f.push([1, "..."]) script tags.
     - We collect funding_goal positions, search backward for title/slug, forward for
       stage/profiles — then filter to AI-safety topics.
  c) Plain HTML fallback (documented as insufficient if reached)

Emits experiments/funding/raw/normalized_manifund.json:
  - grant records: {funder_hint, grantee_name, amount_usd, year, source_url}
  - person records: {name, title, funder_hint, profile_url, source_url}

Run:  uv run experiments/funding/fetch_manifund.py
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CACHE = RAW / "cache"
OUT = RAW / "normalized_manifund.json"
RAW.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

BASE_URL = "https://manifund.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

AI_SAFETY_TERMS = {
    "ai safety",
    "ai alignment",
    "machine learning safety",
    "alignment",
    "existential risk",
    "x-risk",
    "agi",
    "catastrophic risk",
    "interpretability",
    "robustness",
    "red team",
    "red-team",
    "mechanistic",
    "scalable oversight",
    "constitutional ai",
    "deceptive",
    "deception",
    "corrigibility",
    "inner alignment",
    "outer alignment",
    "reward hacking",
    "specification gaming",
    "anthropic",
    "openai safety",
    "deepmind safety",
}

# Cause slugs from the Manifund API that indicate AI safety relevance
AI_SAFETY_CAUSE_SLUGS = {
    "tais",
    "gcr",
    "biosec",
    "ai-gov",
    "x-risk",
    "xrisk",
    "alignment",
}


def _is_ai_safety(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in AI_SAFETY_TERMS)


def _is_ai_safety_project(proj: dict) -> bool:
    """Check causes list (API response) or fall back to text matching (RSC parse)."""
    causes = proj.get("causes", [])
    if causes:
        return any(c.get("slug", "") in AI_SAFETY_CAUSE_SLUGS for c in causes)
    # Fallback: text match on title + round name
    round_name = proj.get("round", "") or ""
    return _is_ai_safety(f"{proj.get('title', '')} {round_name}")


def cached_get(client: httpx.Client, url: str, cache_key: str) -> tuple[int, bytes]:
    """GET with disk cache + backoff on 429/errors. Returns (status_code, body_bytes).
    On persistent failure: return last cache as STALE."""
    cache_file = CACHE / f"{cache_key}.bin"

    for attempt in range(6):
        try:
            r = client.get(url)
        except (httpx.HTTPError, httpx.TransportError):
            wait = 2.0 * (attempt + 1)
            print(f"  [network error on {url}, retry in {wait:.0f}s]")
            time.sleep(wait)
            continue
        if r.status_code == 200:
            cache_file.write_bytes(r.content)
            return 200, r.content
        if r.status_code == 429:
            wait = 3.0 * (attempt + 1)
            print(f"  [429 on {url}, retry in {wait:.0f}s]")
            time.sleep(wait)
            continue
        return r.status_code, r.content

    if cache_file.exists():
        print(f"  [STALE] using cached response for {url}")
        return -1, cache_file.read_bytes()
    return -1, b""


# ---------------------------------------------------------------------------
# Strategy A: Try JSON API endpoints
# ---------------------------------------------------------------------------


def try_api_endpoints(client: httpx.Client) -> list[dict] | None:
    """Try several undocumented API endpoint guesses."""
    endpoints = [
        ("manifund_api_projects", f"{BASE_URL}/api/projects"),
        ("manifund_api_grants", f"{BASE_URL}/api/grants"),
        ("manifund_api_v1_projects", f"{BASE_URL}/api/v1/projects"),
        ("manifund_api_v0_projects", f"{BASE_URL}/api/v0/projects"),
    ]
    for cache_key, url in endpoints:
        status, body = cached_get(client, url, cache_key)
        if status == 200 and body:
            try:
                data = json.loads(body)
                if isinstance(data, list) and data:
                    print(f"  [A] {url} → {len(data)} records")
                    return data
                if isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, list) and len(v) > 5:
                            print(f"  [A] {url} dict → {len(v)} records")
                            return v
            except json.JSONDecodeError:
                pass
        elif status not in (404, 403):
            print(f"  [A] {url} → HTTP {status}")
    return None


# ---------------------------------------------------------------------------
# Strategy B: Parse RSC (React Server Components) payload
# ---------------------------------------------------------------------------
# Manifund uses Next.js App Router. Data is embedded in <script> tags as:
#   self.__next_f.push([1, "...JSON with \" → \\\" escaping..."])
# The inner strings use ONE backslash before each JSON quote.
# We search the raw page text for projects by locating "funding_goal" positions,
# then scan backward/forward within RSC row boundaries for sibling fields.


def _rsc_field(
    text: str, pos: int, field: str, search_forward: bool, window: int = 8000
) -> str | None:
    """Find the nearest occurrence of \"field\":\"value\" near `pos` in decoded page text.
    Quotes in the RSC payload are escaped as \\\" (backslash + double-quote).
    `search_forward=True` searches after pos, else before.
    Returns the unescaped value string or None."""
    # In the decoded text, field quotes appear as: \"field\":\"value\"
    # Pattern: literal \", then field name, then \":\", then value until \"
    pat = rf'\\"{re.escape(field)}\\":(?:\\"|([^\\]+?))\\"'
    # Simpler: match \"field\":\"<content>\" where content has no unescaped quote
    pat2 = rf'\\"{re.escape(field)}\\":\\"([^\\"]*)\\"'
    pat3 = rf'\\"{re.escape(field)}\\":([\d.]+|null|true|false)'  # numeric/bool fields

    region = (
        text[pos : pos + window] if search_forward else text[max(0, pos - window) : pos]
    )

    for p in (pat2, pat3):
        m = re.search(p, region)
        if m:
            return m.group(1)
    return None


def _rsc_int_field(
    text: str, pos: int, field: str, forward: bool = True, window: int = 4000
) -> int | None:
    """Extract an integer RSC field value."""
    region = text[pos : pos + window] if forward else text[max(0, pos - window) : pos]
    m = re.search(rf'\\"{re.escape(field)}\\":(\d+)', region)
    return int(m.group(1)) if m else None


def _find_prev_field_pos(text: str, pos: int, field: str, window: int) -> int:
    """Return the start position of the nearest preceding occurrence of a field."""
    region = text[max(0, pos - window) : pos]
    m = list(re.finditer(rf'\\"{re.escape(field)}\\":', region))
    if not m:
        return -1
    return max(0, pos - window) + m[-1].start()


def extract_projects_from_rsc(page_text: str) -> list[dict]:
    """Extract project records from the RSC payload in the decoded page HTML.

    Locates each \\\"funding_goal\\\":N occurrence, then searches backward (up to 100KB)
    for the project's title and slug, and forward (up to 2KB) for stage/round/year/creator.
    Deduplicates by title.
    """
    # Positions of all funding_goal fields
    positions = [m.start() for m in re.finditer(r'\\"funding_goal\\":\d+', page_text)]
    print(f"  [B] RSC: {len(positions)} funding_goal occurrences")

    projects = []
    seen_titles: set[str] = set()

    for pos in positions:
        # Search backward up to 100KB for title and slug
        back_window = 100_000
        back_region = page_text[max(0, pos - back_window) : pos]

        # The title and slug of the project containing this funding_goal are the
        # LAST occurrence of those fields in the backward region (nearest to pos)
        title_matches = list(re.finditer(r'\\"title\\":\\"([^\\"]+)\\"', back_region))
        slug_matches = list(re.finditer(r'\\"slug\\":\\"([^\\"]+)\\"', back_region))
        creator_matches = list(
            re.finditer(r'\\"username\\":\\"([^\\"]+)\\"', back_region)
        )

        title = title_matches[-1].group(1) if title_matches else None
        slug = slug_matches[-1].group(1) if slug_matches else None
        creator = creator_matches[-1].group(1) if creator_matches else None

        if not title:
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)

        # Forward: funding_goal value, stage, round, auction_close, type
        fwd_region = page_text[pos : pos + 1000]
        goal_m = re.search(r'\\"funding_goal\\":(\d+)', fwd_region)
        stage_m = re.search(r'\\"stage\\":\\"([^\\"]+)\\"', fwd_region)
        round_m = re.search(r'\\"round\\":\\"([^\\"]+)\\"', fwd_region)
        close_m = re.search(r'\\"auction_close\\":\\"([^\\"]+)\\"', fwd_region)
        type_m = re.search(r'\\"type\\":\\"([^\\"]+)\\"', fwd_region)

        funding_goal = int(goal_m.group(1)) if goal_m else None
        stage = stage_m.group(1) if stage_m else None
        round_name = round_m.group(1) if round_m else None
        auction_close = close_m.group(1) if close_m else None
        proj_type = type_m.group(1) if type_m else None

        # Search forward for creator username (profiles object follows the project body)
        fwd_creator_region = page_text[pos : pos + 3000]
        creator_fwd_m = re.search(r'\\"username\\":\\"([^\\"]+)\\"', fwd_creator_region)
        if creator_fwd_m and not creator:
            creator = creator_fwd_m.group(1)

        projects.append(
            {
                "title": title,
                "slug": slug,
                "funding_goal": funding_goal,
                "stage": stage,
                "round": round_name,
                "auction_close": auction_close,
                "type": proj_type,
                "creator": creator,
            }
        )

    return projects


def try_rsc_parse(client: httpx.Client) -> list[dict]:
    """Fetch /projects and parse the RSC streaming payload."""
    status, body = cached_get(client, f"{BASE_URL}/projects", "manifund_projects_html")
    if not body:
        print("  [B] no response")
        return []

    page_text = body.decode("utf-8", errors="replace")
    projects = extract_projects_from_rsc(page_text)
    print(f"  [B] extracted {len(projects)} unique projects from RSC")
    return projects


# ---------------------------------------------------------------------------
# Normalize raw project → grant + person records
# ---------------------------------------------------------------------------


def _extract_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.search(r"(\d{4})", str(date_str))
    return int(m.group(1)) if m else None


def normalize_project(proj: dict) -> tuple[dict | None, dict | None]:
    """Convert a raw project dict to (grant_record | None, person_record | None).

    Uses cause slugs for AI safety filtering when available (API response),
    falls back to text matching for RSC-parsed dicts.
    Person record uses profiles.full_name / profiles.username (not the UUID creator field).
    """
    title = proj.get("title", "").strip()
    if not title:
        return None, None

    if not _is_ai_safety_project(proj):
        return None, None

    slug = proj.get("slug") or re.sub(r"[^\w-]", "-", title.lower()).strip("-")
    source_url = f"{BASE_URL}/projects/{slug}"

    funding_goal = proj.get("funding_goal")
    # Actual funded amount from txns (sum of positive inflows); fall back to goal
    txns = proj.get("txns") or []
    funded_sum = sum(
        float(t.get("amount", 0)) for t in txns if (t.get("amount") or 0) > 0
    )
    amount_usd = (
        funded_sum
        if funded_sum > 0
        else (float(funding_goal) if funding_goal else None)
    )

    year = _extract_year(proj.get("auction_close") or proj.get("created_at"))

    grant = {
        "record_type": "grant",
        "funder_hint": "manifund",
        "grantee_name": title,
        "amount_usd": amount_usd,
        "year": year,
        "source_url": source_url,
    }

    # Person: prefer profiles dict (API) over raw creator UUID
    person = None
    profiles = proj.get("profiles")
    if isinstance(profiles, dict):
        full_name = profiles.get("full_name") or profiles.get("username")
        username = profiles.get("username", "")
        if full_name and username:
            person = {
                "record_type": "person",
                "name": full_name,
                "title": "Regrantor",
                "funder_hint": "manifund",
                "profile_url": f"{BASE_URL}/{username}",
                "source_url": source_url,
            }
    elif isinstance(proj.get("creator"), str) and not re.match(
        r"^[0-9a-f-]{36}$", proj.get("creator", "")
    ):
        # RSC parse: creator is a username string (not a UUID)
        creator = proj["creator"]
        person = {
            "record_type": "person",
            "name": creator,
            "title": "Regrantor",
            "funder_hint": "manifund",
            "profile_url": f"{BASE_URL}/{creator}",
            "source_url": source_url,
        }

    return grant, person


def dedupe_people(people: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for p in people:
        key = (p["name"].lower(), p["funder_hint"])
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=== fetch_manifund.py ===")
    client = httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True)

    raw_projects: list[dict] = []
    method = "none"

    # A: JSON API guesses
    result = try_api_endpoints(client)
    if result is not None:
        raw_projects = result
        method = "api"

    # B: RSC payload parse
    if not raw_projects:
        raw_projects = try_rsc_parse(client)
        method = "rsc"

    print(f"\nRaw projects: {len(raw_projects)} (method={method})")

    # Normalize + filter
    grants: list[dict] = []
    all_people: list[dict] = []

    for proj in raw_projects:
        grant, person = normalize_project(proj)
        if grant:
            grants.append(grant)
        if person:
            all_people.append(person)

    people_deduped = dedupe_people(all_people)

    print(f"AI-safety grants: {len(grants)}")
    print(f"Regrantor persons: {len(people_deduped)}")

    if grants:
        print("\nSample grants:")
        for g in grants[:3]:
            print(
                f"  {g['grantee_name'][:60]!r} | ${g['amount_usd']:,.0f}"
                if g["amount_usd"]
                else f"  {g['grantee_name'][:60]!r} | $null"
                f" | {g['year']} | {g['source_url']}"
            )

    if people_deduped:
        print("\nSample persons:")
        for p in people_deduped[:3]:
            print(f"  {p['name']!r} | {p['title']} | {p['profile_url']}")

    grants_with_amounts = [g for g in grants if g["amount_usd"]]
    total_usd = sum(g["amount_usd"] for g in grants_with_amounts)
    print(
        f"\n$ coverage: {len(grants_with_amounts)}/{len(grants)} have amounts → ${total_usd:,.0f} total"
    )

    # Document limits if partial
    if not grants:
        print(
            "\n[LIMITS] Manifund uses Next.js App Router RSC format."
            " The /projects page streams project data but only the first ~20 projects are"
            " embedded in the initial HTML. A full dataset requires the Supabase REST API"
            " (key not publicly documented). Current output: 0 grants from first-page RSC."
        )

    records = grants + people_deduped
    output = {
        "source": "manifund",
        "fetched": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "limits": (
            "RSC streaming delivers only the first page of ~20 projects;"
            " no public API key found; counts are underestimates"
        )
        if method == "rsc"
        else None,
        "records": records,
    }
    OUT.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {len(records)} records → {OUT}")


if __name__ == "__main__":
    main()
