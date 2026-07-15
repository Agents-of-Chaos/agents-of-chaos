# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "graspologic==3.4.4", "networkx", "cpnet", "numba>=0.59"]
# ///
"""prep_questions — bake src/data/questions/*: question data for the on-map
questions UI (companies graph, all 8 /networks questions: bridges · meet-first
· market-shape · best-handshake · missing-ties · empty-quarter · core-crust ·
rival-orbit) plus the JS kernel-parity fixtures. Run: cd experiments/analyses
&& uv run prep_questions.py — bake.sh runs it AFTER the panel loop because the
default answers are copied from the just-baked envelopes (single source of
truth).

Inputs are ONLY src/data/companies.json, the baked sibling envelopes (brokers,
intro-chains, proximity-rank, market-map, best-new-edge, missing-edges,
block-structure, core-periphery, competitor-nominations), and
src/data/analyses/shared.json — never the private overlays. Re-runs must be
byte-identical (no wall-clock, all randomness seeded, SVD signs fixed).
Heavy recomputes reuse the SIBLING SCRIPTS' OWN functions via importlib
(load_sibling), so asset math is byte-equal to the envelopes by construction;
every recompute is additionally asserted against the envelope rows it must
reproduce.

Asset formats (assets.*, all node-aligned arrays follow nodes.ids order):

  ase        {d: 4, all: [n×4, 4dp], verified: [n×4, 4dp]} — `all` is
             market-map's embedding (all edges); `verified` is
             competitor-nominations' embedding (verified edges only, same
             estimator: n_elbows=2, svd_seed=0, fix_signs, file-order
             adjacency, re-ordered to nodes.ids, rounded 4dp). Recomputed
             borda/rrf ranks over the envelope's candidate pool must equal
             every prospects/rivals row — asserted at bake time.
  sbm        {blocks: [8 short labels], vertBlock: {vertical → block label},
             B: 8×8 [4dp]} — copied verbatim from missing-edges.json
             data.blockP (blocks = rows, B = cells); vertBlock is
             missing-edges.py's VERT_SHORT over VERT_ORDER.
  blockLayers  block-structure.json data.blocks verbatim: {rows, cols,
             layers: [{label, cells 8×8}×3]} — business / shared-investor /
             competitor, in block-structure's display order (≠ sbm order).
  coreness   {full: [...], business: [...], investor: [...]} — Rombach
             coreness per layer aligned to nodes.ids, 4dp, null where the
             node has no edge of that layer's type(s). Recomputed via
             core-periphery.py's own layer_graph/rombach_coreness (same
             cpnet seeding); asserted equal to the envelope's quadrant rows
             (4dp) and rivals rows (3dp) wherever those ids appear.
  handshakes {ids: [LCC ids, ascending], top: [[[candIdx, dPct] ×10] per
             seat]} — exact effective-resistance best-new-edge rankings for
             EVERY seat in the companies LCC (best-new-edge.py's math
             generalized from the AoC seat: L⁺ once via numpy pinv
             hermitian, Sherman–Morrison ΔS_seat per candidate). top[i] is
             the row for seat ids[i]; candIdx indexes nodes.ids (NOT the
             LCC list); dPct = round(100·ΔS_seat/S_seat, 2). Candidates =
             LCC non-neighbors of the seat; top-10 by (-round(dPct, 6), id)
             ascending. The agents-of-chaos row must equal the
             best-new-edge envelope's candidates in id order and 2dp value
             — asserted at bake time and in the strict pytest tier.

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
 11. sbmRank (missing-ties re-aim): inputs = assets.sbm + the live vertical
     labels + the rule-1-3 kernel graph. block(u) = index in sbm.blocks of
     sbm.vertBlock[vertical(u)]. Candidate pool per seat = ALL nodes u with
     u != seat and u not in N(seat) (isolates included). Score pFull[u] =
     sbm.B[block(seat)][block(u)] — a plain lookup of the baked 4dp double,
     NO arithmetic, so cross-language equality is exact by construction.
     Top-10 by (-pFull, id) ascending.
 12. rivalOrbit (rival-orbit re-aim): inputs = assets.ase.verified (n×4 4dp
     doubles, nodes.ids order), the live edge list, params.rrfK and
     params.svnSeeds.
       vdeg[u] = number of DISTINCT neighbors via verified==true edge
         records (either direction).
       seeds(seat) = distinct u != seat sharing a competitor-TYPE edge
         record with seat (any direction, any verified flag), FILTERED to
         vdeg > 0, sorted ascending by id; if empty, fall back to
         params.svnSeeds minus the seat itself (already ascending).
       candidates = all u with vdeg[u] > 0, u != seat, u not in seeds,
         ascending id order.
       For each seed s in ascending order: d(s,u) = sqrt of the
         left-to-right double sum of (X[u][k]-X[s][k])^2 for k = 0..3;
         rank_s = 1-based position of u when candidates are sorted by
         (d(s,u), id) ascending; score[u] += 1.0/(rrfK + rank_s(u)) — one
         term per seed, accumulated in seed order.
       Top-10 by (-sFull, id) ascending; s = round(sFull, 9).
"""

