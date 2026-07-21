# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "graspologic==3.4.4", "networkx", "cpnet", "numba>=0.59"]
# ///
"""prep_questions — bake src/data/questions/*: question data for the on-map
questions UI (companies graph, all 8 /networks questions: bridges · meet-first
· market-shape · best-handshake · missing-ties · empty-quarter · core-crust ·
rival-orbit; funding graph, all 5 /funding questions: funder-shortlist ·
rivals-money · warm-routes · within-reach · funding-bridges) plus the JS
kernel-parity fixtures. Run: cd experiments/analyses && uv run
prep_questions.py — bake.sh runs it AFTER the panel loop because the default
answers are copied from the just-baked envelopes (single source of truth).

Inputs are ONLY src/data/companies.json, src/data/funding.json, the baked
sibling envelopes (brokers, intro-chains, proximity-rank, market-map,
best-new-edge, missing-edges, block-structure, core-periphery,
competitor-nominations, funder-fit, rivals-money, money-brokers), and
src/data/analyses/shared.json — never the private overlays. Re-runs must be
byte-identical (no wall-clock, all randomness seeded, SVD signs fixed).
Heavy recomputes reuse the SIBLING SCRIPTS' OWN functions via importlib
(load_sibling), so asset math is byte-equal to the envelopes by construction;
every recompute is additionally asserted against the envelope rows it must
reproduce. proximity-rank carries no funding-side block, so the within-reach
default is COMPUTED here (kernel rule 14's multi-seed variant, seeded at
assets.sources) — the methods appendix maps it to proximity-rank.

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

Funding asset formats (questions-funding.json; nodes.ids = funding ids
sorted ascending, x/y from shared.json graphs.funding):

  funderFit  {d, funders: {ids, X}, grantees: {ids, X}, seeds} — funder-fit's
             own bipartite money embedding (U√S / V√S, signs fixed), reused
             via load_sibling fit() and rounded 4dp; ids ascending (the
             money-edge funders / funded grantees), seeds = the lane
             grantees. The rule-15 kernel on the BAKED values must reproduce
             every positive-score row of the envelope's ranked table in
             order (asserted); the envelope's zero-score tail encodes
             sub-1e-15 float noise — funders in money components disjoint
             from the seeds' embed at exactly 0 — so only zero-band
             membership (|s| < 1e-6) is asserted for those rows.
  rivalJoins rows {id (funder), rivalId, rivalLabel, usd, live} —
             rivals-money's two-key funder↔rival join re-derived with its
             own canon() and asserted pair-for-pair equal to the envelope's
             joins. rivalId/rivalLabel are COMPANIES-graph facts (deliberately
             not under an `id` key: they are not funding nodes, and the
             /funding client has no companies.json to derive them from);
             usd = the funding money edge's amount (null for name-only
             ties); live = false once the rival exited to an acquirer.
  sources    intro-chains' AoC entry points {id, label, aocDistance} — AoC
             itself is not a funding node; every funding-side walk (warm
             routes, within-reach PPR) starts here.

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
 13. Funding kernel graph: rules 1-3 applied verbatim to funding.json's
     nodes/edges (ALL edge types; the data carries no self-loops and no
     duplicate pairs — asserted). Every funding kernel below runs on this
     graph. params.friction = {grant: 1, investment: 1, affiliation: 1} —
     the /funding path finder and intro-chains' funding side both treat
     every hop as equal; the constant exists so the client prices routes
     from data, not from a hard-coded assumption.
 14. funding PPR (within-reach re-aim): rule 6 verbatim on the rule-13
     graph, alpha = 0.85, 100 iterations. Multi-seed variant (the baked
     within-reach DEFAULT, seeded at assets.sources ids): x0[s] = 1.0/k for
     each of the k seeds; per iteration compute r = alpha*dangling +
     (1.0-alpha) once, then next[s] += r/k for each seed in ascending index
     order. Default rows = funder-kind nodes with sFull > 0, top-25 by
     (-sFull, id), each carrying hops = min over sources of BFS distance.
 15. funderFit (funder-shortlist re-aim): inputs = assets.funderFit (4dp
     doubles). Seat vector v: seat in grantees.ids → grantees.X row; seat
     in funders.ids → funders.X row; the baked DEFAULT (virtual AoC) →
     v[k] = (sum of grantees.X[s][k] over seeds in ascending id order) /
     len(seeds). Candidates = funders.ids minus the seat itself. Score
     sFull[f] = sum over k = 0..d-1 (left to right, accumulator starts
     0.0) of funders.X[f][k]*v[k]. Top-15 by (-sFull, id) ascending;
     s = round(sFull, 9). Seats in neither ids list are unrankable — the
     client shows the isolated variant.
 16. moneyPaths (funding-bridges re-aim): on the rule-13 graph, doors =
     params.doorIds (money-brokers' doors, envelope order). BFS hop
     distances from the seat and from every door. For each door t with
     t != seat and dist(seat,t) finite, every node u not in {seat, t}
     gates t iff dist(seat,u) + dist(u,t) == dist(seat,t). s[u] = number
     of doors u gates (integer), d[u] = dist(seat,u). Rows = nodes with
     s > 0, top-10 by (-s, d, id) ascending — all-integer math, so
     cross-language equality is exact by construction (rows may be empty
     for seats with no path to any door).
 17. Funding fixture seats (fixtures.json "funding" namespace): seat 1 =
     assets.sources[0].id (the AoC entry grantee); seats 2-3 = funderFit
     funders.ids at quantiles 0.5 and 0.95; seat 4 = person-kind ids at
     quantile 0.5; seat 5 = funderFit grantees.ids at quantile 0.75 — each
     pool sorted ascending by (rule-13 degree, id), index floor(q*(n-1));
     all 5 distinct (asserted); ppr + moneyPaths fixtures cover all 5
     seats; funderFit fixtures cover only the 4 embeddable seats (the
     person has no row in the money matrix).
 18. blindSpot facts: every question block carries `blindSpot` (plain text,
     no braces/HTML) naming what the map can't see; every embedded number or
     name is computed at bake and assert-pinned to the sentence it ships in.
     All recomputes are deterministic: sorted iteration, round-then-id
     tie-breaks, no wall-clock.
       bridges: rerun the rule-5 Burt constraint over the VERIFIED-only
         kernel graph (edges with verified == true), eligible = LCC nodes
         with deg >= MIN_DEGREE, ranked by (round(c, 6), id) ascending;
         compare #1 to the brokers envelope's top seat.
       best-handshake: rerun best-new-edge's effective-resistance math on
         the verified-only subgraph's LCC for the default seat (candidates
         = LCC non-neighbors, ranked by (-round(pct, 6), id)); compare #1
         to the envelope's. The default sentence's near-tie clause fires
         iff #1 leads #2 by < NEAR_TIE_PP percentage points (baked 2dp).
       market-shape: n / k = the default seat's edge records in
         companies.json / those with type == "competitor".
       core-crust: p = core-periphery's data.nullTest.pValue (must be
         non-significant — the text says the null test agrees).
       within-reach: m = tracked funders minus walk-reachable ones.
       funding-bridges: a / b = funders holding a current named affiliation
         (money-brokers' own held-door rule) / all funders (must equal the
         envelope's counts.funders); the max-annualFieldGivingUSD funder
         (tie-break by id) must be unheld — the text calls it out.
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
    load_funding,
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
# Funding-side constants (docstring rules 13-17)
FUNDING_FRICTION = {"grant": 1, "investment": 1, "affiliation": 1}
FF_TOP_N = 15  # funderFit ranking depth — matches funder-fit.py TOP_N
FF_ZERO_BAND = 1e-6  # |s| below this = no structural signal (see funderFit)
REACH_TOP_N = 25  # within-reach default row cap
NEAR_TIE_PP = 1.0  # best-handshake near-tie threshold, percentage points (rule 18)
TOP_GATES = 10  # moneyPaths fixture row cap
WARM_PATH_CAP = 5  # warm-routes marks.paths cap
FUNDING_FUNDER_QS = (0.5, 0.95)  # rule-17 seat quantiles
FUNDING_PERSON_Q = 0.5
FUNDING_GRANTEE_Q = 0.75


def load_envelope(
    slug: str, companies: dict | None = None, funding: dict | None = None
) -> dict:
    env = json.loads((OUT_DIR / f"{slug}.json").read_text())
    assert companies is not None or funding is not None, slug
    for gname, gdata in (("companies", companies), ("funding", funding)):
        if gdata is not None:
            assert env["inputs"][gname] == stamp(
                gdata
            ), f"{slug}.json is stale vs live {gname}.json — run bake.sh"
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
    return kernel_graph_from(
        (c["id"] for c in companies["companies"]), companies["edges"]
    )


def build_funding_kernel_graph(funding: dict):
    """Rule 13: the rules-1-3 kernel graph over funding.json."""
    return kernel_graph_from((n["id"] for n in funding["nodes"]), funding["edges"])


def kernel_graph_from(node_ids, edges: list[dict]):
    ids = sorted(node_ids)
    n = len(ids)
    idx = {cid: i for i, cid in enumerate(ids)}
    pair_set = set()
    for e in edges:
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


def ppr_multi(adj, deg, n: int, seed_idxs: list[int]) -> list[float]:
    """Multi-seed PPR (spec rule 14): uniform mass over the seed set, restart
    split equally, seeds visited in ascending index order."""
    assert seed_idxs == sorted(seed_idxs) and seed_idxs
    k = len(seed_idxs)
    x = [0.0] * n
    for s in seed_idxs:
        x[s] = 1.0 / k
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
        r = (PPR_ALPHA * dangling + (1.0 - PPR_ALPHA)) / k
        for s in seed_idxs:
            nxt[s] += r
        x = nxt
    return x


def bfs_dist(adj, start: int, n: int) -> list[int | None]:
    """BFS hop distances; None = unreachable."""
    dist: list[int | None] = [None] * n
    dist[start] = 0
    frontier = [start]
    d = 0
    while frontier:
        d += 1
        nxt = []
        for u in frontier:
            for v in adj[u]:
                if dist[v] is None:
                    dist[v] = d
                    nxt.append(v)
        frontier = nxt
    return dist


def money_paths(
    ids: list[str], adj, seat_i: int, door_dists: dict[int, list[int | None]]
) -> list[dict]:
    """moneyPaths kernel (spec rule 16): how many doors each node gates on the
    seat's shortest paths to the money. All-integer math."""
    n = len(ids)
    ds = bfs_dist(adj, seat_i, n)
    score = [0] * n
    for t, dt in door_dists.items():
        if t == seat_i or ds[t] is None:
            continue
        for u in range(n):
            if u in (seat_i, t) or ds[u] is None or dt[u] is None:
                continue
            if ds[u] + dt[u] == ds[t]:
                score[u] += 1
    gated = [u for u in range(n) if score[u] > 0]
    gated.sort(key=lambda u: (-score[u], ds[u], ids[u]))
    return [{"id": ids[u], "s": score[u], "d": ds[u]} for u in gated[:TOP_GATES]]


