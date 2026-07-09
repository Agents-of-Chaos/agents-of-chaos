#!/usr/bin/env python3
"""experiments/funding/build_funding.py

Merge / validate / emit step for the /funding data pipeline.
Reads:  experiments/funding/raw/normalized_*.json      (fetched + normalized source data)
        experiments/funding/seeds/funders_v1.json      (funder seed list)
        experiments/funding/seeds/starter_funding.json (frozen starter snapshot —
            the hand-seeded plan-1 dataset whose ids/fields carry over; a
            SNAPSHOT, not src/data/funding.json, so re-runs are idempotent)
Writes: src/data/funding.json                          (emitted public dataset)

Stdlib only. Fails loud on bad data — better here than in the browser.
Run:  uv run experiments/funding/build_funding.py
"""
# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "experiments/funding/seeds/funders_v1.json"
RAW_DIR = ROOT / "experiments/funding/raw"
STARTER_PATH = ROOT / "experiments/funding/seeds/starter_funding.json"
ENRICHED = ROOT / "experiments/funding/enrich/enriched.json"
OUT = ROOT / "src/data/funding.json"
GENERATED_AT = "2026-07-09"

# ── Rule 11: FX rates ─────────────────────────────────────────────────────────
FX = {"year": 2025, "GBP": 1.27, "EUR": 1.08}

# ── Private keys must never reach the public file ────────────────────────────
# (mirrors build_network.py; note 'notes' is legal INSIDE apply{} but not as a
# top-level node key — rule 13)
PRIVATE_KEYS = {"warm_path", "stage", "priority"}
# 'notes' at top-level is also private per rule 13, handled separately

# ── Starter node IDs (FROZEN per rule 1) ─────────────────────────────────────
STARTER_FUNDER_IDS = {
    "coefficient-giving",
    "survival-and-flourishing-fund",
    "ltff",
    "manifund",
    "schmidt-sciences",
    "macroscopic-ventures",
    "foresight-institute",
    "future-of-life-institute",
    "nsf",
    "uk-aisi",
    "aria",
    "openai-programs",
    "anthropic-programs",
    "frontier-model-forum-aisf",
    "menlo-ventures",
    "sequoia-capital",
    "insight-partners",
    # reclassified 2026-07-05: CAIF gives grants (research grants, PhD
    # fellowships, co-funds the multi-agent joint call) — funder, not grantee
    "cooperative-ai-foundation",
}
STARTER_GRANTEE_IDS = {
    "far-ai",
    "redwood-research",
    "metr",
    "apollo-research",
    "eleutherai",
    "mats",
    "cais",
    "timaeus",
    "cmu-focal",
    "irregular",
    "promptfoo",
    # agent-security / evals startups with verified investor edges (2026-07-06)
    "goodfire",
    "gray-swan-ai",
    "andon-labs",
    "braintrust",
    "seven-ai",
    "exaforce",
    "surf-ai",
    "oasis-security",
    "bold-security",
    "haize-labs",
    "descope",
}
STARTER_PERSON_IDS = {
    "austin-chen",
    "allison-duettmann",
    "anthony-aguirre",
    # CAIF staff, added with the 2026-07-05 funder reclassification
    "lewis-hammond",
    "cecilia-elena-tilli",
}
ALL_STARTER_IDS = STARTER_FUNDER_IDS | STARTER_GRANTEE_IDS | STARTER_PERSON_IDS

# ── CG programs relevant to the AI safety field ──────────────────────────────
# Only count CG grants in these programs for field-$ purposes (rule 2)
CG_RELEVANT_PROGRAMS = {
    # AI slice only. Plain "Global Catastrophic Risks" is a mixed bucket
    # (climate intervention, nukes — e.g. The Degrees Initiative) and
    # biosecurity has its own programs; neither belongs on an AI-safety map.
    "Potential Risks from Advanced AI",
    "Global Catastrophic Risks Capacity Building",  # field-building pipeline (80k, BlueDot, ...)
}

# ── Grantee alias map for entity resolution (rule 5) ─────────────────────────
# Maps lowercased grantee name variants → existing node id
GRANTEE_ALIASES: dict[str, str] = {
    # far-ai
    "far ai": "far-ai",
    "far.ai": "far-ai",
    "far ai inc": "far-ai",
    "foundational alignment research": "far-ai",
    # redwood-research
    "redwood research": "redwood-research",
    "redwood research group": "redwood-research",
    "redwood research group inc": "redwood-research",
    # metr
    "metr": "metr",
    "model evaluation and threat research": "metr",
    "model evaluation and threat research inc": "metr",
    "arc evals": "metr",
    "arc-evals": "metr",
    # apollo-research
    "apollo research": "apollo-research",
    "apollo research ai foundation": "apollo-research",
    "apollo research foundation": "apollo-research",
    # eleutherai
    "eleutherai": "eleutherai",
    "eleuther ai": "eleutherai",
    "eleutherai institute": "eleutherai",
    # mats
    "mats": "mats",
    "ml alignment theory scholars": "mats",
    "mats research": "mats",
    "seri ml alignment & theory scholars": "mats",
    "seri mats": "mats",
    # cais
    "center for ai safety": "cais",
    "cais": "cais",
    "center for ai safety inc": "cais",
    "center for ai safety action fund inc": "cais",
    "centre for ai safety": "cais",
    "center for ai safety (cais)": "cais",
    "center for ai safety inc.": "cais",
    # the 501(c)(4) Action Fund is mapped into the same public-map entity
    "center for ai safety action fund (cais af)": "cais",
    # far-ai's founding name (renamed from "Fund for Alignment Research" ~2023)
    "fund for alignment research (far)": "far-ai",
    # timaeus
    "timaeus": "timaeus",
    "timaeus (fiscally sponsored by ashgro, inc.)": "timaeus",
    # cooperative-ai-foundation
    "cooperative ai foundation": "cooperative-ai-foundation",
    "caif": "cooperative-ai-foundation",
    # cmu-focal
    "cmu focal": "cmu-focal",
    "focal lab": "cmu-focal",
    "carnegie mellon focal": "cmu-focal",
    "foundations of cooperative ai lab": "cmu-focal",
    # irregular
    "irregular": "irregular",
    "irregular.ai": "irregular",
    # promptfoo
    "promptfoo": "promptfoo",
    # Also accept some common misspellings / alternates for SFF grantees
    "machine intelligence research institute": "miri",  # new node (added below)
    "miri": "miri",
    "the machine intelligence research institute": "miri",
    # mila (pre-registered): CG lists it under two names
    "mila": "mila",
    "montreal institute for learning algorithms": "mila",
    # lightcone-infrastructure (pre-registered): LessWrong is Lightcone's product
    "lightcone infrastructure": "lightcone-infrastructure",
    "lesswrong": "lightcone-infrastructure",
    # ARC's evals team spun out as METR (already aliased as "arc evals")
    "alignment research center (evals team)": "metr",
    # funders that appear as grant RECIPIENTS in fetched data — route to the
    # funder id so the kind-check drops the records instead of duplicating
    # the entity as a grantee (NSF received Open Phil co-funding for SLES;
    # LTFF receives regrants)
    "national science foundation": "nsf",
    "long-term future fund": "ltff",
}


def norm(s: str) -> str:
    """Loose key for matching grantee names (strips common suffixes, punct)."""
    s = s.lower().strip()
    # Remove fiscal sponsorship notes
    s = re.sub(r"\s*\(fiscally sponsored[^)]*\)", "", s)
    # Remove common legal suffixes
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|foundation|institute|the)\b\.?", "", s)
    return re.sub(r"[^a-z0-9]", "", s).strip()


def resolve_grantee(name: str) -> str | None:
    """Return existing node id for a grantee name, or None if unknown."""
    if not name:
        return None
    key = name.lower().strip()
    if key in GRANTEE_ALIASES:
        return GRANTEE_ALIASES[key]
    # Norm-based fallback
    n = norm(name)
    for alias, nid in GRANTEE_ALIASES.items():
        if norm(alias) == n and n:
            return nid
    return None


def slug(s: str) -> str:
    """Convert name to a stable hyphenated id slug."""
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


def gbp_to_usd(gbp: float) -> float:
    """Convert GBP to USD at pinned FX rate (rule 11)."""
    return gbp * FX["GBP"]


def eur_to_usd(eur: float) -> float:
    """Convert EUR to USD at pinned FX rate (rule 11)."""
    return eur * FX["EUR"]


