// papers-core.js — pure, DOM-free graph math shared by the page (client), the seed
// script (Node), and anything else. No d3, no fetch. Keep it dependency-free so it
// imports cleanly in both the browser bundle and `node scripts/seed-papers.mjs`.
//
// The whole design rests on one fact: a paper's SPECTER2 vector already *is* a latent
// position, so relevance is a dot product and "add a paper" is just placing a new
// vector — no eigendecomposition anywhere.

// ── relevance metric ────────────────────────────────────────────────────────────
// w(i,j) = 0.65·cos⁺ + 0.25·bibliographic-coupling + 0.10·direct-citation
// cos⁺ is the only always-defined term, so a paper's heaviest edge points at its most
// semantically-relevant paper by construction; the citation terms only sharpen it.
// (Co-citation, the 4th term in the research's 0.6/0.2/0.1/0.1 blend, is dropped here:
//  it needs full citer lists — thousands of ids per seminal paper — which would bloat
//  the shipped JSON. Documented as a future add behind a co-citation lookup.)
const W_COS = 0.65;
const W_BC = 0.25;
const W_DC = 0.1;

// The Semantic Scholar fields that back toNode's contract — shared so the page and the
// seed script can't drift from what toNode reads. (api/paper.js keeps its own copy on
// purpose: a root Vercel serverless function shouldn't import from src/.)
export const BATCH_FIELDS =
  "title,year,authors,externalIds,citationCount,embedding.specter_v2,references.paperId,abstract,tldr";
export const REC_FIELDS = "title,year,authors,externalIds,citationCount";

/**
 * L2-normalize a vector so cosine similarity collapses to a dot product. Values are
 * rounded to 5 decimals — a unit 768-vector has entries ≈ ±0.036, so 5 decimals is
 * lossless for ranking and trims the shipped JSON by ~30%.
 */
function normalize(vec) {
  if (!vec || !vec.length) return null;
  let n = 0;
  for (const x of vec) n += x * x;
  n = Math.sqrt(n);
  if (n < 1e-9) return null;
  return vec.map((x) => Math.round((x / n) * 1e5) / 1e5);
}

/** Dot product of two already-normalized vectors (= cosine). 0 if either is missing. */
function dot(a, b) {
  if (!a || !b) return 0;
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

/** Salton cosine over two id-sets: |A∩B| / sqrt(|A|·|B|). 0 if either is empty. */
function salton(setA, setB) {
  if (!setA || !setB || !setA.size || !setB.size) return 0;
  const [small, big] = setA.size <= setB.size ? [setA, setB] : [setB, setA];
  let inter = 0;
  for (const x of small) if (big.has(x)) inter++;
  return inter / Math.sqrt(setA.size * setB.size);
}

/**
 * Map one raw Semantic Scholar paper object → our node shape. Returns null if it has
 * no usable id. Normalizes the embedding up front and keeps only the bounded
 * `references` list (used for coupling + direct-citation); citers are intentionally
 * dropped (see metric note above).
 */
export function toNode(p) {
  if (!p || !p.paperId) return null;
  const ext = p.externalIds || {};
  let url = `https://www.semanticscholar.org/paper/${p.paperId}`;
  if (ext.ArXiv) url = `https://arxiv.org/abs/${ext.ArXiv}`;
  else if (ext.DOI) url = `https://doi.org/${ext.DOI}`;
  const refs = (p.references || [])
    .map((r) => r && r.paperId)
    .filter(Boolean);
  return {
    id: p.paperId,
    title: p.title || "(untitled)",
    authors: (p.authors || []).map((a) => a.name).filter(Boolean).slice(0, 6),
    year: p.year ?? null,
    citationCount: p.citationCount ?? 0,
    url,
    arxiv: ext.ArXiv || null,
    vec: normalize((p.embedding && p.embedding.vector) || null),
    refs,
    // shown in the click-to-open detail panel (kept on the node so the page needs no
    // per-view API call); abstract capped to keep the shipped JSON reasonable.
    tldr: (p.tldr && p.tldr.text) || null,
    abstract: p.abstract ? p.abstract.slice(0, 1500) : null,
  };
}

/** Precompute a Set of reference ids per node (for fast coupling / direct-cite). */
function refSets(nodes) {
  const m = new Map();
  for (const n of nodes) m.set(n.id, new Set(n.refs || []));
  return m;
}

/** Blended relevance weight between two nodes, in [0,1]. */
export function edgeWeight(a, b, refSetA, refSetB) {
  const cos = Math.max(0, dot(a.vec, b.vec));
  const bc = salton(refSetA, refSetB);
  const dc = refSetA.has(b.id) || refSetB.has(a.id) ? 1 : 0;
  return W_COS * cos + W_BC * bc + W_DC * dc;
}

/**
 * Build the sparsified edge list among `nodes`. For each node we keep its top-`k`
 * neighbours; an edge survives if it is in *either* endpoint's top-k (union-kNN, a
 * touch denser / more connected than mutual-kNN) and clears `floor`.
 *
 * NB: SPECTER2 cosines for in-field papers are compressed into a high band (~0.5–0.95
 * here), so an *absolute* floor barely sparsifies — kNN is the real structure-giver
 * because it is scale-invariant (top-k preserves a node's relative ordering regardless
 * of where the band sits). `floor` is kept tiny, only to drop near-orthogonal pairs as
 * the corpus diversifies. The view layer then scales edge thickness/heat *relative* to
 * the live weight range so the narrow band reads as real contrast (cf. pass_to_ranks).
 * Returns [{ source, target, w }] with string ids (d3-forceLink friendly).
 */
export function buildEdges(nodes, { k = 6, floor = 0.05 } = {}) {
  const rs = refSets(nodes);
  const n = nodes.length;
  // full upper-triangular weight matrix (n ≤ a few hundred → trivial)
  const perNode = nodes.map(() => []); // [{j, w}]
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const w = edgeWeight(nodes[i], nodes[j], rs.get(nodes[i].id), rs.get(nodes[j].id));
      if (w <= floor) continue;
      perNode[i].push({ j, w });
      perNode[j].push({ j: i, w });
    }
  }
  const keep = new Set();
  const edges = [];
  for (let i = 0; i < n; i++) {
    perNode[i].sort((a, b) => b.w - a.w);
    for (const { j, w } of perNode[i].slice(0, k)) {
      const key = i < j ? `${i}-${j}` : `${j}-${i}`;
      if (keep.has(key)) continue;
      keep.add(key);
      edges.push({ source: nodes[i].id, target: nodes[j].id, w });
    }
  }
  return edges;
}