import importlib.util
import json
import math
import time

import numpy as np
from _shared import (
    HERE,
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
TOP_HANDSHAKES = 10
RRF_K = 60  # reciprocal-rank-fusion constant; asserted == competitor-nominations'
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


def load_sibling(fname: str):
    """Import a sibling analysis script as a module. Reusing the exact
    functions that baked an envelope (instead of copying them) makes asset
    recomputes byte-equal by construction; main() stays guarded, so exec
    only defines names."""
    modname = fname.removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(modname, HERE / fname)
    assert spec and spec.loader, fname
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def fixture_sbm_rank(
    seats: list[str], ids: list[str], idx, adj, sbm: dict, vert: dict[str, str]
) -> dict:
    """Parity fixtures for the sbmRank kernel (spec rule 11)."""
    bidx = {b: i for i, b in enumerate(sbm["blocks"])}
    B = sbm["B"]
    block_of = {cid: bidx[sbm["vertBlock"][vert[cid]]] for cid in ids}
    out: dict[str, list[dict]] = {}
    for seat in seats:
        s_i = idx[seat]
        nbrs = set(adj[s_i])
        bs = block_of[seat]
        cands = [ids[i] for i in range(len(ids)) if i != s_i and i not in nbrs]
        top = sorted(cands, key=lambda u: (-B[bs][block_of[u]], u))[:10]
        out[seat] = [{"id": u, "pFull": B[bs][block_of[u]]} for u in top]
        assert len(out[seat]) == 10
    return out


def fixture_rival_orbit(
    seats: list[str],
    ids: list[str],
    pos,
    companies: dict,
    X: list[list[float]],
    svn_seeds: list[str],
) -> dict:
    """Parity fixtures for the rivalOrbit kernel (spec rule 12). Pure-python
    float math in the spec's accumulation order — no numpy — so the JS mirror
    reproduces sFull bit-for-bit from the same baked 4dp coordinates."""
    ver_nbrs: dict[str, set[str]] = {i: set() for i in ids}
    comp_nbrs: dict[str, set[str]] = {i: set() for i in ids}
    for e in companies["edges"]:
        if e["verified"]:
            ver_nbrs[e["source"]].add(e["target"])
            ver_nbrs[e["target"]].add(e["source"])
        if e["type"] == "competitor":
            comp_nbrs[e["source"]].add(e["target"])
            comp_nbrs[e["target"]].add(e["source"])
    vdeg = {i: len(s) for i, s in ver_nbrs.items()}

    out: dict[str, dict] = {}
    for seat in seats:
        seeds = sorted(s for s in comp_nbrs[seat] if vdeg[s] > 0)
        if not seeds:
            seeds = [s for s in svn_seeds if s != seat]
        seed_set = set(seeds)
        cands = [u for u in ids if vdeg[u] > 0 and u != seat and u not in seed_set]
        assert len(cands) >= 10, f"{seat}: rivalOrbit pool too small"
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
        out[seat] = {
            "seeds": seeds,
            "rows": [
                {"id": u, "s": round(score[u], 9), "sFull": score[u]} for u in top
            ],
        }
    return out


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


# --- P2 assets: verified ASE · SBM copies · coreness · handshakes -----------


def bake_ase_verified(
    companies: dict, cn_env: dict, sorted_ids: list[str]
) -> tuple[list[list[float]], dict]:
    """Verified-edges ASE exactly as competitor-nominations.py computes it
    (its own build_adjacency + embed via load_sibling), re-ordered to
    sorted_ids, 4dp. Proof the embedding matches the envelope: the recomputed
    borda/rrf ranks over the envelope's candidate pool must equal every
    prospects/rivals row. Also returns the facts the rival-orbit sentence
    needs (top prospect + how many seeds place it in their nearest
    TOP_CONSENSUS)."""
    cn = load_sibling("competitor-nominations.py")
    assert cn.RRF_K == RRF_K, "rrfK drifted — update params + kernels.js"

    A_ver, file_ids = cn.build_adjacency(companies, verified_only=True)
    Xv = cn.embed(A_ver)
    assert Xv.shape == (len(file_ids), ASE_D), f"verified ASE dims: {Xv.shape}"

    seed_ids = [c["id"] for c in companies["companies"] if c.get("competitor")]
    pos_file = {cid: k for k, cid in enumerate(file_ids)}
    deg_ver = A_ver.sum(axis=1)
    cand = [c for c in file_ids if c not in set(seed_ids) and deg_ver[pos_file[c]] > 0]
    borda_rank, rrf_rank = cn.fuse(Xv, file_ids, seed_ids, cand)
    for row in cn_env["data"]["prospects"] + cn_env["data"]["rivals"]:
        assert (
            borda_rank[row["id"]] == row["borda"] and rrf_rank[row["id"]] == row["rrf"]
        ), f"recomputed ASE disagrees with competitor-nominations at {row['id']}"

    # how many seeds place the top prospect in their nearest TOP_CONSENSUS —
    # same per-seed ranking as cn.fuse (stable argsort over the pool order)
    top_id = cn_env["data"]["prospects"][0]["id"]
    Xc = Xv[[pos_file[c] for c in cand]]
    ci = cand.index(top_id)
    n_nominate = 0
    for s in seed_ids:
        d = np.linalg.norm(Xc - Xv[pos_file[s]], axis=1)
        rank0 = int(np.where(np.argsort(d, kind="stable") == ci)[0][0])
        n_nominate += rank0 < cn.TOP_CONSENSUS
    assert n_nominate > 0, "top prospect nominated by no seed — reword sentence"

    verified = [
        [round(float(Xv[pos_file[cid], j]), 4) for j in range(ASE_D)]
        for cid in sorted_ids
    ]
    facts = {
        "topId": top_id,
        "topLabel": cn_env["data"]["prospects"][0]["label"],
        "nNominate": n_nominate,
        "nSeeds": len(seed_ids),
        "topConsensus": cn.TOP_CONSENSUS,
        "seedIds": seed_ids,
    }
    return verified, facts


def bake_sbm(me_env: dict) -> dict:
    """assets.sbm — missing-edges' 8×8 verified block base rates, verbatim,
    plus the vertical → block-label map the sbmRank kernel needs."""
    me = load_sibling("missing-edges.py")
    bp = me_env["data"]["blockP"]
    assert bp["rows"] == bp["cols"] == [me.VERT_SHORT[v] for v in me.VERT_ORDER]
    cells = bp["cells"]
    assert len(cells) == 8 and all(len(r) == 8 for r in cells)
    assert all(cells[i][j] == cells[j][i] for i in range(8) for j in range(8))
    return {
        "blocks": bp["rows"],
        "vertBlock": {v: me.VERT_SHORT[v] for v in me.VERT_ORDER},
        "B": cells,
    }


def bake_coreness(companies: dict, cp_env: dict, sorted_ids: list[str]) -> dict:
    """assets.coreness — Rombach coreness per layer, recomputed through
    core-periphery.py's own layer_graph/rombach_coreness (identical cpnet
    seeding), 4dp, null where a node has no edge of the layer's type(s).
    Every envelope quadrant row (4dp) and rivals row (3dp) must match."""
    cp = load_sibling("core-periphery.py")
    t0 = time.perf_counter()
    c_full = cp.rombach_coreness(
        cp.layer_graph(companies, {"business", "shared-investor", "competitor"})
    )
    c_biz = cp.rombach_coreness(cp.layer_graph(companies, {"business"}))
    c_inv = cp.rombach_coreness(cp.layer_graph(companies, {"shared-investor"}))
    print(f"[coreness] 3 Rombach layers recomputed in {time.perf_counter() - t0:.1f}s")

    for p in cp_env["data"]["quadrant"]:
        assert round(c_biz[p["id"]], 4) == p["x"], f"{p['id']}: business coreness"
        assert round(c_inv[p["id"]], 4) == p["y"], f"{p['id']}: investor coreness"
    for r in cp_env["data"]["rivals"]:
        checks = [
            (c_full, r["coreness"]),
            (c_biz, r["business"]),
            (c_inv, r["investor"]),
        ]
        for layer, want in checks:
            got = layer.get(r["id"])
            assert (got is None) == (want is None), f"{r['id']}: layer membership"
            if want is not None:
                assert round(got, 3) == want, f"{r['id']}: coreness vs envelope"
                # the baked 4dp value must re-round to the envelope's 3dp
                # (double-rounding guard for the strict pytest tier)
                assert round(round(got, 4), 3) == want, f"{r['id']}: double-rounding"

    def aligned(layer: dict[str, float]) -> list[float | None]:
        return [round(layer[cid], 4) if cid in layer else None for cid in sorted_ids]

    return {
        "full": aligned(c_full),
        "business": aligned(c_biz),
        "investor": aligned(c_inv),
    }


def bake_handshakes(
    companies: dict, bne_env: dict, sorted_ids: list[str], pos: dict[str, int]
) -> dict:
    """assets.handshakes — best-new-edge.py's exact effective-resistance math
    generalized from the AoC seat to every LCC seat (format in the module
    docstring). The per-seat block below replicates best-new-edge.py's
    float-op sequence verbatim so the AoC row is bit-derived from the same
    numbers the envelope baked."""
    bne = load_sibling("best-new-edge.py")
    ids = [c["id"] for c in companies["companies"]]
    adj: dict[str, set[str]] = {i: set() for i in ids}
    for e in companies["edges"]:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    lcc = bne.largest_component(ids, adj)  # sorted ascending
    n = len(lcc)
    li = {cid: k for k, cid in enumerate(lcc)}

    A = np.zeros((n, n))
    for cid in lcc:
        for nb in adj[cid]:
            if nb in li:
                A[li[cid], li[nb]] = 1.0
    assert np.array_equal(A, A.T) and A.diagonal().sum() == 0
    L = np.diag(A.sum(1)) - A
    Lp = np.linalg.pinv(L, hermitian=True)
    assert np.allclose(Lp.sum(1), 0, atol=1e-9), "L+ rows must sum to 0"
    dg = np.diag(Lp)

    top: list[list[list]] = []
    for cid in lcc:
        a = li[cid]
        r_a = Lp[a, a] + dg - 2.0 * Lp[a, :]
        S_a = float(r_a.sum())
        V = Lp[:, [a]] - Lp  # column u holds v = L+ (e_a - e_u)
        va = V[a, :]
        vtv = (V**2).sum(axis=0)
        denom = 1.0 + r_a
        d_seat = (n * va**2 + vtv) / denom
        candidates = [u for u in lcc if u != cid and u not in adj[cid]]
        assert len(candidates) >= TOP_HANDSHAKES, f"{cid}: candidate pool too small"
        pct = {u: float(100 * d_seat[li[u]] / S_a) for u in candidates}
        ranked = sorted(candidates, key=lambda u: (-round(pct[u], 6), u))
        row = [[pos[u], round(pct[u], 2)] for u in ranked[:TOP_HANDSHAKES]]
        assert all(p > 0 for _, p in row), f"{cid}: Rayleigh monotonicity broke"
        top.append(row)

    # the AoC seat must reproduce the best-new-edge envelope exactly
    env_rows = bne_env["data"]["candidates"]
    aoc_row = top[li[AOC]]
    assert [sorted_ids[ci] for ci, _ in aoc_row] == [r["id"] for r in env_rows], (
        "handshakes AoC ranking disagrees with best-new-edge.json — "
        "tie-break rules drifted"
    )
    assert [p for _, p in aoc_row] == [r["dAocPct"] for r in env_rows]
    return {"ids": lcc, "top": top}


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


def bake_best_handshake(
    bne_env: dict, companies: dict, sorted_ids: list[str], pos, handshakes: dict
) -> dict:
    rows = bne_env["data"]["candidates"]
    proposed = bne_env["data"]["proposed"]
    by_id = {c["id"]: c for c in companies["companies"]}
    top = rows[0]

    # LCC = context (resistance is defined there), candidates lit, AoC anchor
    cls = [0] * len(sorted_ids)
    for cid in handshakes["ids"]:
        cls[pos[cid]] = 1
    for r in rows:
        cls[pos[r["id"]]] = 2
    cls[pos[AOC]] = 3

    edges = [[p["a"], p["b"]] for p in proposed]
    sentence = (
        f"{by_id[AOC]['name']}'s best new tie is {top['label']} — that one edge "
        f"cuts its distance to the whole market by {top['dAocPct']:g}%."
    )
    callouts = [
        {"id": r["id"], "text": f"#{k} handshake · −{r['dAocPct']:g}% distance"}
        for k, r in enumerate(rows[:3], 1)
    ]
    return {
        "question": "Which single handshake matters most?",
        "source": ["best-new-edge"],
        "templates": {
            "default": (
                "{name}'s best new tie is {winner} — that one edge cuts its "
                "distance to the whole market by {pct}%."
            ),
            "self": (
                "{seat} is itself {name}'s #{rank} best new handshake — one tie "
                "would cut {pct}% of {name}'s market distance."
            ),
            "isolated": (
                "{seat} sits outside the connected core — resistance math "
                "can't reach it yet."
            ),
        },
        "thumb": {"cls": cls, "edges": edges},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in rows],
            "rows": rows,
            "marks": {"edges": edges},
        },
    }