def latest_complete_year(records: list[dict]) -> int | None:
    """Latest year whose record COUNT ≥ 30% of prior year's AND ≥ 10 records.

    The 30% threshold detects partial/truncated years; the 10-record floor
    prevents years with only a handful of records from qualifying as 'complete'
    (e.g. NSF 2025 has 8 records = 33% of 2024, but 8 < 10).
    Plan rule: 'use the latest year whose grant COUNT ≥ 30% of the prior year's'.
    """
    year_counts: dict[int, int] = defaultdict(int)
    for r in records:
        t = r.get("record_type") or r.get("type", "")
        if t != "grant":
            continue
        y = r.get("year")
        if y is not None:
            year_counts[int(y)] += 1

    if not year_counts:
        return None

    years = sorted(year_counts)
    best = years[0]
    for i in range(1, len(years)):
        y, prev = years[i], years[i - 1]
        ratio = year_counts[y] / year_counts[prev] if year_counts[prev] > 0 else 0
        if ratio >= 0.30 and year_counts[y] >= 10:
            best = y
    return best


def load_normalized(source_key: str) -> list[dict]:
    """Load records from raw/normalized_<source_key>.json."""
    path = RAW_DIR / f"normalized_{source_key}.json"
    if not path.exists():
        print(f"  WARN: {path.name} not found — skipping", file=sys.stderr)
        return []
    data = json.loads(path.read_text())
    return data.get("records", [])


def fetched_at(source_key: str) -> str:
    """Return the real fetch timestamp from raw/normalized_<source_key>.json.

    Falls back to GENERATED_AT if the file is absent or lacks a 'fetched' key.
    The returned value is the ISO-8601 string stored by the fetcher (e.g.
    '2026-07-03T23:14:50.416428+00:00'); callers embed it in meta.sources.
    """
    path = RAW_DIR / f"normalized_{source_key}.json"
    if not path.exists():
        return GENERATED_AT
    try:
        data = json.loads(path.read_text())
        return data.get("fetched") or GENERATED_AT
    except (json.JSONDecodeError, OSError):
        return GENERATED_AT


def aggregate_edge_records(records: list[dict]) -> dict:
    """Aggregate multiple grant records for the same (funder, grantee) pair.

    Rule 6: per funder→grantee pair, ONE aggregated edge:
      amountUSD = sum (nulls excluded; if ALL null → null)
      year      = latest year
      multiYear  = {start, end} if grants span >1 year
      program   = most frequent program string
      sourceUrl = source's canonical URL
      verified  = true
    """
    amounts = [r.get("amount_usd") for r in records if r.get("amount_usd") is not None]
    years = sorted(set(r.get("year") for r in records if r.get("year") is not None))
    programs = [r.get("program", "") for r in records if r.get("program")]
    source_urls = [r.get("source_url", "") for r in records if r.get("source_url")]
    payers = [r.get("payer_hint") for r in records]

    # The program label must describe the AGGREGATE, not one constituent — a
    # reader following sourceUrl has to be able to reconstruct the sum
    # (spot-check finding, 2026-07-03). Single-round pairs keep the round name;
    # multi-round pairs get an explicit count+span; NSF pairs list award ids so
    # the per-award sourceUrl plus the ids verify the total.
    label: str | None = Counter(programs).most_common(1)[0][0] if programs else None
    if len(records) > 1 and programs and len(set(programs)) > 1:
        span = f" {min(years)}–{max(years)}" if len(years) > 1 else ""
        label = f"{len(records)} grants{span} ({Counter(programs).most_common(1)[0][0]} a.o.)"
    award_ids = [u.split("AWD_ID=")[1] for u in source_urls if "AWD_ID=" in u]
    if len(records) > 1 and len(award_ids) > 1:
        label = f"{label or 'awards'} · awards {', '.join(sorted(set(award_ids)))}"

    agg: dict[str, Any] = {
        "amountUSD": sum(amounts) if amounts else None,
        "year": max(years) if years else None,
        "program": label,
        "sourceUrl": source_urls[0] if source_urls else None,
        "verified": True,
        "_payers": payers,  # internal; removed before emit
        "_nrecords": len(records),  # internal; drives the final aggregate label
        "_award_ids": sorted(set(award_ids)),  # internal; NSF verifiability
    }
    if len(years) > 1:
        agg["multiYear"] = {"start": min(years), "end": max(years)}
    return agg


def apply_enrichment(
    nodes: list[dict],
    nodes_by_id: dict[str, dict],
    all_edges: list[dict],
    valid_domain_ids: set[str],
) -> dict[str, Any]:
    """Merge enrich/enriched.json (research-swarm output; plan-2 step 4).

    Funder records admit the seeded-but-unfetched funders: blurb/thesis/apply/
    checkSize/domains/people come from the swarm's verified records; a dollar
    figure is accepted ONLY with basis.sourceUrl (refused here before the
    validator would refuse it). Grantee records replace the auto-added
    placeholder blurbs; defunct=true removes the node and its edges — a
    landscape map shows live orgs.
    """
    report: dict[str, Any] = {
        "funders_added": [],
        "funders_skipped": [],
        "dollars_nulled": [],
        "grantees_updated": 0,
        "grantees_removed": [],
        "people_added": 0,
    }
    if not ENRICHED.exists():
        report["funders_skipped"].append("enriched.json absent — swarm not run yet")
        return report
    enriched = json.loads(ENRICHED.read_text())
    seeds_by_id = {s["id"]: s for s in json.loads(SEEDS.read_text())["funders"]}

    for rec in enriched.get("funders", []):
        fid = rec.get("id")
        seed = seeds_by_id.get(fid)
        if not seed:
            report["funders_skipped"].append(f"{fid}: not in seeds")
            continue
        if fid in nodes_by_id:
            report["funders_skipped"].append(f"{fid}: already emitted")
            continue
        sources = [
            {
                "url": s["url"],
                "accessed": GENERATED_AT,
                **({"title": s["title"]} if s.get("title") else {}),
            }
            for s in rec.get("sources", [])
            if str(s.get("url", "")).startswith("http")
        ]
        if not sources or not rec.get("blurb") or not rec.get("apply", {}).get("mode"):
            report["funders_skipped"].append(f"{fid}: missing blurb/apply/sources")
            continue
        annual = rec.get("annualFieldGivingUSD")
        basis = rec.get("annualFieldGivingBasis")
        if annual is not None and not (
            basis and str(basis.get("sourceUrl", "")).startswith("http")
        ):
            annual, basis = None, None  # every $ needs a source — null it, never guess
            report["dollars_nulled"].append(fid)
        apply_rec: dict[str, Any] = {
            "mode": rec["apply"]["mode"],
            "lastVerified": GENERATED_AT,
        }
        for k in ("url", "deadline", "notes"):
            v = rec["apply"].get(k)
            if v:
                apply_rec[k] = v
        # a stale deadline would fail validation; demote to closed at build time
        if (
            apply_rec["mode"] == "rounds"
            and apply_rec.get("deadline")
            and apply_rec["deadline"] < GENERATED_AT
        ):
            apply_rec["mode"] = "closed"
            apply_rec["notes"] = (
                apply_rec.get("notes", "") + " (deadline passed; demoted at build)"
            ).strip()
            del apply_rec["deadline"]
        node: dict[str, Any] = {
            "id": fid,
            "kind": "funder",
            "name": seed["name"],
            "funderKind": seed["funderKind"],
            "blurb": rec["blurb"],
            "domainTags": [
                t for t in rec.get("domainTags", []) if t in valid_domain_ids
            ],
            "annualFieldGivingUSD": annual,
            "apply": apply_rec,
            "confidence": rec.get("confidence", "medium"),
            "priorityRank": 0,  # recomputed with everyone else below
            "sources": sources,
            "lastVerified": GENERATED_AT,
            "fieldDollarsUSD": annual if annual is not None else 0,
        }
        aliases = sorted(set(seed.get("aliases", [])) | set(rec.get("aliases", [])))
        if aliases:
            node["aliases"] = aliases
        if basis:
            node["annualFieldGivingBasis"] = {
                "year": basis["year"],
                "method": basis["method"],
                "sourceUrl": basis["sourceUrl"],
                **({"kind": basis["kind"]} if basis.get("kind") else {}),
            }
        if seed.get("networksId"):
            node["networksId"] = seed["networksId"]
        if rec.get("thesis"):
            node["thesis"] = rec["thesis"]
        if rec.get("checkSizeUSD"):
            node["checkSizeUSD"] = rec["checkSizeUSD"]
        if rec.get("inKind"):
            node["inKind"] = True
        if rec.get("url"):
            node["url"] = rec["url"]
        nodes.append(node)
        nodes_by_id[fid] = node
        report["funders_added"].append(fid)
        for p in (rec.get("people") or [])[:2]:
            pid = slug(p["name"])
            if pid in nodes_by_id or not str(p.get("sourceUrl", "")).startswith("http"):
                continue
            pnode: dict[str, Any] = {
                "id": pid,
                "kind": "person",
                "name": p["name"],
                "title": p["title"],
                "blurb": f"{p['title']} — {seed['name']}.",
                "confidence": "medium",
                "priorityRank": 0,
                "sources": [{"url": p["sourceUrl"], "accessed": GENERATED_AT}],
                "lastVerified": GENERATED_AT,
                "fieldDollarsUSD": 0,
            }
            if p.get("profileUrl"):
                pnode["profileUrl"] = p["profileUrl"]
            nodes.append(pnode)
            nodes_by_id[pid] = pnode
            all_edges.append(
                {
                    "type": "affiliation",
                    "source": pid,
                    "target": fid,
                    "role": p["title"],
                    "current": True,
                    "sourceUrl": p["sourceUrl"],
                }
            )
            report["people_added"] += 1

    removed_ids: set[str] = set()
    for rec in enriched.get("grantees", []):
        gid = rec.get("id")
        gnode = nodes_by_id.get(gid)
        if not gnode or gnode["kind"] != "grantee":
            continue
        if rec.get("defunct"):
            removed_ids.add(gid)
            continue
        if rec.get("blurb"):
            gnode["blurb"] = rec["blurb"]
        if rec.get("granteeKind") in {
            "research-org",
            "university",
            "startup",
            "fieldbuilding",
        }:
            gnode["granteeKind"] = rec["granteeKind"]
        tags = [t for t in rec.get("domainTags", []) if t in valid_domain_ids]
        if tags:
            gnode["domainTags"] = tags
        if rec.get("url"):
            gnode["url"] = rec["url"]
        for s in rec.get("sources", []):
            u = str(s.get("url", ""))
            if u.startswith("http") and all(x["url"] != u for x in gnode["sources"]):
                gnode["sources"].append({"url": u, "accessed": GENERATED_AT})
        report["grantees_updated"] += 1

    if removed_ids:
        nodes[:] = [n for n in nodes if n["id"] not in removed_ids]
        for rid in removed_ids:
            del nodes_by_id[rid]
        all_edges[:] = [
            e
            for e in all_edges
            if e["source"] not in removed_ids and e["target"] not in removed_ids
        ]
        report["grantees_removed"] = sorted(removed_ids)
    return report


