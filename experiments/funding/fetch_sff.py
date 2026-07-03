# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch SFF grant recommendations and emit raw/normalized_sff.json.

Source: https://survivalandflourishing.fund/recommendations
Table columns: Round | Source | Organization | Amount | Receiving Charity | Purpose

grantee_name: prefer Organization column; fall back to Receiving Charity only if
Organization is blank. Both columns exist because SFF sometimes recommends grants
to a "Receiving Charity" that is a fiscal sponsor distinct from the named organization.

Run:
    cd experiments/funding && uv run fetch_sff.py
"""
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CACHE = RAW / "cache"
RAW.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

SFF_URL = "https://survivalandflourishing.fund/recommendations"
FUNDER_HINT = "survival-and-flourishing-fund"


# ── helpers ───────────────────────────────────────────────────────────────────


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def parse_amount(s: str) -> int | None:
    s = s.strip().replace(",", "").replace("$", "").replace(" ", "").replace(" ", "")
    if not s or s in ("N/A", "-", "n/a", "TBD"):
        return None
    if s.upper().endswith("M"):
        try:
            return int(float(s[:-1]) * 1_000_000)
        except ValueError:
            return None
    if s.upper().endswith("K"):
        try:
            return int(float(s[:-1]) * 1_000)
        except ValueError:
            return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_year(round_str: str) -> int | None:
    m = re.search(r"(20\d\d)", round_str)
    return int(m.group(1)) if m else None


# ── HTTP cache ────────────────────────────────────────────────────────────────


def cached_get(url: str, key: str) -> bytes:
    """GET with disk cache in raw/cache/ + backoff on 429/503. STALE fallback on all errors."""
    cache_path = CACHE / f"{key}.html"
    if cache_path.exists():
        print(f"  cache hit: {key}")
        return cache_path.read_bytes()

    with httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "funding-pipeline (alexloftus2004@gmail.com)"},
    ) as client:
        for attempt in range(6):
            try:
                r = client.get(url)
            except httpx.HTTPError as e:
                wait = 2.0 * (attempt + 1)
                print(
                    f"  network error ({attempt + 1}/6): {e}; retrying in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            if r.status_code == 200:
                cache_path.write_bytes(r.content)
                print(f"  fetched {url} ({len(r.content):,} bytes)")
                return r.content
            if r.status_code in (429, 503):
                wait = 3.0 * (attempt + 1)
                print(
                    f"  {r.status_code} rate-limit ({attempt + 1}/6); retrying in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code} — aborting retries")
            break

    if cache_path.exists():
        print(f"  STALE fallback: reusing cached {key}")
        return cache_path.read_bytes()
    raise RuntimeError(f"Failed to fetch {url} and no cache available")


# ── HTML table parser ─────────────────────────────────────────────────────────


class TableParser(HTMLParser):
    """Extract all top-level <table> elements as lists of rows (each row = list of cell text)."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._in_row = False
        self._in_cell = False
        self._cell_buf: list[str] = []
        self._row_buf: list[str] = []
        self._table_buf: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._table_buf = []
        elif tag == "tr" and self._depth == 1:
            self._in_row = True
            self._row_buf = []
        elif tag in ("td", "th") and self._in_row and self._depth == 1:
            self._in_cell = True
            self._cell_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._depth == 1 and self._table_buf:
                self.tables.append(self._table_buf)
            self._depth -= 1
        elif tag == "tr" and self._in_row and self._depth == 1:
            if self._row_buf:
                self._table_buf.append(self._row_buf)
            self._in_row = False
        elif tag in ("td", "th") and self._in_cell:
            self._row_buf.append(" ".join(self._cell_buf).strip())
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_buf.append(data)

    def handle_entityref(self, name: str) -> None:
        # basic entity handling for &amp; &nbsp; etc
        mapping = {"amp": "&", "lt": "<", "gt": ">", "nbsp": " ", "quot": '"'}
        if self._in_cell:
            self._cell_buf.append(mapping.get(name, ""))

    def handle_charref(self, name: str) -> None:
        if self._in_cell:
            try:
                ch = chr(int(name[1:], 16) if name.startswith("x") else int(name))
                self._cell_buf.append(ch)
            except (ValueError, OverflowError):
                pass


def find_sff_table(tables: list[list[list[str]]]) -> tuple[list[list[str]], list[str]]:
    """Find the grants table; return (rows, headers)."""
    EXPECTED = {"round", "source", "organization", "amount", "receiving"}
    for table in tables:
        if not table:
            continue
        headers = [c.strip().lower() for c in table[0]]
        if len(EXPECTED & set(headers)) >= 3:
            return table, headers
    # fallback: largest table
    biggest = max(tables, key=len)
    headers = [c.strip().lower() for c in biggest[0]]
    print(
        f"  WARNING: expected headers not found; using largest table ({len(biggest)} rows)"
    )
    print(f"  headers found: {headers}")
    return biggest, headers


