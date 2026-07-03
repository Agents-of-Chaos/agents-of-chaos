# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch UK government AI-safety funding data from AISI and ARIA.

Pages:
  - https://alignmentproject.aisi.gov.uk/   (round totals, backer list, status/reopen notes)
  - https://aria.org.uk/opportunity-spaces/mathematics-for-safe-ai/safeguarded-ai/funding
  - https://aria.org.uk/funding-opportunities  (programme budget, live call deadlines)

Emits experiments/funding/raw/normalized_gov_uk.json:
  - funder_total records: {funder_hint, year, amount_usd, amount_original, method, source_url}
  - apply_status records: {record_type, funder_hint, mode_guess, deadline, notes, source_url}

Run:  uv run experiments/funding/fetch_gov_uk.py
"""
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
OUT = RAW / "normalized_gov_uk.json"
RAW.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Approximate GBP → USD rate (pinned per plan)
GBP_TO_USD = 1.27


def cached_get(client: httpx.Client, url: str, cache_key: str) -> tuple[int, bytes]:
    """GET with disk cache + backoff. Returns (status_code, body_bytes).
    STALE fallback on repeated failure."""
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
        print(f"  [HTTP {r.status_code} on {url}]")
        return r.status_code, r.content

    if cache_file.exists():
        print(f"  [STALE] using cached response for {url}")
        return -1, cache_file.read_bytes()
    return -1, b""


# ---------------------------------------------------------------------------
# HTML utilities
# ---------------------------------------------------------------------------


class PlainTextHTMLParser(HTMLParser):
    """Strip tags, preserve meaningful whitespace, gather text."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = False
        self._depth = 0
        self._block_tags = {
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "td",
            "th",
            "div",
            "section",
            "article",
            "header",
            "footer",
            "blockquote",
            "pre",
        }
        self._skip_tags = {"script", "style", "noscript", "svg", "path"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True
            self._depth += 1
        elif tag in self._block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._depth -= 1
            if self._depth <= 0:
                self._skip = False
                self._depth = 0
        elif tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def html_to_text(html: str) -> str:
    p = PlainTextHTMLParser()
    p.feed(html)
    return p.get_text()


def _parse_gbp_amount(text: str) -> float | None:
    """Extract a GBP number from a string like '£5m', '£500,000', '5 million'."""
    text = text.strip()
    m = re.search(r"£\s*([\d,\.]+)\s*([mb]illion|m|k)?", text, re.I)
    if not m:
        m = re.search(
            r"([\d,\.]+)\s*(million|billion|m|k)?\s*(?:gbp|pounds?)", text, re.I
        )
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix in ("b", "billion"):
        val *= 1_000_000_000
    elif suffix in ("m", "million"):
        val *= 1_000_000
    elif suffix == "k":
        val *= 1_000
    return val


def _find_year(text: str) -> int | None:
    m = re.search(r"\b(202[0-9])\b", text)
    return int(m.group(1)) if m else None


def _find_iso_deadline(text: str) -> str | None:
    """Look for a real dated deadline in the text — returns ISO date string or None."""
    # Match "DD Month YYYY" or "Month DD, YYYY" or "YYYY-MM-DD"
    patterns = [
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(202[0-9])\b",
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(202[0-9])\b",
        r"\b(202[0-9])-(\d{2})-(\d{2})\b",
    ]
    months = {
        m: i + 1
        for i, m in enumerate(
            [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ]
        )
    }
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            g = m.groups()
            try:
                if len(g) == 3 and g[1] in months:
                    # "DD Month YYYY"
                    day, month_name, year = int(g[0]), g[1].capitalize(), int(g[2])
                    return f"{year:04d}-{months[month_name]:02d}-{day:02d}"
                elif len(g) == 3 and g[0] in months:
                    # "Month DD, YYYY"
                    month_name, day, year = g[0].capitalize(), int(g[1]), int(g[2])
                    return f"{year:04d}-{months[month_name]:02d}-{day:02d}"
                elif len(g) == 3 and re.match(r"\d{4}", g[0]):
                    # "YYYY-MM-DD"
                    return f"{g[0]}-{g[1]}-{g[2]}"
            except (ValueError, KeyError):
                pass
    return None


# ---------------------------------------------------------------------------
# AISI Alignment Project page
# ---------------------------------------------------------------------------

AISI_URL = "https://alignmentproject.aisi.gov.uk/"


def fetch_aisi(client: httpx.Client) -> list[dict]:
    """Scrape the AISI alignment project page for round totals and status.

    The page is JS-rendered but its static HTML still contains enough text to extract:
      - Round 1 total (e.g. "over £27 million were awarded to over 60 projects")
      - Max grant size ("funding of up to £1 million")
      - Status note ("applications are currently closed ... expected to reopen in summer 2026")
    """
    records = []
    status, body = cached_get(client, AISI_URL, "aisi_home")
    if not body:
        print("  [AISI] no response")
        return records

    html = body.decode("utf-8", errors="replace")
    text = html_to_text(html)

    # Save raw text for inspection
    (CACHE / "aisi_text.txt").write_text(text[:5000])

    # Specific patterns that match AISI page text (verified from live fetch)
    amount_patterns = [
        # "over £27 million were awarded to over 60 projects"
        r"(£[\d,\.]+\s*(?:million|m|bn|billion)?)\s+were\s+awarded",
        # "funding of up to £1 million"
        r"funding\s+of\s+up\s+to\s+(£[\d,\.]+\s*(?:million|m|bn|billion)?)",
        # generic fallbacks
        r"(£[\d,\.]+\s*(?:million|m|bn|billion)?)\s*(?:in\s+)?(?:total\s+)?(?:funding|grants?|awards?|committed)",
        r"(?:funding|grants?|awards?|total)\s+of\s+(£[\d,\.]+\s*(?:million|m|bn|billion)?)",
        r"(£[\d,\.]+\s*(?:million|m|bn|billion)?)\s*(?:to|for|across)\s+\d+\s+(?:projects?|organisations?)",
    ]

    seen_vals: set[float] = set()
    for pat in amount_patterns:
        for m in re.finditer(pat, text, re.I):
            snippet = m.group(0)
            gbp_val = _parse_gbp_amount(snippet)
            if not gbp_val or gbp_val < 100 or gbp_val in seen_vals:
                continue
            seen_vals.add(gbp_val)
            year = _find_year(snippet) or _find_year(text[:3000])
            method_snippet = text[max(0, m.start() - 20) : m.end() + 80].strip()
            records.append(
                {
                    "record_type": "funder_total",
                    "funder_hint": "uk-aisi",
                    "year": year,
                    "amount_usd": None,
                    "amount_original": {"value": gbp_val, "currency": "GBP"},
                    "method": method_snippet[:200],
                    "source_url": AISI_URL,
                }
            )
            print(f"  [AISI] amount: £{gbp_val:,.0f} | {method_snippet[:80]}")

    if not seen_vals:
        print("  [AISI] JS-rendered page: no GBP amounts in static HTML")
        print(f"    page text excerpt: {text[:400]!r}")

    # Mode detection: check "currently closed" BEFORE checking for bare "open"
    # to avoid "reopen" triggering a false-positive "rounds" reading.
    lower_text = text.lower()
    closed_phrases = [
        "currently closed",
        "applications are currently closed",
        "not currently accepting",
        "round closed",
        "applications closed",
    ]
    open_phrases = [
        "applications open",
        "now open",
        "apply now",
        "accepting applications",
    ]

    mode_guess = "closed"
    for phrase in closed_phrases:
        if phrase in lower_text:
            mode_guess = "closed"
            break
    else:
        for phrase in open_phrases:
            if phrase in lower_text:
                mode_guess = "rounds"
                break

    # Grab the specific status note sentence if present
    status_note = ""
    for line in text.split("\n"):
        stripped = line.strip()
        if "closed" in stripped.lower() or "reopen" in stripped.lower():
            if len(stripped) > 20:
                status_note = stripped[:300]
                break

    notes = (
        status_note
        or text[
            text.lower().find("application") : text.lower().find("application") + 300
        ]
    )
    deadline = _find_iso_deadline(text)

    records.append(
        {
            "record_type": "apply_status",
            "funder_hint": "uk-aisi",
            "mode_guess": mode_guess,
            "deadline": deadline,
            "notes": notes[:500],
            "source_url": AISI_URL,
        }
    )
    print(f"  [AISI] apply_status: mode={mode_guess}, deadline={deadline}")

    return records


# ---------------------------------------------------------------------------
# ARIA pages
# ---------------------------------------------------------------------------

ARIA_SAFEGUARDED_URL = "https://www.aria.org.uk/opportunity-spaces/mathematics-for-safe-ai/safeguarded-ai/funding"
ARIA_OPPORTUNITIES_URL = "https://www.aria.org.uk/funding-opportunities"
ARIA_MAIN_URL = "https://www.aria.org.uk"


def fetch_aria(client: httpx.Client) -> list[dict]:
    """Scrape ARIA pages for programme budget and call deadlines."""
    records = []

    pages = [
        ("aria_safeguarded_funding", ARIA_SAFEGUARDED_URL, "aria"),
        ("aria_funding_opportunities", ARIA_OPPORTUNITIES_URL, "aria"),
    ]

    for cache_key, url, funder_hint in pages:
        status, body = cached_get(client, url, cache_key)
        if not body:
            print(f"  [ARIA] no response for {url}")
            continue

        html = body.decode("utf-8", errors="replace")
        text = html_to_text(html)
        (CACHE / f"{cache_key}_text.txt").write_text(text[:6000])

        print(f"  [ARIA] fetched {url} ({len(text)} chars)")

        # Extract GBP amounts — deduplicate by value so repeated "up to £500k"
        # per-project language doesn't generate 4 identical funder_total records.
        seen_vals: set[float] = set()
        for m in re.finditer(
            r"£\s*[\d,\.]+\s*(?:million|m|billion|bn|k)?",
            text,
            re.I,
        ):
            snippet = text[max(0, m.start() - 30) : m.end() + 100]
            gbp_val = _parse_gbp_amount(m.group(0))
            if not gbp_val or gbp_val < 100 or gbp_val in seen_vals:
                continue
            seen_vals.add(gbp_val)
            year = _find_year(snippet)
            records.append(
                {
                    "record_type": "funder_total",
                    "funder_hint": funder_hint,
                    "year": year,
                    "amount_usd": None,
                    "amount_original": {"value": gbp_val, "currency": "GBP"},
                    "method": snippet.strip()[:200],
                    "source_url": url,
                }
            )
            print(f"  [ARIA] amount: £{gbp_val:,.0f} | {snippet[:80]}")

        # Status / deadline
        lower_text = text.lower()
        open_indicators = [
            "open",
            "now open",
            "applications open",
            "apply now",
            "accepting applications",
        ]
        closed_indicators = [
            "closed",
            "not currently",
            "no longer",
            "applications closed",
        ]

        mode_guess = "closed"
        for ind in open_indicators:
            if ind in lower_text:
                mode_guess = "rounds"
                break

        deadline = _find_iso_deadline(text)

        # Grab relevant status lines
        status_lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if len(stripped) > 15 and any(
                kw in stripped.lower()
                for kw in [
                    "open",
                    "closed",
                    "apply",
                    "deadline",
                    "funding",
                    "call",
                    "programme",
                    "round",
                ]
            ):
                status_lines.append(stripped)

        notes = " | ".join(status_lines[:5]) if status_lines else text[:300]

        records.append(
            {
                "record_type": "apply_status",
                "funder_hint": funder_hint,
                "mode_guess": mode_guess,
                "deadline": deadline,
                "notes": notes[:500],
                "source_url": url,
            }
        )
        print(f"  [ARIA] apply_status ({url}): mode={mode_guess}, deadline={deadline}")

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=== fetch_gov_uk.py ===")
    client = httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True)

    records: list[dict] = []

    print("\n-- AISI --")
    aisi_records = fetch_aisi(client)
    records.extend(aisi_records)

    print("\n-- ARIA --")
    aria_records = fetch_aria(client)
    records.extend(aria_records)

    # Summary
    totals = [r for r in records if r.get("record_type") == "funder_total"]
    statuses = [r for r in records if r.get("record_type") == "apply_status"]

    print(f"\nfunder_total records: {len(totals)}")
    print(f"apply_status records: {len(statuses)}")

    # Sample output
    print("\nSample funder_total records:")
    for r in totals[:3]:
        orig = r.get("amount_original", {})
        print(
            f"  {r['funder_hint']} | {orig.get('currency')} {orig.get('value'):,.0f} | {r['year']} | {r['method'][:60]}"
        )

    print("\nSample apply_status records:")
    for r in statuses[:3]:
        print(
            f"  {r['funder_hint']} | mode={r['mode_guess']} | deadline={r['deadline']} | {r['notes'][:80]}"
        )

    output = {
        "source": "gov_uk",
        "fetched": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    OUT.write_text(json.dumps(output, indent=2))
    print(f"\nWrote {len(records)} records → {OUT}")


if __name__ == "__main__":
    main()
