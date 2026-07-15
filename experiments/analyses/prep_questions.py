# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "graspologic==3.4.4"]
# ///
"""prep_questions — bake src/data/questions/*: question data for the on-map
questions UI (P1, companies graph: bridges · meet-first · market-shape) plus
the JS kernel-parity fixtures. Run: cd experiments/analyses && uv run
prep_questions.py — bake.sh runs it AFTER the panel loop because the default
answers are copied from the just-baked envelopes (single source of truth).

Inputs are ONLY src/data/companies.json, the baked sibling envelopes (brokers,
intro-chains, proximity-rank, market-map), and src/data/analyses/shared.json —
never the private overlays. Re-runs must be byte-identical (no wall-clock, all
randomness seeded, SVD signs fixed).

Kernel determinism spec — the JS mirror (src/scripts/questions/kernels.js)
must follow these rules EXACTLY; fixtures.json is the parity oracle:

  1. Graph = UNDIRECTED SIMPLE graph over ALL edges: dedupe (source,target)
     pairs regardless of direction; no self-loops exist in the data.
  2. Node index = position in the list of node ids sorted ascending (plain
     string comparison; ids are ASCII slugs so Python str < / JS < agree).
  3. Adjacency lists sorted ascending by neighbor index.
  4. All floating-point accumulation iterates in ascending index order;
     scores are plain float64 (double) arithmetic, no fma, no reordering.
  5. Burt: invdeg[i] = 1.0/deg[i] precomputed. c_i = sum_{j in N(i), asc}
     (inner)^2 where inner = invdeg[i] + sum_{q in N(i), q != j, asc,
     q adjacent to j} invdeg[i]*invdeg[q]. Terms added ONLY when q~j
     (no +0.0 adds).
  6. PPR: x0 = e_seat; 100 fixed iterations of
       next = zeros; for u asc: if deg[u]>0: contrib = alpha*(x[u]/deg[u]);
         for v in N(u) asc: next[v] += contrib
       dangling = sum over u asc with deg[u]==0 of x[u]
       next[seat] = next[seat] + alpha*dangling + (1.0-alpha)
     alpha = 0.85. No renormalization, no early stop.
  7. Fixture seats: 'agents-of-chaos' + nodes at index floor(q*(n-1)) for
     q in (0.1, 0.4, 0.55, 0.7, 0.95) of the list of ALL nodes sorted asc
     by (degree, id).
  8. Constraint candidate pool per seat = BFS 2-hop neighborhood (dist<=2,
     seat included), filtered to degree >= 3; sort key (round(c,6), id) asc;
     take 10.
  9. PPR top-10: sort key (-sFull, id) asc; take 10 (seat not excluded).
 10. Fixture floats: c = round(x, 6), s = round(x, 9) (Python round-half-even
     on the exact decimal expansion of the double); cFull/sFull =
     full-precision doubles (JSON shortest-roundtrip repr) for the
     exact-equality assertion in node --test.
"""

import json

import numpy as np
from _shared import (
    OUT_DIR,
    QUESTIONS_DIR,
    emit_questions,
    fix_signs,
    load_companies,
    stamp,
)

AOC = "agents-of-chaos"
SEED = 0
ASE_D = 4  # matches market-map's Zhu–Ghodsi pick; asserted against the envelope
PPR_ALPHA = 0.85
PPR_ITERS = 100
MIN_DEGREE = 3
FIXTURE_QUANTILES = (0.1, 0.4, 0.55, 0.7, 0.95)
# Route friction per edge type — must stay equal to intro-chains.py FRICTION,
# so client-side route recomputation prices edges like the baked chains.
FRICTION = {"business": 1, "shared-investor": 2, "competitor": 10}


def load_envelope(slug: str, companies: dict) -> dict:
    env = json.loads((OUT_DIR / f"{slug}.json").read_text())
    assert env["inputs"]["companies"] == stamp(
        companies
    ), f"{slug}.json is stale vs live companies.json — run bake.sh"
    return env