def main() -> int:  # noqa: C901 (complex but sequential)
    # ── Load seeds ─────────────────────────────────────────────────────────
    seeds_data = json.loads(SEEDS.read_text())
    seed_ids = {s["id"] for s in seeds_data["funders"]}
    seed_by_id = {s["id"]: s for s in seeds_data["funders"]}

    # Rule 1: assert frozen funder ids ⊇ starter funder ids
    assert (
        STARTER_FUNDER_IDS <= seed_ids
    ), f"Seeds missing starter funder IDs: {STARTER_FUNDER_IDS - seed_ids}"

    # ── Load starter data ───────────────────────────────────────────────────
    starter = json.loads(STARTER_PATH.read_text())
    starter_nodes_by_id: dict[str, dict] = {n["id"]: n for n in starter["nodes"]}
    assert ALL_STARTER_IDS == set(starter_nodes_by_id), (
        f"Starter id mismatch: extra={set(starter_nodes_by_id)-ALL_STARTER_IDS}, "
        f"missing={ALL_STARTER_IDS-set(starter_nodes_by_id)}"
    )

    # ── Load normalized sources ─────────────────────────────────────────────
    cg_records = load_normalized("coefficient")
    sff_records = load_normalized("sff")
    ltff_records = load_normalized("eafunds")
    nsf_records = load_normalized("nsf")
    manifund_records = load_normalized("manifund")
    govuk_records = load_normalized("gov_uk")

    # ── Rule 2: compute annualFieldGivingUSD from fetched data ─────────────

    # coefficient-giving: use archive funder_total record (year 2024, $126.9M)
    cg_total_record = next(
        (
            r
            for r in cg_records
            if r.get("record_type") == "funder_total"
            and r.get("funder_hint") == "coefficient-giving"
        ),
        None,
    )
    assert (
        cg_total_record is not None
    ), "CG funder_total record missing from normalized_coefficient.json"
    # Recompute CY2024 from the build's own program slice so the headline
    # figure matches exactly the grants this map admits (the fetcher's
    # funder_total used a looser filter that included biosecurity).
    cg_2024 = [
        r
        for r in cg_records
        if r.get("record_type") == "grant"
        and r.get("year") == 2024
        and r.get("program") in CG_RELEVANT_PROGRAMS
        and r.get("amount_usd") is not None
    ]
    assert (
        len(cg_2024) >= 50
    ), f"CG CY2024 slice suspiciously small: {len(cg_2024)} grants"
    cg_annual = sum(r["amount_usd"] for r in cg_2024)
    cg_basis = {
        "year": 2024,
        "method": "sum of CY2024 grants in the archived Open Phil grants DB, programs: "
        + " + ".join(sorted(CG_RELEVANT_PROGRAMS)),
        "sourceUrl": cg_total_record["source_url"],
    }

    # survival-and-flourishing-fund: recompute CY2025 sum from grant records (rule 2)
    sff_2025_grants = [
        r
        for r in sff_records
        if (r.get("record_type") == "grant") and r.get("year") == 2025
    ]
    sff_annual = sum(
        r["amount_usd"] for r in sff_2025_grants if r.get("amount_usd") is not None
    )
    sff_count_2025 = len(sff_2025_grants)
    assert sff_count_2025 >= 50, f"Expected ≥50 SFF 2025 grants, got {sff_count_2025}"
    sff_basis = {
        "year": 2025,
        "method": "sum of SFF 2025 rows from the public recommendations table (grant records recomputed)",
        "sourceUrl": "https://survivalandflourishing.fund/recommendations",
    }

    # jaan-tallinn: his single-payer 2025 SFF sum (rule 4 / rule 3)
    # All 2025 SFF grants have payer_hint='jaan-tallinn' (verified in analysis)
    jt_funder_total = next(
        (
            r
            for r in sff_records
            if r.get("record_type") == "funder_total"
            and r.get("funder_hint") == "jaan-tallinn"
            and r.get("year") == 2025
        ),
        None,
    )
    assert (
        jt_funder_total is not None
    ), "jaan-tallinn funder_total missing from normalized_sff.json"
    jt_annual = jt_funder_total["amount_usd"]
    jt_basis = {
        "year": 2025,
        "method": jt_funder_total["method"],
        "sourceUrl": jt_funder_total["source_url"],
    }

    # ltff: latest complete year rule (rule 2)
    ltff_year = latest_complete_year(ltff_records)
    assert ltff_year is not None, "Could not determine LTFF latest complete year"
    ltff_year_grants = [
        r
        for r in ltff_records
        if (r.get("type") == "grant" or r.get("record_type") == "grant")
        and r.get("year") == ltff_year
    ]
    ltff_annual = sum(
        r["amount_usd"] for r in ltff_year_grants if r.get("amount_usd") is not None
    )
    ltff_basis = {
        "year": ltff_year,
        "method": (
            f"sum of LTFF grant records CY{ltff_year} (latest complete year: "
            f"{len(ltff_year_grants)} records, ≥30% of prior year's count)"
        ),
        "sourceUrl": "https://funds.effectivealtruism.org/api/grants",
    }
    print(
        f"  LTFF latest complete year: {ltff_year} ({len(ltff_year_grants)} records, ${ltff_annual:,.0f})"
    )

    # nsf: latest complete year rule (rule 2; method notes SLES+keyword slice)
    nsf_grant_records = [
        r
        for r in nsf_records
        if (r.get("type") == "grant" or r.get("record_type") == "grant")
    ]
    nsf_year = latest_complete_year(nsf_records)
    assert nsf_year is not None, "Could not determine NSF latest complete year"
    nsf_year_grants = [r for r in nsf_grant_records if r.get("year") == nsf_year]
    nsf_annual = sum(
        r["amount_usd"] for r in nsf_year_grants if r.get("amount_usd") is not None
    )
    nsf_basis = {
        "year": nsf_year,
        "method": (
            f"sum of field-relevant NSF awards CY{nsf_year} (latest complete year: "
            f"{len(nsf_year_grants)} records; SLES+keyword slice — not all of NSF)"
        ),
        "sourceUrl": "https://resources.research.gov/common/webapi/awardapisearch-v1.htm",
    }
    print(
        f"  NSF latest complete year: {nsf_year} ({len(nsf_year_grants)} records, ${nsf_annual:,.0f})"
    )

    # ── Rule 10: gov_uk apply_status for aria and uk-aisi ──────────────────
    aria_apply_status = next(
        (
            r
            for r in govuk_records
            if r.get("record_type") == "apply_status"
            and r.get("funder_hint") == "aria"
            and r.get("deadline") is not None
        ),
        None,
    )
    aisi_apply_status = next(
        (
            r
            for r in govuk_records
            if r.get("record_type") == "apply_status"
            and r.get("funder_hint") == "uk-aisi"
        ),
        None,
    )

    # ── Build node set: start from starter, then layer changes ─────────────

    # Deep-copy starter nodes; we'll mutate the funder nodes
    nodes: list[dict] = []
    for n in starter["nodes"]:
        import copy

        nodes.append(copy.deepcopy(n))

    nodes_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    # ── Rule 2: update annualFieldGivingUSD for key funders ────────────────

    def update_funder_dollars(
        funder_id: str, annual: float | None, basis: dict | None
    ) -> None:
        n = nodes_by_id[funder_id]
        n["annualFieldGivingUSD"] = annual
        if annual is not None:
            n["annualFieldGivingBasis"] = basis
        elif "annualFieldGivingBasis" in n:
            del n["annualFieldGivingBasis"]
        n["fieldDollarsUSD"] = annual if annual is not None else 0

    update_funder_dollars("coefficient-giving", cg_annual, cg_basis)
    update_funder_dollars("survival-and-flourishing-fund", sff_annual, sff_basis)
    update_funder_dollars("ltff", ltff_annual, ltff_basis)
    update_funder_dollars("nsf", nsf_annual, nsf_basis)

    # ── Rule 10: update aria apply from gov_uk live data ───────────────────
    aria_node = nodes_by_id["aria"]
    if aria_apply_status:
        # Rule 10 specifies exact fields for aria.apply
        aria_node["apply"] = {
            "mode": "rounds",
            "url": "https://aria.org.uk/funding-opportunities",
            "deadline": aria_apply_status.get("deadline", "2026-07-27"),
            "notes": (
                "Opportunity Seeds: up to £500k/project; "
                "Safeguarded AI TA rounds announced separately"
            ),
            "lastVerified": GENERATED_AT,
        }
    else:
        # Fallback: keep existing apply but update lastVerified
        aria_node["apply"]["lastVerified"] = GENERATED_AT

    # uk-aisi: closed with reopen-summer-2026 note
    aisi_node = nodes_by_id["uk-aisi"]
    aisi_node["apply"] = {
        "mode": "closed",
        "url": "https://alignmentproject.aisi.gov.uk/",
        "notes": "round 1 closed; reopens summer 2026",
        "lastVerified": GENERATED_AT,
    }

    # ── Pre-register merge-target nodes before resolution loop ──────────────
    # These grantees appear in the fetched data under MULTIPLE names (all
    # mapped to one id in GRANTEE_ALIASES). The node must exist in nodes_by_id
    # BEFORE raw_pairs are processed so every name variant's grants land on
    # the same node instead of auto-admitting duplicates (MILA vs "Montreal
    # Institute for Learning Algorithms"; LessWrong is run by Lightcone).
    # Pre-registered nodes are NOT counted against the auto-admit budget.
    PREREGISTERED_GRANTEES: list[dict[str, Any]] = [
        {
            "id": "miri",
            "name": "Machine Intelligence Research Institute",
            "aliases": ["MIRI"],
        },
        {
            "id": "mila",
            "name": "Mila — Quebec AI Institute",
            "aliases": ["MILA", "Montreal Institute for Learning Algorithms"],
        },
        {
            "id": "lightcone-infrastructure",
            "name": "Lightcone Infrastructure",
            "aliases": ["LessWrong"],
        },
    ]
    for pre in PREREGISTERED_GRANTEES:
        node_pre: dict[str, Any] = {
            "id": pre["id"],
            "kind": "grantee",
            "name": pre["name"],
            "aliases": pre["aliases"],
            "granteeKind": "research-org",
            "blurb": "AI-safety grantee (auto-added from coefficient, sff; details pending enrichment)",
            "domainTags": [],
            "confidence": "medium",
            "sources": [
                {
                    "url": "https://github.com/rufuspollock/open-philanthropy-grants",
                    "accessed": GENERATED_AT,
                }
            ],
            "lastVerified": GENERATED_AT,
            "fieldDollarsUSD": 0,  # recomputed below
        }
        nodes.append(node_pre)
        nodes_by_id[pre["id"]] = node_pre

    # ── Rule 3: add jaan-tallinn as new funder node ─────────────────────────
    jt_node: dict[str, Any] = {
        "id": "jaan-tallinn",
        "kind": "funder",
        "name": "Jaan Tallinn",
        "aliases": ["Jaan Tallinn"],
        "funderKind": "philanthropy",
        "blurb": (
            "Skype/Kazaa co-founder; the largest individual payer behind "
            "SFF's s-process rounds."
        ),
        "domainTags": ["technical-alignment", "policy-governance", "field-building"],
        "annualFieldGivingUSD": jt_annual,
        "annualFieldGivingBasis": jt_basis,
        "apply": {
            "mode": "invite-only",
            "lastVerified": GENERATED_AT,
        },
        "confidence": "high",
        "url": "https://jaan.online",
        "sources": [{"url": jt_basis["sourceUrl"], "accessed": GENERATED_AT}],
        "lastVerified": GENERATED_AT,
        "fieldDollarsUSD": jt_annual,
    }
    nodes.append(jt_node)
    nodes_by_id["jaan-tallinn"] = jt_node

    # ── Rule 5/6: Aggregate fetched grant records into edges ────────────────

    # Collect all fetched grants from the primary sources
    # (funder_id, grantee_name) → list of record dicts
    raw_pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)

    def add_grant_records(
        records: list[dict], source_filter: str | None = None
    ) -> None:
        for r in records:
            t = r.get("record_type") or r.get("type", "")
            if t != "grant":
                continue
            funder = r.get("funder_hint", "")
            grantee = r.get("grantee_name", "")
            if not grantee or grantee.startswith("(") or grantee.lower() == "anonymous":
                continue
            raw_pairs[(funder, grantee)].append(r)

    # Rule 6: aggregate ALL fetched grants into edges (the latest-complete-year
    # filters above apply ONLY to rule-2 annualFieldGivingUSD, not to edges).
    # CG judgment call: restrict to AI-safety-relevant programs — the archive
    # also contains Biosecurity/Pandemic grants (Johns Hopkins CHS, Sherlock
    # Biosciences ...) that would pollute an AI-safety funder map.
    cg_grant_records = [
        r
        for r in cg_records
        if r.get("record_type") == "grant"
        and r.get("program", "") in CG_RELEVANT_PROGRAMS
    ]
    add_grant_records(cg_grant_records)

    # SFF: all grant records (all rounds, 2019-2025)
    add_grant_records([r for r in sff_records if r.get("record_type") == "grant"])

    # LTFF: all grant records
    add_grant_records(
        [
            r
            for r in ltff_records
            if (r.get("type") == "grant" or r.get("record_type") == "grant")
        ]
    )

    # NSF: all grant records (field-relevant slice by construction)
    add_grant_records(
        [
            r
            for r in nsf_records
            if (r.get("type") == "grant" or r.get("record_type") == "grant")
        ]
    )

    # ── Resolve grantees and build edge pairs ───────────────────────────────
    # (funder_id, grantee_id) → aggregated edge data
    fetched_edges: dict[tuple[str, str], dict] = {}

    # Track unresolved grantees for new node admission
    unresolved_grantees: dict[str, dict] = defaultdict(
        lambda: {"total": 0.0, "count": 0, "sources": set(), "source_url": None}
    )

    # funder_hint → human-readable source name (for the auto-added blurb)
    FUNDER_TO_SOURCE = {
        "coefficient-giving": "coefficient",
        "survival-and-flourishing-fund": "sff",
        "ltff": "eafunds",
        "nsf": "nsf",
        "aistof": "manifund",  # AISTOF regrants flow through Manifund rails
    }

    for (funder_hint, grantee_name), records in raw_pairs.items():
        grantee_id = resolve_grantee(grantee_name)
        if not grantee_id:
            # Track for possible new node admission
            amt = sum(
                r["amount_usd"] for r in records if r.get("amount_usd") is not None
            )
            unresolved_grantees[grantee_name]["total"] += amt
            unresolved_grantees[grantee_name]["count"] += len(records)
            unresolved_grantees[grantee_name]["sources"].add(
                FUNDER_TO_SOURCE.get(funder_hint, funder_hint)
            )
            for r in records:
                if (
                    r.get("source_url")
                    and unresolved_grantees[grantee_name]["source_url"] is None
                ):
                    unresolved_grantees[grantee_name]["source_url"] = r["source_url"]
            continue

        # Check funder is known
        if funder_hint not in nodes_by_id:
            continue  # skip records from unknown funders

        # Check grantee is a grantee node (not a funder)
        if nodes_by_id.get(grantee_id, {}).get("kind") != "grantee":
            continue

        pair = (funder_hint, grantee_id)
        if pair not in fetched_edges:
            fetched_edges[pair] = aggregate_edge_records(records)
        else:
            # Merge additional records into existing aggregate
            existing = fetched_edges[pair]
            new_agg = aggregate_edge_records(records)
            # Combine amounts
            existing_amt = existing.get("amountUSD")
            new_amt = new_agg.get("amountUSD")
            if existing_amt is not None and new_amt is not None:
                existing["amountUSD"] = existing_amt + new_amt
            elif new_amt is not None:
                existing["amountUSD"] = new_amt
            # Extend multiYear if needed
            existing_years = set()
            if existing.get("year"):
                existing_years.add(existing["year"])
            if existing.get("multiYear"):
                existing_years.update(
                    range(
                        existing["multiYear"]["start"], existing["multiYear"]["end"] + 1
                    )
                )
            if new_agg.get("year"):
                existing_years.add(new_agg["year"])
            if len(existing_years) > 1:
                existing["multiYear"] = {
                    "start": min(existing_years),
                    "end": max(existing_years),
                }
                existing["year"] = max(existing_years)
            elif existing_years:
                existing["year"] = max(existing_years)
            # Update payers list + internal aggregate-label bookkeeping
            existing.setdefault("_payers", []).extend(new_agg.get("_payers", []))
            existing["_nrecords"] = existing.get("_nrecords", 1) + new_agg.get(
                "_nrecords", 1
            )
            existing["_award_ids"] = sorted(
                set(existing.get("_award_ids", [])) | set(new_agg.get("_award_ids", []))
            )

    # ── Rule 4: SFF regrantOf logic + _payers cleanup ───────────────────────
    # regrantOf only if ALL rows in the pair share exactly 'jaan-tallinn' as payer.
    # Compound/other payers → no regrantOf, no new payer nodes.
    for pair, agg in list(fetched_edges.items()):
        funder_id, _ = pair
        payers = agg.pop("_payers", [])  # always remove internal field before emit
        if funder_id == "survival-and-flourishing-fund":
            payers_set = set(p for p in payers if p is not None)
            if payers_set == {"jaan-tallinn"}:
                agg["regrantOf"] = "jaan-tallinn"
            # else: mixed/other payers → no regrantOf (compound payers, rule 4)

    # ── Rule 5: Admit top 15 new grantees ───────────────────────────────────
    # MIRI was pre-registered above (before resolution loop) so its grants are
    # already in fetched_edges. It is NOT counted in the top-15 budget below.

    # Sort unresolved by total $ and admit top 15 (excluding MIRI which is already resolved)
    unresolved_sorted = sorted(
        unresolved_grantees.items(),
        key=lambda x: -x[1]["total"],
    )

    # Build new grantee nodes (top 15)
    new_grantee_nodes: list[dict] = []
    new_grantee_id_map: dict[str, str] = {}  # grantee_name → node_id

    # Pre-defined slug mappings for clean IDs
    SLUG_OVERRIDES: dict[str, str] = {
        "Center for Security and Emerging Technology": "cset",
        "Centre for Effective Altruism": "centre-for-effective-altruism",
        "Effective Ventures Foundation": "effective-ventures-foundation",
        "80,000 Hours": "80000-hours",
        "OpenAI": "openai",
        "Effective Ventures Foundation USA": "effective-ventures-foundation-usa",
        "Effective Altruism Funds": "effective-altruism-funds",
        "RAND Corporation": "rand-corporation",
        "University of California, Berkeley": "uc-berkeley",
        "Future of Humanity Institute": "future-of-humanity-institute",
        "Massachusetts Institute of Technology": "mit",
        "Berkeley Existential Risk Initiative": "beri",
        "Lightcone Infrastructure": "lightcone-infrastructure",
        "Epoch": "epoch",
    }

    # Controller exclusions (2026-07-03): keep the public map honest. These rank
    # in the top-15 by raw archive dollars but distort a "who funds the field
    # NOW" landscape: umbrella/regrant vehicles double-count money that
    # re-emerges downstream (CEA/EVF/EA Funds ⊃ LTFF), OpenAI's $30M is a 2017
    # grant that reads as a funder on this map, and FHI dissolved in 2024.
    AUTO_ADMIT_EXCLUDE: dict[str, str] = {
        "OpenAI": "frontier lab; 2017 OP grant is history — reads as funder here",
        "Centre for Effective Altruism": "umbrella/regrant vehicle (double-counts the LTFF chain)",
        "Effective Ventures Foundation": "umbrella/regrant vehicle",
        "Effective Ventures Foundation USA": "umbrella/regrant vehicle",
        "Effective Altruism Funds": "regrant vehicle (parent of LTFF)",
        "Future of Humanity Institute": "dissolved 2024; historical grants only",
        "Open Phil AI Fellowship": "Coefficient Giving's own internal program, not an independent grantee",
        "Founders Pledge": "regrant vehicle; seeded as a funder (founders-pledge-gcr)",
        "Longview Philanthropy": "regrant vehicle; seeded as a funder (longview-philanthropy)",
        "Atlas Fellowship": "program discontinued (atlasfellowship.org, verified 2026-07-03)",
        # cap-45 curation (2026-07-06):
        "Centre for Effective Altruism,Effective Ventures Foundation USA": (
            "compound source record for the CEA/EVF umbrella (already excluded)"
        ),
        "SecureDNA": "biosecurity org (SFF's broader scope) — not an AI-safety grantee",
    }
    excluded_grantees: list[tuple[str, float, str]] = []

    admitted_count = 0

    for grantee_name, info in unresolved_sorted:
        if grantee_name in AUTO_ADMIT_EXCLUDE:
            excluded_grantees.append(
                (grantee_name, info["total"], AUTO_ADMIT_EXCLUDE[grantee_name])
            )
            continue
        if admitted_count >= 45:
            continue  # below top-15 → dropped (recomputed + reported below)

        grantee_id = SLUG_OVERRIDES.get(grantee_name) or slug(grantee_name)

        # Skip if id conflicts with existing nodes or miri
        if grantee_id in nodes_by_id or grantee_id == "miri":
            continue

        # Determine granteeKind: university if name contains University/Institute of Technology/College
        name_lower = grantee_name.lower()
        if (
            "university" in name_lower
            or "institute of technology" in name_lower
            or "college" in name_lower
        ):
            grantee_kind = "university"
        else:
            grantee_kind = "research-org"

        # Source label for blurb
        sources_label = ", ".join(sorted(info["sources"]))
        node: dict[str, Any] = {
            "id": grantee_id,
            "kind": "grantee",
            "name": grantee_name,
            "granteeKind": grantee_kind,
            "blurb": f"AI-safety grantee (auto-added from {sources_label}; details pending enrichment)",
            "domainTags": [],
            "confidence": "medium",
            "sources": [
                {
                    "url": info["source_url"]
                    or "https://github.com/rufuspollock/open-philanthropy-grants",
                    "accessed": GENERATED_AT,
                }
            ],
            "lastVerified": GENERATED_AT,
            "fieldDollarsUSD": 0,  # recomputed below
        }
        new_grantee_nodes.append(node)
        new_grantee_id_map[grantee_name] = grantee_id
        admitted_count += 1

    # Register new nodes
    for node in new_grantee_nodes:
        nodes.append(node)
        nodes_by_id[node["id"]] = node

    # Update GRANTEE_ALIASES for the newly admitted grantees
    for grantee_name, grantee_id in new_grantee_id_map.items():
        GRANTEE_ALIASES[grantee_name.lower()] = grantee_id

    # ── Rule 8: NSF SLES program officer person nodes ───────────────────────
    # Include ONLY program officers with "AI-Safety" in their title
    # (these correspond to Safe Learning-Enabled Systems / SLES program grants)
    nsf_person_records = [
        r
        for r in nsf_records
        if (r.get("type") == "person" or r.get("record_type") == "person")
        and r.get("funder_hint") == "nsf"
        and "AI-Safety" in r.get("title", "")
    ]
    # Deduplicate by name
    seen_po_names: set[str] = set()
    nsf_po_nodes: list[dict] = []
    nsf_po_edges: list[dict] = []
    for r in nsf_person_records:
        name = r["name"]
        if name in seen_po_names:
            continue
        seen_po_names.add(name)
        po_id = slug(name)
        if po_id in nodes_by_id:
            po_id = f"nsf-{po_id}"  # guard against unlikely collision
        po_node: dict[str, Any] = {
            "id": po_id,
            "kind": "person",
            "name": name,
            "title": r["title"],
            "blurb": f"NSF Program Officer — {r['title'].replace('Program Officer, ', '')}",
            "domainTags": [],
            "confidence": "high",
            "profileUrl": r.get("profile_url"),
            "sources": [{"url": r["source_url"], "accessed": GENERATED_AT}],
            "lastVerified": GENERATED_AT,
            "fieldDollarsUSD": 0,  # persons are never dollar-sized
        }
        nsf_po_nodes.append(po_node)
        nodes.append(po_node)
        nodes_by_id[po_id] = po_node
        nsf_po_edges.append(
            {
                "type": "affiliation",
                "source": po_id,
                "target": "nsf",
                "role": r["title"],
                "current": True,
                "sourceUrl": r["source_url"],
            }
        )

    skipped_po_count = len(
        set(
            r["name"]
            for r in nsf_records
            if (r.get("type") == "person")
            and r.get("funder_hint") == "nsf"
            and "AI-Safety" not in r.get("title", "")
        )
    )
    print(f"  NSF SLES program officers admitted: {len(nsf_po_nodes)}")
    print(f"  NSF program officers skipped (not SLES): {skipped_po_count}")

    # ── Build final edge list ────────────────────────────────────────────────

    # Start with non-grant carry-over edges from starter
    carry_edges: list[dict] = [
        e for e in starter["edges"] if e["type"] in ("investment", "affiliation")
    ]

    # ── Rule 1: Starter grant edges — replace / keep / drop ──────────────────
    # verified:false starter grant edges are REPLACED by fetched evidence where
    # available. KEEP a starter verified:false edge only if its funder has no
    # fetched grant coverage — the controller's explicit keep-list:
    KEEP_STARTER_PAIRS = {
        ("uk-aisi", "far-ai"),
        ("aria", "eleutherai"),
        ("schmidt-sciences", "far-ai"),
        ("frontier-model-forum-aisf", "apollo-research"),
        ("anthropic-programs", "timaeus"),
        ("future-of-life-institute", "cais"),
        ("foresight-institute", "timaeus"),
    }
    # nsf→cmu-focal: checked — NSF fetched slice has NO Carnegie Mellon / FOCAL
    # award, so it is dropped (rule 1). manifund→timaeus: manifund IS a covered
    # fetched source with no evidence for that pair and it is NOT on the
    # keep-list, so it is dropped too (rules 1 + 7).
    new_grant_edges: list[dict] = []
    dropped_starter_edges: list[tuple[str, str]] = []

    def edge_from_agg(src: str, tgt: str, agg: dict) -> dict:
        edge: dict[str, Any] = {
            "type": "grant",
            "source": src,
            "target": tgt,
            "amountUSD": agg.get("amountUSD"),
            "verified": True,
            "sourceUrl": agg.get("sourceUrl"),
        }
        if agg.get("year"):
            edge["year"] = agg["year"]
        if agg.get("multiYear"):
            edge["multiYear"] = agg["multiYear"]
        # Aggregate label must describe the aggregate (spot-check 2026-07-03):
        # multi-record pairs say so explicitly, so a reader following sourceUrl
        # can reconstruct the sum; NSF pairs list every award id.
        n = agg.get("_nrecords", 1)
        award_ids = agg.get("_award_ids", [])
        if n > 1:
            my = agg.get("multiYear")
            span = (
                f" {my['start']}–{my['end']}"
                if my
                else (f" {agg['year']}" if agg.get("year") else "")
            )
            label = f"{n} grants{span}"
            if len(award_ids) > 1:
                label += f" · awards {', '.join(award_ids)}"
            edge["program"] = label
        elif agg.get("program"):
            edge["program"] = agg["program"]
        if agg.get("regrantOf"):
            edge["regrantOf"] = agg["regrantOf"]
        return edge

    for e in starter["edges"]:
        if e["type"] != "grant":
            continue
        src, tgt = e["source"], e["target"]
        pair = (src, tgt)

        if pair in fetched_edges:
            # REPLACE with fetched evidence (verified:true)
            new_grant_edges.append(edge_from_agg(src, tgt, fetched_edges.pop(pair)))
        elif e.get("verified", False):
            # verified:true starter edges carry over verbatim (rule 1)
            new_grant_edges.append(dict(e))
        elif pair in KEEP_STARTER_PAIRS:
            # funder has no fetched grant coverage — keep as verified:false null-$
            new_grant_edges.append(dict(e))
        else:
            # covered funder, no fetched evidence for the pair → drop
            dropped_starter_edges.append(pair)
            print(
                f"  DROP starter edge {src}→{tgt} (covered source, no fetched evidence)"
            )

    # Add remaining fetched edges (to existing grantees that weren't in starter)
    for (src, tgt), agg in fetched_edges.items():
        # Only emit edges between admitted nodes
        if src not in nodes_by_id or tgt not in nodes_by_id:
            continue
        if (
            nodes_by_id[src]["kind"] != "funder"
            or nodes_by_id[tgt]["kind"] != "grantee"
        ):
            continue
        new_grant_edges.append(edge_from_agg(src, tgt, agg))

    # ── Rule 7: Manifund grant edges (null $ only, existing grantees only) ──
    manifund_grant_count = 0
    manifund_grant_records = [
        r for r in manifund_records if r.get("record_type") == "grant"
    ]
    manifund_pairs_seen: set[str] = set()
    for r in manifund_grant_records:
        grantee_id = resolve_grantee(r.get("grantee_name", ""))
        if not grantee_id or grantee_id not in nodes_by_id:
            continue
        if nodes_by_id.get(grantee_id, {}).get("kind") != "grantee":
            continue
        pair_key = f"manifund→{grantee_id}"
        if pair_key in manifund_pairs_seen:
            continue
        manifund_pairs_seen.add(pair_key)
        new_grant_edges.append(
            {
                "type": "grant",
                "source": "manifund",
                "target": grantee_id,
                "amountUSD": None,  # amounts are funding goals, not disbursements (rule 7)
                "verified": False,
                "sourceUrl": r.get("source_url"),
            }
        )
        manifund_grant_count += 1
    print(
        f"  Manifund grant edges added (null $, existing grantees only): {manifund_grant_count}"
    )
    print("  ProPublica 990 records: context only, not used in v1 emit (rule 9)")

    # ── Build new edges for the admitted grantees from the unresolved pool ──
    # Re-resolve ALL names that failed the first pass — the alias registration
    # above means cross-source variants (e.g. NSF "University of California-
    # Berkeley" vs CG "University of California, Berkeley") now resolve to the
    # admitted node via the norm() fallback. Group by (funder, resolved id) so
    # variants merge into ONE aggregated edge (rule 6).
    new_pairs: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (funder_hint, grantee_name), records in raw_pairs.items():
        if grantee_name not in unresolved_grantees:
            continue  # resolved on the first pass — already edged
        grantee_id = resolve_grantee(grantee_name)
        if not grantee_id or grantee_id not in nodes_by_id:
            continue  # still unresolved → dropped (reported below)
        if funder_hint not in nodes_by_id:
            continue
        new_pairs[(funder_hint, grantee_id)].extend(records)

    for (funder_hint, grantee_id), records in new_pairs.items():
        agg = aggregate_edge_records(records)
        # SFF regrantOf for new grantees (rule 4, same sole-payer condition)
        payers = agg.pop("_payers", [])
        if funder_hint == "survival-and-flourishing-fund":
            payers_set = set(p for p in payers if p is not None)
            if payers_set == {"jaan-tallinn"}:
                agg["regrantOf"] = "jaan-tallinn"
        new_grant_edges.append(edge_from_agg(funder_hint, grantee_id, agg))

    # Recompute the dropped list post-resolution (rule 5 report line)
    dropped_grantees = [
        (name, info["total"])
        for name, info in unresolved_grantees.items()
        if resolve_grantee(name) not in nodes_by_id
    ]

    # ── Combine all edges ────────────────────────────────────────────────────
    all_edges = carry_edges + new_grant_edges + nsf_po_edges

    # ── Plan-2 step 4: merge the research-swarm enrichment (if present) ─────
    # Runs BEFORE fieldDollars/priorityRank so enriched funders participate.
    enrich_report = apply_enrichment(
        nodes, nodes_by_id, all_edges, {d["id"] for d in starter["meta"]["domains"]}
    )

    # ── Rule 12: compute fieldDollarsUSD for all grantees ──────────────────
    # fieldDollarsUSD = sum of verified inbound edges' amountUSD (regrant-deduped:
    # SFF edges with regrantOf are still counted at the grantee level since the
    # money reaches them; the dedup is that jaan-tallinn has no DIRECT grant edges)
    grantee_inbound: dict[str, float] = defaultdict(float)
    grantee_has_edge: set[str] = set()
    for e in all_edges:
        if e["type"] in ("grant", "investment") and e.get("verified", False):
            tgt = e["target"]
            amt = e.get("amountUSD")
            if amt is not None:
                grantee_inbound[tgt] += amt
            grantee_has_edge.add(tgt)

    for n in nodes:
        if n["kind"] == "grantee":
            n["fieldDollarsUSD"] = round(grantee_inbound[n["id"]], 2)

    # ── Rule 12: compute priorityRank ────────────────────────────────────────
    # Funders: ordered by (annualFieldGivingUSD ?? 0) desc, open-now first among ties
    # Grantees: by fieldDollarsUSD desc
    # People: after grantees
    TODAY = GENERATED_AT

    def is_open(n: dict) -> bool:
        apply = n.get("apply", {})
        mode = apply.get("mode", "")
        deadline = apply.get("deadline")
        if mode == "closed":
            return False
        if mode == "rounds" and deadline and deadline < TODAY:
            return False
        return mode in ("rolling", "rounds", "invite-only")

    funders = [n for n in nodes if n["kind"] == "funder"]
    grantees = [n for n in nodes if n["kind"] == "grantee"]
    people = [n for n in nodes if n["kind"] == "person"]

    # Rule 12: funders by (annualFieldGivingUSD ?? 0) desc, open-now nudged up —
    # among ties: open && rolling first, then any other open mode, then closed.
    def open_nudge(n: dict) -> int:
        if is_open(n) and n.get("apply", {}).get("mode") == "rolling":
            return 0
        return 1 if is_open(n) else 2

    funders_sorted = sorted(
        funders,
        key=lambda n: (
            -(n.get("annualFieldGivingUSD") or 0),
            open_nudge(n),
            n["id"],
        ),
    )
    grantees_sorted = sorted(
        grantees, key=lambda n: (-n.get("fieldDollarsUSD", 0), n["id"])
    )
    people_sorted = sorted(people, key=lambda n: n["id"])

    rank = 1
    for n in funders_sorted:
        n["priorityRank"] = rank
        rank += 1
    for n in grantees_sorted:
        n["priorityRank"] = rank
        rank += 1
    for n in people_sorted:
        n["priorityRank"] = rank
        rank += 1

    # ── Rule 13: validate before emit ────────────────────────────────────────
    all_ids = {n["id"] for n in nodes}

    # Frozen starter ids still present
    assert (
        ALL_STARTER_IDS <= all_ids
    ), f"Missing starter ids: {ALL_STARTER_IDS - all_ids}"

    # Rule 4: jaan-tallinn must have NO direct grant/investment edges — his
    # money flows via SFF edges' regrantOf; his node is sized by his payer total.
    jt_direct = [
        e
        for e in all_edges
        if e["type"] in ("grant", "investment") and e["source"] == "jaan-tallinn"
    ]
    assert not jt_direct, f"jaan-tallinn has direct funding edges: {jt_direct}"

    # Rule 13: regrant sums recomputed TWO WAYS —
    #   way1: sum of emitted SFF grant edges carrying regrantOf=jaan-tallinn
    #   way2: independent re-aggregation of raw SFF records by resolved grantee,
    #         counting only sole-payer jaan-tallinn groups (rule 4 condition)
    way1 = sum(
        e.get("amountUSD") or 0
        for e in all_edges
        if e["type"] == "grant"
        and e["source"] == "survival-and-flourishing-fund"
        and e.get("regrantOf") == "jaan-tallinn"
    )
    sff_by_gid: dict[str, list[dict]] = defaultdict(list)
    for r in sff_records:
        if r.get("record_type") != "grant":
            continue
        gname = r.get("grantee_name", "")
        if not gname or gname.startswith("(") or gname.lower() == "anonymous":
            continue
        gid = resolve_grantee(gname)
        if gid and gid in nodes_by_id and nodes_by_id[gid]["kind"] == "grantee":
            sff_by_gid[gid].append(r)
    way2 = 0.0
    for gid, rs in sff_by_gid.items():
        payer_set = {r.get("payer_hint") for r in rs}
        if payer_set == {"jaan-tallinn"}:
            way2 += sum(r["amount_usd"] or 0 for r in rs)
    assert way1 == way2, f"regrant recompute mismatch: edges={way1} raw={way2}"

    # No duplicate ids
    id_counts = Counter(n["id"] for n in nodes)
    dupes = {k: v for k, v in id_counts.items() if v > 1}
    assert not dupes, f"Duplicate node ids: {dupes}"

    # Validator rules (mirrors funding-validate.ts)
    valid_domain_ids = {d["id"] for d in starter["meta"]["domains"]}
    valid_apply_modes = {"rolling", "rounds", "invite-only", "closed"}
    valid_funder_kinds = {"philanthropy", "government", "vc", "corporate"}
    valid_grantee_kinds = {"research-org", "university", "startup", "fieldbuilding"}

    person_has_affil: set[str] = set()
    grantee_has_funding_edge: set[str] = set()

    for e in all_edges:
        assert e["source"] in all_ids, f"Edge from unknown node: {e['source']}"
        assert e["target"] in all_ids, f"Edge to unknown node: {e['target']}"
        assert e["source"] != e["target"], f"Self-loop: {e['source']}"
        src_node = nodes_by_id[e["source"]]
        tgt_node = nodes_by_id[e["target"]]
        if e["type"] == "grant":
            assert (
                src_node["kind"] == "funder"
            ), f"Grant edge from non-funder: {e['source']}"
            assert (
                tgt_node["kind"] == "grantee"
            ), f"Grant edge to non-grantee: {e['target']}"
            if e.get("amountUSD") is not None:
                assert e.get("sourceUrl", "").startswith(
                    "http"
                ), f"{e['source']}→{e['target']}: amountUSD without http sourceUrl"
            if e.get("regrantOf"):
                assert e["regrantOf"] in all_ids, f"regrantOf unknown: {e['regrantOf']}"
            grantee_has_funding_edge.add(e["target"])
        elif e["type"] == "investment":
            assert (
                src_node["kind"] == "funder"
            ), f"Investment from non-funder: {e['source']}"
            assert (
                tgt_node["kind"] == "grantee"
            ), f"Investment to non-grantee: {e['target']}"
            if e.get("amountUSD") is not None:
                assert e.get("sourceUrl", "").startswith(
                    "http"
                ), f"{e['source']}→{e['target']}: amountUSD without http sourceUrl"
            grantee_has_funding_edge.add(e["target"])
        elif e["type"] == "affiliation":
            assert (
                src_node["kind"] == "person"
            ), f"Affiliation from non-person: {e['source']}"
            assert (
                tgt_node["kind"] == "funder"
            ), f"Affiliation to non-funder: {e['target']}"
            person_has_affil.add(e["source"])
        else:
            raise AssertionError(f"Unknown edge type: {e['type']}")

    # Need to add edges for existing grantees that might not have funding edges
    # (manifund grants add null-amount edges)

    for n in nodes:
        # All nodes need sources
        assert (
            n.get("sources") and len(n["sources"]) > 0
        ), f"Node {n['id']} has no sources"
        # All nodes need priorityRank
        assert isinstance(
            n.get("priorityRank"), int
        ), f"Node {n['id']} missing priorityRank"
        # All nodes need non-negative fieldDollarsUSD
        assert (
            isinstance(n.get("fieldDollarsUSD"), (int, float))
            and n["fieldDollarsUSD"] >= 0
        ), f"Node {n['id']} has invalid fieldDollarsUSD: {n.get('fieldDollarsUSD')}"
        # Domain tags must be valid
        for tag in n.get("domainTags", []):
            assert (
                tag in valid_domain_ids
            ), f"Node {n['id']} has invalid domain tag: {tag}"
        # networksId check (skipped here — companies.json is not loaded; tested in pytest)
        # Private key leakage guard (rule 13)
        for key in PRIVATE_KEYS:
            assert key not in n, f"Node {n['id']} contains private key '{key}'"
        assert (
            "notes" not in n
        ), f"Node {n['id']} has top-level 'notes' key (private; only legal inside apply{{}})"

        if n["kind"] == "funder":
            assert (
                n.get("funderKind") in valid_funder_kinds
            ), f"Node {n['id']} has invalid funderKind: {n.get('funderKind')}"
            apply = n.get("apply", {})
            assert (
                apply.get("mode") in valid_apply_modes
            ), f"Node {n['id']} apply.mode missing/unknown: {apply.get('mode')}"
            # Past deadline check
            deadline = apply.get("deadline")
            if apply.get("mode") == "rounds" and deadline and deadline < GENERATED_AT:
                raise AssertionError(
                    f"Node {n['id']} rounds deadline {deadline} is in the past — "
                    f"re-verify or set mode 'closed'"
                )
            # Dollar source check
            annual = n.get("annualFieldGivingUSD")
            if annual is not None:
                assert annual >= 0, f"Node {n['id']} has negative annual giving"
                basis = n.get("annualFieldGivingBasis", {})
                assert basis.get("sourceUrl", "").startswith(
                    "http"
                ), f"Node {n['id']} annualFieldGivingUSD has no basis.sourceUrl"
            # fieldDollarsUSD must equal annualFieldGivingUSD ?? 0
            expected_field = annual if annual is not None else 0
            assert n["fieldDollarsUSD"] == expected_field, (
                f"Node {n['id']} fieldDollarsUSD={n['fieldDollarsUSD']} "
                f"but annualFieldGivingUSD={annual} (expected {expected_field})"
            )

        elif n["kind"] == "grantee":
            assert (
                n.get("granteeKind") in valid_grantee_kinds
            ), f"Node {n['id']} has invalid granteeKind: {n.get('granteeKind')}"
            if n["id"] not in grantee_has_funding_edge:
                raise AssertionError(
                    f"Grantee {n['id']} has no funding edge — invisible on map"
                )

        elif n["kind"] == "person":
            assert n.get("title"), f"Person {n['id']} missing title"
            if n["id"] not in person_has_affil:
                raise AssertionError(f"Person {n['id']} has no affiliation edge")

    # priorityRank must be unique 1..N
    ranks = [n["priorityRank"] for n in nodes]
    assert sorted(ranks) == list(
        range(1, len(nodes) + 1)
    ), f"priorityRank not a unique 1..{len(nodes)} sequence: {sorted(ranks)}"

    # ── Rule 12: meta block ──────────────────────────────────────────────────
    kind_counts = Counter(n["kind"] for n in nodes)
    edge_counts = Counter(e["type"] for e in all_edges)

    meta: dict[str, Any] = {
        "generated": "build_funding.py",
        "generatedAt": GENERATED_AT,
        "fx": {
            "year": FX["year"],
            "GBP": FX["GBP"],
            "EUR": FX["EUR"],
        },
        "domains": starter["meta"]["domains"],
        "sources": {
            "eafunds": {
                "name": "EA Funds API",
                "url": "https://funds.effectivealtruism.org/api/grants",
                "fetched": fetched_at("eafunds"),
            },
            "nsf": {
                "name": "NSF Awards API",
                "url": "https://resources.research.gov/common/webapi/awardapisearch-v1.htm",
                "fetched": fetched_at("nsf"),
            },
            "sff": {
                "name": "SFF Recommendations Table",
                "url": "https://survivalandflourishing.fund/recommendations",
                "fetched": fetched_at("sff"),
            },
            "propublica": {
                "name": "ProPublica Nonprofit Explorer",
                "url": "https://projects.propublica.org/nonprofits/",
                "fetched": fetched_at("propublica"),
            },
            "manifund": {
                "name": "Manifund API",
                "url": "https://manifund.org",
                "fetched": fetched_at("manifund"),
            },
            "gov_uk": {
                "name": "gov.uk / ARIA / UK AISI",
                "url": "https://aria.org.uk",
                "fetched": fetched_at("gov_uk"),
            },
            "coefficient": {
                "name": "Coefficient Giving Archive (rufuspollock)",
                "url": "https://github.com/rufuspollock/open-philanthropy-grants",
                "fetched": fetched_at("coefficient"),
            },
        },
        "counts": dict(kind_counts),
        "edge_counts": dict(edge_counts),
    }

    out = {
        "meta": meta,
        "nodes": nodes,
        "edges": all_edges,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    print(
        f"  nodes: {len(nodes)} (funder={kind_counts['funder']}, grantee={kind_counts['grantee']}, person={kind_counts['person']})"
    )
    print(f"  edges: {len(all_edges)} {dict(edge_counts)}")
    print(f"  new funder: jaan-tallinn (${jt_annual:,.0f} annual via SFF 2025)")
    print(
        f"  new grantees ({admitted_count} + miri): miri, {', '.join(n['id'] for n in new_grantee_nodes)}"
    )
    print(
        f"  NSF program officers: {len(nsf_po_nodes)} ({', '.join(n['name'] for n in nsf_po_nodes)})"
    )
    print(f"  CG annualFieldGivingUSD: ${cg_annual:,.0f} (year={cg_basis['year']})")
    print(
        f"  SFF annualFieldGivingUSD: ${sff_annual:,.0f} (CY2025, recomputed from {sff_count_2025} records)"
    )
    print(f"  LTFF annualFieldGivingUSD: ${ltff_annual:,.0f} (CY{ltff_year})")
    print(
        f"  NSF annualFieldGivingUSD: ${nsf_annual:,.0f} (CY{nsf_year}, SLES+keyword slice)"
    )
    print(
        f"  ARIA apply updated: deadline {aria_node['apply'].get('deadline')} (live from gov.uk)"
    )
    print(
        f"  dropped starter edges (covered source, no fetched evidence): {dropped_starter_edges}"
    )
    print("  SFF jaan-tallinn payer → regrantOf edges created")
    print("\n  top-10 priority:")
    for n in sorted(nodes, key=lambda x: x["priorityRank"])[:10]:
        dollars = f"${n.get('fieldDollarsUSD', 0):,.0f}"
        print(f"    #{n['priorityRank']:2d}  {n['id']:<45} {dollars}")
    print(
        f"\n  dropped grantees (unresolved, rank >15): {len(dropped_grantees)} ({sum(d[1] for d in dropped_grantees):,.0f}$ total)"
    )
    print("\n  enrichment merge:")
    print(
        f"    funders added: {len(enrich_report['funders_added'])} ({', '.join(enrich_report['funders_added']) or '—'})"
    )
    print(
        f"    people added: {enrich_report['people_added']}  grantees updated: {enrich_report['grantees_updated']}"
    )
    if enrich_report["grantees_removed"]:
        print(
            f"    grantees removed (defunct): {', '.join(enrich_report['grantees_removed'])}"
        )
    for s in enrich_report["funders_skipped"]:
        print(f"    skipped: {s}")
    if enrich_report["dollars_nulled"]:
        print(
            f"    $ nulled (no basis source): {', '.join(enrich_report['dollars_nulled'])}"
        )
    print(f"  excluded grantees (controller list): {len(excluded_grantees)}")
    for name, total, reason in excluded_grantees:
        print(f"    - {name} (${total:,.0f}): {reason}")
    print("  distinct dropped payer strings (SFF non-jaan-tallinn):")
    non_jt_payers = {
        r.get("payer_hint")
        for r in sff_records
        if r.get("record_type") == "grant"
        and r.get("payer_hint") not in (None, "jaan-tallinn")
    }
    for p in sorted(non_jt_payers):
        print(f"    {p}")
    print(
        "  seeded, awaiting enrichment (rule 3): darpa, ballistic-ventures, a16z, redpoint-ventures,"
    )
    print(
        "    google-deepmind, microsoft-afmr, aws-programs, syn-ventures, yl-ventures, cyberstarts,"
    )
    print(
        "    ai-risk-mitigation-fund, longview-philanthropy, founders-pledge-gcr, halcyon-futures,"
    )
    print(
        "    safe-ai-fund, craig-newmark-philanthropies, iarpa, nist-caisi, ukri-epsrc, eu-horizon"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