def bake_missing_ties(
    me_env: dict, companies: dict, sorted_ids: list[str], pos
) -> dict:
    rows = me_env["data"]["unmapped"]
    assert rows
    top = rows[0]

    # triage labels are "A ↔ B" NAME strings — resolve to ids via the live
    # names; drop pairs that no longer resolve (nightly churn tolerance)
    name_to_id = {c["name"]: c["id"] for c in companies["companies"]}
    assert len(name_to_id) == len(companies["companies"]), "duplicate company names"
    edges: list[list[str]] = []
    for t in me_env["data"]["triage"]:
        a, sep, b = t["label"].partition(" ↔ ")
        assert sep, f"unparseable triage label {t['label']!r}"
        if a in name_to_id and b in name_to_id:
            edges.append([name_to_id[a], name_to_id[b]])
        if len(edges) == 5:
            break
    assert edges, "no triage pair resolved to live ids"

    vendor_ids: list[str] = []
    for r in rows:
        if r["id"] not in vendor_ids:
            vendor_ids.append(r["id"])

    cls = [1] * len(sorted_ids)
    for cid in vendor_ids:
        cls[pos[cid]] = 2

    # top-3 DISTINCT vendors (rows repeat a vendor per prospect; three
    # callouts on one node would stack)
    callouts = []
    seen: set[str] = set()
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        callouts.append(
            {
                "id": r["id"],
                "text": f"unmapped tie to {r['prospect']} · "
                f"{round(r['phat'] * 100, 2):g}% base rate",
            }
        )
        if len(callouts) == 3:
            break

    sentence = (
        f"{len(rows)} vendor→buyer ties probably exist but aren't on the map — "
        f"starting with {top['label']} × {top['prospect']}."
    )
    return {
        "question": "Which ties should exist but don't?",
        "source": ["missing-edges"],
        "templates": {
            "default": (
                "The market's base rates say {name} should already have a tie "
                "to {top} — {pct}% of pairs like this do."
            ),
            "self": (
                "{seat} is one of the vendors with likely-unmapped buyers — "
                "{top} first."
            ),
            "isolated": (
                "{seat} has no mapped ties at all — every expected tie is "
                "missing; the base rates say start with {top}."
            ),
        },
        "thumb": {"cls": cls, "edges": edges},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": vendor_ids,
            "rows": rows,
            "marks": {"edges": edges},
        },
    }