# --- deterministic kernel graph (spec rules 1-3) ---------------------------


def build_kernel_graph(companies: dict):
    ids = sorted(c["id"] for c in companies["companies"])
    n = len(ids)
    idx = {cid: i for i, cid in enumerate(ids)}
    pair_set = set()
    for e in companies["edges"]:
        a, b = idx[e["source"]], idx[e["target"]]
        assert a != b, f"self-loop at {e['source']}"
        pair_set.add((min(a, b), max(a, b)))
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in pair_set:
        adj[a].append(b)
        adj[b].append(a)
    for lst in adj:
        lst.sort()
    deg = [len(lst) for lst in adj]
    return ids, idx, adj, deg, len(pair_set)


def constraint(adj, adj_sets, invdeg, i: int) -> float:
    """Burt constraint, equal weights (spec rule 5)."""
    c = 0.0
    pi = invdeg[i]
    for j in adj[i]:
        inner = pi
        for q in adj[i]:
            if q != j and j in adj_sets[q]:
                inner += pi * invdeg[q]
        c += inner * inner
    return c


def two_hop(adj, seed: int) -> list[int]:
    """BFS 2-hop neighborhood, seat included (spec rule 8 pool)."""
    seen = {seed}
    frontier = [seed]
    for _ in range(2):
        nxt = []
        for u in frontier:
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    nxt.append(v)
        frontier = nxt
    return sorted(seen)


def ppr(adj, deg, n: int, seed: int) -> list[float]:
    """Personalized PageRank, fixed 100 iterations (spec rule 6)."""
    x = [0.0] * n
    x[seed] = 1.0
    for _ in range(PPR_ITERS):
        nxt = [0.0] * n
        for u in range(n):
            if deg[u] > 0:
                contrib = PPR_ALPHA * (x[u] / deg[u])
                for v in adj[u]:
                    nxt[v] += contrib
        dangling = 0.0
        for u in range(n):
            if deg[u] == 0:
                dangling += x[u]
        nxt[seed] = nxt[seed] + PPR_ALPHA * dangling + (1.0 - PPR_ALPHA)
        x = nxt
    return x


def bake_fixtures(ids, idx, adj, deg, n_pairs) -> dict:
    """6-seat parity fixtures for the constraint + ppr kernels (spec 7-10)."""
    n = len(ids)
    adj_sets = [set(lst) for lst in adj]
    invdeg = [1.0 / d if d > 0 else 0.0 for d in deg]
    by_deg = sorted(range(n), key=lambda i: (deg[i], ids[i]))
    seats = [AOC] + [ids[by_deg[int(q * (n - 1))]] for q in FIXTURE_QUANTILES]
    assert len(set(seats)) == 6, f"fixture seats collide: {seats}"

    fixtures = {
        "meta": {
            "seats": seats,
            "alpha": PPR_ALPHA,
            "iterations": PPR_ITERS,
            "minDegree": MIN_DEGREE,
            "nodes": n,
            "undirectedEdges": n_pairs,
        },
        "constraint": {},
        "ppr": {},
    }
    for seat in seats:
        s_i = idx[seat]
        pool = [i for i in two_hop(adj, s_i) if deg[i] >= MIN_DEGREE]
        c_rows = sorted(
            ((round(constraint(adj, adj_sets, invdeg, i), 6), ids[i], i) for i in pool),
            key=lambda t: (t[0], t[1]),
        )[:10]
        fixtures["constraint"][seat] = [
            {"id": cid, "c": c6, "cFull": constraint(adj, adj_sets, invdeg, i)}
            for c6, cid, i in c_rows
        ]
        x = ppr(adj, deg, n, s_i)
        top = sorted(range(n), key=lambda i: (-x[i], ids[i]))[:10]
        fixtures["ppr"][seat] = [
            {"id": ids[i], "s": round(x[i], 9), "sFull": x[i]} for i in top
        ]
    return fixtures


# --- ASE asset: must reproduce market-map's embedding exactly ---------------


