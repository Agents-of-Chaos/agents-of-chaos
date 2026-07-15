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
P2_SLUGS = {
    "best-handshake",
    "missing-ties",
    "empty-quarter",
    "core-crust",
    "rival-orbit",
}
ALL_SLUGS = P1_SLUGS | P2_SLUGS
PRIVATE_KEYS = ("warm_path", "stage", "notes", "priority")
SIZE_HARD = 160_000
BRACES = re.compile(r"\{([a-zA-Z0-9]+)\}")
RRF_K = 60
ASE_D = 4


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


def test_exactly_eight_questions(qdata):
    assert set(qdata["questions"]) == ALL_SLUGS


@pytest.mark.parametrize("slug", sorted(ALL_SLUGS))
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


@pytest.mark.parametrize("slug", sorted(ALL_SLUGS))
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
    for k in ("all", "verified"):
        assert len(ase[k]) == n, f"ase.{k} misaligned"
        assert all(len(row) == ase["d"] for row in ase[k])
    coreness = qdata["assets"]["coreness"]
    assert set(coreness) == {"full", "business", "investor"}
    for k, vals in coreness.items():
        assert len(vals) == n, f"coreness.{k} misaligned"
        assert all(v is None or 0.0 <= v <= 1.0 for v in vals), f"coreness.{k} range"
    for slug, q in qdata["questions"].items():
        assert len(q["thumb"]["cls"]) == n, f"{slug}: thumb.cls misaligned"


def test_sbm_assets_schema(qdata):
    sbm = qdata["assets"]["sbm"]
    assert len(sbm["blocks"]) == 8 and len(set(sbm["blocks"])) == 8
    assert len(sbm["B"]) == 8 and all(len(r) == 8 for r in sbm["B"])
    assert all(
        sbm["B"][i][j] == sbm["B"][j][i] for i in range(8) for j in range(8)
    ), "sbm.B not symmetric"
    assert set(sbm["vertBlock"].values()) == set(sbm["blocks"])
    assert len(sbm["vertBlock"]) == 8, "vertBlock must map all 8 verticals"
    layers = qdata["assets"]["blockLayers"]
    assert layers["rows"] == layers["cols"] and len(layers["rows"]) == 8
    assert len(layers["layers"]) == 3
    for ly in layers["layers"]:
        assert ly["label"].strip()
        assert len(ly["cells"]) == 8 and all(len(r) == 8 for r in ly["cells"])


def test_handshakes_shape(qdata):
    hs = qdata["assets"]["handshakes"]
    nodes = qdata["nodes"]["ids"]
    n = len(nodes)
    idset = set(nodes)
    assert hs["ids"] == sorted(hs["ids"]) and len(set(hs["ids"])) == len(hs["ids"])
    assert set(hs["ids"]) <= idset, "handshake seat outside nodes.ids"
    assert len(hs["top"]) == len(hs["ids"]), "one top-10 row per LCC seat"
    for seat, row in zip(hs["ids"], hs["top"]):
        assert len(row) == 10, f"{seat}: expected exactly 10 handshake candidates"
        cands = [ci for ci, _ in row]
        assert len(set(cands)) == 10, f"{seat}: duplicate candidates"
        for ci, pct in row:
            assert isinstance(ci, int) and 0 <= ci < n, f"{seat}: candIdx {ci}"
            assert nodes[ci] != seat, f"{seat}: nominated itself"
            assert isinstance(pct, float) and pct > 0, f"{seat}: dPct {pct}"
        # ranked by (-round(dPct, 6), id) then stored at 2dp — consecutive
        # stored values may tick up by ≤0.01 only when the 6dp near-tie
        # straddles a 2dp boundary
        for (_, p1), (_, p2) in zip(row, row[1:]):
            assert p1 >= p2 - 0.01 - 1e-9, f"{seat}: dPct order broken"


def test_hull_groups(qdata):
    q = qdata["questions"]["empty-quarter"]
    hull = q["default"]["marks"]["hull"]
    assert isinstance(hull, list) and len(hull) >= 2, "need ≥2 hull groups"
    for group in hull:
        assert isinstance(group, list) and group, "empty hull group"
        assert group == sorted(group) and len(set(group)) == len(group)
    assert q["thumb"]["hull"] == hull


