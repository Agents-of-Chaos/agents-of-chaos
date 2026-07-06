"""Validate the baked /networks/analyses JSONs. Run: pytest experiments/analyses/tests

Two tiers:
- always-on: schema, finiteness, leakage, sizes — safe under nightly graph churn,
  so this suite never blocks the funding-nightly PR gate.
- strict (ANALYSES_STRICT=1, set by bake.sh): 100% id membership in the LIVE
  graphs + input stamps equal the live graphs — the regeneration gate.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "src" / "data" / "analyses"
STRICT = os.environ.get("ANALYSES_STRICT") == "1"

GRAPHS = {"companies", "funding", "both"}
PRIVATE_KEYS = {"warm_path", "stage", "notes"}
ENVELOPE_KEYS = {"slug", "graph", "title", "sub", "headline", "prose", "inputs", "data"}
SIZE_HARD = 300_000


def analysis_files() -> list[Path]:
    return sorted(p for p in OUT.glob("*.json") if p.stem != "shared")


@pytest.fixture(scope="module")
def live_ids() -> set[str]:
    companies = json.loads((ROOT / "src/data/companies.json").read_text())
    funding = json.loads((ROOT / "src/data/funding.json").read_text())
    return {c["id"] for c in companies["companies"]} | {
        n["id"] for n in funding["nodes"]
    }


@pytest.fixture(scope="module")
def live_stamps() -> dict:
    companies = json.loads((ROOT / "src/data/companies.json").read_text())
    funding = json.loads((ROOT / "src/data/funding.json").read_text())
    return {
        "companies": {
            "nodes": len(companies["companies"]),
            "edges": len(companies["edges"]),
        },
        "funding": {"nodes": len(funding["nodes"]), "edges": len(funding["edges"])},
    }


def _raise_on_nan(x: str):
    raise AssertionError(f"non-finite literal {x!r} in baked JSON")


def walk_ids(value, out: set[str]):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "id" and isinstance(v, str):
                out.add(v)
            else:
                walk_ids(v, out)
    elif isinstance(value, list):
        for v in value:
            walk_ids(v, out)


def walk_floats(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            walk_floats(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            walk_floats(v, f"{path}[{i}]")
    elif isinstance(value, float):
        assert math.isfinite(value), f"non-finite float at {path}"


def test_analyses_exist():
    assert analysis_files(), "no baked analyses found — run bake.sh"
    assert (OUT / "shared.json").exists(), "shared.json missing — run prep_shared.py"


@pytest.mark.parametrize("path", analysis_files(), ids=lambda p: p.stem)
def test_envelope(path: Path):
    env = json.loads(path.read_text(), parse_constant=_raise_on_nan)
    missing = ENVELOPE_KEYS - env.keys()
    assert not missing, f"missing envelope keys: {missing}"
    assert env["slug"] == path.stem
    assert re.match(r"^[a-z0-9-]+$", env["slug"])
    assert env["graph"] in GRAPHS
    for k in ("intro", "how", "method"):
        assert env["prose"].get(k, "").startswith("<p>"), f"prose.{k} missing/not html"
    assert "<strong>" in env["headline"], "headline needs its key number in <strong>"
    assert "<script" not in json.dumps(env), "script tag in baked analysis"
    assert isinstance(env["inputs"], dict) and env["inputs"]
    for g, s in env["inputs"].items():
        assert g in ("companies", "funding")
        assert set(s) == {"nodes", "edges"}
    walk_floats(env["data"])


@pytest.mark.parametrize("path", analysis_files(), ids=lambda p: p.stem)
def test_no_private_keys(path: Path):
    raw = path.read_text()
    for k in PRIVATE_KEYS:
        assert f'"{k}"' not in raw, f"private key {k!r} leaked into {path.name}"


@pytest.mark.parametrize("path", analysis_files(), ids=lambda p: p.stem)
def test_size_caps(path: Path):
    assert (
        path.stat().st_size < SIZE_HARD
    ), f"{path.name} over the {SIZE_HARD}B hard cap"


@pytest.mark.parametrize("path", analysis_files(), ids=lambda p: p.stem)
def test_ids_have_labels_nearby(path: Path):
    """Every object with an id must also bake a label (staleness fallback)."""

    def walk(value, where=""):
        if isinstance(value, dict):
            if "id" in value and isinstance(value["id"], str):
                assert (
                    "label" in value
                ), f"{path.name}: id without baked label at {where}"
            for k, v in value.items():
                walk(v, f"{where}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{where}[{i}]")

    env = json.loads(path.read_text())
    walk(env["data"], "data")


@pytest.mark.parametrize("path", analysis_files(), ids=lambda p: p.stem)
def test_ids_membership(path: Path, live_ids):
    env = json.loads(path.read_text())
    shipped: set[str] = set()
    walk_ids(env["data"], shipped)
    stale = shipped - live_ids
    if STRICT:
        assert not stale, f"{path.name}: stale ids at bake time: {sorted(stale)[:8]}"
    elif stale:
        pytest.skip(
            f"{len(stale)} stale id(s) vs live graphs (ok under churn): {sorted(stale)[:4]}"
        )


@pytest.mark.parametrize("path", analysis_files(), ids=lambda p: p.stem)
def test_input_stamps(path: Path, live_stamps):
    if not STRICT:
        pytest.skip("stamp equality only enforced at bake time (ANALYSES_STRICT=1)")
    env = json.loads(path.read_text())
    for g, s in env["inputs"].items():
        assert (
            s == live_stamps[g]
        ), f"{path.name}: {g} stamp {s} != live {live_stamps[g]} — rebake"


def test_shared_json(live_ids):
    shared = json.loads((OUT / "shared.json").read_text())
    for g in ("companies", "funding"):
        graph = shared["graphs"][g]
        assert graph["nodes"], f"shared.json {g} empty"
        for node_id, n in graph["nodes"].items():
            assert set(n) >= {"label", "group", "degree", "x", "y"}
            assert 0 <= n["x"] <= 1 and 0 <= n["y"] <= 1
        for a, b in graph["edges"]:
            assert (
                a in graph["nodes"] and b in graph["nodes"]
            ), f"dangling shared edge {a}~{b}"
    if STRICT:
        shared_ids = set(shared["graphs"]["companies"]["nodes"]) | set(
            shared["graphs"]["funding"]["nodes"]
        )
        assert (
            shared_ids == live_ids
        ), "shared.json drifted from live graphs — rerun prep_shared.py"
