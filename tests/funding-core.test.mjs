// Tests for src/scripts/funding-core.js — the pure graph/dollar math under /funding.
// Run: npm test  (node --test, no dependencies)
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PERSON_R, UNKNOWN_R,
  makeSqrtScale, nodeDollars, radiusFor, edgeWidthFor,
  buildAdjacency, shortestPath, isOpenNow, computeVisible,
  sliderToUsd, formatUsd, topGrants,
} from "../src/scripts/funding-core.js";

const closeTo = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} !≈ ${b}`);

// ── node factories ─────────────────────────────────────────────────────────
const funder = (id, extra = {}) => ({
  id, kind: "funder", name: id, blurb: `${id} blurb`, funderKind: "philanthropy",
  annualFieldGivingUSD: null, fieldDollarsUSD: 0, confidence: "high",
  sources: [], priorityRank: 1, lastVerified: "2026-07-02",
  apply: { mode: "invite-only", lastVerified: "2026-07-02" }, ...extra,
});
const grantee = (id, extra = {}) => ({
  id, kind: "grantee", name: id, blurb: `${id} blurb`, granteeKind: "research-org",
  fieldDollarsUSD: 0, confidence: "high", sources: [], priorityRank: 50,
  lastVerified: "2026-07-02", ...extra,
});
const person = (id, extra = {}) => ({
  id, kind: "person", name: id, blurb: `${id} blurb`, title: "Program Officer",
  fieldDollarsUSD: 0, confidence: "high", sources: [], priorityRank: 90,
  lastVerified: "2026-07-02", ...extra,
});
const grant = (source, target, extra = {}) =>
  ({ type: "grant", source, target, amountUSD: null, verified: true, ...extra });
const affil = (source, target) =>
  ({ type: "affiliation", source, target, role: "Program Officer", current: true });

// ── scales ─────────────────────────────────────────────────────────────────
test("makeSqrtScale is sqrt-monotone and clamped", () => {
  const s = makeSqrtScale([1_000_000, 100_000_000], [5, 26]);
  closeTo(s(1_000_000), 5);
  closeTo(s(100_000_000), 26);
  // 100× dollars = 10× the sqrt position: halfway up the sqrt range lands mid-range
  const mid = s(Math.pow((Math.sqrt(1e6) + Math.sqrt(1e8)) / 2, 2));
  closeTo(mid, (5 + 26) / 2, 1e-3);
  assert.ok(s(500_000_000) === 26, "clamps above");
  assert.ok(s(10) === 5, "clamps below");
  // degenerate domain → constant floor, no NaN
  const flat = makeSqrtScale([0, 0], [5, 26]);
  assert.equal(flat(123), 5);
});

test("nodeDollars: person is always null; zero/unknown fieldDollars is null", () => {
  assert.equal(nodeDollars(person("p", { fieldDollarsUSD: 9e9 })), null); // rogue field ignored
  assert.equal(nodeDollars(funder("f")), null); // 0 → unknown
  assert.equal(nodeDollars(funder("f", { fieldDollarsUSD: 5e6 })), 5e6);
  assert.equal(nodeDollars(grantee("g", { fieldDollarsUSD: 3e7 })), 3e7);
});

test("radiusFor: person constant, unknown constant, else scaled", () => {
  const s = makeSqrtScale([1e6, 1e8], [5, 26]);
  assert.equal(radiusFor(person("p", { fieldDollarsUSD: 9e9 }), s), PERSON_R);
  assert.equal(radiusFor(funder("f"), s), UNKNOWN_R);
  closeTo(radiusFor(funder("f", { fieldDollarsUSD: 1e8 }), s), 26);
});

test("edgeWidthFor: affiliation fixed, undisclosed hairline, else sqrt-scaled", () => {
  const s = makeSqrtScale([50_000, 80_000_000], [0.7, 6]);
  assert.equal(edgeWidthFor(affil("p", "f"), s), 0.8);
  assert.equal(edgeWidthFor(grant("f", "g"), s), 0.7); // amountUSD null
  closeTo(edgeWidthFor(grant("f", "g", { amountUSD: 80_000_000 }), s), 6);
});

// ── BFS path finder ────────────────────────────────────────────────────────
const NODES = [funder("cg"), funder("sff"), grantee("far"), grantee("metr"), person("po"), funder("island")];
const EDGES = [grant("cg", "far"), grant("sff", "far"), grant("sff", "metr"), affil("po", "cg")];
const ADJ = buildAdjacency(NODES, EDGES);

test("buildAdjacency is symmetric and covers every node", () => {
  assert.ok(ADJ.get("cg").has("far") && ADJ.get("far").has("cg"));
  assert.ok(ADJ.has("island") && ADJ.get("island").size === 0);
});

test("shortestPath: direct hop", () => {
  assert.deepEqual(shortestPath(ADJ, "cg", "far"), { ids: ["cg", "far"], len: 1 });
});

test("shortestPath: multi-hop through a grantee, ordered from→to", () => {
  const r = shortestPath(ADJ, "cg", "metr");
  assert.deepEqual(r.ids, ["cg", "far", "sff", "metr"]);
  assert.equal(r.len, 3);
});

test("shortestPath: person→grantee chain via their funder", () => {
  assert.deepEqual(shortestPath(ADJ, "po", "far").ids, ["po", "cg", "far"]);
});

test("shortestPath: disconnected and self both return null", () => {
  assert.equal(shortestPath(ADJ, "cg", "island"), null);
  assert.equal(shortestPath(ADJ, "cg", "cg"), null);
});

// ── open-now ───────────────────────────────────────────────────────────────
const TODAY = "2026-07-02";
test("isOpenNow: rolling open, invite-only/closed never, rounds by deadline", () => {
  assert.equal(isOpenNow(funder("a", { apply: { mode: "rolling", lastVerified: TODAY } }), TODAY), true);
  assert.equal(isOpenNow(funder("b", { apply: { mode: "invite-only", lastVerified: TODAY } }), TODAY), false);
  assert.equal(isOpenNow(funder("c", { apply: { mode: "closed", lastVerified: TODAY } }), TODAY), false);
  assert.equal(isOpenNow(funder("d", { apply: { mode: "rounds", deadline: "2026-09-30", lastVerified: TODAY } }), TODAY), true);
  assert.equal(isOpenNow(funder("e", { apply: { mode: "rounds", deadline: "2026-07-02", lastVerified: TODAY } }), TODAY), true); // boundary: same-day still open
  assert.equal(isOpenNow(funder("f", { apply: { mode: "rounds", deadline: "2026-05-17", lastVerified: TODAY } }), TODAY), false);
  assert.equal(isOpenNow(funder("g", { apply: { mode: "rounds", lastVerified: TODAY } }), TODAY), false); // rounds w/o known deadline
  assert.equal(isOpenNow(grantee("h"), TODAY), false); // non-funder / missing apply
});

// ── visibility ─────────────────────────────────────────────────────────────
const VN = [
  funder("cg", { funderKind: "philanthropy", annualFieldGivingUSD: 128e6, fieldDollarsUSD: 128e6, domainTags: ["technical-alignment"] }),
  funder("nsf", { funderKind: "government", annualFieldGivingUSD: null, domainTags: ["technical-alignment"] }),
  funder("menlo", { funderKind: "vc", annualFieldGivingUSD: 100e6, fieldDollarsUSD: 100e6, domainTags: ["agent-security"] }),
  grantee("far", { domainTags: ["technical-alignment"] }),
  grantee("promptfoo", { granteeKind: "startup", domainTags: ["agent-security"] }),
  person("po-cg"),
];
const VE = [
  grant("cg", "far", { amountUSD: 2e6, sourceUrl: "https://x.example/g1" }),
  { type: "investment", source: "menlo", target: "promptfoo", amountUSD: 18.4e6, verified: true },
  affil("po-cg", "cg"),
];
const F = (over = {}) => ({ kinds: new Set(["philanthropy", "government", "vc", "corporate"]), domains: new Set(), minUsd: 0, query: "", ...over });

test("computeVisible: everything visible with open filters", () => {
  const v = computeVisible(VN, VE, F());
  assert.equal(v.size, VN.length);
});

test("computeVisible: kind toggle hides the funder, its orphaned person, and sole-funder grantees", () => {
  const v = computeVisible(VN, VE, F({ kinds: new Set(["government", "vc", "corporate"]) }));
  assert.ok(!v.has("cg") && !v.has("po-cg") && !v.has("far"));
  assert.ok(v.has("nsf") && v.has("menlo") && v.has("promptfoo"));
});

test("computeVisible: grantee survives while at least one visible funder remains", () => {
  const edges2 = [...VE, grant("nsf", "far")];
  const v = computeVisible(VN, edges2, F({ kinds: new Set(["government"]) }));
  assert.ok(v.has("far"), "still fed by nsf");
  assert.ok(!v.has("promptfoo"), "menlo hidden → promptfoo starves");
});

test("computeVisible: domain chips filter funders and tagged grantees", () => {
  const v = computeVisible(VN, VE, F({ domains: new Set(["agent-security"]) }));
  assert.ok(v.has("menlo") && v.has("promptfoo"));
  assert.ok(!v.has("cg") && !v.has("far"));
});

test("computeVisible: $ floor hides small AND unknown-$ funders (slider asserts 'gives ≥ $X')", () => {
  const v = computeVisible(VN, VE, F({ minUsd: 110e6 }));
  assert.ok(v.has("cg"));
  assert.ok(!v.has("nsf"), "unknown $ can't prove ≥ floor");
  assert.ok(!v.has("menlo"));
});

test("computeVisible: query matches names, aliases, and reveals a searched person's funder", () => {
  const withAlias = VN.map((n) => (n.id === "cg" ? { ...n, aliases: ["Open Philanthropy"] } : n));
  assert.ok(computeVisible(withAlias, VE, F({ query: "open philanthropy" })).has("cg"));
  const v = computeVisible(VN, VE, F({ query: "po-cg" }));
  assert.ok(v.has("po-cg") && v.has("cg"), "person match keeps the person and its funder");
  assert.ok(!v.has("menlo"));
});

// ── slider / formatting / grants ───────────────────────────────────────────
test("sliderToUsd: 0→0, 100→max, strictly monotone in between", () => {
  const MAX = 128e6;
  assert.equal(sliderToUsd(0, MAX), 0);
  closeTo(sliderToUsd(100, MAX), MAX);
  let prev = 0;
  for (let v = 1; v <= 100; v++) {
    const cur = sliderToUsd(v, MAX);
    assert.ok(cur > prev, `monotone at ${v}`);
    prev = cur;
  }
  assert.ok(sliderToUsd(50, MAX) < MAX / 2, "exponential ramp favors resolution at the small end");
});

test("formatUsd", () => {
  assert.equal(formatUsd(1_200_000), "$1.2M");
  assert.equal(formatUsd(350_000), "$350k");
  assert.equal(formatUsd(40_000_000), "$40M");
  assert.equal(formatUsd(128_000_000), "$128M");
  assert.equal(formatUsd(1_500_000_000), "$1.5B");
  assert.equal(formatUsd(500), "$500");
  assert.equal(formatUsd(null), "—");
});

test("topGrants: only that funder's grant edges, $ desc, undisclosed last, capped", () => {
  const es = [
    grant("cg", "a", { amountUSD: 1e6, year: 2024, sourceUrl: "https://x.example/a" }),
    grant("cg", "b", { amountUSD: 5e6, year: 2023, sourceUrl: "https://x.example/b" }),
    grant("cg", "c"), // undisclosed
    grant("cg", "d", { amountUSD: 5e6, year: 2025, sourceUrl: "https://x.example/d" }),
    grant("sff", "z", { amountUSD: 9e9, sourceUrl: "https://x.example/z" }),
    { type: "investment", source: "cg", target: "y", amountUSD: 9e9, verified: true },
  ];
  const top = topGrants(es, "cg", 3);
  assert.deepEqual(top.map((g) => g.target), ["d", "b", "a"]); // ties broken by year desc
  assert.equal(topGrants(es, "cg", 9).at(-1).target, "c"); // undisclosed sorts last
});
