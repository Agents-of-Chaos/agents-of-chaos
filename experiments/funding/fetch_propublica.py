# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""Fetch ProPublica Nonprofit Explorer v2 data for EA/AI-safety orgs.

Emits raw/normalized_propublica.json: funder_total-style records tagged
{record_type: "org_990", ...} for use as context/verification in build_funding.py.
These are medium-confidence records — org 990 totals, not grant-level data.

Flow per target:
  1. GET /v2/search.json?q=<query> → pick best name match (log EIN + similarity)
  2. GET /v2/organizations/<ein>.json → latest filing with totals
  3. Emit one org_990 record per resolved org

Run:
    cd experiments/funding && uv run fetch_propublica.py
"""
import json
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CACHE = RAW / "cache"
RAW.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

BASE = "https://projects.propublica.org/nonprofits/api/v2"
HEADERS = {"User-Agent": "funding-pipeline (alexloftus2004@gmail.com)"}

# (canonical_name, [search_queries])
# Multiple queries are tried in order; the best similarity match across all wins.
# Apollo Research: US entity likely absent — tolerate zero hits.
# METR: try full name first; "METR" alone returns garbage (4-letter ambiguity).
# EleutherAI: try both "EleutherAI" and "EleutherAI Institute"; note "Eleuthera
#   Institute" (EIN 383909905) is a known false-positive (different org, Bahamas).
TARGETS: list[tuple[str, list[str]]] = [
    ("Future of Life Institute", ["Future of Life Institute"]),
    ("Foresight Institute", ["Foresight Institute"]),
    ("Redwood Research", ["Redwood Research"]),
    ("Center for AI Safety", ["Center for AI Safety"]),
    ("FAR AI", ["FAR AI"]),
    (
        "Model Evaluation and Threat Research",
        ["Model Evaluation and Threat Research", "METR"],
    ),
    ("Apollo Research", ["Apollo Research"]),
    ("EleutherAI", ["EleutherAI", "EleutherAI Institute"]),
    ("Longview Philanthropy", ["Longview Philanthropy"]),
    ("Founders Pledge", ["Founders Pledge"]),
]

# EINs that are known false positives for a given canonical name.
# The multi-query search may surface these; we reject them explicitly.
FALSE_POSITIVES: dict[str, set[str]] = {
    # "Eleuthera Institute" and "Eleutheria" are character-overlap false positives;
    # EleutherAI appears to have no registered US 990-filing entity on ProPublica.
    "EleutherAI": {"383909905", "472126479"},
}

MIN_SIM = 0.5  # reject matches below this similarity threshold


# ── helpers ───────────────────────────────────────────────────────────────────


def name_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def safe_key(s: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", s.lower()).strip("_")


# ── HTTP cache ────────────────────────────────────────────────────────────────


def cached_get_json(url: str, key: str, params: dict[str, str] | None = None) -> dict:
    """GET JSON with disk cache in raw/cache/ + backoff. STALE fallback on failure.
    Returns {} on 404 or unrecoverable error (never raises — callers tolerate no-data).
    """
    cache_path = CACHE / f"{key}.json"
    if cache_path.exists():
        print(f"    cache hit: {key}")
        return json.loads(cache_path.read_text())

    with httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        for attempt in range(6):
            try:
                r = client.get(url, params=params or {})
            except httpx.HTTPError as e:
                wait = 2.0 * (attempt + 1)
                print(
                    f"    network error ({attempt + 1}/6): {e}; retrying in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            if r.status_code == 200:
                data = r.json()
                cache_path.write_text(json.dumps(data, indent=2))
                return data
            if r.status_code in (429, 503):
                wait = 3.0 * (attempt + 1)
                print(
                    f"    {r.status_code} rate-limit ({attempt + 1}/6); retrying in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            if r.status_code == 404:
                print(f"    404 — no ProPublica record at {url}")
                return {}
            print(f"    HTTP {r.status_code} — aborting")
            break

    if cache_path.exists():
        print(f"    STALE fallback: reusing cached {key}")
        return json.loads(cache_path.read_text())
    return {}  # graceful empty — never crash


# ── org resolution ────────────────────────────────────────────────────────────


def _search_single(
    canonical: str, query: str
) -> tuple[str | None, str | None, float, str]:
    """One query → (ein, matched_name, sim, note). sim=-1 on no results."""
    data = cached_get_json(
        f"{BASE}/search.json",
        f"pp_search_{safe_key(query)}",
        {"q": query},
    )
    orgs = data.get("organizations", [])
    if not orgs:
        return None, None, -1.0, "0 results"

    best = max(orgs, key=lambda o: name_sim(canonical, o.get("name", "")))
    sim = name_sim(canonical, best.get("name", ""))
    ein_raw = best.get("ein", "")
    ein = str(ein_raw).zfill(9) if ein_raw else None
    matched = best.get("name", "")
    return ein, matched, sim, f"sim={sim:.2f}, {len(orgs)} results for '{query}'"


def search_org_multi(
    canonical: str, queries: list[str]
) -> tuple[str | None, str | None, str]:
    """Try all queries; return the highest-sim match that clears MIN_SIM and isn't a
    known false positive. Returns (None, None, note) if nothing qualifies."""
    fp_eins = FALSE_POSITIVES.get(canonical, set())
    best_ein: str | None = None
    best_matched: str | None = None
    best_sim = -1.0
    best_note = "no results across all queries"

    for query in queries:
        ein, matched, sim, note = _search_single(canonical, query)
        if ein is None or sim <= best_sim:
            continue
        if ein in fp_eins:
            print(f"    skipping known false positive EIN {ein} ('{matched}')")
            continue
        best_ein, best_matched, best_sim, best_note = ein, matched, sim, note

    if best_sim < MIN_SIM:
        return (
            None,
            None,
            f"best match '{best_matched}' below threshold (sim={best_sim:.2f})",
        )
    return best_ein, best_matched, best_note


# ── filing extraction ─────────────────────────────────────────────────────────


def int_field(filing: dict, *names: str) -> int | None:
    """Extract first non-null integer from a filing dict, trying multiple field name variants."""
    for name in names:
        v = filing.get(name)
        if v is not None and v != "":
            try:
                return int(float(str(v).replace(",", "")))
            except (ValueError, TypeError):
                pass
    return None


def get_org_record(ein: str, canonical: str) -> dict[str, Any] | None:
    """Fetch org JSON; return normalized org_990 record or None if no filing data."""
    data = cached_get_json(
        f"{BASE}/organizations/{ein}.json",
        f"pp_org_{ein}",
    )
    if not data:
        return None

    org = data.get("organization", {})
    filings = data.get("filings_with_data", [])
    if not filings:
        return None

    latest = filings[0]  # ProPublica returns most recent first

    fiscal_year = latest.get("tax_prd_yr") or latest.get("taxyear")
    if fiscal_year:
        try:
            fiscal_year = int(str(fiscal_year)[:4])
        except (ValueError, TypeError):
            fiscal_year = None

    total_revenue = int_field(latest, "totrevenue", "totrevnue")
    total_expenses = int_field(latest, "totfuncexpns", "totexpns")
    # ProPublica uses several field names for grants paid across form versions
    grants_paid = int_field(latest, "grntspd", "totgrantspd", "grscontrgifts")

    return {
        "record_type": "org_990",
        "org_name": canonical,
        "matched_name": org.get("name", ""),
        "ein": ein,
        "fiscal_year": fiscal_year,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "grants_paid": grants_paid,
        "source_url": f"https://projects.propublica.org/nonprofits/organizations/{ein}",
    }


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=== fetch_propublica.py ===")

    records: list[dict] = []
    resolution_log: list[dict] = []

    for canonical, queries in TARGETS:
        print(f"\n  {canonical}  (queries: {queries})")
        ein, matched, note = search_org_multi(canonical, queries)
        resolution_log.append(
            {
                "canonical": canonical,
                "queries": queries,
                "ein": ein,
                "matched_name": matched,
                "note": note,
            }
        )

        if ein is None:
            print(f"    -> no match: {note}")
            continue

        print(f"    -> EIN {ein} | '{matched}' | {note}")
        rec = get_org_record(ein, canonical)
        if rec is None:
            print("    -> resolved but no filing data")
            continue

        records.append(rec)
        fy = rec.get("fiscal_year", "?")
        rev = (
            f"${rec['total_revenue']:,}"
            if rec.get("total_revenue") is not None
            else "null"
        )
        exp = (
            f"${rec['total_expenses']:,}"
            if rec.get("total_expenses") is not None
            else "null"
        )
        gp = (
            f"${rec['grants_paid']:,}" if rec.get("grants_paid") is not None else "null"
        )
        print(f"    -> FY{fy} | revenue={rev} | expenses={exp} | grants_paid={gp}")

    out = {
        "source": "propublica-nonprofit-explorer",
        "fetched": datetime.now(timezone.utc).isoformat(),
        "resolution_log": resolution_log,
        "records": records,
    }

    out_path = RAW / "normalized_propublica.json"
    out_path.write_text(json.dumps(out, indent=2))

    # terse report
    n_resolved = sum(1 for r in resolution_log if r["ein"])
    n_with_data = len(records)
    print(f"\n  resolved:    {n_resolved}/{len(TARGETS)} orgs found on ProPublica")
    print(f"  org_990 records: {n_with_data}")

    print("\n  3 samples:")
    for r in records[:3]:
        fy = r.get("fiscal_year", "?")
        rev = (
            f"${r['total_revenue']:,}" if r.get("total_revenue") is not None else "null"
        )
        print(f"    {r['org_name']} | FY{fy} | revenue={rev} | ein={r['ein']}")

    print(f"\n  written → {out_path}")


if __name__ == "__main__":
    main()
