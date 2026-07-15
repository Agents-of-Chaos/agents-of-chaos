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

/** Fill `{slot}` placeholders. Values must be pre-formatted strings/numbers. */
export function fillTemplate(tpl, slots) {
  return tpl.replace(/\{(\w+)\}/g, (m, key) => (slots[key] !== undefined ? String(slots[key]) : m));
}

/** Count with a pre-pluralized unit: fmtCount(3, "tie", "ties") → "3 ties". */
export function fmtCount(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}
