"""pytest gate over the EMITTED src/data/funding.json.

One test per funding-validate.ts rule family, plus the pipeline-specific
invariants (frozen ids, regrant recompute, private-key leakage, pinned fx,
domains drift vs funding-types.ts).

Run:  python3 -m pytest experiments/funding/tests/ -v
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FUNDING = ROOT / "src/data/funding.json"
COMPANIES = ROOT / "src/data/companies.json"
FUNDING_TYPES = ROOT / "src/data/funding-types.ts"
OVERLAY = ROOT / "private/funding-overlay.json"

# All 32 starter node ids — FROZEN, must never disappear from the dataset.
STARTER_IDS = {
    # 17 funders
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
    # 12 grantees
    "far-ai",
    "redwood-research",
    "metr",
    "apollo-research",
    "eleutherai",
    "mats",
    "cais",
    "timaeus",
    "cooperative-ai-foundation",
    "cmu-focal",
    "irregular",
    "promptfoo",
    # 3 people
    "austin-chen",
    "allison-duettmann",
    "anthony-aguirre",
}
assert len(STARTER_IDS) == 32

# 'notes' is legal INSIDE apply{} but not as a top-level node key.
PRIVATE_KEYS = {"stage", "warm_path", "notes", "priority"}

APPLY_MODES = {"rolling", "rounds", "invite-only", "closed"}
FUNDER_KINDS = {"philanthropy", "government", "vc", "corporate"}
GRANTEE_KINDS = {"research-org", "university", "startup", "fieldbuilding"}


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(FUNDING.read_text())


@pytest.fixture(scope="module")
def nodes(data) -> list[dict]:
    return data["nodes"]


@pytest.fixture(scope="module")
def nodes_by_id(nodes) -> dict[str, dict]:
    return {n["id"]: n for n in nodes}


@pytest.fixture(scope="module")
def edges(data) -> list[dict]:
    return data["edges"]


@pytest.fixture(scope="module")
def company_ids() -> set[str]:
    raw = json.loads(COMPANIES.read_text())
    return {c["id"] for c in raw["companies"]}


# ── ids: unique + frozen ─────────────────────────────────────────────────────


def test_ids_unique(nodes):
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), "duplicate node ids"


def test_frozen_starter_ids_present(nodes_by_id):
    missing = STARTER_IDS - set(nodes_by_id)
    assert not missing, f"frozen starter ids missing: {missing}"


# ── every $ has a source ─────────────────────────────────────────────────────


def test_every_node_has_sources(nodes):
    for n in nodes:
        assert n.get("sources"), f"{n['id']}: no sources"
        for s in n["sources"]:
            assert s["url"].startswith("http"), f"{n['id']}: bad source url"


def test_funder_dollar_has_basis_source(nodes):
    for n in nodes:
        if n["kind"] != "funder":
            continue
        annual = n.get("annualFieldGivingUSD")
        if annual is not None:
            assert annual >= 0, f"{n['id']}: negative annual giving"
            basis = n.get("annualFieldGivingBasis") or {}
            assert basis.get("sourceUrl", "").startswith(
                "http"
            ), f"{n['id']}: annualFieldGivingUSD without basis.sourceUrl"
            assert isinstance(basis.get("year"), int), f"{n['id']}: basis.year missing"
            assert basis.get("method"), f"{n['id']}: basis.method missing"


def test_edge_dollar_has_source_url(edges):
    for e in edges:
        if e["type"] in ("grant", "investment") and e.get("amountUSD") is not None:
            assert e.get("sourceUrl", "").startswith(
                "http"
            ), f"{e['source']}→{e['target']}: $ amount without sourceUrl"


# ── edge endpoint kinds ──────────────────────────────────────────────────────


def test_edge_endpoints_exist_no_self_loops(edges, nodes_by_id):
    for e in edges:
        assert e["source"] in nodes_by_id, f"edge from unknown node {e['source']}"
        assert e["target"] in nodes_by_id, f"edge to unknown node {e['target']}"
        assert e["source"] != e["target"], f"self-loop on {e['source']}"


def test_edge_endpoint_kinds(edges, nodes_by_id):
    for e in edges:
        src, tgt = nodes_by_id[e["source"]], nodes_by_id[e["target"]]
        if e["type"] == "grant":
            assert src["kind"] == "funder", f"grant from non-funder {src['id']}"
            assert tgt["kind"] == "grantee", f"grant to non-grantee {tgt['id']}"
        elif e["type"] == "investment":
            assert src["kind"] == "funder", f"investment from non-funder {src['id']}"
            assert tgt["kind"] == "grantee", f"investment to non-grantee {tgt['id']}"
        elif e["type"] == "affiliation":
            assert src["kind"] == "person", f"affiliation from non-person {src['id']}"
            assert tgt["kind"] == "funder", f"affiliation to non-funder {tgt['id']}"
        else:
            raise AssertionError(f"unknown edge type {e['type']}")


# ── regrant: recompute independently, no double count ────────────────────────


def test_regrant_targets_exist(edges, nodes_by_id):
    for e in edges:
        if e.get("regrantOf"):
            assert e["regrantOf"] in nodes_by_id, f"regrantOf unknown {e['regrantOf']}"
            assert nodes_by_id[e["regrantOf"]]["kind"] == "funder"


def test_regrant_no_double_count(edges):
    """The payer behind regrantOf edges must have NO direct grant/investment
    edges — otherwise the same dollars would be drawn twice on the map."""
    payers = {e["regrantOf"] for e in edges if e.get("regrantOf")}
    for payer in payers:
        direct = [
            e
            for e in edges
            if e["type"] in ("grant", "investment") and e["source"] == payer
        ]
        assert not direct, f"regrant payer {payer} also has direct edges: {direct}"


def test_regrant_sum_recompute(edges, nodes_by_id):
    """Independent recompute of the jaan-tallinn regrant mechanism."""
    regrant_edges = [e for e in edges if e.get("regrantOf") == "jaan-tallinn"]
    regrant_sum = sum(e.get("amountUSD") or 0 for e in regrant_edges)

    # (a) There must be actual regrant dollars — not just a zero-sum placeholder.
    assert regrant_sum > 0, f"regrant_sum is {regrant_sum}; expected > 0"

    # (b) Every edge that carries a regrantOf field must originate from SFF
    #     and reference jaan-tallinn (the only regrant payer currently modelled).
    for e in edges:
        if e.get("regrantOf") is not None:
            assert e["source"] == "survival-and-flourishing-fund", (
                f"edge {e['source']}→{e['target']} carries regrantOf "
                f"but source is not survival-and-flourishing-fund"
            )
            assert (
                e["regrantOf"] == "jaan-tallinn"
            ), f"unexpected regrantOf value: {e['regrantOf']!r}"

    # (c) jaan-tallinn must have ZERO direct grant/investment edges — his
    #     dollars flow only through SFF regrantOf edges (dedup invariant).
    direct = [
        e
        for e in edges
        if e["type"] in ("grant", "investment") and e["source"] == "jaan-tallinn"
    ]
    assert not direct, (
        f"jaan-tallinn has direct grant/investment edges; " f"expected 0, got: {direct}"
    )

    # (d) jaan-tallinn's annualFieldGivingUSD must cover at least the emitted
    #     regrant sum (payer total >= distributed total is a sanity floor).
    jt = nodes_by_id["jaan-tallinn"]
    jt_annual = jt.get("annualFieldGivingUSD") or 0
    assert (
        jt_annual >= regrant_sum
    ), f"jaan-tallinn annualFieldGivingUSD {jt_annual} < regrant_sum {regrant_sum}"
    # sizing comes from SFF payer total, never from edges
    assert jt["fieldDollarsUSD"] == jt["annualFieldGivingUSD"]


# ── networksId membership ────────────────────────────────────────────────────


def test_networksid_membership(nodes, company_ids):
    for n in nodes:
        if n.get("networksId"):
            assert (
                n["networksId"] in company_ids
            ), f"{n['id']}: networksId {n['networksId']} not in companies.json"


# ── apply / deadlines ────────────────────────────────────────────────────────


def test_funder_apply_mode_valid(nodes):
    for n in nodes:
        if n["kind"] == "funder":
            assert n.get("funderKind") in FUNDER_KINDS, f"{n['id']}: bad funderKind"
            apply = n.get("apply") or {}
            assert apply.get("mode") in APPLY_MODES, f"{n['id']}: bad apply.mode"


def test_no_past_deadlines(data, nodes):
    generated_at = data["meta"]["generatedAt"]
    assert generated_at, "meta.generatedAt required (drives open-now)"
    for n in nodes:
        if n["kind"] != "funder":
            continue
        apply = n.get("apply") or {}
        if apply.get("mode") == "rounds" and apply.get("deadline"):
            assert (
                apply["deadline"] >= generated_at
            ), f"{n['id']}: rounds deadline {apply['deadline']} in the past"


# ── person / grantee structural rules ────────────────────────────────────────


def test_person_has_title_and_affiliation(nodes, edges):
    with_affil = {e["source"] for e in edges if e["type"] == "affiliation"}
    for n in nodes:
        if n["kind"] == "person":
            assert n.get("title"), f"person {n['id']} missing title"
            assert n["id"] in with_affil, f"person {n['id']} has no affiliation edge"


def test_every_grantee_is_fed(nodes, edges):
    fed = {e["target"] for e in edges if e["type"] in ("grant", "investment")}
    for n in nodes:
        if n["kind"] == "grantee":
            assert n.get("granteeKind") in GRANTEE_KINDS, f"{n['id']}: bad granteeKind"
            assert n["id"] in fed, f"grantee {n['id']} has no funding edge"


# ── fieldDollarsUSD consistency ──────────────────────────────────────────────


def test_field_dollars_nonneg_number(nodes):
    for n in nodes:
        v = n.get("fieldDollarsUSD")
        assert isinstance(v, (int, float)) and v >= 0, f"{n['id']}: bad fieldDollarsUSD"


def test_funder_field_dollars_equals_annual(nodes):
    for n in nodes:
        if n["kind"] == "funder":
            expected = n.get("annualFieldGivingUSD")
            expected = expected if expected is not None else 0
            assert (
                n["fieldDollarsUSD"] == expected
            ), f"{n['id']}: fieldDollarsUSD != annualFieldGivingUSD ?? 0"


def test_grantee_field_dollars_recompute(nodes, edges):
    """Recompute each grantee's fieldDollarsUSD from its verified inbound edges."""
    inbound: dict[str, float] = {}
    for e in edges:
        if e["type"] in ("grant", "investment") and e.get("verified"):
            amt = e.get("amountUSD")
            if amt is not None:
                inbound[e["target"]] = inbound.get(e["target"], 0) + amt
    for n in nodes:
        if n["kind"] == "grantee":
            expected = round(inbound.get(n["id"], 0), 2)
            assert n["fieldDollarsUSD"] == expected, (
                f"{n['id']}: fieldDollarsUSD {n['fieldDollarsUSD']} != "
                f"recomputed inbound {expected}"
            )