def bake_empty_quarter(
    bs_env: dict, companies: dict, sorted_ids: list[str], pos, deg
) -> dict:
    blocks = bs_env["data"]["blocks"]
    labels = blocks["rows"]
    biz = next(
        ly["cells"] for ly in blocks["layers"] if ly["label"].startswith("business")
    )

    # recompute the story from the matrix (never prose-parse): the quiet pair
    # is security × banks (must be exactly zero), the loudest corridor is the
    # densest off-diagonal business cell
    i_sec, i_bank = labels.index("security"), labels.index("banks")
    assert biz[i_sec][i_bank] == 0.0, "security × banks gained a business tie — reword"
    li, lj = max(
        ((i, j) for i in range(8) for j in range(i + 1, 8)),
        key=lambda ij: biz[ij[0]][ij[1]],
    )
    loud_pct = round(biz[li][lj] * 100, 2)

    sec_ids = sorted(
        c["id"]
        for c in companies["companies"]
        if c["vertical"] == "security-eval-vendor"
    )
    bank_ids = sorted(
        c["id"] for c in companies["companies"] if c["vertical"] == "bank-fintech"
    )
    assert sec_ids and bank_ids
    hull = [sec_ids, bank_ids]

    def rep(group: list[str]) -> str:
        """Hull callout anchor: the group's best-connected node (tie: id)."""
        return sorted(group, key=lambda cid: (-deg[pos[cid]], cid))[0]

    sec_rep, bank_rep = rep(sec_ids), rep(bank_ids)
    callouts = [
        {
            "id": sec_rep,
            "text": f"zero business ties cross this gap — {len(sec_ids)} security vendors",
        },
        {
            "id": bank_rep,
            "text": f"zero business ties cross this gap — {len(bank_ids)} banks",
        },
    ]
    sentence = (
        f"No business tie links the {len(sec_ids)} security vendors to the "
        f"{len(bank_ids)} banks — the loudest corridor, {labels[li]} × "
        f"{labels[lj]}, wires {loud_pct:g}% of its possible pairs."
    )

    cls = [1] * len(sorted_ids)
    for cid in sec_ids + bank_ids:
        cls[pos[cid]] = 2
    cls[pos[sec_rep]] = 3
    cls[pos[bank_rep]] = 3

    rows = bs_env["data"]["misShelved"]
    assert rows
    return {
        "question": "Where is the market empty?",
        "source": ["block-structure"],
        "templates": {
            "default": (
                "{name}'s shelf ({block}) holds zero {layer} ties to {empty} — "
                "its loudest corridor is {loud}."
            ),
            "self": (
                "{seat} is itself mis-shelved — wired like {wiredWith}, "
                "filed under {shelved}."
            ),
            "isolated": "{seat} has no mapped ties — no corridor to measure yet.",
        },
        "thumb": {"cls": cls, "hull": hull},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in rows],
            "rows": rows,
            "marks": {"hull": hull},
        },
    }


