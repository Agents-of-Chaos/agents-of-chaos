// Tests for src/scripts/papers-core.js — the pure graph math under /papers.
// Run: npm test  (node --test, no dependencies)
import { test } from "node:test";
import assert from "node:assert/strict";
import { toNode, edgeWeight, buildEdges, vnRank } from "../src/scripts/papers-core.js";

// minimal node factory with a pre-normalized vector (papers-core stores unit vectors)
const mk = (id, vec, extra = {}) => ({
  id, title: id, authors: [], year: 2026, citationCount: 0, url: "", arxiv: null,
  vec, refs: [], ...extra,
});
const closeTo = (a, b, eps = 1e-4) => assert.ok(Math.abs(a - b) < eps, `${a} !≈ ${b}`);

// ── toNode ────────────────────────────────────────────────────────────────────────
test("toNode maps the S2 shape and normalizes the embedding to a unit vector", () => {
  const n = toNode({
    paperId: "a".repeat(40),
    title: "T", year: 2026,
    authors: [{ name: "A" }, { name: "B" }, {}, { name: "C" }],
    externalIds: { ArXiv: "2606.00001" },
    citationCount: 7,
    references: [{ paperId: "r1" }, {}, { paperId: "r2" }, null],
    embedding: { vector: [3, 4] }, // → [0.6, 0.8]
    abstract: "x".repeat(2000),
    tldr: { text: "short" },
  });
  assert.equal(n.url, "https://arxiv.org/abs/2606.00001"); // arXiv beats the S2 fallback
  assert.deepEqual(n.authors, ["A", "B", "C"]);
  assert.deepEqual(n.refs, ["r1", "r2"]);
  assert.deepEqual(n.vec, [0.6, 0.8]);
  closeTo(n.vec.reduce((s, x) => s + x * x, 0), 1); // unit norm survives the 5-decimal rounding
  assert.equal(n.abstract.length, 1500); // capped
  assert.equal(n.tldr, "short");
});

test("toNode: DOI url when no arXiv id; null without a paperId; null vec for a zero vector", () => {
  const doi = toNode({ paperId: "x", externalIds: { DOI: "10.1/abc" } });
  assert.equal(doi.url, "https://doi.org/10.1/abc");
  assert.equal(toNode({ title: "no id" }), null);
  assert.equal(toNode({ paperId: "y", embedding: { vector: [0, 0] } }).vec, null);
});

// ── edgeWeight ────────────────────────────────────────────────────────────────────
test("edgeWeight blends cosine, shared references, and direct citation", () => {
  const a = mk("A", [1, 0], { refs: ["B", "r1", "r2"] });
  const b = mk("B", [1, 0], { refs: ["r1", "r3"] });
  const w = edgeWeight(a, b, new Set(a.refs), new Set(b.refs));
  // cos=1 → 0.65 · shared {r1}: 1/√(3·2) → 0.25·0.40825 · A cites B → 0.10
  closeTo(w, 0.65 + 0.25 / Math.sqrt(6) + 0.1);
});

test("edgeWeight is 0 for orthogonal, citation-free papers (and negative cosines clamp)", () => {
  const a = mk("A", [1, 0]), b = mk("B", [0, 1]), c = mk("C", [-1, 0]);
  assert.equal(edgeWeight(a, b, new Set(), new Set()), 0);
  assert.equal(edgeWeight(a, c, new Set(), new Set()), 0); // cos⁺ clamps -1 → 0
});

// ── buildEdges ────────────────────────────────────────────────────────────────────
test("buildEdges keeps union-kNN edges over the floor, keyed by node ids", () => {
  const A = mk("A", [1, 0]);
  const B = mk("B", [0.92195, 0.38733]); // ≈0.92 to A, ≈0.39 to C
  const C = mk("C", [0, 1]);             // ⊥ A → weight 0 → floored out
  const edges = buildEdges([A, B, C], { k: 1 });
  const keys = edges.map((e) => [e.source, e.target].sort().join("-")).sort();
  assert.deepEqual(keys, ["A-B", "B-C"]); // A-C never survives; B-C kept because it is C's top-1
  for (const e of edges) assert.equal(typeof e.source, "string");
});

// ── vnRank ────────────────────────────────────────────────────────────────────────
const S1 = mk("S1", [1, 0]), S2 = mk("S2", [0, 1]);
const nearBoth = mk("both", [0.70711, 0.70711]);
const nearOne = mk("one", [1, 0]);

test("vnRank max-agg: relevant if close to ANY seed; nearestId is the closest seed", () => {
  const r = vnRank([nearBoth, nearOne], [S1, S2]);
  assert.deepEqual(r.map((x) => x.id), ["one", "both"]); // dot 1.0 beats 0.707
  assert.equal(r[0].nearestId, "S1");
});

test("vnRank min-agg (multi-focus): relevant only if close to ALL seeds", () => {
  const r = vnRank([nearBoth, nearOne], [S1, S2], { agg: "min" });
  assert.deepEqual(r.map((x) => x.id), ["both", "one"]); // min(0.707,0.707) beats min(1,0)
});

test("vnRank skips vector-less candidates and seeds; empty input → []", () => {
  const r = vnRank([mk("novec", null), nearOne], [mk("blindseed", null), S1]);
  assert.deepEqual(r.map((x) => x.id), ["one"]);
  assert.deepEqual(vnRank([nearOne], [mk("blindseed", null)]), []);
});

test("citeWeight lifts the better-known of two equally-relevant papers", () => {
  const a = mk("obscure", [1, 0], { citationCount: 0 });
  const b = mk("famous", [1, 0], { citationCount: 1000 });
  const r = vnRank([a, b], [S1], { citeWeight: 0.25 });
  assert.equal(r[0].id, "famous");
});

test("citeWeight never flips a clear relevance gap — relevance stays primary", () => {
  const relevant = mk("relevant", [1, 0], { citationCount: 0 });
  const famous = mk("famous", [0.70711, 0.70711], { citationCount: 100000 });
  const r = vnRank([relevant, famous], [S1], { citeWeight: 0.25 });
  assert.equal(r[0].id, "relevant");
});

test("citeWeight scores can exceed 1.0 — display code must rank, not percentage, them", () => {
  const top = mk("top", [1, 0], { citationCount: 1000 });
  const other = mk("other", [0.9, 0.43589], { citationCount: 0 });
  const r = vnRank([top, other], [S1], { citeWeight: 0.25 });
  assert.ok(r[0].vnScore > 1, `expected >1, got ${r[0].vnScore}`); // relNorm 1 + 0.25·popNorm 1
});

test("single candidate: the citation nudge is inert (no set to normalize against)", () => {
  const r = vnRank([nearBoth], [S1], { citeWeight: 0.25 });
  closeTo(r[0].vnScore, 0.70711); // raw nearest-seed cosine
});