def col_idx(headers: list[str], fragment: str) -> int | None:
    for i, h in enumerate(headers):
        if fragment in h:
            return i
    return None


def parse_grants(html_bytes: bytes) -> list[dict[str, Any]]:
    parser = TableParser()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    assert parser.tables, "No <table> elements found on SFF page"

    table, headers = find_sff_table(parser.tables)
    print(f"  headers: {headers}")

    idx_round = col_idx(headers, "round")
    idx_source = col_idx(headers, "source")
    idx_org = col_idx(headers, "organization")
    idx_amount = col_idx(headers, "amount")
    idx_receiving = col_idx(headers, "receiving")

    def cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    records = []
    for row in table[1:]:
        if not any(c.strip() for c in row):
            continue

        round_str = cell(row, idx_round)
        source = cell(row, idx_source)
        org = cell(row, idx_org)
        amount_str = cell(row, idx_amount)
        receiving = cell(row, idx_receiving)

        # grantee: prefer Organization; fall back to Receiving Charity
        grantee = org if org else receiving
        if not grantee:
            continue

        records.append(
            {
                "funder_hint": FUNDER_HINT,
                "grantee_name": grantee,
                "amount_usd": parse_amount(amount_str),
                "year": parse_year(round_str),
                "program": round_str,
                "payer_hint": slugify(source) if source else None,
                "source_url": SFF_URL,
                "_payer_raw": source,  # audit field; stripped before output
            }
        )

    return records


# ── funder totals ─────────────────────────────────────────────────────────────


def build_funder_totals(grants: list[dict]) -> list[dict]:
    totals: list[dict] = []

    # SFF total per year
    by_year: defaultdict[int, list[int]] = defaultdict(list)
    for g in grants:
        if g["year"] is not None and g["amount_usd"] is not None:
            by_year[g["year"]].append(g["amount_usd"])

    for year in sorted(by_year):
        totals.append(
            {
                "funder_hint": FUNDER_HINT,
                "year": year,
                "amount_usd": sum(by_year[year]),
                "method": f"sum of SFF {year} rows",
                "source_url": SFF_URL,
            }
        )

    # per payer for the latest year only
    if by_year:
        latest = max(by_year)
        by_payer: defaultdict[str, list[int]] = defaultdict(list)
        for g in grants:
            payer_raw = g.get("_payer_raw", "")
            if g["year"] == latest and g["amount_usd"] is not None and payer_raw:
                by_payer[payer_raw].append(g["amount_usd"])

        for payer_raw in sorted(by_payer):
            slug = slugify(payer_raw)
            if slug:
                totals.append(
                    {
                        "funder_hint": slug,
                        "year": latest,
                        "amount_usd": sum(by_payer[payer_raw]),
                        "method": f"sum of SFF {latest} rows paid by {payer_raw}",
                        "source_url": SFF_URL,
                    }
                )

    return totals


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=== fetch_sff.py ===")

    html_bytes = cached_get(SFF_URL, "sff_recommendations")
    grants_raw = parse_grants(html_bytes)

    # strip internal audit fields
    grants = [
        {
            "record_type": "grant",
            **{k: v for k, v in g.items() if not k.startswith("_")},
        }
        for g in grants_raw
    ]
    funder_totals = [
        {"record_type": "funder_total", **r} for r in build_funder_totals(grants_raw)
    ]

    out = {
        "source": "survival-and-flourishing-fund",
        "fetched": datetime.now(timezone.utc).isoformat(),
        "records": grants + funder_totals,
    }

    out_path = RAW / "normalized_sff.json"
    out_path.write_text(json.dumps(out, indent=2))

    # terse report
    years = sorted({g.get("year") for g in grants if g.get("year")})
    dollar_grants = [g for g in grants if g.get("amount_usd") is not None]
    total_usd = sum(g["amount_usd"] for g in dollar_grants)
    payers = sorted({g.get("payer_hint") for g in grants if g.get("payer_hint")})

    yr_range = f"{years[0]}–{years[-1]}" if years else "?"
    print(f"\n  grants:        {len(grants):,}  ({len(years)} years: {yr_range})")
    print(f"  funder_totals: {len(funder_totals):,}")
    print(
        f"  $ coverage:    {len(dollar_grants)}/{len(grants)} have amounts; total ${total_usd:,.0f}"
    )
    print(
        f"  payers ({len(payers)}):  {', '.join(payers[:6])}{'...' if len(payers) > 6 else ''}"
    )

    print("\n  3 grant samples:")
    for g in grants[:3]:
        amt = f"${g['amount_usd']:,}" if g.get("amount_usd") is not None else "N/A"
        print(
            f"    {g['grantee_name']} | {g.get('program', '?')} | {amt} | payer={g.get('payer_hint')}"
        )

    print(f"\n  written → {out_path}")


if __name__ == "__main__":
    main()