def bake_core_crust(cp_env: dict, sorted_ids: list[str], pos) -> dict:
    quadrant = cp_env["data"]["quadrant"]
    assert len(quadrant) >= 20, "quadrant too thin for a top-20 table"

    # same prospect rule as core-periphery.py, on the envelope's own rounded
    # values (safe: coreness clusters ≤0.25 / ≥0.75, midpoints sit in the
    # kernel gap, 4dp rounding can't flip membership)
    xs = [p["x"] for p in quadrant]
    ys = [p["y"] for p in quadrant]
    mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    prospects = sorted(
        (p for p in quadrant if p["x"] < mx and p["y"] >= my), key=lambda p: -p["y"]
    )
    assert len(prospects) >= 3, "prospect quadrant collapsed — reword"

    # rows: the 20 most investor-core dual-layer companies (sort (-y, id))
    rows = sorted(quadrant, key=lambda p: (-p["y"], p["id"]))[:20]

    cls = [1] * len(sorted_ids)
    for p in quadrant:
        cls[pos[p["id"]]] = 2
    for p in prospects[:5]:
        cls[pos[p["id"]]] = 3

    callouts = [
        {"id": p["id"], "text": f"prospect #{k} · money-core, business-crust"}
        for k, p in enumerate(prospects[:3], 1)
    ]
    sentence = (
        f"{len(prospects)} of {len(quadrant)} dual-wired companies sit in the "
        f"prospect corner — investor-core but business-crust — led by "
        f"{prospects[0]['label']}, {prospects[1]['label']}, and "
        f"{prospects[2]['label']}."
    )
    return {
        "question": "Who runs the core — who's still outside?",
        "source": ["core-periphery"],
        "templates": {
            "default": (
                "{name} sits in the {corner} corner — business coreness {bc}, "
                "investor coreness {ic}."
            ),
            "self": "{seat} is in the prospect corner itself — financed, not yet embedded.",
            "offcore": (
                "{seat} has no shared-investor ties, so it can't sit on the "
                "money axis — business coreness only: {bc}."
            ),
            "isolated": "{seat} has too few ties to score — coreness needs an edge.",
        },
        "thumb": {"cls": cls},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [p["id"] for p in prospects],
            "rows": rows,
            "marks": {},
        },
    }