def bake_ase(companies: dict, market_map: dict, sorted_ids: list[str]) -> dict:
    """ASE identical to market-map.py (file-order adjacency, n_elbows=2,
    svd_seed=0, fix_signs), re-ordered to sorted_ids and rounded to 4dp.
    Dims 0-1 are asserted equal to the envelope's data.map per id."""
    from graspologic.embed import AdjacencySpectralEmbed

    file_ids = [c["id"] for c in companies["companies"]]
    idx = {cid: k for k, cid in enumerate(file_ids)}
    A = np.zeros((len(file_ids), len(file_ids)))
    for e in companies["edges"]:
        a, b = idx[e["source"]], idx[e["target"]]
        A[a, b] = A[b, a] = 1.0
    X = AdjacencySpectralEmbed(n_elbows=2, svd_seed=SEED).fit_transform(A)
    assert isinstance(X, np.ndarray) and X.ndim == 2, "undirected ASE expected"
    X = fix_signs(X)
    assert X.shape == (len(file_ids), ASE_D), f"ASE dims changed: {X.shape}"

    by_id = {
        cid: [round(float(X[i, j]), 4) for j in range(ASE_D)]
        for i, cid in enumerate(file_ids)
    }
    map_xy = {p["id"]: (p["x"], p["y"]) for p in market_map["data"]["map"]}
    assert set(map_xy) == set(by_id), "market-map data.map id set drifted"
    for cid, row in by_id.items():
        assert (row[0], row[1]) == map_xy[
            cid
        ], f"ASE dims 0-1 disagree with market-map for {cid}"
    return {"d": ASE_D, "all": [by_id[cid] for cid in sorted_ids]}


# --- question blocks --------------------------------------------------------


def bake_bridges(brokers_env, companies, sorted_ids, pos, adj, deg, idx) -> dict:
    rows = brokers_env["data"]["brokers"]
    assert rows and rows == sorted(
        rows, key=lambda r: r["constraint"]
    ), "brokers rows not ascending by constraint"
    n_verticals = len({c["vertical"] for c in companies["companies"]})
    assert n_verticals == 8, f"vertical count changed ({n_verticals}) — reword"

    # eligible = degree floor within the giant component, same population the
    # brokers envelope ranks (constraint says nothing below MIN_DEGREE)
    n = len(sorted_ids)
    seen: set[int] = set()
    lcc: set[int] = set()
    for start in range(n):
        if start in seen:
            continue
        comp = {start}
        frontier = [start]
        seen.add(start)
        while frontier:
            u = frontier.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    comp.add(v)
                    frontier.append(v)
        if len(comp) > len(lcc):
            lcc = comp
    eligible = {sorted_ids[i] for i in lcc if deg[i] >= MIN_DEGREE}
    broker_ids = [r["id"] for r in rows]
    assert set(broker_ids) <= eligible, "brokers envelope ranks a non-eligible node"

    cls = [0] * n
    for cid in eligible:
        cls[pos[cid]] = 1
    for k, cid in enumerate(broker_ids):
        cls[pos[cid]] = 3 if k < 5 else 2

    top, second = rows[0], rows[1]
    ratio = round(top["effSize"] / second["effSize"], 1)
    sentence = (
        f"{top['label']} holds the market's least-constrained seat — it bridges "
        f"{top['spans']} of {n_verticals} verticals, {ratio:g}× the effective "
        f"reach of the next broker."
    )
    callouts = [
        {"id": r["id"], "text": f"#{k} bridge · spans {r['spans']} verticals"}
        for k, r in enumerate(rows[:3], 1)
    ]
    return {
        "question": "Who bridges the market?",
        "source": ["brokers"],
        "templates": {
            "default": (
                "{name} holds the least-constrained seat near {seat} — "
                "it spans {spans} of 8 verticals."
            ),
            "self": (
                "{seat} is itself a bridge — #{rank} of {n} by constraint, "
                "spanning {spans} verticals."
            ),
            "isolated": (
                "{seat} has too few mapped ties for brokerage to mean anything yet."
            ),
        },
        "thumb": {"cls": cls, "rings": broker_ids[:5]},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": broker_ids,
            "rows": rows,
            "marks": {},
        },
    }