def test_person_field_dollars_zero(nodes):
    for n in nodes:
        if n["kind"] == "person":
            assert n["fieldDollarsUSD"] == 0, f"person {n['id']} is dollar-sized"


# ── priorityRank ─────────────────────────────────────────────────────────────


def test_priority_rank_unique_1_to_n(nodes):
    ranks = sorted(n["priorityRank"] for n in nodes)
    assert ranks == list(range(1, len(nodes) + 1)), "priorityRank not unique 1..N"


# ── private-key leakage guard ────────────────────────────────────────────────


def test_no_private_keys_in_public(nodes):
    for n in nodes:
        leaked = PRIVATE_KEYS & set(n)
        assert not leaked, f"{n['id']}: private keys leaked: {leaked}"


# ── meta: fx pinned + domains drift ──────────────────────────────────────────


def test_meta_fx_pinned(data):
    fx = data["meta"].get("fx") or {}
    assert fx.get("year") == 2025, "fx.year must be pinned to 2025"
    assert fx.get("GBP") == 1.27, "GBP rate must be pinned at 1.27"
    assert fx.get("EUR") == 1.08, "EUR rate must be pinned at 1.08"


def test_domains_match_funding_types(data, nodes):
    """meta.domains and every node domainTag must match the DOMAINS ids baked
    into src/data/funding-types.ts (parsed with a regex so they can't drift)."""
    ts = FUNDING_TYPES.read_text()
    m = re.search(r"export const DOMAINS[^=]*=\s*\[(.*?)\];", ts, re.DOTALL)
    assert m, "could not locate DOMAINS in funding-types.ts"
    ts_ids = set(re.findall(r'id:\s*"([^"]+)"', m.group(1)))
    assert ts_ids, "no DOMAINS ids parsed from funding-types.ts"

    meta_ids = {d["id"] for d in data["meta"]["domains"]}
    assert meta_ids == ts_ids, f"meta.domains drift: {meta_ids ^ ts_ids}"

    for n in nodes:
        for t in n.get("domainTags", []):
            assert t in ts_ids, f"{n['id']}: unknown domain tag {t}"