def bake_rival_orbit(cn_env: dict, sorted_ids: list[str], pos, facts: dict) -> dict:
    rows = cn_env["data"]["prospects"]
    seeds = [s["id"] for s in cn_env["data"]["seeds"]]
    assert rows and seeds
    assert facts["topId"] == rows[0]["id"] and facts["seedIds"] == seeds

    cls = [1] * len(sorted_ids)
    for r in rows:
        cls[pos[r["id"]]] = 2
    for s in seeds:
        cls[pos[s]] = 3

    callouts = [
        {
            "id": r["id"],
            "text": f"#{k} prospect · borda #{r['borda']} · {r['deg']} verified edges",
        }
        for k, r in enumerate(rows[:3], 1)
    ]
    sentence = (
        f"{facts['topLabel']} sits closest to the rival pack — "
        f"{facts['nNominate']} of the {facts['nSeeds']} flagged rivals rank it "
        f"in their nearest {facts['topConsensus']}."
    )
    return {
        "question": "Who else looks like a rival?",
        "source": ["competitor-nominations"],
        "templates": {
            "default": (
                "The graph treats {top} like one of {name}'s rivals — "
                "{k} of {n} seeds rank it nearby."
            ),
            "self": "{seat} is itself nominated — the graph puts it in the rival orbit.",
            "isolated": (
                "{seat} has no verified ties — the embedding can't place it, "
                "so no orbit yet."
            ),
        },
        "thumb": {"cls": cls},
        "default": {
            "seat": AOC,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in rows],
            "rows": rows,
            "marks": {},
        },
    }