def bake_meet_first(chains_env, prox_env, sorted_ids, pos) -> dict:
    company_chains = chains_env["data"]["companyChains"]
    leaderboard = chains_env["data"]["leaderboard"]
    counts = chains_env["data"]["counts"]
    reach = prox_env["data"]["reach"]
    assert company_chains and leaderboard and reach

    # the top intermediary; the baked sentence claims "all N routes" so the
    # appearance count must actually cover every company chain
    lead = leaderboard[0]
    n_routes = counts["companyChains"]
    assert (
        lead["appearances"] == n_routes
    ), "top intermediary no longer on every route — reword the sentence"
    by_target = {c["target"]["id"]: c for c in company_chains}
    top3 = reach[:3]
    assert all(r["id"] in by_target for r in top3), "reach top-3 lack baked chains"
    hops3 = {len(by_target[r["id"]]["chains"][0]["edges"]) for r in top3}
    assert len(hops3) == 1, f"reach top-3 at unequal hops {hops3} — reword"
    sentence = (
        f"{top3[0]['label']}, {top3[1]['label']}, and {top3[2]['label']} sit "
        f"{hops3.pop()} handshakes out — all {n_routes} best routes open "
        f"through {lead['label']}."
    )
    callouts = [
        {"id": lead["id"], "text": f"every route opens here · {n_routes} of {n_routes}"}
    ]
    for cc in company_chains[:2]:
        best = cc["chains"][0]
        callouts.append(
            {
                "id": cc["target"]["id"],
                "text": f"{cc['why']} · {len(best['edges'])} handshakes",
            }
        )

    # merged evidence rows (≤20): every baked chain target first (route facts),
    # then proximity-rank's top reach rows that add new companies, PPR-ranked
    rank_of = {r["id"]: k for k, r in enumerate(reach, 1)}
    rows = []
    for cc in company_chains:
        best = cc["chains"][0]
        rows.append(
            {
                "id": cc["target"]["id"],
                "label": cc["target"]["label"],
                "via": best["nodes"][1]["label"],
                "hops": len(best["edges"]),
                "score": best["score"],
                "rank": rank_of.get(cc["target"]["id"]),
            }
        )
    have = {r["id"] for r in rows}
    for k, r in enumerate(reach, 1):
        if len(rows) >= 20:
            break
        if r["id"] in have:
            continue
        rows.append(
            {
                "id": r["id"],
                "label": r["label"],
                "via": None,
                "hops": r["hops"],
                "score": None,
                "rank": k,
            }
        )
    assert len(rows) <= 20

    paths = [[nd["id"] for nd in cc["chains"][0]["nodes"]] for cc in company_chains[:5]]
    chain_ids: list[str] = []
    for p in paths:
        for cid in p:
            if cid not in chain_ids:
                chain_ids.append(cid)

    cls = [0] * len(sorted_ids)
    for cc in company_chains:  # any baked chain member = context
        for ch in cc["chains"]:
            for nd in ch["nodes"]:
                cls[pos[nd["id"]]] = 1
    for p in paths:  # top-5 first-chains = lit
        for cid in p:
            cls[pos[cid]] = 2
    cls[pos[AOC]] = 3
    cls[pos[lead["id"]]] = 3

    return {
        "question": "Who should we meet first?",
        "source": ["intro-chains", "proximity-rank"],
        "templates": {
            "default": (
                "The best route to {target} opens through {via} — {hops} handshakes."
            ),
            "isolated": "{seat} has no mapped ties — no routes to rank yet.",
        },
        "thumb": {"cls": cls, "paths": paths},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": chain_ids,
            "rows": rows,
            "marks": {"paths": paths},
        },
    }