/**
 * Vertex nomination over unread `candidates` given the `seeds`, with two knobs:
 *
 *  - `agg` aggregates a candidate's per-seed cosines:
 *      "max" (default) → nearest-seed cosine: relevant if close to *any* seed (whole-set
 *        nomination over a reading list that spans threads, or a single focus paper).
 *      "min"           → farthest-seed cosine: relevant only if close to *all* seeds
 *        (a multi-paper focus selection — "papers closest to ALL of these").
 *
 *  - `citeWeight` (0 = off) adds a gentle popularity nudge so well-known papers surface
 *      among similarly-relevant ones. Relevance and log-citations are each min-max
 *      normalized across THIS candidate set (scale-invariant, adaptive), then combined as
 *      `relevanceNorm + citeWeight · citationsNorm`. Relevance stays primary: the most
 *      relevant paper still wins; citations only lift papers of comparable relevance.
 *
 * Returns candidates sorted by the combined score desc, each with `.vnScore` (the score used
 * to rank + weight the ghost) and `.nearestId` (the closest seed, for the tether).
 */
export function vnRank(candidates, seeds, { agg = "max", citeWeight = 0 } = {}) {
  const scored = [];
  for (const c of candidates) {
    if (!c.vec) continue;
    let best = -1, bestId = null, worst = Infinity, n = 0;
    for (const r of seeds) {
      if (!r.vec) continue;
      const s = dot(c.vec, r.vec);
      if (s > best) { best = s; bestId = r.id; }
      if (s < worst) worst = s;
      n++;
    }
    if (!n) continue;
    scored.push({ c, bestId, rel: agg === "min" ? worst : best, pop: Math.log1p(Math.max(0, c.citationCount || 0)) });
  }
  const useCite = citeWeight > 0 && scored.length > 1;
  let rlo = 0, rspan = 1, plo = 0, pspan = 1;
  if (useCite) {
    const rels = scored.map((x) => x.rel), pops = scored.map((x) => x.pop);
    rlo = Math.min(...rels); rspan = (Math.max(...rels) - rlo) || 1;
    plo = Math.min(...pops); pspan = (Math.max(...pops) - plo) || 1;
  }
  for (const x of scored) {
    x.score = useCite ? (x.rel - rlo) / rspan + citeWeight * ((x.pop - plo) / pspan) : x.rel;
  }
  return scored
    .sort((a, b) => b.score - a.score)
    .map((x) => ({ ...x.c, vnScore: x.score, nearestId: x.bestId }));
}
