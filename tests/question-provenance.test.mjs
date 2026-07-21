// Route-hop provenance (annotate.ts pathHopTrusted): a rendered route hop is
// trusted iff some edge under it is verified — or, on the FUNDING graph only,
// an affiliation (source-backed but carrying no `verified` field; the engine
// coerces missing to false, see audit-infra §2/§6). Untrusted hops draw dashed
// "2 3" and trigger the answer-bar marksNote. The helper is pure (no DOM), so
// node imports annotate.ts untranspiled — the funding-degrade test precedent.

import assert from "node:assert/strict";
import { test } from "node:test";
import { pathHopTrusted, pathsHaveUntrustedHop } from "../src/scripts/questions/annotate.ts";

/** Build the engine's typed adjacency exactly as engine.ts buildCtx does:
 *  both directions, `verified ?? false`. */
function adjTOf(edges) {
  const adjT = new Map();
  const push = (a, e) => {
    const l = adjT.get(a);
    if (l) l.push(e);
    else adjT.set(a, [e]);
  };
  for (const e of edges) {
    push(e.source, { to: e.target, type: e.type, verified: e.verified ?? false });
    push(e.target, { to: e.source, type: e.type, verified: e.verified ?? false });
  }
  return adjT;
}

test("verified hop is trusted", () => {
  const adjT = adjTOf([{ source: "a", target: "b", type: "business", verified: true }]);
  assert.deepEqual(pathHopTrusted(["a", "b"], adjT, "companies"), [true]);
});

test("unverified hop is untrusted", () => {
  const adjT = adjTOf([{ source: "a", target: "b", type: "business", verified: false }]);
  assert.deepEqual(pathHopTrusted(["a", "b"], adjT, "companies"), [false]);
});

test("funding affiliation hop (no verified field) is trusted on funding only", () => {
  // affiliations carry no `verified` in funding.json — the adjacency builder
  // coerces it to false, but the edge is source-backed
  const adjT = adjTOf([{ source: "person", target: "funder", type: "affiliation" }]);
  assert.deepEqual(pathHopTrusted(["person", "funder"], adjT, "funding"), [true]);
  // the same edge shape on the companies graph earns no affiliation pass
  assert.deepEqual(pathHopTrusted(["person", "funder"], adjT, "companies"), [false]);
});

test("missing pair is untrusted", () => {
  const adjT = adjTOf([{ source: "a", target: "b", type: "business", verified: true }]);
  assert.deepEqual(pathHopTrusted(["a", "zzz"], adjT, "companies"), [false]);
  assert.deepEqual(pathHopTrusted(["a", "zzz"], adjT, "funding"), [false]);
});

test("2-node path yields exactly one hop; short paths yield none", () => {
  const adjT = adjTOf([{ source: "a", target: "b", type: "grant", verified: true }]);
  assert.equal(pathHopTrusted(["a", "b"], adjT, "funding").length, 1);
  assert.deepEqual(pathHopTrusted(["a"], adjT, "funding"), []);
  assert.deepEqual(pathHopTrusted([], adjT, "funding"), []);
});

test("multi-hop path flags exactly the untrusted hops, in order", () => {
  const adjT = adjTOf([
    { source: "a", target: "b", type: "business", verified: true },
    { source: "b", target: "c", type: "competitor", verified: false }, // inferred
    { source: "c", target: "d", type: "shared-investor", verified: true },
  ]);
  assert.deepEqual(pathHopTrusted(["a", "b", "c", "d"], adjT, "companies"), [true, false, true]);
});

test("parallel typed edges aggregate: any trustworthy edge trusts the hop", () => {
  // up to three parallel edges per pair (one per type) with mixed flags —
  // the check must aggregate, not name "the" traversed edge (infra §6)
  const adjT = adjTOf([
    { source: "a", target: "b", type: "competitor", verified: false },
    { source: "a", target: "b", type: "shared-investor", verified: true },
  ]);
  assert.deepEqual(pathHopTrusted(["a", "b"], adjT, "companies"), [true]);
});

test("hop trust is direction-agnostic (adjacency is undirected)", () => {
  const adjT = adjTOf([{ source: "a", target: "b", type: "business", verified: true }]);
  assert.deepEqual(pathHopTrusted(["b", "a"], adjT, "companies"), [true]);
});

test("pathsHaveUntrustedHop: the marksNote trigger", () => {
  const adjT = adjTOf([
    { source: "a", target: "b", type: "business", verified: true },
    { source: "b", target: "c", type: "business", verified: false },
  ]);
  const prov = { adjT, graph: "companies" };
  assert.equal(pathsHaveUntrustedHop([["a", "b"]], prov), false);
  assert.equal(pathsHaveUntrustedHop([["a", "b"], ["a", "b", "c"]], prov), true);
  assert.equal(pathsHaveUntrustedHop([], prov), false);
  assert.equal(pathsHaveUntrustedHop(undefined, prov), false);
  assert.equal(pathsHaveUntrustedHop([["a", "b", "c"]], undefined), false);
});