def bake_market_shape(mm_env, companies, sorted_ids, pos) -> dict:
    neighbors = mm_env["data"]["neighbors"]
    assert len(neighbors) >= 3, "market-map neighbors too thin"
    by_id = {c["id"]: c for c in companies["companies"]}
    aoc_label = by_id[AOC]["name"]
    sentence = (
        f"In measured-similarity space, {aoc_label} sits closest to "
        f"{neighbors[0]['label']}, {neighbors[1]['label']}, and "
        f"{neighbors[2]['label']}."
    )
    callouts = [
        {"id": r["id"], "text": f"#{k} nearest · distance {r['distance']}"}
        for k, r in enumerate(neighbors[:3], 1)
    ]
    # the whole cloud stays visible (context) — the answer IS the shape;
    # neighbors lit, AoC anchored
    cls = [1] * len(sorted_ids)
    for r in neighbors:
        cls[pos[r["id"]]] = 2
    cls[pos[AOC]] = 3
    return {
        "question": "What does the market really look like?",
        "source": ["market-map"],
        "templates": {
            "default": (
                "In measured-similarity space, {name} sits closest to {n1} and {n2}."
            ),
            "isolated": (
                "{seat} embeds at the origin — too few verified ties to place it."
            ),
        },
        "thumb": {"cls": cls, "useAse": True},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in neighbors],
            "rows": neighbors,
            "marks": {},
        },
    }


def main() -> None:
    companies = load_companies()
    brokers_env = load_envelope("brokers", companies)
    chains_env = load_envelope("intro-chains", companies)
    prox_env = load_envelope("proximity-rank", companies)
    mm_env = load_envelope("market-map", companies)

    shared = json.loads((OUT_DIR / "shared.json").read_text())
    layout = shared["graphs"]["companies"]
    assert layout["stamp"] == stamp(companies), "shared.json stale — run bake.sh"

    sorted_ids, idx, adj, deg, n_pairs = build_kernel_graph(companies)
    pos = idx  # sorted_ids position == kernel index (both sorted ascending)
    assert set(sorted_ids) == set(layout["nodes"]), "shared.json id set drifted"
    labels = {c["id"]: c["name"] for c in companies["companies"]}

    payload = {
        "kind": "question-data",
        "graph": "companies",
        "inputs": {"companies": stamp(companies)},
        "nodes": {
            "ids": sorted_ids,
            "x": [layout["nodes"][cid]["x"] for cid in sorted_ids],
            "y": [layout["nodes"][cid]["y"] for cid in sorted_ids],
            "label": [labels[cid] for cid in sorted_ids],
        },
        "assets": {"ase": bake_ase(companies, mm_env, sorted_ids)},
        "params": {
            "friction": FRICTION,
            "pprAlpha": PPR_ALPHA,
            "pprIters": PPR_ITERS,
            "minDegree": MIN_DEGREE,
        },
        "questions": {
            "bridges": bake_bridges(
                brokers_env, companies, sorted_ids, pos, adj, deg, idx
            ),
            "meet-first": bake_meet_first(chains_env, prox_env, sorted_ids, pos),
            "market-shape": bake_market_shape(mm_env, companies, sorted_ids, pos),
        },
    }
    emit_questions(payload, "questions-companies")

    fixtures = bake_fixtures(sorted_ids, idx, adj, deg, n_pairs)
    id_set = set(sorted_ids)
    for kernel in ("constraint", "ppr"):
        for seat, rows in fixtures[kernel].items():
            assert seat in id_set
            assert all(r["id"] in id_set for r in rows)
    blob = json.dumps(
        fixtures, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    (QUESTIONS_DIR / "fixtures.json").write_text(blob + "\n")
    print(
        f"[fixtures] OK {len(blob) / 1024:.0f}KB — {len(fixtures['meta']['seats'])} "
        f"seats × 2 kernels ({fixtures['meta']['nodes']}n/"
        f"{fixtures['meta']['undirectedEdges']}ue)"
    )


if __name__ == "__main__":
    main()