# ── coefficient-giving: CG_RELEVANT_PROGRAMS filter pinned ───────────────────

BUILD_FUNDING = Path(__file__).resolve().parents[1] / "build_funding.py"


def test_cg_basis_method_names_all_programs(nodes_by_id):
    """coefficient-giving's annualFieldGivingBasis.method must mention every
    program in CG_RELEVANT_PROGRAMS as defined in build_funding.py.

    Parsing the set from source with a regex means this test fails loudly
    if someone widens the filter without updating the basis method string —
    keeping the public-facing explanation in sync with the actual filter logic.
    """
    src = BUILD_FUNDING.read_text()
    # Extract the set literal that follows CG_RELEVANT_PROGRAMS = {
    m = re.search(r"CG_RELEVANT_PROGRAMS\s*=\s*\{([^}]+)\}", src, re.DOTALL)
    assert m, "CG_RELEVANT_PROGRAMS not found in build_funding.py"
    programs = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert programs, "no programs parsed from CG_RELEVANT_PROGRAMS"

    cg = nodes_by_id.get("coefficient-giving")
    assert cg is not None, "coefficient-giving node missing"
    basis = cg.get("annualFieldGivingBasis") or {}
    method = basis.get("method") or ""
    for prog in programs:
        assert prog in method, (
            f"CG_RELEVANT_PROGRAMS program {prog!r} not mentioned in "
            f"coefficient-giving annualFieldGivingBasis.method: {method!r}"
        )


# ── private overlay (skipped when absent) ────────────────────────────────────


def test_overlay_ids_subset(nodes_by_id):
    if not OVERLAY.exists():
        pytest.skip("private/funding-overlay.json absent")
    overlay = json.loads(OVERLAY.read_text())
    entries = overlay if isinstance(overlay, list) else overlay.get("entries", [])
    for entry in entries:
        assert entry["id"] in nodes_by_id, f"overlay id {entry['id']} not in nodes"