def main() -> None:
    companies = load_companies()
    brokers_env = load_envelope("brokers", companies)
    chains_env = load_envelope("intro-chains", companies)
    prox_env = load_envelope("proximity-rank", companies)
    mm_env = load_envelope("market-map", companies)
    bne_env = load_envelope("best-new-edge", companies)
    me_env = load_envelope("missing-edges", companies)
    bs_env = load_envelope("block-structure", companies)
    cp_env = load_envelope("core-periphery", companies)
    cn_env = load_envelope("competitor-nominations", companies)

    shared = json.loads((OUT_DIR / "shared.json").read_text())
    layout = shared["graphs"]["companies"]
    assert layout["stamp"] == stamp(companies), "shared.json stale — run bake.sh"

    sorted_ids, idx, adj, deg, n_pairs = build_kernel_graph(companies)
    pos = idx  # sorted_ids position == kernel index (both sorted ascending)
    assert set(sorted_ids) == set(layout["nodes"]), "shared.json id set drifted"
    labels = {c["id"]: c["name"] for c in companies["companies"]}
    vert = {c["id"]: c["vertical"] for c in companies["companies"]}
    svn_seeds = sorted(c["id"] for c in companies["companies"] if c.get("competitor"))
    assert len(svn_seeds) == 14, "competitor flag count drifted"

    ase = bake_ase(companies, mm_env, sorted_ids)
    ase["verified"], cn_facts = bake_ase_verified(companies, cn_env, sorted_ids)
    sbm = bake_sbm(me_env)
    handshakes = bake_handshakes(companies, bne_env, sorted_ids, pos)

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
        "assets": {
            "ase": ase,
            "sbm": sbm,
            "blockLayers": bs_env["data"]["blocks"],
            "coreness": bake_coreness(companies, cp_env, sorted_ids),
            "handshakes": handshakes,
        },
        "params": {
            "friction": FRICTION,
            "pprAlpha": PPR_ALPHA,
            "pprIters": PPR_ITERS,
            "minDegree": MIN_DEGREE,
            "rrfK": RRF_K,
            "svnSeeds": svn_seeds,
        },
        "questions": {
            "bridges": bake_bridges(
                brokers_env, companies, sorted_ids, pos, adj, deg, idx
            ),
            "meet-first": bake_meet_first(chains_env, prox_env, sorted_ids, pos),
            "market-shape": bake_market_shape(mm_env, companies, sorted_ids, pos),
            "best-handshake": bake_best_handshake(
                bne_env, companies, sorted_ids, pos, handshakes
            ),
            "missing-ties": bake_missing_ties(me_env, companies, sorted_ids, pos),
            "empty-quarter": bake_empty_quarter(
                bs_env, companies, sorted_ids, pos, deg
            ),
            "core-crust": bake_core_crust(cp_env, sorted_ids, pos),
            "rival-orbit": bake_rival_orbit(cn_env, sorted_ids, pos, cn_facts),
        },
    }
    emit_questions(payload, "questions-companies")

    fixtures = bake_fixtures(sorted_ids, idx, adj, deg, n_pairs)
    fixtures["meta"]["rrfK"] = RRF_K
    seats = fixtures["meta"]["seats"]
    fixtures["sbmRank"] = fixture_sbm_rank(seats, sorted_ids, idx, adj, sbm, vert)
    fixtures["rivalOrbit"] = fixture_rival_orbit(
        seats, sorted_ids, pos, companies, ase["verified"], svn_seeds
    )
    id_set = set(sorted_ids)
    for kernel in ("constraint", "ppr", "sbmRank"):
        for seat, rows in fixtures[kernel].items():
            assert seat in id_set
            assert all(r["id"] in id_set for r in rows)
    for seat, blk in fixtures["rivalOrbit"].items():
        assert seat in id_set
        assert all(s in id_set for s in blk["seeds"])
        assert all(r["id"] in id_set for r in blk["rows"])
    blob = json.dumps(
        fixtures, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    (QUESTIONS_DIR / "fixtures.json").write_text(blob + "\n")
    print(
        f"[fixtures] OK {len(blob) / 1024:.0f}KB — {len(fixtures['meta']['seats'])} "
        f"seats × 4 kernels ({fixtures['meta']['nodes']}n/"
        f"{fixtures['meta']['undirectedEdges']}ue)"
    )


if __name__ == "__main__":
    main()
