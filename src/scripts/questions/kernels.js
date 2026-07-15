// Pure math kernels for the questions system — no DOM, no d3, imported
// untranspiled by node --test (tests/question-kernels.test.mjs) and by the
// question defs in the browser.
//
// DETERMINISM SPEC (must mirror experiments/analyses/prep_questions.py —
// fixtures assert bit-identical float64 across Python and JS):
//  1. undirected SIMPLE graph: dedupe edges by unordered pair; no self-loops
//  2. node index = position in ids sorted ascending (ASCII slugs)
//  3. adjacency lists sorted ascending by neighbor index
//  4. all accumulation in ascending-index order, plain float64
//  5. Burt constraint: equal weights, add terms only when q~j
//  6. PPR: exactly `nIter` iterations, scatter form, no early stop
//  7. ranked outputs: sort (-score, id) / (round6(c), id) ascending
// Verified in the P0-S4 spike: 100/100 fixture scores bit-identical.

/** @param {{companies: {id: string}[], edges: {source: string, target: string}[]}} data */
export function buildGraph(data) {
  const ids = data.companies.map((c) => c.id).sort();
  const n = ids.length;
  const idx = new Map(ids.map((cid, i) => [cid, i]));
  const pairSet = new Set();
  for (const e of data.edges) {
    const a = idx.get(e.source);
    const b = idx.get(e.target);
    if (a === undefined || b === undefined || a === b) continue;
    pairSet.add(a < b ? a * n + b : b * n + a);
  }
  const adj = Array.from({ length: n }, () => []);
  for (const key of pairSet) {
    const a = Math.floor(key / n);
    const b = key % n;
    adj[a].push(b);
    adj[b].push(a);
  }
  for (const lst of adj) lst.sort((x, y) => x - y);
  const deg = adj.map((lst) => lst.length);
  const adjSets = adj.map((lst) => new Set(lst));
  return { ids, idx, n, adj, deg, adjSets };
}

/** Burt constraint of node i (equal weights, ascending accumulation). */
export function constraint(g, i) {
  const invdeg = g.invdeg ?? (g.invdeg = g.deg.map((d) => (d > 0 ? 1.0 / d : 0.0)));
  let c = 0.0;
  const pi = invdeg[i];
  for (const j of g.adj[i]) {
    let inner = pi;
    for (const q of g.adj[i]) {
      if (q !== j && g.adjSets[q].has(j)) inner += pi * invdeg[q];
    }
    c += inner * inner;
  }
  return c;
}

/** BFS 2-hop neighborhood indices (seat included), ascending. */
export function twoHop(g, seed) {
  const seen = new Set([seed]);
  let frontier = [seed];
  for (let hop = 0; hop < 2; hop++) {
    const nxt = [];
    for (const u of frontier)
      for (const v of g.adj[u])
        if (!seen.has(v)) {
          seen.add(v);
          nxt.push(v);
        }
    frontier = nxt;
  }
  return [...seen].sort((a, b) => a - b);
}

/** Personalized PageRank from `seed`, fixed iteration count (spec rule 6). */
export function ppr(g, seed, alpha = 0.85, nIter = 100) {
  const n = g.n;
  let x = new Array(n).fill(0.0);
  x[seed] = 1.0;
  for (let it = 0; it < nIter; it++) {
    const nxt = new Array(n).fill(0.0);
    for (let u = 0; u < n; u++) {
      if (g.deg[u] > 0) {
        const contrib = alpha * (x[u] / g.deg[u]);
        for (const v of g.adj[u]) nxt[v] += contrib;
      }
    }
    let dangling = 0.0;
    for (let u = 0; u < n; u++) if (g.deg[u] === 0) dangling += x[u];
    nxt[seed] = nxt[seed] + alpha * dangling + (1.0 - alpha);
    x = nxt;
  }
  return x;
}

export const round6 = (x) => Math.round(x * 1e6) / 1e6;
export const round9 = (x) => Math.round(x * 1e9) / 1e9;