def ff_virtual(ff: dict) -> list[float]:
    """Rule 15's default (virtual-AoC) seat vector from the BAKED asset:
    mean of the seed grantees' rows, summed in ascending id order."""
    gpos = {g: i for i, g in enumerate(ff["grantees"]["ids"])}
    v = [0.0] * ff["d"]
    for s in ff["seeds"]:
        row = ff["grantees"]["X"][gpos[s]]
        for k in range(ff["d"]):
            v[k] += row[k]
    return [x / len(ff["seeds"]) for x in v]


def ff_scores(ff: dict, v: list[float], exclude: str | None = None) -> dict[str, float]:
    """Rule 15 dot-product scores over the baked funder embedding."""
    d = ff["d"]
    score: dict[str, float] = {}
    for f, row in zip(ff["funders"]["ids"], ff["funders"]["X"]):
        if f == exclude:
            continue
        t = 0.0
        for k in range(d):
            t += row[k] * v[k]
        score[f] = t
    return score


def ff_rank(ff: dict, v: list[float], exclude: str | None = None) -> list[dict]:
    """Rule 15 ranking: top-15 by (-sFull, id) over ff_scores."""
    score = ff_scores(ff, v, exclude)
    top = sorted(score, key=lambda f: (-score[f], f))[:FF_TOP_N]
    return [{"id": f, "s": round(score[f], 9), "sFull": score[f]} for f in top]


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


# --- verified-only blind-spot recomputes (docstring rule 18) ----------------


def largest_component_idx(adj, n: int) -> set[int]:
    """Largest connected component of an index-based adjacency, as indices."""
    seen: set[int] = set()
    best: set[int] = set()
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
        if len(comp) > len(best):
            best = comp
    return best


def verified_constraint_top(companies: dict) -> str:
    """Rule 18 (bridges blindSpot): the least-constrained seat when only
    verified edges count — same constraint kernel, verified-only graph,
    eligible = LCC ∩ deg >= MIN_DEGREE, key (round(c, 6), id) ascending."""
    ids, _, adj, deg, _ = kernel_graph_from(
        (c["id"] for c in companies["companies"]),
        [e for e in companies["edges"] if e["verified"]],
    )
    lcc = largest_component_idx(adj, len(ids))
    eligible = [i for i in lcc if deg[i] >= MIN_DEGREE]
    assert eligible, "verified-only graph has no eligible brokers"
    adj_sets = [set(lst) for lst in adj]
    invdeg = [1.0 / d if d > 0 else 0.0 for d in deg]
    ranked = sorted(
        eligible,
        key=lambda i: (round(constraint(adj, adj_sets, invdeg, i), 6), ids[i]),
    )
    return ids[ranked[0]]


