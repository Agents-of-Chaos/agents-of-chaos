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