/** Top-10 lowest-constraint nodes (deg ≥ minDeg) in seat's 2-hop pool. */
export function constraintTop10(g, seatIdx, minDeg = 3) {
  const rows = [];
  for (const i of twoHop(g, seatIdx)) {
    if (g.deg[i] >= minDeg) {
      const cf = constraint(g, i);
      rows.push({ id: g.ids[i], c: round6(cf), cFull: cf, degree: g.deg[i] });
    }
  }
  rows.sort((a, b) => (a.c !== b.c ? a.c - b.c : a.id < b.id ? -1 : 1));
  return rows.slice(0, 10);
}

/** Top-10 PPR scores from seat, sort (-sFull, id). */
export function pprTop10(g, seatIdx, alpha = 0.85, nIter = 100) {
  const x = ppr(g, seatIdx, alpha, nIter);
  const order = Array.from({ length: g.n }, (_, i) => i);
  order.sort((a, b) => (x[a] !== x[b] ? x[b] - x[a] : g.ids[a] < g.ids[b] ? -1 : 1));
  return order.slice(0, 10).map((i) => ({ id: g.ids[i], s: round9(x[i]), sFull: x[i] }));
}

/**
 * Friction-weighted shortest paths (Dijkstra) over a typed adjacency.
 * @param {Map<string, {to: string, type: string}[]>} adjT
 * @param {Record<string, number>} friction  edge-type → weight
 * @returns {{dist: Map<string, number>, prev: Map<string, string>}}
 */
export function dijkstra(adjT, friction, from) {
  const dist = new Map([[from, 0]]);
  const prev = new Map();
  const done = new Set();
  // O(n²) scan-min is plenty at n≈200
  while (true) {
    let u = null;
    let best = Infinity;
    for (const [id, d] of dist) {
      if (!done.has(id) && d < best) {
        best = d;
        u = id;
      }
    }
    if (u === null) break;
    done.add(u);
    for (const e of adjT.get(u) ?? []) {
      const w = friction[e.type] ?? 1;
      const nd = best + w;
      const cur = dist.get(e.to);
      if (cur === undefined || nd < cur || (nd === cur && u < (prev.get(e.to) ?? "￿"))) {
        dist.set(e.to, nd);
        prev.set(e.to, u);
      }
    }
  }
  return { dist, prev };
}

/** Reconstruct the path from `from` to `to` out of dijkstra's prev map. */
export function pathTo(prev, from, to) {
  const path = [to];
  let cur = to;
  while (cur !== from) {
    const p = prev.get(cur);
    if (p === undefined) return null;
    path.push(p);
    cur = p;
  }
  return path.reverse();
}

/**
 * k nearest neighbors of `seatIdx` in a coordinate table (squared L2, all dims).
 * @param {number[][]} coords  row i ↔ ids[i]
 */
export function knn(coords, ids, seatIdx, k) {
  const s = coords[seatIdx];
  const rows = [];
  for (let i = 0; i < coords.length; i++) {
    if (i === seatIdx) continue;
    let d = 0;
    for (let j = 0; j < s.length; j++) {
      const dx = coords[i][j] - s[j];
      d += dx * dx;
    }
    rows.push({ id: ids[i], d: Math.sqrt(d) });
  }
  rows.sort((a, b) => (a.d !== b.d ? a.d - b.d : a.id < b.id ? -1 : 1));
  return rows.slice(0, k);
}

/**
 * SBM link prediction (P2, missing-ties — spec rule 11): top-10 NON-neighbors
 * of `seat`, ranked by the block-probability B[block(seat)][block(u)]
 * descending, ties broken id ascending. Candidates iterate `ids` ascending —
 * every u != seat with u not in N(seat), isolates included. pFull is a plain
 * lookup of the baked 4dp double (NO arithmetic — cross-language equality is
 * exact by construction). Nodes whose vertical has no block index are skipped.
 * @param {Record<string, string>} vertOf   node id → vertical
 * @param {number[][]} B                    block probability matrix
 * @param {Record<string, number>} blockIdx vertical → row/col index into B
 * @param {Set<string>} adjSet              the seat's neighbor ids (live graph)
 * @param {string[]} ids                    all node ids, sorted ascending
 * @param {string} seat
 * @returns {{id: string, p: number, pFull: number}[]}
 */