def verified_handshake_top(companies: dict, seat: str) -> str:
    """Rule 18 (best-handshake blindSpot): best-new-edge's exact
    effective-resistance float-op sequence (see bake_handshakes) rerun on the
    VERIFIED-only subgraph's LCC for one seat; #1 by (-round(pct, 6), id)."""
    bne = load_sibling("best-new-edge.py")
    ids = [c["id"] for c in companies["companies"]]
    adj: dict[str, set[str]] = {i: set() for i in ids}
    for e in companies["edges"]:
        if e["verified"]:
            adj[e["source"]].add(e["target"])
            adj[e["target"]].add(e["source"])
    lcc = bne.largest_component(ids, adj)  # sorted ascending
    assert seat in lcc, f"{seat} fell out of the verified LCC — reword blindSpot"
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
    dg = np.diag(Lp)
    a = li[seat]
    r_a = Lp[a, a] + dg - 2.0 * Lp[a, :]
    S_a = float(r_a.sum())
    V = Lp[:, [a]] - Lp
    va = V[a, :]
    vtv = (V**2).sum(axis=0)
    denom = 1.0 + r_a
    d_seat = (n * va**2 + vtv) / denom
    candidates = [u for u in lcc if u != seat and u not in adj[seat]]
    assert candidates, "verified-only handshake pool is empty"
    pct = {u: float(100 * d_seat[li[u]] / S_a) for u in candidates}
    return sorted(candidates, key=lambda u: (-round(pct[u], 6), u))[0]


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
    lcc = largest_component_idx(adj, n)
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
        f"{top['label']} holds the map's least-constrained seat — it bridges "
        f"{top['spans']} of {n_verticals} verticals, {ratio:g}× the effective "
        f"reach of the next broker."
    )
    callouts = [
        {"id": r["id"], "text": f"#{k} bridge · spans {r['spans']} verticals"}
        for k, r in enumerate(rows[:3], 1)
    ]
    # rule 18: does the #1 seat survive when only verified edges count?
    ver_top = verified_constraint_top(companies)
    labels = {c["id"]: c["name"] for c in companies["companies"]}
    ver_clause = (
        "the top seat holds"
        if ver_top == top["id"]
        else f"the top seat passes to {labels[ver_top]}"
    )
    blind_spot = (
        "Constraint counts mapped ties only — a missing tie between two "
        f"partners fakes a gap to bridge. On verified ties alone {ver_clause}."
    )
    assert ("passes to" in blind_spot) == (ver_top != top["id"])
    return {
        "question": "Who bridges the market?",
        "source": ["brokers"],
        "blindSpot": blind_spot,
        "templates": {
            "default": (
                "{name} holds the map's least-constrained seat near {seat} — "
                "it spans {spans} of 8 verticals."
            ),
            "self": (
                "{seat} is itself one of the map's bridges — #{rank} of {n} "
                "by constraint, spanning {spans} verticals."
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


def bake_meet_first(chains_env, prox_env, companies, sorted_ids, pos) -> dict:
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
    # rule 18 tripwire: "open through {lead}" leans on every chain's first hop
    # being seat→lead; the "inferred tie" clause fires iff that edge is
    # unverified in companies.json
    first_hops = {
        (ch["nodes"][0]["id"], ch["nodes"][1]["id"])
        for cc in company_chains
        for ch in cc["chains"]
    }
    assert first_hops == {
        (AOC, lead["id"])
    }, f"routes no longer all open at AoC→{lead['id']} — reword the sentence"
    hop_verified = any(
        e["verified"] and {e["source"], e["target"]} == {AOC, lead["id"]}
        for e in companies["edges"]
    )
    lead_clause = lead["label"] if hop_verified else f"{lead['label']}'s inferred tie"
    sentence = (
        f"{top3[0]['label']}, {top3[1]['label']}, and {top3[2]['label']} sit "
        f"{hops3.pop()} mapped handshakes out — all {n_routes} traced routes "
        f"open through {lead_clause}."
    )
    assert ("inferred" in sentence) == (not hop_verified)
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
        "blindSpot": (
            "Routes are the cheapest we can document — quieter, shorter routes "
            "may exist. Dashed hops are inferred ties, not yet verified."
        ),
        "templates": {
            "default": (
                "The best mapped route to {target} opens through {via} — "
                "{hops} handshakes."
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
    # rule 18: how thin is the wiring AoC's own placement rests on?
    aoc_edges = [e for e in companies["edges"] if AOC in (e["source"], e["target"])]
    n_aoc = len(aoc_edges)
    n_rival = sum(1 for e in aoc_edges if e["type"] == "competitor")
    assert 0 < n_rival <= n_aoc, "AoC edge inventory changed — reword blindSpot"
    return {
        "question": "What does the market look like, measured?",
        "source": ["market-map"],
        "blindSpot": (
            "Similarity is measured on mapped ties, so quiet companies drift "
            f"outward. AoC's own seat rests on {n_aoc} edges, {n_rival} of "
            "them rival ties."
        ),
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
    # rule 18: near-tie honesty — name #2 when it trails #1 by < NEAR_TIE_PP
    # (dAocPct is baked at 2dp, descending)
    margin = round(top["dAocPct"] - rows[1]["dAocPct"], 2)
    assert margin >= 0, "candidates no longer descending by dAocPct"
    near_tie = margin < NEAR_TIE_PP
    if near_tie:
        sentence = (
            f"{by_id[AOC]['name']}'s best new tie on the map is {top['label']} "
            f"— barely ahead of {rows[1]['label']} — one edge would cut its "
            f"mapped market distance by {round(top['dAocPct'], 1):g}%."
        )
    else:
        sentence = (
            f"{by_id[AOC]['name']}'s best new tie on the map is {top['label']} "
            f"— that one edge would cut its mapped market distance by "
            f"{round(top['dAocPct'], 1):g}%."
        )
    assert ("barely ahead" in sentence) == near_tie
    callouts = [
        {"id": r["id"], "text": f"#{k} handshake · −{r['dAocPct']:g}% distance"}
        for k, r in enumerate(rows[:3], 1)
    ]
    # rule 18: does the #1 handshake survive on verified ties alone?
    ver_top = verified_handshake_top(companies, AOC)
    ver_clause = (
        "pick the same #1"
        if ver_top == top["id"]
        else f"put {by_id[ver_top]['name']} first"
    )
    blind_spot = (
        "Resistance rewards thin wiring — and thin often means a quiet "
        f"portfolio, not a small one. Verified ties alone {ver_clause}."
    )
    assert ("same #1" in blind_spot) == (ver_top == top["id"])
    return {
        "question": "Which single handshake matters most?",
        "source": ["best-new-edge"],
        "blindSpot": blind_spot,
        "templates": {
            "default": (
                "{name}'s best new tie on the map is {winner} — that one edge "
                "would cut its mapped market distance by {pct}%."
            ),
            "self": (
                "{seat} is itself {name}'s #{rank} best new handshake — one tie "
                "would cut {pct}% of {name}'s market distance."
            ),
            "isolated": (
                "{seat} has no mapped tie into the connected core — "
                "resistance math can't reach it yet."
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
                "text": f"predicted tie to {r['prospect']} · "
                f"{round(r['phat'] * 100, 2):g}% base rate",
            }
        )
        if len(callouts) == 3:
            break

    sentence = (
        f"{len(rows)} vendor→buyer ties are the map's likeliest blind spots — "
        f"starting with {top['label']} × {top['prospect']}."
    )
    return {
        "question": "Which ties should exist but don't?",
        "source": ["missing-edges"],
        "blindSpot": (
            "These are predictions, not observations — a predicted tie may "
            "already exist privately. Base rates come from mapped densities, "
            "which undercount."
        ),
        "templates": {
            "default": (
                "The market's base rates say {name} may already have a tie "
                "to {top} — {pct}% of mapped pairs like this do."
            ),
            "self": (
                "{seat} is one of the vendors with likely-unmapped buyers — "
                "{top} first."
            ),
            "isolated": (
                "{seat} has no mapped ties at all — every expected tie is "
                "missing from the map."
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
            "text": f"zero mapped business ties cross this gap — "
            f"{len(sec_ids)} security vendors",
        },
        {
            "id": bank_rep,
            "text": f"zero mapped business ties cross this gap — {len(bank_ids)} banks",
        },
    ]
    sentence = (
        f"No business tie on the map links the {len(sec_ids)} security "
        f"vendors to the {len(bank_ids)} banks — open ground or quiet deals; "
        f"the loudest corridor, {labels[li]} × {labels[lj]}, wires "
        f"{loud_pct:g}% of its possible pairs."
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
        "blindSpot": (
            "An empty cell is a fact about the map: bank and hospital "
            "security deals are the least announced in the ecosystem. Open "
            "ground — or quiet deals."
        ),
        "templates": {
            "default": (
                "{name}'s shelf ({block}) holds zero mapped {layer} ties to "
                "{empty} — its loudest corridor is {loud}."
            ),
            "self": (
                "{seat} reads as mis-shelved — its mapped ties run with "
                "{wiredWith}, though it's filed under {shelved}."
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
        {"id": p["id"], "text": f"prospect #{k} · money-core, business-quiet"}
        for k, p in enumerate(prospects[:3], 1)
    ]
    sentence = (
        f"{len(prospects)} of {len(quadrant)} dual-wired companies sit in the "
        f"prospect corner — investor-core, business-quiet on the map — led by "
        f"{prospects[0]['label']}, {prospects[1]['label']}, and "
        f"{prospects[2]['label']}."
    )
    # rule 18: the null test must still agree the core is not special —
    # "the null test agrees" is a fact the blindSpot states
    null_test = cp_env["data"]["nullTest"]
    p_val = null_test["pValue"]
    assert (
        0 < p_val <= 1 and not null_test["significant"]
    ), "core-periphery null test turned significant — reword blindSpot"
    return {
        "question": "Who holds the core — who still looks outside?",
        "source": ["core-periphery"],
        "blindSpot": (
            "Coreness counts mapped ties — a quiet dealbook reads as crust. "
            "Core means well-connected on record, nothing more (the null test "
            f"agrees, p = {p_val:g})."
        ),
        "templates": {
            "default": (
                "{name} sits in the {corner} corner — business coreness {bc}, "
                "investor coreness {ic}."
            ),
            "self": (
                "{seat} is in the prospect corner itself — financed, not yet "
                "visibly embedded."
            ),
            "offcore": (
                "{seat} has no mapped shared-investor ties, so it can't sit "
                "on the money axis — business coreness only: {bc}."
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
            "text": f"#{k} closest · borda #{r['borda']} · {r['deg']} verified edges",
        }
        for k, r in enumerate(rows[:3], 1)
    ]
    sentence = (
        f"The graph puts {facts['topLabel']} closest to the rival pack — "
        f"{facts['nNominate']} of the {facts['nSeeds']} flagged rivals rank it "
        f"in their nearest {facts['topConsensus']}."
    )
    return {
        "question": "Who else orbits our rivals?",
        "source": ["competitor-nominations"],
        "blindSpot": (
            "Nominations are hypotheses from mapped wiring — near the rival "
            "pack means wired into red-teaming, not selling against us (or "
            "buying from us)."
        ),
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


# --- /funding: assets --------------------------------------------------------


def fmt_hops(h: int) -> str:
    return "one handshake" if h == 1 else f"{h} handshakes"


def bake_funder_fit_asset(funding: dict, ff_env: dict, ff_mod) -> tuple[dict, dict]:
    """assets.funderFit — funder-fit.py's own bipartite money embedding via
    load_sibling fit() (byte-equal by construction), rounded 4dp. Proof the
    baked values carry the envelope's answer: the rule-15 kernel over them
    must reproduce every positive-score ranked row in order; the zero-score
    tail (funders in money components disjoint from the seeds' component
    embed at exactly 0) only has to land in the zero band — its envelope
    order encodes sub-1e-15 float noise."""
    r = ff_mod.fit(funding)
    d = int(r["d"])
    funders, grantees, seeds = r["funders"], r["grantees"], r["seeds"]
    assert funders == sorted(funders) and grantees == sorted(grantees)
    assert seeds == sorted(seeds) and set(seeds) <= set(grantees)
    assert not set(funders) & set(grantees), "rule 15 needs disjoint ids lists"
    asset = {
        "d": d,
        "funders": {
            "ids": funders,
            "X": [[round(float(v), 4) for v in row] for row in r["X_f"]],
        },
        "grantees": {
            "ids": grantees,
            "X": [[round(float(v), 4) for v in row] for row in r["X_g"]],
        },
        "seeds": seeds,
    }
    assert [s["id"] for s in ff_env["data"]["seeds"]] == seeds

    score = ff_scores(asset, ff_virtual(asset))
    kern_order = sorted(score, key=lambda f: (-score[f], f))
    ranked = ff_env["data"]["ranked"]
    assert len(ranked) == FF_TOP_N
    pos_rows = [row for row in ranked if row["score"] > 0]
    assert len(pos_rows) >= 3, "structural signal collapsed — reword everything"
    assert kern_order[: len(pos_rows)] == [
        x["id"] for x in pos_rows
    ], "rule-15 kernel over the baked 4dp embedding disagrees with funder-fit"
    for row in ranked[len(pos_rows) :]:
        assert abs(score[row["id"]]) < FF_ZERO_BAND, f"{row['id']}: not zero-band"
    n_signal = sum(1 for s in score.values() if s > FF_ZERO_BAND)
    assert n_signal < FF_TOP_N, "positive-fit set overflows the top-15"
    return asset, {"nSignal": n_signal, "nEmb": len(funders)}


def bake_rival_joins(
    rm_env: dict, rm_mod, funding: dict, companies: dict
) -> tuple[list[dict], list[str]]:
    """assets.rivalJoins — rivals-money.py's two-key funder↔rival join,
    re-derived with its own canon() and asserted pair-for-pair equal to the
    envelope's joins (formats in the module docstring). Also returns the
    funding-side rival grantee ids (thumbnail context)."""
    funders = {n["id"]: n for n in funding["nodes"] if n["kind"] == "funder"}
    cnodes = {c["id"]: c for c in companies["companies"]}
    rival_ids = sorted(c["id"] for c in companies["companies"] if c.get("competitor"))
    riv_fund = {
        n["id"]: n.get("networksId") or n["id"]
        for n in funding["nodes"]
        if n["kind"] == "grantee" and (n.get("networksId") or n["id"]) in set(rival_ids)
    }
    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    pairs: dict[tuple[str, str], dict | None] = {}
    for e in money:
        if e["target"] in riv_fund:
            pairs[(e["source"], riv_fund[e["target"]])] = e
    funder_by_canon = {rm_mod.canon(f["name"]): fid for fid, f in funders.items()}
    acquired: set[str] = set()
    for rid in rival_ids:
        for raw in cnodes[rid].get("investors") or []:
            if "(acquirer)" in raw:
                acquired.add(rid)
                continue
            fid = funder_by_canon.get(rm_mod.canon(raw))
            if fid:
                pairs.setdefault((fid, rid), None)

    env_pairs = [
        (ch["nodes"][0]["id"], ch["nodes"][1]["id"]) for ch in rm_env["data"]["joins"]
    ]
    assert sorted(pairs) == sorted(env_pairs), "join drifted from rivals-money.json"
    rows = []
    for ch in rm_env["data"]["joins"]:
        fid, rid = ch["nodes"][0]["id"], ch["nodes"][1]["id"]
        edge = pairs[(fid, rid)]
        assert ch["edges"][0]["verified"] == bool(edge), (fid, rid)
        assert funders[fid]["name"] == ch["nodes"][0]["label"], fid
        assert cnodes[rid]["name"] == ch["nodes"][1]["label"], rid
        rows.append(
            {
                "id": fid,
                "rivalId": rid,
                "rivalLabel": cnodes[rid]["name"],
                "usd": edge.get("amountUSD") if edge else None,
                "live": rid not in acquired,
            }
        )
    # per-backer dollar sums must equal the envelope's rivalBackers table
    for r in rm_env["data"]["rivalBackers"]:
        got = sum(x["usd"] for x in rows if x["id"] == r["id"] and x["usd"]) or None
        assert got == r["usd"], f"{r['id']}: rival $ sum drifted"
    return rows, sorted(riv_fund)


def bake_sources_asset(chains_env: dict, funding_id_set: set[str]) -> list[dict]:
    """assets.sources — intro-chains' AoC entry points, verbatim minus the
    redundant graph tag (everything here is the funding graph)."""
    rows = chains_env["data"]["sources"]
    assert rows and all(r["graph"] == "funding" for r in rows)
    out = [
        {"id": r["id"], "label": r["label"], "aocDistance": r["aocDistance"]}
        for r in rows
    ]
    assert all(r["id"] in funding_id_set for r in out)
    return out


# --- /funding: question blocks ------------------------------------------------


def bake_funder_shortlist(ff_env, ff_asset, ff_facts, sorted_ids, pos, seat) -> dict:
    rows = ff_env["data"]["ranked"]
    top3 = rows[:3]
    assert all(r["score"] > 0 for r in top3), "top-3 fit went flat — reword"
    sentence = (
        f"Read as a recommender, the money graph makes {top3[0]['label']} the "
        f"#1 structural fit for an AoC-shaped org — {top3[1]['label']} and "
        f"{top3[2]['label']} follow, and only {ff_facts['nSignal']} of the "
        f"{ff_facts['nEmb']} funders with tracked money edges carry enough "
        f"tracked signal to rank at all."
    )
    callouts = [
        {"id": r["id"], "text": f"#{k} structural fit · rubric #{r['rubricRank']}"}
        for k, r in enumerate(top3, 1)
    ]
    cls = [0] * len(sorted_ids)
    for cid in ff_asset["grantees"]["ids"] + ff_asset["funders"]["ids"]:
        cls[pos[cid]] = 1
    for r in rows:
        cls[pos[r["id"]]] = 2
    for r in top3:
        cls[pos[r["id"]]] = 3
    return {
        "question": "Which funders should we apply to now?",
        "source": ["funder-fit"],
        "blindSpot": (
            "Fit is scored on tracked money only — a funder with a quiet "
            "portfolio scores low on data, not on interest. Zero fit means "
            "unranked, not unfit."
        ),
        "templates": {
            "default": (
                "The money graph puts {top} closest to funders already backing "
                "orgs shaped like {name} — #1 of {n} embeddable funders."
            ),
            "self": (
                "{seat} is itself on the structural shortlist — #{rank} of {n} "
                "funders with tracked money edges."
            ),
            "isolated": (
                "{seat} has no tracked money edge — the recommender has no row "
                "to embed it with."
            ),
        },
        "thumb": {"cls": cls},
        "default": {
            "seat": seat,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in rows],
            "rows": rows,
            "marks": {},
        },
    }


def bake_rivals_money(
    rm_env, rm_mod, ff_mod, rival_joins, riv_fund_ids, sorted_ids, pos, seat
) -> dict:
    backers = rm_env["data"]["rivalBackers"]
    clean = rm_env["data"]["cleanTargets"]
    assert backers and clean
    verified_usd = sum(r["usd"] for r in backers if r["usd"])
    assert verified_usd == sum(r["usd"] for r in rival_joins if r["usd"])
    sentence = (
        f"{len(backers)} tracked checkbooks have already funded a flagged "
        f"rival — {rm_mod.fmt_usd(verified_usd)} of it verified — while "
        f"{len(clean)} funders back agent-security or evals work with no "
        f"rival tie on record."
    )
    b0, c0, c1 = backers[0], clean[0], clean[1]
    assert c0["usd"] and c1["usd"], "clean leaders lost their disclosed $ — reword"
    b0_usd = rm_mod.fmt_usd(b0["usd"]) if b0["usd"] else "$ undisclosed"
    callouts = [
        {
            "id": b0["id"],
            "text": f"#1 tracked rival backer · {b0_usd} · {b0['conflict']}",
        },
        {
            "id": c0["id"],
            "text": f"#1 clean target · {ff_mod.fmt_usd(c0['usd'])} in lane, "
            "no tracked rival tie",
        },
        {
            "id": c1["id"],
            "text": f"#2 clean target · {ff_mod.fmt_usd(c1['usd'])} in lane, "
            "no tracked rival tie",
        },
    ]
    cls = [0] * len(sorted_ids)
    for cid in riv_fund_ids:  # the rivals visible on this map = context
        cls[pos[cid]] = 1
    for r in clean:
        cls[pos[r["id"]]] = 2
    for r in backers:
        cls[pos[r["id"]]] = 3
    return {
        "question": "Who funds our rivals?",
        "source": ["rivals-money"],
        "blindSpot": (
            "The join sees tracked positions only — absence means untracked, "
            "not unconflicted. Undisclosed stakes are exactly what this can "
            "miss."
        ),
        "templates": {
            "default": (
                "{name} has backed {rivals} — likely conflicted for our "
                "equity, appetite for the category proven."
            ),
            "self": (
                "{seat} has backed {rivals} — ask about conflicts before "
                "pitching; the appetite is real."
            ),
            "isolated": (
                "{seat} holds no tracked money edge — its rival exposure is "
                "invisible on this map."
            ),
        },
        "thumb": {"cls": cls},
        "default": {
            "seat": seat,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in backers] + [r["id"] for r in clean],
            "rows": backers + clean,
            "marks": {},
        },
    }


def bake_warm_routes(chains_env, sources_asset, sorted_ids, pos, seat) -> dict:
    groups_f = chains_env["data"]["fundingChains"]
    groups_p = chains_env["data"]["personRoutes"]
    counts = chains_env["data"]["counts"]
    assert groups_f and groups_p
    reachable = [g for g in groups_f + groups_p if g["chains"]]
    n_unreach = sum(1 for g in groups_f if not g["chains"])
    assert n_unreach == counts["unreachableFunderTargets"]

    # marks.paths: best chain per reachable target, cheapest first, capped
    best = sorted(reachable, key=lambda g: (g["chains"][0]["score"], g["target"]["id"]))
    paths = [[nd["id"] for nd in g["chains"][0]["nodes"]] for g in best[:WARM_PATH_CAP]]

    rows = []
    for g in groups_f:
        ch = g["chains"][0] if g["chains"] else None
        rows.append(
            {
                "id": g["target"]["id"],
                "label": g["target"]["label"],
                "kind": g["kind"],
                "rank": g["rank"],
                "from": ch["nodes"][0]["id"] if ch else None,
                "hops": len(ch["edges"]) if ch else None,
                "flag": g.get("flag"),
            }
        )
    for g in groups_p:
        ch = g["chains"][0]
        rows.append(
            {
                "id": g["target"]["id"],
                "label": g["target"]["label"],
                "kind": "person",
                "role": g["role"],
                "door": ch["nodes"][-2]["id"],
                "from": ch["nodes"][0]["id"],
                "hops": len(ch["edges"]),
            }
        )
    assert len(rows) <= 20

    fund_best = groups_f[0]
    assert fund_best["rank"] == 1 and fund_best["chains"], "top funder unreachable"
    direct = fund_best["chains"][0]
    hops0 = len(direct["edges"])
    person_best = min(
        groups_p, key=lambda g: (len(g["chains"][0]["edges"]), g["target"]["id"])
    )
    hops_p = len(person_best["chains"][0]["edges"])
    sentence = (
        f"{fund_best['target']['label']} — the #1 shortlist funder — is "
        f"{fmt_hops(hops0)} from {direct['nodes'][0]['label']}; the nearest "
        f"mapped doorkeeper, {person_best['target']['label']} at "
        f"{person_best['via']}, sits {fmt_hops(hops_p)} out."
    )
    used = {fund_best["target"]["id"], person_best["target"]["id"]}
    hub = next(
        r
        for r in chains_env["data"]["leaderboard"]
        if r["graph"] == "funding" and r["id"] not in used
    )
    assert hub["appearances"] >= 2
    n_funding_routes = counts["fundingChains"] + counts["personChains"]
    callouts = [
        {
            "id": fund_best["target"]["id"],
            "text": f"#1 shortlist funder · {fmt_hops(hops0)} out",
        },
        {
            "id": person_best["target"]["id"],
            "text": f"nearest named doorkeeper · "
            f"{person_best['role'].split(',')[0]}, {person_best['via']}",
        },
        {
            "id": hub["id"],
            "text": f"route hub · on {hub['appearances']} of "
            f"{n_funding_routes} funding routes",
        },
    ]

    chain_ids: list[str] = []
    for p in paths:
        for nid in p:
            if nid not in chain_ids:
                chain_ids.append(nid)

    cls = [0] * len(sorted_ids)
    for g in reachable:  # any baked chain member = context
        for ch in g["chains"]:
            for nd in ch["nodes"]:
                cls[pos[nd["id"]]] = 1
    for p in paths:  # shipped best routes = lit
        for nid in p:
            cls[pos[nid]] = 2
    for s in sources_asset:
        cls[pos[s["id"]]] = 3
    for p in paths:
        cls[pos[p[-1]]] = 3
    return {
        "question": "Who can introduce us to a funder?",
        "source": ["intro-chains"],
        "blindSpot": (
            "Every hop is a sourced edge, but recall is partial — the warmest "
            "real-world intro may be unmapped. Mapped routes are upper bounds."
        ),
        "templates": {
            "default": (
                "The warmest mapped route to {target} starts at {from} — {hops}."
            ),
            "self": (
                "{seat} is on the warm-route map itself — money paths open "
                "through it."
            ),
            "isolated": (
                "{seat} has no mapped funding ties — no warm route reaches " "it yet."
            ),
        },
        "thumb": {"cls": cls, "paths": paths},
        "default": {
            "seat": seat,
            "sentence": sentence,
            "callouts": callouts,
            "ids": chain_ids,
            "rows": rows,
            "marks": {"paths": paths},
        },
    }


def bake_within_reach(funding, sorted_ids, pos, adj, deg, sources_asset, seat) -> dict:
    """No proximity-rank funding block exists — the default is computed here
    per docstring rule 14: multi-seed PPR from assets.sources, top-25
    funder-kind rows, hops = min BFS distance over the sources."""
    kind = {n["id"]: n["kind"] for n in funding["nodes"]}
    fkind = {n["id"]: n.get("funderKind") for n in funding["nodes"]}
    labels = {n["id"]: n["name"] for n in funding["nodes"]}
    n = len(sorted_ids)
    seed_idxs = sorted(pos[s["id"]] for s in sources_asset)
    x = ppr_multi(adj, deg, n, seed_idxs)
    hops: list[int | None] = [None] * n
    for si in seed_idxs:
        dsi = bfs_dist(adj, si, n)
        for u in range(n):
            if dsi[u] is not None and (hops[u] is None or dsi[u] < hops[u]):
                hops[u] = dsi[u]

    reach_f = [u for u in range(n) if kind[sorted_ids[u]] == "funder" and x[u] > 0.0]
    reach_f.sort(key=lambda u: (-x[u], sorted_ids[u]))
    rows = [
        {
            "id": sorted_ids[u],
            "label": labels[sorted_ids[u]],
            "kind": fkind[sorted_ids[u]],
            "hops": hops[u],
            "s": round(x[u], 9),
        }
        for u in reach_f[:REACH_TOP_N]
    ]
    assert 3 <= len(rows) <= REACH_TOP_N
    assert all(r["hops"] is not None and r["hops"] >= 1 for r in rows)
    n_funders = sum(1 for cid in sorted_ids if kind[cid] == "funder")
    n_reach = len(reach_f)
    assert n_reach < n_funders, "every funder reachable — reword the sentence"
    assert len(sources_asset) == 3, "sentence says three entry grantees"
    top = rows[0]
    sentence = (
        f"Random walks from AoC's three entry grantees find mapped paths to "
        f"just {n_reach} of the {n_funders} tracked funders — the walk lands "
        f"on {top['label']} first, {fmt_hops(top['hops'])} out."
    )
    n_off_record = n_funders - n_reach  # rule 18; > 0 by the assert above
    callouts = [
        {"id": r["id"], "text": f"#{k} within reach · {fmt_hops(r['hops'])}"}
        for k, r in enumerate(rows[:3], 1)
    ]
    cls = [0] * n
    for u in range(n):
        if hops[u] is not None:
            cls[u] = 1
    for r in rows:
        cls[pos[r["id"]]] = 2
    for r in rows[:3]:
        cls[pos[r["id"]]] = 3
    for s in sources_asset:
        cls[pos[s["id"]]] = 3
    return {
        "question": "Which funders are within reach?",
        "source": ["proximity-rank"],
        "blindSpot": (
            "Reach means mapped-path reach — funders with quiet portfolios "
            f"leave no path to find. The other {n_off_record} aren't out of "
            "reach; they're off the record."
        ),
        "templates": {
            "default": (
                "The walk from {seat} lands on {top} first — {n} of {nf} "
                "tracked funders have a mapped money path at all."
            ),
            "self": (
                "{seat} is #{rank} within reach — {hops} from our corner of "
                "the money graph."
            ),
            "isolated": (
                "{seat} sits in a pocket of the money graph no walk from our "
                "corner reaches."
            ),
        },
        "thumb": {"cls": cls},
        "default": {
            "seat": seat,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in rows],
            "rows": rows,
            "marks": {},
        },
    }


def bake_funding_bridges(
    mb_env, mb_mod, funding, sorted_ids, pos, seat
) -> tuple[dict, list[str]]:
    rows = mb_env["data"]["gatekeepers"]
    doors = mb_env["data"]["doors"]
    assert rows and doors
    door_ids = [d["id"] for d in doors]
    assert len(set(door_ids)) == len(door_ids)

    # the envelope table ships person ids + funder NAMES; re-derive each
    # person's door from the live graph and assert every envelope number
    fnodes = {n["id"]: n for n in funding["nodes"]}
    door_of: dict[str, str] = {}
    for e in funding["edges"]:
        if e["type"] == "affiliation" and e.get("current"):
            assert e["source"] not in door_of, f"{e['source']}: >1 affiliation"
            door_of[e["source"]] = e["target"]
    for r in rows:
        fid = door_of[r["id"]]
        assert fnodes[fid]["name"] == r["funder"], r["id"]
        assert round(fnodes[fid].get("annualFieldGivingUSD") or 0) == r["gatedUSD"]
        assert fid in set(door_ids), r["id"]
    for d in doors:
        assert round(fnodes[d["id"]].get("annualFieldGivingUSD") or 0) == d["gatedUSD"]

    dollar_people = [r for r in rows if r["gatedUSD"] > 0]
    gated_total = sum(d["gatedUSD"] for d in doors)
    pay_and_bridge = sorted(
        {door_of[r["id"]] for r in rows if r["gatedUSD"] > 0 and r["brokeragePct"] > 0}
    )
    assert pay_and_bridge == ["nsf"], pay_and_bridge
    n_nsf = sum(1 for r in rows if door_of[r["id"]] == "nsf")
    sentence = (
        f"{len(dollar_people)} named people hold the doors to "
        f"{mb_mod.fmt_usd(gated_total)} a year of verified field money — and "
        f"among doors with a name on them, only NSF's {n_nsf} program "
        f"officers hold one that both pays and bridges money territories."
    )
    # rule 18: people coverage + the unheld biggest checkbook the text names
    funder_ids_all = sorted(n["id"] for n in funding["nodes"] if n["kind"] == "funder")
    held = set(door_of.values()) & set(funder_ids_all)
    n_held, n_funders = len(held), len(funder_ids_all)
    assert n_funders == mb_env["data"]["counts"]["funders"], "coverage drifted"
    assert 0 < n_held < n_funders
    biggest = min(
        funder_ids_all,
        key=lambda fid: (-(fnodes[fid].get("annualFieldGivingUSD") or 0), fid),
    )
    assert (
        biggest not in held
    ), "the biggest tracked checkbook gained a named holder — reword blindSpot"
    blind_spot = (
        f"Doorkeeping is computed on named staff at {n_held} of {n_funders} "
        "funders — the biggest tracked checkbook has no named holder on the "
        "map yet. Bridges inflate where edges are missing."
    )
    top_bridge = sorted(rows, key=lambda r: (-r["brokeragePct"], r["id"]))[0]
    assert top_bridge["brokeragePct"] > 0
    nsf_first = next(r for r in rows if door_of[r["id"]] == "nsf")
    assert rows[0]["gatedUSD"] > 0
    callouts = [
        {
            "id": rows[0]["id"],
            "text": f"biggest door held · {mb_mod.fmt_usd(rows[0]['gatedUSD'])}/yr "
            f"at {rows[0]['funder']}",
        },
        {
            "id": top_bridge["id"],
            "text": f"top people-held bridge on the map · {top_bridge['funder']}",
        },
        {
            "id": nsf_first["id"],
            "text": "the only named-staff door that pays AND bridges",
        },
    ]
    assert len({c["id"] for c in callouts}) == 3

    cls = [0] * len(sorted_ids)
    for e in funding["edges"]:  # the money graph itself = context
        if e["type"] in ("grant", "investment"):
            cls[pos[e["source"]]] = 1
            cls[pos[e["target"]]] = 1
    for r in rows:
        cls[pos[r["id"]]] = 2
    for fid in door_ids:
        cls[pos[fid]] = 3
    block = {
        "question": "Who gatekeeps the money?",
        "source": ["money-brokers"],
        "blindSpot": blind_spot,
        "templates": {
            "default": (
                "{name} sits on {seat}'s mapped routes to {doors} of the "
                "tracked money doors."
            ),
            "self": (
                "{seat} is itself a doorkeeper — the door to {funder} opens " "with it."
            ),
            "isolated": "{seat} has no path to a tracked money door yet.",
        },
        "thumb": {"cls": cls, "rings": door_ids[:5]},
        "default": {
            "seat": seat,
            "sentence": sentence,
            "callouts": callouts,
            "ids": [r["id"] for r in rows],
            "rows": rows,
            "marks": {},
        },
    }
    return block, door_ids


def bake_funding_fixtures(
    funding, ids, idx, adj, deg, n_pairs, ff_asset, sources_asset, door_ids
) -> dict:
    """Rule-17 seats × the three re-aimable funding kernels (rules 14-16)."""
    kind = {n["id"]: n["kind"] for n in funding["nodes"]}
    n = len(ids)

    def pick(pool: list[str], q: float) -> str:
        by = sorted(pool, key=lambda cid: (deg[idx[cid]], cid))
        return by[int(q * (len(by) - 1))]

    funder_pool = ff_asset["funders"]["ids"]
    grantee_pool = ff_asset["grantees"]["ids"]
    person_pool = [cid for cid in ids if kind[cid] == "person"]
    seats = [
        sources_asset[0]["id"],
        pick(funder_pool, FUNDING_FUNDER_QS[0]),
        pick(funder_pool, FUNDING_FUNDER_QS[1]),
        pick(person_pool, FUNDING_PERSON_Q),
        pick(grantee_pool, FUNDING_GRANTEE_Q),
    ]
    assert len(set(seats)) == 5, f"funding fixture seats collide: {seats}"
    assert seats[0] in grantee_pool, "AoC entry grantee not embeddable"

    door_dists = {idx[t]: bfs_dist(adj, idx[t], n) for t in door_ids}
    fx: dict = {
        "meta": {
            "seats": seats,
            "alpha": PPR_ALPHA,
            "iterations": PPR_ITERS,
            "ffTopN": FF_TOP_N,
            "doorIds": door_ids,
            "nodes": n,
            "undirectedEdges": n_pairs,
        },
        "ppr": {},
        "funderFit": {},
        "moneyPaths": {},
    }
    gpos = {g: i for i, g in enumerate(grantee_pool)}
    fpos = {f: i for i, f in enumerate(funder_pool)}
    for seat in seats:
        s_i = idx[seat]
        x = ppr(adj, deg, n, s_i)
        top = sorted(range(n), key=lambda u: (-x[u], ids[u]))[:10]
        fx["ppr"][seat] = [
            {"id": ids[u], "s": round(x[u], 9), "sFull": x[u]} for u in top
        ]
        fx["moneyPaths"][seat] = money_paths(ids, adj, s_i, door_dists)
        if seat in gpos:
            fx["funderFit"][seat] = ff_rank(
                ff_asset, ff_asset["grantees"]["X"][gpos[seat]]
            )
        elif seat in fpos:
            fx["funderFit"][seat] = ff_rank(
                ff_asset, ff_asset["funders"]["X"][fpos[seat]], exclude=seat
            )
    assert len(fx["funderFit"]) == 4, "expected exactly one non-embeddable seat"
    return fx


def main() -> None:
    companies = load_companies()
    funding = load_funding()
    brokers_env = load_envelope("brokers", companies)
    chains_env = load_envelope("intro-chains", companies, funding)
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
            "meet-first": bake_meet_first(
                chains_env, prox_env, companies, sorted_ids, pos
            ),
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

    # --- /funding: questions-funding.json + the "funding" fixture namespace ---
    ff_env = load_envelope("funder-fit", funding=funding)
    rm_env = load_envelope("rivals-money", companies, funding)
    mb_env = load_envelope("money-brokers", funding=funding)

    layout_f = shared["graphs"]["funding"]
    assert layout_f["stamp"] == stamp(funding), "shared.json stale — run bake.sh"
    f_ids, f_idx, f_adj, f_deg, f_pairs = build_funding_kernel_graph(funding)
    assert set(f_ids) == set(layout_f["nodes"]), "shared.json funding ids drifted"
    f_labels = {n["id"]: n["name"] for n in funding["nodes"]}

    rm_mod = load_sibling("rivals-money.py")
    mb_mod = load_sibling("money-brokers.py")
    ff_mod = load_sibling("funder-fit.py")
    ff_asset, ff_facts = bake_funder_fit_asset(funding, ff_env, ff_mod)
    rival_joins, riv_fund_ids = bake_rival_joins(rm_env, rm_mod, funding, companies)
    sources_asset = bake_sources_asset(chains_env, set(f_ids))
    # AoC is not a funding node — the default seat is its nearest entry grantee
    f_seat = sources_asset[0]["id"]
    bridges_block, door_ids = bake_funding_bridges(
        mb_env, mb_mod, funding, f_ids, f_idx, f_seat
    )

    payload_f = {
        "kind": "question-data",
        "graph": "funding",
        "inputs": {"funding": stamp(funding), "companies": stamp(companies)},
        "nodes": {
            "ids": f_ids,
            "x": [layout_f["nodes"][cid]["x"] for cid in f_ids],
            "y": [layout_f["nodes"][cid]["y"] for cid in f_ids],
            "label": [f_labels[cid] for cid in f_ids],
        },
        "assets": {
            "funderFit": ff_asset,
            "rivalJoins": rival_joins,
            "sources": sources_asset,
        },
        "params": {
            "friction": FUNDING_FRICTION,
            "pprAlpha": PPR_ALPHA,
            "pprIters": PPR_ITERS,
            "ffTopN": FF_TOP_N,
            "doorIds": door_ids,
        },
        "questions": {
            "funder-shortlist": bake_funder_shortlist(
                ff_env, ff_asset, ff_facts, f_ids, f_idx, f_seat
            ),
            "rivals-money": bake_rivals_money(
                rm_env, rm_mod, ff_mod, rival_joins, riv_fund_ids, f_ids, f_idx, f_seat
            ),
            "warm-routes": bake_warm_routes(
                chains_env, sources_asset, f_ids, f_idx, f_seat
            ),
            "within-reach": bake_within_reach(
                funding, f_ids, f_idx, f_adj, f_deg, sources_asset, f_seat
            ),
            "funding-bridges": bridges_block,
        },
    }
    emit_questions(payload_f, "questions-funding")

    fixtures["funding"] = bake_funding_fixtures(
        funding, f_ids, f_idx, f_adj, f_deg, f_pairs, ff_asset, sources_asset, door_ids
    )
    f_id_set = set(f_ids)
    ffx = fixtures["funding"]
    assert set(ffx["meta"]["seats"]) <= f_id_set
    assert set(ffx["meta"]["doorIds"]) <= f_id_set
    for kernel in ("ppr", "funderFit", "moneyPaths"):
        for seat, rows in ffx[kernel].items():
            assert seat in f_id_set
            assert all(r["id"] in f_id_set for r in rows)

    blob = json.dumps(
        fixtures, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    (QUESTIONS_DIR / "fixtures.json").write_text(blob + "\n")
    print(
        f"[fixtures] OK {len(blob) / 1024:.0f}KB — {len(fixtures['meta']['seats'])} "
        f"seats × 4 kernels ({fixtures['meta']['nodes']}n/"
        f"{fixtures['meta']['undirectedEdges']}ue) + funding "
        f"{len(ffx['meta']['seats'])} seats × 3 kernels ({ffx['meta']['nodes']}n/"
        f"{ffx['meta']['undirectedEdges']}ue)"
    )


if __name__ == "__main__":
    main()