@pytest.mark.parametrize("slug", ["best-handshake", "missing-ties"])
def test_ghost_edge_marks(qdata, slug):
    edges = qdata["questions"][slug]["default"]["marks"]["edges"]
    assert isinstance(edges, list) and 1 <= len(edges) <= 5
    for pair in edges:
        assert len(pair) == 2 and pair[0] != pair[1], f"bad ghost edge {pair}"
    assert qdata["questions"][slug]["thumb"]["edges"] == edges


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
        for block in (q["thumb"], d["marks"]):
            for key in ("paths", "edges", "hull"):
                for p in block.get(key, []):
                    refs += p
        missing = [r for r in refs if r not in idset]
        assert not missing, f"{slug}: ids not in nodes.ids: {missing[:5]}"
    assert set(qdata["params"]["svnSeeds"]) <= idset
    assert qdata["params"]["svnSeeds"] == sorted(qdata["params"]["svnSeeds"])
    assert qdata["params"]["rrfK"] == RRF_K


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
    assert meta["rrfK"] == RRF_K
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


def test_fixtures_sbm_rank_shape(fixtures, qdata):
    seats = fixtures["meta"]["seats"]
    assert set(fixtures["sbmRank"]) == set(seats)
    b_values = {v for row in qdata["assets"]["sbm"]["B"] for v in row}
    for seat in seats:
        rows = fixtures["sbmRank"][seat]
        assert len(rows) == 10
        for r in rows:
            assert set(r) == {"id", "pFull"}
            assert r["pFull"] in b_values, f"{seat}/{r['id']}: pFull not a B cell"
            assert r["id"] != seat
        # spec rule 11 ordering: (-pFull, id) ascending
        keys = [(-r["pFull"], r["id"]) for r in rows]
        assert keys == sorted(keys), f"{seat}: sbmRank rows out of order"


def test_fixtures_rival_orbit_shape(fixtures):
    seats = fixtures["meta"]["seats"]
    assert set(fixtures["rivalOrbit"]) == set(seats)
    for seat in seats:
        blk = fixtures["rivalOrbit"][seat]
        assert set(blk) == {"seeds", "rows"}
        seeds = blk["seeds"]
        assert seeds and seeds == sorted(seeds) and len(set(seeds)) == len(seeds)
        assert seat not in seeds
        rows = blk["rows"]
        assert len(rows) == 10
        for r in rows:
            assert set(r) == {"id", "s", "sFull"}
            assert r["s"] == round(r["sFull"], 9), f"{seat}/{r['id']}: s rounding"
            assert 0 < r["sFull"] < len(seeds) / RRF_K, f"{seat}/{r['id']}: sFull range"
            assert r["id"] != seat and r["id"] not in seeds
        # spec rule 12 ordering: (-sFull, id) ascending
        keys = [(-r["sFull"], r["id"]) for r in rows]
        assert keys == sorted(keys), f"{seat}: rivalOrbit rows out of order"


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
    for kernel in ("constraint", "ppr", "sbmRank"):
        for seat, rows in fixtures[kernel].items():
            stale = {r["id"] for r in rows} - live
            assert not stale, f"{kernel}/{seat}: stale fixture ids {sorted(stale)[:5]}"
    for seat, blk in fixtures["rivalOrbit"].items():
        stale = (set(blk["seeds"]) | {r["id"] for r in blk["rows"]}) - live
        assert not stale, f"rivalOrbit/{seat}: stale fixture ids {sorted(stale)[:5]}"


# --- strict tier: P2 cross-envelope equalities -------------------------------


def test_strict_sbm_matches_missing_edges(qdata, live_companies):
    skip_unless_strict()
    me = json.loads((ADIR / "missing-edges.json").read_text())
    sbm = qdata["assets"]["sbm"]
    assert sbm["blocks"] == me["data"]["blockP"]["rows"]
    assert sbm["B"] == me["data"]["blockP"]["cells"]
    assert set(sbm["vertBlock"]) == {c["vertical"] for c in live_companies["companies"]}


def test_strict_block_layers_verbatim(qdata):
    skip_unless_strict()
    bs = json.loads((ADIR / "block-structure.json").read_text())
    assert qdata["assets"]["blockLayers"] == bs["data"]["blocks"]


def test_strict_coreness_matches_core_periphery(qdata):
    """Baked 4dp coreness must reproduce every envelope row at its rounding
    (quadrant: 4dp exact; rivals: 3dp — the bake asserts the double-rounding
    is safe)."""
    skip_unless_strict()
    cp = json.loads((ADIR / "core-periphery.json").read_text())
    pos = {cid: i for i, cid in enumerate(qdata["nodes"]["ids"])}
    c = qdata["assets"]["coreness"]
    for p in cp["data"]["quadrant"]:
        assert c["business"][pos[p["id"]]] == p["x"], f"{p['id']}: business"
        assert c["investor"][pos[p["id"]]] == p["y"], f"{p['id']}: investor"
    for r in cp["data"]["rivals"]:
        for layer, want in (
            ("full", r["coreness"]),
            ("business", r["business"]),
            ("investor", r["investor"]),
        ):
            got = c[layer][pos[r["id"]]]
            assert (got is None) == (want is None), f"{r['id']}: {layer} membership"
            if want is not None:
                assert round(got, 3) == want, f"{r['id']}: {layer} coreness"


