"""Validate the built /networks dataset. Run: pytest experiments/networks/tests

The most important test is `test_no_private_keys_in_public` — the leakage guard.
The public companies.json is committed and deployed; it must never carry warm
paths, pipeline stage, or notes. The other tests catch the bugs that would make
the D3 viz throw or mislead (dangling edges, bad enums, out-of-range size)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ROOT / "src" / "data" / "companies.json"
OVERLAY = ROOT / "private" / "overlay.json"

VERTICALS = {
    "frontier-lab",
    "agent-native-startup",
    "bank-fintech",
    "healthcare",
    "security-eval-vendor",
    "investor-vc",
    "infra-platform",
    "enterprise-other",
}
EDGE_TYPES = {"business", "shared-investor", "competitor"}
PRIVATE_KEYS = {"warm_path", "stage", "notes", "priority"}


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(PUBLIC.read_text())


@pytest.fixture(scope="module")
def companies(data) -> list[dict]:
    return data["companies"]


@pytest.fixture(scope="module")
def ids(companies) -> set[str]:
    return {c["id"] for c in companies}


def test_unique_ids(companies, ids):
    assert len(ids) == len(companies), "duplicate company ids"


def test_vertical_enum(companies):
    bad = [c["id"] for c in companies if c["vertical"] not in VERTICALS]
    assert not bad, f"unknown vertical on: {bad}"


def test_intensity_range(companies):
    bad = [c["id"] for c in companies if not (0 <= c["intensity"] <= 5)]
    assert not bad, f"intensity out of range on: {bad}"


def test_required_fields(companies):
    for c in companies:
        for k in ("id", "name", "vertical", "blurb", "intensity", "confidence"):
            assert k in c and c[k] != "", f"{c.get('id')}: missing {k}"


def test_edge_endpoints_exist(data, ids):
    for e in data["edges"]:
        assert e["source"] in ids, f"edge from unknown {e['source']}"
        assert e["target"] in ids, f"edge to unknown {e['target']}"


def test_no_self_loops(data):
    assert not [e for e in data["edges"] if e["source"] == e["target"]]


def test_edge_types(data):
    bad = [e for e in data["edges"] if e["type"] not in EDGE_TYPES]
    assert not bad, f"bad edge types: {bad}"


def test_no_private_keys_in_public(companies):
    """LEAKAGE GUARD: warm paths / stage / notes must never reach the public file."""
    for c in companies:
        leaked = PRIVATE_KEYS & set(c)
        assert (
            not leaked
        ), f"{c['id']}: private keys leaked into public companies.json: {leaked}"


def test_overlay_ids_subset(ids):
    """Every private overlay entry must join to a real company."""
    if not OVERLAY.exists():
        pytest.skip("no private/overlay.json (public-only checkout)")
    raw = json.loads(OVERLAY.read_text())
    entries = raw if isinstance(raw, list) else raw.get("entries", [])
    unknown = [e["id"] for e in entries if e.get("id") and e["id"] not in ids]
    assert not unknown, f"overlay references companies not in the map: {unknown}"


# ── directory taxonomy: sub-category ("what they do") + competitor flag ──────
# The /networks directory groups each vertical into sub-categories and lights up
# AoC's direct competitors. meta.subcategories is the canonical taxonomy baked
# into the public file; every company must carry a subcategory in its vertical's
# set, and the 13 direct competitors must stay flagged (drift fails loudly).

# The 14 direct competitors of Agents of Chaos (design-approved set). Red-teaming
# vendors scattered across sub-categories — a cross-cutting flag, not one bucket.
EXPECTED_COMPETITORS = {
    "adversa-ai",
    "calypsoai",
    "garak-nvidia",
    "gray-swan-ai",
    "haize-labs",
    "irregular",
    "mindgard",
    "patronus-ai",
    "promptfoo",
    "protect-ai-palo-alto-networks",
    "repello-ai",
    "robust-intelligence-cisco",
    "splxai",
    "troj-ai",
}


@pytest.fixture(scope="module")
def subcats(data) -> dict:
    return data["meta"]["subcategories"]


def test_meta_subcategories_cover_every_vertical(subcats):
    assert set(subcats) == VERTICALS, "meta.subcategories must cover every vertical"
    for v, items in subcats.items():
        assert items, f"{v}: no sub-categories"
        for it in items:
            for k in ("key", "label", "isBuyer"):
                assert k in it, f"{v}: sub-category missing {k}"
        keys = [it["key"] for it in items]
        assert len(keys) == len(set(keys)), f"{v}: duplicate sub-category keys"


def test_every_company_has_valid_subcategory(companies, subcats):
    allowed = {v: {s["key"] for s in items} for v, items in subcats.items()}
    for c in companies:
        sub = c.get("subcategory")
        assert sub, f"{c['id']}: missing subcategory"
        assert (
            sub in allowed[c["vertical"]]
        ), f"{c['id']}: subcategory {sub!r} not in {c['vertical']} taxonomy"


def test_priority_rank_is_unique_permutation(companies):
    """priorityRank = a unique 1..N-1 over everyone except AoC (which is 0, the anchor)."""
    aoc = [c for c in companies if c["id"] == "agents-of-chaos"]
    assert aoc and aoc[0]["priorityRank"] == 0, "Agents of Chaos must be priorityRank 0"
    others = [c["priorityRank"] for c in companies if c["id"] != "agents-of-chaos"]
    assert set(others) == set(
        range(1, len(companies))
    ), "priorityRank must be a unique 1..N-1 permutation"


def test_competitor_flag_is_bool_and_matches_expected(companies):
    flagged = set()
    for c in companies:
        if "competitor" in c:
            assert isinstance(c["competitor"], bool), f"{c['id']}: competitor not bool"
            if c["competitor"]:
                flagged.add(c["id"])
    assert (
        flagged == EXPECTED_COMPETITORS
    ), f"competitor drift: missing {EXPECTED_COMPETITORS - flagged}, extra {flagged - EXPECTED_COMPETITORS}"
    assert "agents-of-chaos" not in flagged, "AoC must not be its own competitor"


def test_audit_demoted_edges_are_dashed(data):
    """Every audit-demoted tie (an investor claim the top-20 audit could not
    confirm) must ship unverified so the map draws it dashed, not solid."""
    audit = json.loads((ROOT / "experiments" / "networks" / "edge_audit.json").read_text())
    demote = audit.get("demote", [])
    assert demote, "expected a demote list in edge_audit.json"
    by_key = {
        (frozenset((e["source"], e["target"])), e["type"]): e for e in data["edges"]
    }
    for d in demote:
        e = by_key.get((frozenset((d["a"], d["b"])), d["type"]))
        assert e is not None, f"demoted edge missing from public data: {d}"
        assert e["verified"] is False, f"demoted edge shipped as solid: {d}"