export function sbmRank(vertOf, B, blockIdx, adjSet, ids, seat) {
  const sb = blockIdx[vertOf[seat]];
  if (sb === undefined) return [];
  const rows = [];
  for (const u of ids) {
    if (u === seat || adjSet.has(u)) continue;
    const ub = blockIdx[vertOf[u]];
    if (ub === undefined) continue;
    const p = B[sb][ub];
    rows.push({ id: u, p: round6(p), pFull: p });
  }
  rows.sort((a, b) => (a.pFull !== b.pFull ? b.pFull - a.pFull : a.id < b.id ? -1 : 1));
  return rows.slice(0, 10);
}

/**
 * Rival-orbit nomination (P2 — spec rule 12): per-seed euclidean-distance
 * ranks over the verified-edges ASE cloud, fused by reciprocal-rank fusion
 * (competitor-nominations.py's fuse()). Candidates = all u with verified
 * degree > 0, u != seat, u not in seeds, ascending id order — verified
 * isolates embed at the exact origin, their "distance to seeds" is an
 * artifact. For each seed IN GIVEN ORDER (callers pass ascending): d(s,u) =
 * sqrt of the left-to-right double sum of squared dim differences; rank_s =
 * 1-based position under (d, id) ascending; score[u] += 1.0/(rrfK + rank_s),
 * one term per seed, accumulated in seed order.
 * Output: top-10 by (-sFull, id), s = round9(sFull).
 * @param {number[][]} aseVerified row i ↔ ids[i] (4dp doubles)
 * @param {string[]} ids           sorted ascending
 * @param {string[]} seedIds       accumulation follows this order exactly
 * @param {number} rrfK
 * @param {string} seat            excluded from the candidate pool
 * @param {Set<string>} verifiedIds ids with >=1 verified edge (vdeg > 0)
 * @returns {{id: string, s: number, sFull: number}[]}
 */
export function rivalOrbitRank(aseVerified, ids, seedIds, rrfK, seat, verifiedIds) {
  const seedSet = new Set(seedIds);
  const cand = []; // indices into ids, ascending (ids sorted → id-ascending)
  for (let i = 0; i < ids.length; i++) {
    if (ids[i] === seat || seedSet.has(ids[i]) || !verifiedIds.has(ids[i])) continue;
    cand.push(i);
  }
  const score = new Map(cand.map((i) => [i, 0.0]));
  for (const s of seedIds) {
    const si = ids.indexOf(s);
    if (si < 0) continue;
    const srow = aseVerified[si];
    const byDist = cand.map((i) => {
      let d = 0.0;
      const row = aseVerified[i];
      for (let j = 0; j < srow.length; j++) {
        const dx = row[j] - srow[j];
        d += dx * dx;
      }
      return { i, d: Math.sqrt(d) };
    });
    byDist.sort((a, b) => (a.d !== b.d ? a.d - b.d : a.i - b.i)); // tie → id asc
    for (let r = 0; r < byDist.length; r++) {
      const i = byDist[r].i;
      score.set(i, score.get(i) + 1.0 / (rrfK + r + 1));
    }
  }
  const rows = cand.map((i) => ({ id: ids[i], s: 0, sFull: score.get(i) }));
  rows.sort((a, b) => (a.sFull !== b.sFull ? b.sFull - a.sFull : a.id < b.id ? -1 : 1));
  const top = rows.slice(0, 10);
  for (const r of top) r.s = round9(r.sFull);
  return top;
}

/**
 * Mean of selected rows (P3, funding funderFit target): the "virtual seat"
 * position = the plain columnwise mean of X over idxList, accumulated in the
 * GIVEN order (callers pass ascending — funder-fit.py's seed order). Empty
 * idxList → zero vector of X's row width.
 * @param {number[][]} X
 * @param {number[]} idxList row indices into X
 * @returns {number[]}
 */
export function meanRows(X, idxList) {
  const w = X.length ? X[0].length : 0;
  const out = new Array(w).fill(0.0);
  if (!idxList.length) return out;
  for (const i of idxList) {
    const row = X[i];
    for (let j = 0; j < w; j++) out[j] += row[j];
  }
  for (let j = 0; j < w; j++) out[j] /= idxList.length;
  return out;
}