def test_strict_handshakes_aoc_matches_best_new_edge(qdata):
    skip_unless_strict()
    bne = json.loads((ADIR / "best-new-edge.json").read_text())
    hs = qdata["assets"]["handshakes"]
    nodes = qdata["nodes"]["ids"]
    row = hs["top"][hs["ids"].index("agents-of-chaos")]
    env = bne["data"]["candidates"]
    assert [nodes[ci] for ci, _ in row] == [r["id"] for r in env]
    assert [p for _, p in row] == [r["dAocPct"] for r in env]


def test_strict_handshakes_seats_are_lcc(qdata, live_companies):
    """handshakes.ids must be exactly the live graph's largest component, and
    every nominated candidate a same-component non-neighbor of its seat."""
    skip_unless_strict()
    adj: dict[str, set[str]] = {c["id"]: set() for c in live_companies["companies"]}
    for e in live_companies["edges"]:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    seen: set[str] = set()
    lcc: set[str] = set()
    for start in adj:
        if start in seen:
            continue
        comp, stack = {start}, [start]
        while stack:
            for y in adj[stack.pop()]:
                if y not in comp:
                    comp.add(y)
                    stack.append(y)
        seen |= comp
        if len(comp) > len(lcc):
            lcc = comp
    hs = qdata["assets"]["handshakes"]
    nodes = qdata["nodes"]["ids"]
    assert hs["ids"] == sorted(lcc)
    for seat, row in zip(hs["ids"], hs["top"]):
        for ci, _ in row:
            cand = nodes[ci]
            assert cand in lcc, f"{seat}: {cand} outside the LCC"
            assert cand not in adj[seat], f"{seat}: {cand} already a neighbor"


def test_strict_p2_rows_verbatim(qdata):
    skip_unless_strict()
    bne = json.loads((ADIR / "best-new-edge.json").read_text())
    me = json.loads((ADIR / "missing-edges.json").read_text())
    bs = json.loads((ADIR / "block-structure.json").read_text())
    cn = json.loads((ADIR / "competitor-nominations.json").read_text())
    q = qdata["questions"]
    assert q["best-handshake"]["default"]["rows"] == bne["data"]["candidates"]
    assert q["best-handshake"]["default"]["marks"]["edges"] == [
        [p["a"], p["b"]] for p in bne["data"]["proposed"]
    ]
    assert q["missing-ties"]["default"]["rows"] == me["data"]["unmapped"]
    assert q["empty-quarter"]["default"]["rows"] == bs["data"]["misShelved"]
    assert q["rival-orbit"]["default"]["rows"] == cn["data"]["prospects"]


def test_strict_missing_ties_edges_resolve(qdata, live_companies):
    """marks.edges must be the first ≤5 triage pairs whose 'A ↔ B' name
    labels resolve against the live company names."""
    skip_unless_strict()
    me = json.loads((ADIR / "missing-edges.json").read_text())
    name_to_id = {c["name"]: c["id"] for c in live_companies["companies"]}
    want = []
    for t in me["data"]["triage"]:
        a, sep, b = t["label"].partition(" ↔ ")
        assert sep, t["label"]
        if a in name_to_id and b in name_to_id:
            want.append([name_to_id[a], name_to_id[b]])
        if len(want) == 5:
            break
    assert qdata["questions"]["missing-ties"]["default"]["marks"]["edges"] == want


def test_strict_empty_quarter_hull_live(qdata, live_companies):
    skip_unless_strict()
    hull = qdata["questions"]["empty-quarter"]["default"]["marks"]["hull"]
    by_vert = {
        v: sorted(c["id"] for c in live_companies["companies"] if c["vertical"] == v)
        for v in ("security-eval-vendor", "bank-fintech")
    }
    assert hull == [by_vert["security-eval-vendor"], by_vert["bank-fintech"]]


