"""Validate the baked question data (src/data/questions/). Run:
pytest experiments/analyses/tests

Two tiers, same split as test_analyses_data.py:
- always-on: schema, alignment, finiteness, leakage, template rules, sizes —
  safe under nightly graph churn, never blocks the funding-nightly PR gate.
- strict (ANALYSES_STRICT=1, set by bake.sh): stamps equal the live graphs,
  nodes == live ids, layout == shared.json, cross-envelope equality — the
  regeneration gate.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
QDIR = ROOT / "src" / "data" / "questions"
ADIR = ROOT / "src" / "data" / "analyses"
STRICT = os.environ.get("ANALYSES_STRICT") == "1"

QUESTIONS_FILE = QDIR / "questions-companies.json"
FIXTURES_FILE = QDIR / "fixtures.json"
P1_SLUGS = {"bridges", "meet-first", "market-shape"}
PRIVATE_KEYS = ("warm_path", "stage", "notes", "priority")
SIZE_HARD = 160_000
BRACES = re.compile(r"\{([a-zA-Z0-9]+)\}")


def _raise_on_nan(x: str):
    raise AssertionError(f"non-finite literal {x!r} in baked JSON")


@pytest.fixture(scope="module")
def qdata() -> dict:
    return json.loads(QUESTIONS_FILE.read_text(), parse_constant=_raise_on_nan)


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURES_FILE.read_text(), parse_constant=_raise_on_nan)


@pytest.fixture(scope="module")
def live_companies() -> dict:
    return json.loads((ROOT / "src/data/companies.json").read_text())


def walk_floats(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            walk_floats(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            walk_floats(v, f"{path}[{i}]")
    elif isinstance(value, float):
        assert math.isfinite(value), f"non-finite float at {path}"


# --- always-on tier ---------------------------------------------------------


def test_files_exist():
    assert (
        QUESTIONS_FILE.exists()
    ), "questions-companies.json missing — run prep_questions.py"
    assert FIXTURES_FILE.exists(), "fixtures.json missing — run prep_questions.py"


def test_kind_and_graph(qdata):
    assert qdata["kind"] == "question-data"
    assert qdata["graph"] == "companies"
    assert isinstance(qdata["inputs"], dict) and "companies" in qdata["inputs"]
    assert set(qdata["inputs"]["companies"]) == {"nodes", "edges"}


def test_exactly_p1_questions(qdata):
    assert set(qdata["questions"]) == P1_SLUGS


@pytest.mark.parametrize("slug", sorted(P1_SLUGS))
def test_question_schema(qdata, slug):
    q = qdata["questions"][slug]
    for k in ("question", "source", "templates", "thumb", "default"):
        assert k in q, f"{slug}: missing {k}"
    assert q["question"].strip().endswith("?")
    assert isinstance(q["source"], list) and q["source"]
    assert "default" in q["templates"] and "isolated" in q["templates"]
    d = q["default"]
    for k in ("seat", "sentence", "callouts", "ids", "rows", "marks"):
        assert k in d, f"{slug}: default missing {k}"
    # we bake FINAL sentences — non-empty, no unfilled {slot} left inside
    assert d["sentence"].strip(), f"{slug}: empty default sentence"
    assert "{" not in d["sentence"], f"{slug}: unfilled slot in default sentence"
    assert "<" not in d["sentence"], f"{slug}: HTML in default sentence"
    assert isinstance(d["callouts"], list) and 1 <= len(d["callouts"]) <= 3
    for c in d["callouts"]:
        assert set(c) == {"id", "text"} and c["text"].strip()
    assert isinstance(d["ids"], list) and d["ids"]
    assert isinstance(d["rows"], list) and d["rows"]
    assert isinstance(d["marks"], dict)


@pytest.mark.parametrize("slug", sorted(P1_SLUGS))
def test_template_braces(qdata, slug):
    for name, tpl in qdata["questions"][slug]["templates"].items():
        assert tpl.count("{") == tpl.count("}"), f"{slug}.{name}: unbalanced braces"
        stripped = BRACES.sub("", tpl)
        assert (
            "{" not in stripped and "}" not in stripped
        ), f"{slug}.{name}: malformed slot syntax"
        assert (
            "{seat}" in tpl or name == "default"
        ), f"{slug}.{name}: variant templates should reference the seat"


def test_aligned_arrays(qdata):
    nodes = qdata["nodes"]
    n = len(nodes["ids"])
    assert n > 0
    assert nodes["ids"] == sorted(nodes["ids"])
    assert len(set(nodes["ids"])) == n
    for k in ("x", "y", "label"):
        assert len(nodes[k]) == n, f"nodes.{k} misaligned"
    ase = qdata["assets"]["ase"]
    assert len(ase["all"]) == n
    assert all(len(row) == ase["d"] for row in ase["all"])
    for slug, q in qdata["questions"].items():
        assert len(q["thumb"]["cls"]) == n, f"{slug}: thumb.cls misaligned"


def test_cls_values(qdata):
    for slug, q in qdata["questions"].items():
        for c in q["thumb"]["cls"]:
            assert isinstance(c, int) and 0 <= c <= 3, f"{slug}: bad cls {c!r}"


def test_ids_internal_integrity(qdata):
    """Every id referenced anywhere must exist in nodes.ids."""
    idset = set(qdata["nodes"]["ids"])
    for slug, q in qdata["questions"].items():
        d = q["default"]
        assert d["seat"] in idset
        refs = list(d["ids"]) + [c["id"] for c in d["callouts"]]
        refs += [r["id"] for r in d["rows"] if isinstance(r, dict) and "id" in r]
        refs += q["thumb"].get("rings", [])
        for p in q["thumb"].get("paths", []) + d["marks"].get("paths", []):
            refs += p
        missing = [r for r in refs if r not in idset]
        assert not missing, f"{slug}: ids not in nodes.ids: {missing[:5]}"


def test_finiteness(qdata, fixtures):
    walk_floats(qdata)
    walk_floats(fixtures)


@pytest.mark.parametrize("path", [QUESTIONS_FILE, FIXTURES_FILE], ids=lambda p: p.stem)
def test_no_private_keys(path: Path):
    raw = path.read_text()
    for k in PRIVATE_KEYS:
        # '"<k>":' matches only KEYS in minified JSON (a closing string quote
        # is never followed by ':'), so prose containing the word is fine
        assert f'"{k}":' not in raw, f"private key {k!r} leaked into {path.name}"


@pytest.mark.parametrize("path", [QUESTIONS_FILE, FIXTURES_FILE], ids=lambda p: p.stem)
def test_size_caps(path: Path):
    assert path.stat().st_size < SIZE_HARD, f"{path.name} over the {SIZE_HARD}B cap"


def test_fixtures_shape(fixtures):
    meta = fixtures["meta"]
    seats = meta["seats"]
    assert len(seats) == 6 and len(set(seats)) == 6
    assert seats[0] == "agents-of-chaos"
    assert meta["alpha"] == 0.85 and meta["iterations"] == 100
    assert set(fixtures["constraint"]) == set(seats)
    assert set(fixtures["ppr"]) == set(seats)
    for seat in seats:
        c_rows = fixtures["constraint"][seat]
        assert len(c_rows) <= 10
        for r in c_rows:
            assert set(r) == {"id", "c", "cFull"}
            assert r["c"] == round(
                r["cFull"], 6
            ), f"{seat}/{r['id']}: c != round(cFull, 6)"
        # spec rule 8 ordering: (round6(c), id) ascending
        keys = [(r["c"], r["id"]) for r in c_rows]
        assert keys == sorted(keys), f"{seat}: constraint rows out of order"
        p_rows = fixtures["ppr"][seat]
        assert len(p_rows) == 10
        for r in p_rows:
            assert set(r) == {"id", "s", "sFull"}
            assert r["s"] == round(
                r["sFull"], 9
            ), f"{seat}/{r['id']}: s != round(sFull, 9)"
        # spec rule 9 ordering: (-sFull, id) ascending
        pkeys = [(-r["sFull"], r["id"]) for r in p_rows]
        assert pkeys == sorted(pkeys), f"{seat}: ppr rows out of order"


# --- strict tier (bake gate: ANALYSES_STRICT=1) ------------------------------


def skip_unless_strict():
    if not STRICT:
        pytest.skip(
            "cross-envelope equality only enforced at bake time (ANALYSES_STRICT=1)"
        )


def test_strict_stamp(qdata, live_companies):
    skip_unless_strict()
    live = {
        "nodes": len(live_companies["companies"]),
        "edges": len(live_companies["edges"]),
    }
    assert qdata["inputs"]["companies"] == live, "questions data stale — rerun bake.sh"


def test_strict_nodes_are_live(qdata, live_companies):
    skip_unless_strict()
    assert qdata["nodes"]["ids"] == sorted(c["id"] for c in live_companies["companies"])


def test_strict_layout_matches_shared(qdata):
    skip_unless_strict()
    shared = json.loads((ADIR / "shared.json").read_text())
    layout = shared["graphs"]["companies"]["nodes"]
    nodes = qdata["nodes"]
    for i, cid in enumerate(nodes["ids"]):
        assert nodes["x"][i] == layout[cid]["x"], f"{cid}: x != shared.json layout"
        assert nodes["y"][i] == layout[cid]["y"], f"{cid}: y != shared.json layout"


def test_strict_ase_matches_market_map(qdata):
    skip_unless_strict()
    mm = json.loads((ADIR / "market-map.json").read_text())
    map_xy = {p["id"]: (p["x"], p["y"]) for p in mm["data"]["map"]}
    nodes = qdata["nodes"]
    ase = qdata["assets"]["ase"]["all"]
    for i, cid in enumerate(nodes["ids"]):
        assert (ase[i][0], ase[i][1]) == map_xy[
            cid
        ], f"{cid}: ase dims 0-1 != market-map"


def test_strict_bridges_rows_verbatim(qdata):
    skip_unless_strict()
    brokers = json.loads((ADIR / "brokers.json").read_text())
    assert (
        qdata["questions"]["bridges"]["default"]["rows"] == brokers["data"]["brokers"]
    )


def test_strict_market_shape_rows_verbatim(qdata):
    skip_unless_strict()
    mm = json.loads((ADIR / "market-map.json").read_text())
    assert (
        qdata["questions"]["market-shape"]["default"]["rows"] == mm["data"]["neighbors"]
    )


def test_strict_fixture_constraint_vs_brokers(fixtures):
    """Cross-check the kernel against the brokers envelope on shared ids.

    Verified equivalent weightings: the envelope's nx.constraint (equal-weight
    Burt on the mixed-graph LCC) computes the same quantity as the fixture
    kernel on the full simple graph — an LCC node's neighbors all live in the
    LCC, so its degree (and constraint) is identical in both. Values agree at
    the envelope's 3-decimal rounding for every overlapping id (checked
    2026-07-15). Rank ORDER is deliberately not cross-checked: the envelope
    ranks all eligible LCC nodes with tie-break (constraint, -effSize, id)
    while the fixture pools the seat's 2-hop neighborhood with tie-break
    (round(c, 6), id)."""
    skip_unless_strict()
    brokers = json.loads((ADIR / "brokers.json").read_text())
    envelope_c = {r["id"]: r["constraint"] for r in brokers["data"]["brokers"]}
    aoc_rows = fixtures["constraint"]["agents-of-chaos"]
    overlap = [r for r in aoc_rows if r["id"] in envelope_c]
    assert overlap, "no overlap between AoC fixture and brokers envelope?"
    for r in overlap:
        assert round(r["cFull"], 3) == envelope_c[r["id"]], (
            f"{r['id']}: kernel constraint {round(r['cFull'], 3)} != "
            f"envelope {envelope_c[r['id']]}"
        )


def test_strict_fixture_ids_live(fixtures, live_companies):
    skip_unless_strict()
    live = {c["id"] for c in live_companies["companies"]}
    assert set(fixtures["meta"]["seats"]) <= live
    for kernel in ("constraint", "ppr"):
        for seat, rows in fixtures[kernel].items():
            stale = {r["id"] for r in rows} - live
            assert not stale, f"{kernel}/{seat}: stale fixture ids {sorted(stale)[:5]}"