/**
 * Dot-product ranking (P3, funding funder-shortlist re-aim): score[i] =
 * left-to-right double sum of X[i][j]*target[j] (RDPG read: expected
 * log-dollar mass). Candidates iterate ids in the GIVEN order (callers pass
 * the asset's id list, ascending), minus excludeId. Top-k by (-sFull, id)
 * ascending; s = round9(sFull).
 * @param {number[][]} X       row i ↔ ids[i]
 * @param {string[]} ids
 * @param {number[]} target
 * @param {number} k
 * @param {string|null} excludeId
 * @returns {{id: string, s: number, sFull: number}[]}
 */
export function dotRank(X, ids, target, k = 10, excludeId = null) {
  const rows = [];
  for (let i = 0; i < ids.length; i++) {
    if (ids[i] === excludeId) continue;
    let s = 0.0;
    const row = X[i];
    for (let j = 0; j < target.length; j++) s += row[j] * target[j];
    rows.push({ id: ids[i], s: 0, sFull: s });
  }
  rows.sort((a, b) => (a.sFull !== b.sFull ? b.sFull - a.sFull : a.id < b.id ? -1 : 1));
  const top = rows.slice(0, k);
  for (const r of top) r.s = round9(r.sFull);
  return top;
}

/** BFS hop distances from `from` over a kernel graph; -1 = unreachable. */
export function bfsDist(g, from) {
  const dist = new Array(g.n).fill(-1);
  dist[from] = 0;
  let frontier = [from];
  while (frontier.length) {
    const next = [];
    for (const u of frontier)
      for (const v of g.adj[u])
        if (dist[v] < 0) {
          dist[v] = dist[u] + 1;
          next.push(v);
        }
    frontier = next;
  }
  return dist;
}

/**
 * moneyPaths (P3, funding-bridges re-aim — spec rule 16): doors =
 * params.doorIds (money-brokers' doors, envelope order). BFS hop distances
 * from the seat and from every door; for each door t (t != seat,
 * dist(seat,t) finite), a node u not in {seat, t} GATES t iff
 * dist(seat,u) + dist(u,t) == dist(seat,t). s[u] = number of doors u gates
 * (integer), d[u] = dist(seat,u). Rows = nodes with s > 0, top-10 by
 * (-s, d, id) ascending — all-integer math, cross-language exact by
 * construction. May be empty (seat with no path to any door).
 * @param {ReturnType<typeof buildGraph>} g  the rule-13 funding kernel graph
 * @param {number} seatIdx
 * @param {string[]} doorIds
 * @returns {{id: string, s: number, d: number}[]}
 */
export function moneyPaths(g, seatIdx, doorIds) {
  const ds = bfsDist(g, seatIdx);
  const gates = new Array(g.n).fill(0);
  for (const doorId of doorIds) {
    const t = g.idx.get(doorId);
    if (t === undefined || t === seatIdx || ds[t] < 0) continue;
    const dt = bfsDist(g, t);
    for (let u = 0; u < g.n; u++) {
      if (u === seatIdx || u === t) continue;
      if (ds[u] >= 0 && dt[u] >= 0 && ds[u] + dt[u] === ds[t]) gates[u] += 1;
    }
  }
  const rows = [];
  for (let u = 0; u < g.n; u++)
    if (gates[u] > 0) rows.push({ id: g.ids[u], s: gates[u], d: ds[u] });
  rows.sort((a, b) => b.s - a.s || a.d - b.d || (a.id < b.id ? -1 : 1));
  return rows.slice(0, 10);
}

/** Fill `{slot}` placeholders. Values must be pre-formatted strings/numbers. */
export function fillTemplate(tpl, slots) {
  return tpl.replace(/\{(\w+)\}/g, (m, key) => (slots[key] !== undefined ? String(slots[key]) : m));
}

/** Count with a pre-pluralized unit: fmtCount(3, "tie", "ties") → "3 ties". */
export function fmtCount(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}