def test_strict_core_crust_rows_rule(qdata):
    """rows = the 20 most investor-core quadrant companies (sort (-y, id));
    default.ids = the prospect quadrant (x < mid-x, y ≥ mid-y, sort -y)."""
    skip_unless_strict()
    cp = json.loads((ADIR / "core-periphery.json").read_text())
    quadrant = cp["data"]["quadrant"]
    xs = [p["x"] for p in quadrant]
    ys = [p["y"] for p in quadrant]
    mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    prospects = sorted(
        (p for p in quadrant if p["x"] < mx and p["y"] >= my), key=lambda p: -p["y"]
    )
    d = qdata["questions"]["core-crust"]["default"]
    assert d["rows"] == sorted(quadrant, key=lambda p: (-p["y"], p["id"]))[:20]
    assert d["ids"] == [p["id"] for p in prospects]


def test_strict_svn_seeds_live(qdata, live_companies):
    skip_unless_strict()
    want = sorted(c["id"] for c in live_companies["companies"] if c.get("competitor"))
    assert qdata["params"]["svnSeeds"] == want


# --- strict tier: full fixture recomputes (pure stdlib = the kernel spec) ----


def kernel_graph(live_companies):
    ids = sorted(c["id"] for c in live_companies["companies"])
    idx = {cid: i for i, cid in enumerate(ids)}
    adj: dict[str, set[str]] = {cid: set() for cid in ids}
    for e in live_companies["edges"]:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    return ids, idx, adj


def test_strict_fixture_sbm_rank_recompute(qdata, fixtures, live_companies):
    """Re-derive every sbmRank fixture row from the baked sbm asset + the
    live graph, following spec rule 11 exactly."""
    skip_unless_strict()
    ids, _, adj = kernel_graph(live_companies)
    vert = {c["id"]: c["vertical"] for c in live_companies["companies"]}
    sbm = qdata["assets"]["sbm"]
    bidx = {b: i for i, b in enumerate(sbm["blocks"])}
    block_of = {cid: bidx[sbm["vertBlock"][vert[cid]]] for cid in ids}
    for seat, rows in fixtures["sbmRank"].items():
        bs = block_of[seat]
        cands = [u for u in ids if u != seat and u not in adj[seat]]
        top = sorted(cands, key=lambda u: (-sbm["B"][bs][block_of[u]], u))[:10]
        want = [{"id": u, "pFull": sbm["B"][bs][block_of[u]]} for u in top]
        assert rows == want, f"sbmRank/{seat} drifted from spec rule 11"


def test_strict_fixture_rival_orbit_recompute(qdata, fixtures, live_companies):
    """Re-derive every rivalOrbit fixture block from the baked verified ASE +
    the live graph, following spec rule 12 exactly (same accumulation order,
    so sFull must match bit-for-bit)."""
    skip_unless_strict()
    ids = qdata["nodes"]["ids"]
    pos = {cid: i for i, cid in enumerate(ids)}
    X = qdata["assets"]["ase"]["verified"]
    svn = qdata["params"]["svnSeeds"]
    ver_nbrs: dict[str, set[str]] = {cid: set() for cid in ids}
    comp_nbrs: dict[str, set[str]] = {cid: set() for cid in ids}
    for e in live_companies["edges"]:
        if e["verified"]:
            ver_nbrs[e["source"]].add(e["target"])
            ver_nbrs[e["target"]].add(e["source"])
        if e["type"] == "competitor":
            comp_nbrs[e["source"]].add(e["target"])
            comp_nbrs[e["target"]].add(e["source"])
    for seat, blk in fixtures["rivalOrbit"].items():
        seeds = sorted(s for s in comp_nbrs[seat] if ver_nbrs[s])
        if not seeds:
            seeds = [s for s in svn if s != seat]
        assert blk["seeds"] == seeds, f"rivalOrbit/{seat}: seed set drifted"
        seed_set = set(seeds)
        cands = [u for u in ids if ver_nbrs[u] and u != seat and u not in seed_set]
        score = dict.fromkeys(cands, 0.0)
        for s in seeds:
            xs = X[pos[s]]
            d = {}
            for u in cands:
                xu = X[pos[u]]
                t = 0.0
                for k in range(ASE_D):
                    diff = xu[k] - xs[k]
                    t += diff * diff
                d[u] = math.sqrt(t)
            order = sorted(cands, key=lambda u: (d[u], u))
            for rank0, u in enumerate(order):
                score[u] += 1.0 / (RRF_K + rank0 + 1)
        top = sorted(cands, key=lambda u: (-score[u], u))[:10]
        want = [{"id": u, "s": round(score[u], 9), "sFull": score[u]} for u in top]
        assert blk["rows"] == want, f"rivalOrbit/{seat} drifted from spec rule 12"
