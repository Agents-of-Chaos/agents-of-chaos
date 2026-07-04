# /funding Page Implementation Plan (plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship agents-of-chaos.ai/funding — a dollar-weighted territory force map of the AI-safety funding landscape (funders / grantees / people) with map+directory views, filters, an open-now lens, a public path finder, and a dev-only private overlay — running on a hand-seeded starter dataset (plan 2 replaces the data; plan 3 adds the nightly loop).

**Architecture:** Clone-and-adapt the /networks page (`src/scripts/networks-graph.ts` et al.) with all pure math in a new DOM-free module `funding-core.js` (papers-core pattern, node:test-covered). Dataset is typed + validated at Astro build time (`companies.ts` pattern). The private overlay uses the exact dev-only dead-elimination mechanism of `NetworkGraph.astro`.

**Tech Stack:** Astro 6.4.3, D3 7.9.0 (already deps — no new dependencies), TypeScript, `node --test`.

**Spec:** `docs/superpowers/specs/2026-07-02-funding-map-design.md`

## Global Constraints

- Palette: cream bg `#fffff8`, red `#a00` reserved for highlight/path/funded-stage only; kind colors philanthropy `#4c6b8a`, government `#5a7d5a`, vc `#9b6a6a`, corporate `#a6611a`; grantee `#8a8475`; person `#b08968`.
- No `Math.random()` / `Date.now()` in layout or data — deterministic layout (golden-angle seeding), open-now derives from `meta.generatedAt`, never the wall clock.
- Never commit without `npm test` && `npm run build` passing (repo CLAUDE.md).
- `npx astro check` has 15 pre-existing errors (d3 generics, node:fs in NetworkGraph.astro); the clone adds matching ones — they do NOT block `npm run build` and are not a gate.
- Privacy invariant: `private/funding-overlay.json` is read ONLY inside `import.meta.env.DEV`; nothing from it may reach `dist/`.
- Do NOT modify any `/networks` or `/papers` file except `src/layouts/Base.astro` (Task 3).
- Every dollar figure in `funding.json` that is non-null must carry a source URL (validator-enforced).
- All new element ids are `fund-*`; CSS classes `fund-*` / `pp-*`; directory reuses `dir-*` class names but scoped under `.fund-directory`.
- Commit messages: `funding: <what>` + the Co-Authored-By/Claude-Session trailer used in this repo's recent commits.

---

### Task 1: Types + pure math module (TDD)

**Files:**
- Create: `src/data/funding-types.ts`
- Create: `src/scripts/funding-core.js`
- Create: `tests/funding-core.test.mjs`

**Interfaces:**
- Produces (used by every later task):
  - Types: `FundingNode = FunderNode | GranteeNode | PersonNode`, `FundingEdge = GrantEdge | InvestmentEdge | AffiliationEdge`, `FunderKind`, `ApplyMode`, `FundingStage`, `FundingOverlayEntry`, `FundingData`, `FundingMeta`, `DomainMeta`
  - Tables/helpers: `FUNDER_KINDS`, `DOMAINS`, `FUNDING_STAGES`, `GRANTEE_COLOR`, `PERSON_COLOR`, `funderColor(k)`, `funderLabel(k)`, `fundingStageColor(s)`, `fundingStageLabel(s)`, `nodeColor(n)` — plus re-exported `escapeHtml`
  - funding-core (pure JS): `PERSON_R`, `UNKNOWN_R`, `makeSqrtScale`, `nodeDollars`, `radiusFor`, `edgeWidthFor`, `buildAdjacency`, `shortestPath`, `isOpenNow`, `computeVisible`, `sliderToUsd`, `formatUsd`, `topGrants`

- [ ] **Step 1: Write `src/data/funding-types.ts`** (complete file):

```ts
/* Types + display metadata for the /funding landscape map.
 *
 * Two-layer, exactly like /networks (see network-types.ts):
 *   - PUBLIC  (funding.json)  — funders, grantees, publicly-listed people; every
 *               dollar figure carries a source URL. Committed, shipped.
 *   - PRIVATE (private/funding-overlay.json, gitignored) — OUR pipeline stage +
 *               warm paths. Loaded ONLY in `astro dev`, never in a prod build.
 *
 * Color encodes FUNDER KIND, size encodes FIELD-RELEVANT DOLLARS (sqrt scale).
 * Red (#a00) stays reserved for highlight / the active path / a funded stage. */

export type NodeKind = "funder" | "grantee" | "person";
export type FunderKind = "philanthropy" | "government" | "vc" | "corporate";
export type GranteeKind = "research-org" | "university" | "startup" | "fieldbuilding";
export type ApplyMode = "rolling" | "rounds" | "invite-only" | "closed";
export type Confidence = "high" | "medium" | "low";

export interface SourceRef {
  url: string;
  title?: string;
  accessed: string; // ISO date
}

export interface Apply {
  mode: ApplyMode;
  url?: string;
  deadline?: string; // ISO date of the next known close (rounds only)
  notes?: string; // "reopens summer 2026"
  lastVerified: string; // ISO date — the nightly job's re-verification clock
}

export interface AnnualBasis {
  year: number; // basis year for the figure
  method: string; // e.g. "sum of AI-safety fund grants CY2025, multi-year amortized"
  sourceUrl: string;
}

interface NodeBase {
  id: string; // stable slug — node id, edge endpoint, #f= deep-link token. FROZEN once emitted.
  kind: NodeKind;
  name: string;
  aliases?: string[]; // for entity resolution + search ("Open Philanthropy")
  blurb: string; // one line
  domainTags?: string[]; // DOMAINS ids — what work this money touches
  confidence: Confidence; // research confidence → node opacity
  sources: SourceRef[]; // node-level provenance (validator: >= 1)
  networksId?: string; // companies.json id when the same entity is on /networks
  priorityRank: number; // "approach first" rank (1 = highest)
  url?: string;
  lastVerified: string; // ISO date
  /* Baked sizing value (sqrt → radius): funder = annualFieldGivingUSD ?? 0;
   * grantee = verified in-field $ received (regrant-deduped, amortized);
   * person = 0 (people are never dollar-sized). */
  fieldDollarsUSD: number;
  x?: number; // optional baked initial layout
  y?: number;
}

export interface FunderNode extends NodeBase {
  kind: "funder";
  funderKind: FunderKind; // → color + territory
  program?: string; // sub-group within the kind (directory grouping), e.g. "Technical AI Safety"
  annualFieldGivingUSD: number | null; // $ into THIS FIELD per year; null = no public figure
  annualFieldGivingBasis?: AnnualBasis; // REQUIRED (validator) whenever the figure is non-null
  checkSizeUSD?: { min: number; max: number };
  thesis?: string; // their theory of change, for the dossier
  apply: Apply;
  inKind?: boolean; // compute/API credits rather than cash
}

export interface GranteeNode extends NodeBase {
  kind: "grantee";
  granteeKind: GranteeKind;
}

export interface PersonNode extends NodeBase {
  kind: "person"; // publicly-listed program officers / fund managers ONLY
  title: string; // the publicly listed role
  profileUrl?: string;
}

export type FundingNode = FunderNode | GranteeNode | PersonNode;

export type FundingEdgeType = "grant" | "investment" | "affiliation";

export interface GrantEdge {
  type: "grant";
  source: string; // funder id
  target: string; // grantee id
  amountUSD: number | null; // null = undisclosed (hairline). Non-null REQUIRES sourceUrl.
  amountOriginal?: { value: number; currency: "GBP" | "EUR" | "USD" };
  year?: number;
  multiYear?: { start: number; end: number }; // sizing amortizes total across years
  program?: string; // "SFF-2025 Main Round"
  sourceUrl?: string;
  verified: boolean; // true = solid; false = inferred, dashed
  regrantOf?: string; // payer funder id (dedup key: SFF rows paid by Jaan Tallinn etc.)
}

export interface InvestmentEdge {
  type: "investment";
  source: string; // vc/corporate funder id
  target: string; // startup grantee id
  amountUSD: number | null; // disclosed round total (attribution upper bound)
  year?: number;
  round?: string; // "Series B (co-led)"
  sourceUrl?: string;
  verified: boolean;
}

export interface AffiliationEdge {
  type: "affiliation";
  source: string; // person id
  target: string; // funder id
  role: string; // "Co-founder", "Program Officer, Technical AI Safety"
  current: boolean; // append-only history: job changes flip this, never delete
  sourceUrl?: string;
  lastVerified?: string;
}

export type FundingEdge = GrantEdge | InvestmentEdge | AffiliationEdge;

export interface DomainMeta {
  id: string;
  label: string;
}

export interface FundingMeta {
  generated?: string; // producer ("hand-seeded starter" | "build_funding.py")
  generatedAt: string; // ISO date — the snapshot clock that drives open-now
  domains: DomainMeta[];
  fx?: Record<string, number>; // pinned annual-average rates used for conversion
  [k: string]: unknown;
}

export interface FundingData {
  meta: FundingMeta;
  nodes: FundingNode[];
  edges: FundingEdge[];
}

export type FundingStage = "cold" | "warm" | "in-convo" | "applied" | "funded";

export interface FundingOverlayEntry {
  id: string; // joins to FundingNode.id
  stage?: FundingStage;
  warm_path?: string;
  notes?: string;
}

/* Funder kind → label + color. Same restrained site palette as VERTICALS in
 * network-types.ts; order fixes the 2×2 territory grid in funding-graph.ts. */
export const FUNDER_KINDS: { id: FunderKind; label: string; color: string }[] = [
  { id: "philanthropy", label: "philanthropy", color: "#4c6b8a" },
  { id: "government", label: "government", color: "#5a7d5a" },
  { id: "vc", label: "venture", color: "#9b6a6a" },
  { id: "corporate", label: "corporate programs", color: "#a6611a" },
];

export const GRANTEE_COLOR = "#8a8475"; // neutral gray-tan — grantees are context, funders are the map
export const PERSON_COLOR = "#b08968"; // small outlined dots

/* Domain tags → labels (what the money funds). Baked copy also lives in
 * funding.json meta.domains so the pipeline and the page can't drift. */
export const DOMAINS: DomainMeta[] = [
  { id: "technical-alignment", label: "technical alignment" },
  { id: "interpretability", label: "interpretability" },
  { id: "evals", label: "evals" },
  { id: "agent-security", label: "agent security" },
  { id: "policy-governance", label: "policy / governance" },
  { id: "open-source", label: "open source" },
  { id: "field-building", label: "field building" },
];

/* Fundraising pipeline stage → label + color (PRIVATE layer only).
 * Cold→warm ramp ending in the reserved accent red once the money lands. */
export const FUNDING_STAGES: { id: FundingStage; label: string; color: string }[] = [
  { id: "cold", label: "cold", color: "#b3ab9c" },
  { id: "warm", label: "warm", color: "#b08968" },
  { id: "in-convo", label: "in conversation", color: "#a6611a" },
  { id: "applied", label: "applied", color: "#5a7d5a" },
  { id: "funded", label: "funded", color: "#a00" },
];

/* Single source of truth for HTML escaping — same policy module as /networks. */
export { escapeHtml } from "./network-types";

export const funderColor = (k: FunderKind): string =>
  FUNDER_KINDS.find((x) => x.id === k)?.color ?? GRANTEE_COLOR;
export const funderLabel = (k: FunderKind): string =>
  FUNDER_KINDS.find((x) => x.id === k)?.label ?? k;
export const fundingStageColor = (s?: FundingStage): string =>
  FUNDING_STAGES.find((x) => x.id === s)?.color ?? FUNDING_STAGES[0].color;
export const fundingStageLabel = (s?: FundingStage): string =>
  FUNDING_STAGES.find((x) => x.id === s)?.label ?? (s ?? "");
export const domainLabel = (id: string): string =>
  DOMAINS.find((d) => d.id === id)?.label ?? id;

export const nodeColor = (n: FundingNode): string =>
  n.kind === "funder" ? funderColor(n.funderKind) : n.kind === "grantee" ? GRANTEE_COLOR : PERSON_COLOR;
```

- [ ] **Step 2: Write the failing tests** — `tests/funding-core.test.mjs` (complete file):

```js
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
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `cd <worktree-root> && npm test`
Expected: FAIL — `Cannot find module '.../src/scripts/funding-core.js'`

- [ ] **Step 3: Write `src/scripts/funding-core.js`** (complete file):

```js
/* Pure graph/dollar math for the /funding landscape map.
 * NO DOM, NO d3, NO fetch — mirrors src/scripts/papers-core.js so `node --test`
 * imports it untranspiled. funding-graph.ts (view) owns all rendering.
 *
 * Sizing philosophy: AREA is proportional to field-relevant dollars (sqrt radius,
 * Tufte-honest). People are NEVER dollar-sized; unknown dollars render small with
 * a dotted outline (the view reads UNKNOWN_R).
 *
 * @typedef {import("../data/funding-types").FundingNode} FundingNode
 * @typedef {import("../data/funding-types").FundingEdge} FundingEdge
 * @typedef {import("../data/funding-types").FunderNode} FunderNode
 */

export const PERSON_R = 4; // px — constant, regardless of any dollar field
export const UNKNOWN_R = 5; // px — "no public $" nodes (dotted outline in the view)

/** Clamped sqrt scale: dollars → pixels. Degenerate domains collapse to r0. */
export function makeSqrtScale([d0, d1], [r0, r1]) {
  const s0 = Math.sqrt(Math.max(0, d0));
  const s1 = Math.sqrt(Math.max(0, d1));
  if (!(s1 > s0)) return () => r0;
  return (x) => {
    const t = (Math.sqrt(Math.max(0, x)) - s0) / (s1 - s0);
    return r0 + (r1 - r0) * Math.min(1, Math.max(0, t));
  };
}

/** The dollars a node is sized by, or null when unknown. People are always null. */
export function nodeDollars(node) {
  if (node.kind === "person") return null;
  return node.fieldDollarsUSD > 0 ? node.fieldDollarsUSD : null;
}

/** Node radius under a dollar scale (see PERSON_R / UNKNOWN_R above). */
export function radiusFor(node, scale) {
  if (node.kind === "person") return PERSON_R;
  const d = nodeDollars(node);
  return d == null ? UNKNOWN_R : scale(d);
}

/** Edge stroke width: affiliations fixed-thin, undisclosed grants hairline. */
export function edgeWidthFor(edge, scale) {
  if (edge.type === "affiliation") return 0.8;
  return edge.amountUSD == null ? 0.7 : scale(edge.amountUSD);
}

/** Undirected adjacency over ALL nodes (isolates get empty sets). */
export function buildAdjacency(nodes, edges) {
  const adj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const e of edges) {
    if (!adj.has(e.source) || !adj.has(e.target)) continue;
    adj.get(e.source).add(e.target);
    adj.get(e.target).add(e.source);
  }
  return adj;
}

/** BFS shortest path a→b. Returns { ids, len } or null (unreachable / a===b). */
export function shortestPath(adj, a, b) {
  if (a === b || !adj.has(a) || !adj.has(b)) return null;
  const prev = new Map([[a, null]]);
  let frontier = [a];
  while (frontier.length) {
    const next = [];
    for (const id of frontier) {
      for (const nb of adj.get(id) ?? []) {
        if (prev.has(nb)) continue;
        prev.set(nb, id);
        if (nb === b) {
          const ids = [b];
          for (let cur = id; cur !== null; cur = prev.get(cur)) ids.push(cur);
          ids.reverse();
          return { ids, len: ids.length - 1 };
        }
        next.push(nb);
      }
    }
    frontier = next;
  }
  return null;
}

/** Is this funder accepting applications as of the dataset snapshot date?
 *  Snapshot-dated (meta.generatedAt), never the wall clock — a static page
 *  must not silently claim freshness it doesn't have. */
export function isOpenNow(node, todayIso) {
  if (node.kind !== "funder" || !node.apply) return false;
  const { mode, deadline } = node.apply;
  if (mode === "rolling") return true;
  if (mode === "rounds") return !!deadline && deadline.slice(0, 10) >= todayIso.slice(0, 10);
  return false; // invite-only | closed
}

const matchText = (n, q) =>
  n.name.toLowerCase().includes(q) ||
  n.blurb.toLowerCase().includes(q) ||
  (n.aliases ?? []).some((a) => a.toLowerCase().includes(q)) ||
  n.id.toLowerCase().includes(q);

/** Two-pass visible set. Funders pass on their own merits; grantees are visible
 *  iff at least one VISIBLE funder feeds them; people follow their funder.
 *  `filters = { kinds:Set<FunderKind>, domains:Set<string>, minUsd:number, query:string }`.
 *  The open-now lens is NOT here — it highlights, it never filters. */
export function computeVisible(nodes, edges, filters) {
  const q = (filters.query ?? "").trim().toLowerCase();
  const domainPass = (n) =>
    filters.domains.size === 0 ||
    !n.domainTags?.length || // untagged nodes follow their neighbors, not the chips
    n.domainTags.some((t) => filters.domains.has(t));
  // funder-domain chips are strict: a tagged-or-not funder must match when chips are active
  const funderDomainPass = (f) =>
    filters.domains.size === 0 || (f.domainTags ?? []).some((t) => filters.domains.has(t));

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const peopleOf = new Map(); // funder id → person nodes (via affiliation edges)
  for (const e of edges) {
    if (e.type !== "affiliation") continue;
    const p = byId.get(e.source);
    if (!p) continue;
    if (!peopleOf.has(e.target)) peopleOf.set(e.target, []);
    peopleOf.get(e.target).push(p);
  }

  // pass 1 — funders
  const visible = new Set();
  for (const n of nodes) {
    if (n.kind !== "funder") continue;
    if (!filters.kinds.has(n.funderKind)) continue;
    if (!funderDomainPass(n)) continue;
    if (filters.minUsd > 0 && !(n.annualFieldGivingUSD != null && n.annualFieldGivingUSD >= filters.minUsd)) continue;
    if (q && !matchText(n, q) && !(peopleOf.get(n.id) ?? []).some((p) => matchText(p, q))) continue;
    visible.add(n.id);
  }

  // pass 2 — grantees: need at least one visible funding edge
  for (const n of nodes) {
    if (n.kind !== "grantee") continue;
    if (!domainPass(n)) continue;
    if (q && !matchText(n, q)) continue;
    const fed = edges.some(
      (e) => (e.type === "grant" || e.type === "investment") && e.target === n.id && visible.has(e.source),
    );
    if (fed) visible.add(n.id);
  }

  // pass 3 — people: follow their (visible) funder
  for (const e of edges) {
    if (e.type !== "affiliation" || !visible.has(e.target)) continue;
    const p = byId.get(e.source);
    if (!p) continue;
    if (q && !matchText(p, q) && !matchText(byId.get(e.target), q)) continue;
    visible.add(p.id);
  }
  return visible;
}

/** Slider position (0..100) → dollar floor. Exponential ramp so most of the
 *  slider's travel covers the small-check end where funders actually differ. */
export function sliderToUsd(v, maxUsd, k = 6) {
  if (v <= 0) return 0;
  if (v >= 100) return maxUsd;
  return (maxUsd * Math.expm1((k * v) / 100)) / Math.expm1(k);
}

/** "$1.2M" / "$350k" / "$40M" / "$1.5B" / "—". One formatter for graph,
 *  directory, dossier, and tooltip — they must never disagree. */
export function formatUsd(n) {
  if (n == null) return "—";
  const trim = (x) => String(Number(x.toFixed(1))); // 1.0 → "1"
  if (n >= 1e9) return `$${trim(n / 1e9)}B`;
  if (n >= 1e6) return n < 1e7 ? `$${trim(n / 1e6)}M` : `$${Math.round(n / 1e6)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${Math.round(n)}`;
}

/** A funder's notable grants: $ desc (undisclosed last), then year desc. */
export function topGrants(edges, funderId, n = 5) {
  return edges
    .filter((e) => e.type === "grant" && e.source === funderId)
    .sort((a, b) => (b.amountUSD ?? -1) - (a.amountUSD ?? -1) || (b.year ?? 0) - (a.year ?? 0))
    .slice(0, n);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test`
Expected: PASS — all `funding-core` tests green, `papers-core` tests untouched and green.

- [ ] **Step 5: Commit**

```bash
git add src/data/funding-types.ts src/scripts/funding-core.js tests/funding-core.test.mjs
git commit -m "funding: types + pure dollar/graph math module (TDD)"
```

---

### Task 2: Starter dataset + build-time validator

**Files:**
- Create: `src/data/funding.json`
- Create: `src/data/funding.ts`

**Interfaces:**
- Consumes: all types from Task 1.
- Produces: `import { fundingNodes, fundingEdges, fundingMeta } from "../data/funding"` — validated at Astro build time. Also re-exports everything from `funding-types`.

- [ ] **Step 1: Verify the `networksId` cross-links actually exist in companies.json**

Run (from worktree root):
```bash
python3 -c "
import json
ids = {c['id'] for c in json.load(open('src/data/companies.json'))['companies']}
for want in ['openai','anthropic','metr','apollo-research','irregular','promptfoo','gray-swan-ai','menlo-ventures','sequoia-capital']:
    print(('OK  ' if want in ids else 'MISS'), want)
"
```
For any `MISS`, search `python3 -c "...print([c['id'] for c in ...] )" | tr ',' '\n' | grep -i <name>` and use the real id in Step 2 — or drop the `networksId` field from that node entirely. Never invent an id: `funding.ts` will fail the build on a bad one.

- [ ] **Step 2: Write `src/data/funding.json`**

Hand-seeded starter: 17 funders / 12 grantees / 3 people / 29 edges (32 nodes). Real orgs, real sources; every non-null dollar carries its source; anything not yet verified is `null` + `confidence: "medium"|"low"` or `verified: false` (dashed). Plan 2's pipeline regenerates this file — ids are FROZEN from here on.

Complete file (adjust only `networksId` fields per Step 1):

```json
{
  "meta": {
    "generated": "hand-seeded starter (plan 1); replaced by experiments/funding pipeline (plan 2)",
    "generatedAt": "2026-07-02",
    "fx": { "GBP": 1.27, "EUR": 1.08 },
    "domains": [
      { "id": "technical-alignment", "label": "technical alignment" },
      { "id": "interpretability", "label": "interpretability" },
      { "id": "evals", "label": "evals" },
      { "id": "agent-security", "label": "agent security" },
      { "id": "policy-governance", "label": "policy / governance" },
      { "id": "open-source", "label": "open source" },
      { "id": "field-building", "label": "field building" }
    ]
  },
  "nodes": [
    {
      "id": "coefficient-giving", "kind": "funder", "name": "Coefficient Giving",
      "aliases": ["Open Philanthropy"], "funderKind": "philanthropy",
      "blurb": "The largest AI-safety philanthropy — program-based funds (technical AI safety, AI governance), backed chiefly by Dustin Moskovitz and Cari Tuna.",
      "domainTags": ["technical-alignment", "policy-governance", "field-building"],
      "annualFieldGivingUSD": 128000000,
      "annualFieldGivingBasis": { "year": 2025, "method": "sum of AI-safety-relevant grants CY2025 from the public grants database, multi-year amortized", "sourceUrl": "https://coefficientgiving.org/funds" },
      "checkSizeUSD": { "min": 50000, "max": 10000000 },
      "thesis": "Fund the research, institutions, and talent pipelines that make transformative AI go well; concentrated bets, program officers with real budgets.",
      "apply": { "mode": "rolling", "url": "https://coefficientgiving.org/funds", "notes": "RFPs per fund; general inquiries rolling", "lastVerified": "2026-07-02" },
      "confidence": "high", "priorityRank": 1, "url": "https://coefficientgiving.org",
      "sources": [{ "url": "https://coefficientgiving.org/research/open-philanthropy-is-now-coefficient-giving/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 128000000
    },
    {
      "id": "survival-and-flourishing-fund", "kind": "funder", "name": "Survival & Flourishing Fund",
      "aliases": ["SFF"], "funderKind": "philanthropy",
      "blurb": "S-process rounds recommending grants paid by Jaan Tallinn, Jed McCaleb, and allied donors — one of the largest x-risk funders.",
      "domainTags": ["technical-alignment", "policy-governance", "field-building"],
      "annualFieldGivingUSD": 34920000,
      "annualFieldGivingBasis": { "year": 2025, "method": "sum of 2025 round recommendations from the public table", "sourceUrl": "https://survivalandflourishing.fund/recommendations" },
      "checkSizeUSD": { "min": 100000, "max": 3000000 },
      "apply": { "mode": "rounds", "url": "https://survivalandflourishing.fund", "notes": "annual s-process rounds; application windows announced on the site", "lastVerified": "2026-07-02" },
      "confidence": "high", "priorityRank": 2, "url": "https://survivalandflourishing.fund",
      "sources": [{ "url": "https://survivalandflourishing.fund/recommendations", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 34920000
    },
    {
      "id": "ltff", "kind": "funder", "name": "Long-Term Future Fund",
      "aliases": ["LTFF", "EA Funds LTFF"], "funderKind": "philanthropy",
      "blurb": "EA Funds' rolling small-grants fund for AI safety and x-risk — the field's default first check for individuals and small projects.",
      "domainTags": ["technical-alignment", "interpretability", "field-building"],
      "annualFieldGivingUSD": null,
      "checkSizeUSD": { "min": 5000, "max": 400000 },
      "apply": { "mode": "rolling", "url": "https://funds.effectivealtruism.org/funds/far-future", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 4, "url": "https://funds.effectivealtruism.org",
      "sources": [{ "url": "https://funds.effectivealtruism.org/api/grants", "title": "public grants CSV", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "manifund", "kind": "funder", "name": "Manifund",
      "funderKind": "philanthropy",
      "blurb": "Regranting marketplace: named regrantors with $100k+ budgets fund AI-safety projects in public, writeups and all.",
      "domainTags": ["technical-alignment", "field-building"],
      "annualFieldGivingUSD": null,
      "checkSizeUSD": { "min": 5000, "max": 250000 },
      "apply": { "mode": "rolling", "url": "https://manifund.org", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 8, "url": "https://manifund.org",
      "sources": [{ "url": "https://manifund.org/about/regranting", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "schmidt-sciences", "kind": "funder", "name": "Schmidt Sciences",
      "funderKind": "philanthropy",
      "blurb": "Eric and Wendy Schmidt's science philanthropy — AI Safety Science program (Bengio, Kolter among 27 funded projects) plus a joint agent-safety call with Google DeepMind and ARIA.",
      "domainTags": ["technical-alignment", "evals", "agent-security"],
      "annualFieldGivingUSD": 10000000,
      "annualFieldGivingBasis": { "year": 2025, "method": "AI Safety Science program commitment at launch", "sourceUrl": "https://www.schmidtsciences.org/new-10-million-ai-safety-science-program-launched-for-foundational-research/" },
      "checkSizeUSD": { "min": 250000, "max": 5000000 },
      "apply": { "mode": "closed", "url": "https://www.schmidtsciences.org/trustworthy-ai/", "notes": "Science of Trustworthy AI RFP closed 2026-05-17; joint $10M agent-ecosystems call with Google DeepMind + ARIA announced — watch for the next window", "lastVerified": "2026-07-02" },
      "confidence": "high", "priorityRank": 3, "url": "https://www.schmidtsciences.org",
      "sources": [{ "url": "https://www.schmidtsciences.org/new-10-million-ai-safety-science-program-launched-for-foundational-research/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 10000000
    },
    {
      "id": "macroscopic-ventures", "kind": "funder", "name": "Macroscopic Ventures",
      "aliases": ["Macroscopic"], "funderKind": "philanthropy",
      "blurb": "Philanthropic fund making large targeted AI-safety bets — $15M to the Cooperative AI Foundation, $3M to CMU's FOCAL lab.",
      "domainTags": ["technical-alignment", "field-building"],
      "annualFieldGivingUSD": 18000000,
      "annualFieldGivingBasis": { "year": 2025, "method": "sum of grants listed on the public grants page", "sourceUrl": "https://macroscopic.org/grants" },
      "apply": { "mode": "invite-only", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 9, "url": "https://macroscopic.org",
      "sources": [{ "url": "https://macroscopic.org/grants", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 18000000
    },
    {
      "id": "foresight-institute", "kind": "funder", "name": "Foresight Institute",
      "funderKind": "philanthropy",
      "blurb": "Runs focused AI-safety grant rounds (~$3M/yr) with small fast checks — plus fellowships and workshops that seed the field.",
      "domainTags": ["technical-alignment", "field-building"],
      "annualFieldGivingUSD": 3000000,
      "annualFieldGivingBasis": { "year": 2025, "method": "AI safety grants program rate per its public grant pages", "sourceUrl": "https://foresight.org/grants/grants-ai-for-science-safety/" },
      "checkSizeUSD": { "min": 10000, "max": 100000 },
      "apply": { "mode": "rounds", "url": "https://foresight.org/grants/", "notes": "periodic rounds — next window on the site", "lastVerified": "2026-07-02" },
      "confidence": "low", "priorityRank": 10, "url": "https://foresight.org",
      "sources": [{ "url": "https://foresight.org/grants/grants-ai-for-science-safety/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 3000000
    },
    {
      "id": "future-of-life-institute", "kind": "funder", "name": "Future of Life Institute",
      "aliases": ["FLI"], "funderKind": "philanthropy",
      "blurb": "Grantmaking plus advocacy on transformative-AI risk; also appears as a payer in SFF rounds.",
      "domainTags": ["technical-alignment", "policy-governance", "field-building"],
      "annualFieldGivingUSD": null,
      "apply": { "mode": "rounds", "url": "https://futureoflife.org/our-work/grantmaking-work/", "notes": "themed RFPs open periodically", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 11, "url": "https://futureoflife.org",
      "sources": [{ "url": "https://futureoflife.org/our-work/grantmaking-work/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "nsf", "kind": "funder", "name": "NSF",
      "aliases": ["National Science Foundation"], "funderKind": "government",
      "blurb": "US federal science funding; the Safe Learning-Enabled Systems program (co-funded with Coefficient Giving) is the flagship AI-safety vehicle.",
      "domainTags": ["technical-alignment", "evals"],
      "annualFieldGivingUSD": null,
      "apply": { "mode": "rounds", "url": "https://new.nsf.gov/funding", "notes": "field-relevant slice to be computed from the Awards API by the pipeline (plan 2)", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 6, "url": "https://www.nsf.gov",
      "sources": [{ "url": "https://resources.research.gov/common/webapi/awardapisearch-v1.htm", "title": "NSF Awards API", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "uk-aisi", "kind": "funder", "name": "UK AISI — Alignment Project",
      "aliases": ["AI Security Institute", "The Alignment Project"], "funderKind": "government",
      "blurb": "UK government-led international coalition funding alignment research — £27M round 1 across 60+ projects, backed by Schmidt Sciences, AWS, Anthropic and others.",
      "domainTags": ["technical-alignment", "evals"],
      "annualFieldGivingUSD": 34290000,
      "annualFieldGivingBasis": { "year": 2025, "method": "Alignment Project round 1 total £27M at 1.27 USD/GBP", "sourceUrl": "https://alignmentproject.aisi.gov.uk/" },
      "apply": { "mode": "rounds", "url": "https://alignmentproject.aisi.gov.uk/", "notes": "round 1 closed; reopens summer 2026", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 5, "url": "https://alignmentproject.aisi.gov.uk",
      "sources": [{ "url": "https://www.gov.uk/government/news/ai-security-institute-launches-international-coalition-to-safeguard-ai-development", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 34290000
    },
    {
      "id": "aria", "kind": "funder", "name": "ARIA — Safeguarded AI",
      "aliases": ["Advanced Research and Invention Agency"], "funderKind": "government",
      "blurb": "UK ARIA's £59M Safeguarded AI programme — mathematically verifiable safety guarantees, £2–3.5M per team calls.",
      "domainTags": ["technical-alignment"],
      "annualFieldGivingUSD": 18700000,
      "annualFieldGivingBasis": { "year": 2025, "method": "£59M programme budget over its ~4-year life at 1.27 USD/GBP (estimate)", "sourceUrl": "https://aria.org.uk/opportunity-spaces/mathematics-for-safe-ai/safeguarded-ai/funding" },
      "checkSizeUSD": { "min": 2500000, "max": 4500000 },
      "apply": { "mode": "rounds", "url": "https://aria.org.uk/funding-opportunities", "notes": "TA-level calls open and close through the programme; check current opportunities", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 7, "url": "https://aria.org.uk",
      "sources": [{ "url": "https://aria.org.uk/opportunity-spaces/mathematics-for-safe-ai/safeguarded-ai/funding", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 18700000
    },
    {
      "id": "openai-programs", "kind": "funder", "name": "OpenAI (grant programs)",
      "aliases": ["OpenAI Cybersecurity Grant Program"], "funderKind": "corporate", "networksId": "openai",
      "blurb": "Cybersecurity Grant Program ($1M grants, 28 projects incl. prompt-injection work) plus $10M in API credits via Trusted Access for Cyber.",
      "domainTags": ["agent-security", "evals"],
      "annualFieldGivingUSD": null, "inKind": true,
      "apply": { "mode": "rolling", "url": "https://openai.com/index/openai-cybersecurity-grant-program/", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 12, "url": "https://openai.com",
      "sources": [{ "url": "https://openai.com/index/openai-cybersecurity-grant-program/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "anthropic-programs", "kind": "funder", "name": "Anthropic (fellows & access)",
      "aliases": ["Anthropic Fellows Program"], "funderKind": "corporate", "networksId": "anthropic",
      "blurb": "Fellows Program cohorts (funding + mentorship, incl. AI security) and researcher compute/API access.",
      "domainTags": ["technical-alignment", "interpretability", "agent-security"],
      "annualFieldGivingUSD": null, "inKind": true,
      "apply": { "mode": "rounds", "url": "https://alignment.anthropic.com/2025/anthropic-fellows-program-2026/", "notes": "cohort applications open per intake", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 13, "url": "https://www.anthropic.com",
      "sources": [{ "url": "https://alignment.anthropic.com/2025/anthropic-fellows-program-2026/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "frontier-model-forum-aisf", "kind": "funder", "name": "AI Safety Fund (Frontier Model Forum)",
      "aliases": ["AISF"], "funderKind": "corporate",
      "blurb": "The frontier labs' pooled $10M+ safety fund — rounds in 2024 and 2025 funding independent safety research.",
      "domainTags": ["evals", "agent-security", "technical-alignment"],
      "annualFieldGivingUSD": 10000000,
      "annualFieldGivingBasis": { "year": 2024, "method": "initial pooled commitment ($10M+) at launch", "sourceUrl": "https://www.frontiermodelforum.org/ai-safety-fund/" },
      "apply": { "mode": "rounds", "url": "https://www.frontiermodelforum.org/ai-safety-fund/", "notes": "rounds announced by the Forum", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 14, "url": "https://www.frontiermodelforum.org",
      "sources": [{ "url": "https://www.frontiermodelforum.org/ai-safety-fund/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 10000000
    },
    {
      "id": "menlo-ventures", "kind": "funder", "name": "Menlo Ventures",
      "funderKind": "vc", "networksId": "menlo-ventures",
      "blurb": "Runs the $100M Anthology Fund with Anthropic — the most explicit VC vehicle for the AI/agent ecosystem, security startups included.",
      "domainTags": ["agent-security"],
      "annualFieldGivingUSD": 100000000,
      "annualFieldGivingBasis": { "year": 2024, "method": "Anthology Fund commitment (fund total, not annual — attribution upper bound)", "sourceUrl": "https://menlovc.com/anthology-fund/" },
      "apply": { "mode": "rolling", "url": "https://menlovc.com", "notes": "pitch anytime; Anthology targets AI-native startups", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 15, "url": "https://menlovc.com",
      "sources": [{ "url": "https://menlovc.com/anthology-fund/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 100000000
    },
    {
      "id": "sequoia-capital", "kind": "funder", "name": "Sequoia Capital",
      "funderKind": "vc", "networksId": "sequoia-capital",
      "blurb": "Generalist tier-1 that has moved decisively into AI security — co-led Irregular's $80M Series B.",
      "domainTags": ["agent-security"],
      "annualFieldGivingUSD": null,
      "apply": { "mode": "rolling", "url": "https://www.sequoiacap.com", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 16, "url": "https://www.sequoiacap.com",
      "sources": [{ "url": "https://thenextweb.com/news/openai-acquires-promptfoo-ai-security-frontier", "title": "AI-security round coverage", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "insight-partners", "kind": "funder", "name": "Insight Partners",
      "funderKind": "vc",
      "blurb": "Growth investor that led Promptfoo's $18.4M Series A — one of the clearest bets on agent-security tooling.",
      "domainTags": ["agent-security"],
      "annualFieldGivingUSD": null,
      "apply": { "mode": "rolling", "url": "https://www.insightpartners.com", "lastVerified": "2026-07-02" },
      "confidence": "medium", "priorityRank": 17, "url": "https://www.insightpartners.com",
      "sources": [{ "url": "https://thenextweb.com/news/openai-acquires-promptfoo-ai-security-frontier", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },

    {
      "id": "far-ai", "kind": "grantee", "name": "FAR.AI", "granteeKind": "research-org",
      "blurb": "Frontier-AI safety research nonprofit with $30M+ multi-funder support.",
      "domainTags": ["technical-alignment", "evals"],
      "confidence": "high", "priorityRank": 30, "url": "https://www.far.ai",
      "sources": [{ "url": "https://www.far.ai/news/30m-multi-funder-support", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 30000000
    },
    {
      "id": "redwood-research", "kind": "grantee", "name": "Redwood Research", "granteeKind": "research-org",
      "blurb": "AI control and alignment research org; long-standing Coefficient Giving grantee.",
      "domainTags": ["technical-alignment"],
      "confidence": "high", "priorityRank": 31, "url": "https://www.redwoodresearch.org",
      "sources": [{ "url": "https://www.redwoodresearch.org", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "metr", "kind": "grantee", "name": "METR", "granteeKind": "research-org", "networksId": "metr",
      "blurb": "Frontier-model autonomy and dangerous-capability evaluations.",
      "domainTags": ["evals"],
      "confidence": "high", "priorityRank": 32, "url": "https://metr.org",
      "sources": [{ "url": "https://metr.org", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "apollo-research", "kind": "grantee", "name": "Apollo Research", "granteeKind": "research-org", "networksId": "apollo-research",
      "blurb": "Deception and scheming evals for frontier models.",
      "domainTags": ["evals"],
      "confidence": "high", "priorityRank": 33, "url": "https://www.apolloresearch.ai",
      "sources": [{ "url": "https://www.apolloresearch.ai", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "eleutherai", "kind": "grantee", "name": "EleutherAI", "granteeKind": "research-org",
      "blurb": "Open-source AI research lab — interpretability, open models, and the infrastructure the open safety ecosystem runs on.",
      "domainTags": ["open-source", "interpretability"],
      "confidence": "high", "priorityRank": 34, "url": "https://www.eleuther.ai",
      "sources": [{ "url": "https://www.eleuther.ai", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "mats", "kind": "grantee", "name": "MATS", "granteeKind": "fieldbuilding",
      "blurb": "ML Alignment Theory Scholars — the field's main research-talent pipeline.",
      "domainTags": ["field-building", "technical-alignment"],
      "confidence": "high", "priorityRank": 35, "url": "https://www.matsprogram.org",
      "sources": [{ "url": "https://www.matsprogram.org", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "cais", "kind": "grantee", "name": "Center for AI Safety", "granteeKind": "research-org",
      "blurb": "Research plus field-building (compute cluster, benchmarks, statements) on societal-scale AI risk.",
      "domainTags": ["technical-alignment", "field-building"],
      "confidence": "high", "priorityRank": 36, "url": "https://www.safe.ai",
      "sources": [{ "url": "https://www.safe.ai", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "timaeus", "kind": "grantee", "name": "Timaeus", "granteeKind": "research-org",
      "blurb": "Developmental interpretability research org.",
      "domainTags": ["interpretability"],
      "confidence": "medium", "priorityRank": 37, "url": "https://timaeus.co",
      "sources": [{ "url": "https://timaeus.co", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "cooperative-ai-foundation", "kind": "grantee", "name": "Cooperative AI Foundation", "granteeKind": "research-org",
      "blurb": "Research charity on cooperative intelligence in AI systems — $15M backed by Macroscopic.",
      "domainTags": ["technical-alignment"],
      "confidence": "high", "priorityRank": 38, "url": "https://www.cooperativeai.com",
      "sources": [{ "url": "https://macroscopic.org/grants", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 15000000
    },
    {
      "id": "cmu-focal", "kind": "grantee", "name": "CMU FOCAL", "granteeKind": "university",
      "blurb": "Carnegie Mellon's Foundations of Cooperative AI Lab.",
      "domainTags": ["technical-alignment"],
      "confidence": "high", "priorityRank": 39, "url": "https://www.cs.cmu.edu/~focal/",
      "sources": [{ "url": "https://macroscopic.org/grants", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 3000000
    },
    {
      "id": "irregular", "kind": "grantee", "name": "Irregular", "granteeKind": "startup", "networksId": "irregular",
      "blurb": "AI security startup — raised an $80M Series B co-led by Sequoia and Redpoint.",
      "domainTags": ["agent-security"],
      "confidence": "high", "priorityRank": 40, "url": "https://www.irregular.com",
      "sources": [{ "url": "https://thenextweb.com/news/openai-acquires-promptfoo-ai-security-frontier", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 80000000
    },
    {
      "id": "promptfoo", "kind": "grantee", "name": "Promptfoo", "granteeKind": "startup", "networksId": "promptfoo",
      "blurb": "LLM red-teaming and eval tooling; $18.4M Series A led by Insight Partners.",
      "domainTags": ["agent-security", "evals"],
      "confidence": "high", "priorityRank": 41, "url": "https://www.promptfoo.dev",
      "sources": [{ "url": "https://thenextweb.com/news/openai-acquires-promptfoo-ai-security-frontier", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 18400000
    },

    {
      "id": "austin-chen", "kind": "person", "name": "Austin Chen", "title": "Co-founder, Manifund",
      "blurb": "Runs the Manifund regranting marketplace.",
      "confidence": "high", "priorityRank": 60, "profileUrl": "https://manifund.org/about",
      "sources": [{ "url": "https://manifund.org/about", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "allison-duettmann", "kind": "person", "name": "Allison Duettmann", "title": "CEO, Foresight Institute",
      "blurb": "Leads Foresight's grants, fellowships, and workshops.",
      "confidence": "high", "priorityRank": 61, "profileUrl": "https://foresight.org/about-us/",
      "sources": [{ "url": "https://foresight.org/about-us/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    },
    {
      "id": "anthony-aguirre", "kind": "person", "name": "Anthony Aguirre", "title": "Executive Director, Future of Life Institute",
      "blurb": "Leads FLI's grantmaking and advocacy.",
      "confidence": "high", "priorityRank": 62, "profileUrl": "https://futureoflife.org/person/anthony-aguirre/",
      "sources": [{ "url": "https://futureoflife.org/person/anthony-aguirre/", "accessed": "2026-07-02" }],
      "lastVerified": "2026-07-02", "fieldDollarsUSD": 0
    }
  ],
  "edges": [
    { "type": "grant", "source": "macroscopic-ventures", "target": "cooperative-ai-foundation", "amountUSD": 15000000, "year": 2024, "sourceUrl": "https://macroscopic.org/grants", "verified": true },
    { "type": "grant", "source": "macroscopic-ventures", "target": "cmu-focal", "amountUSD": 3000000, "year": 2024, "sourceUrl": "https://macroscopic.org/grants", "verified": true },

    { "type": "grant", "source": "coefficient-giving", "target": "far-ai", "amountUSD": null, "verified": true, "sourceUrl": "https://coefficientgiving.org/funds" },
    { "type": "grant", "source": "coefficient-giving", "target": "redwood-research", "amountUSD": null, "verified": true, "sourceUrl": "https://coefficientgiving.org/funds" },
    { "type": "grant", "source": "coefficient-giving", "target": "metr", "amountUSD": null, "verified": true, "sourceUrl": "https://coefficientgiving.org/funds" },
    { "type": "grant", "source": "coefficient-giving", "target": "mats", "amountUSD": null, "verified": true, "sourceUrl": "https://coefficientgiving.org/funds" },
    { "type": "grant", "source": "coefficient-giving", "target": "apollo-research", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "coefficient-giving", "target": "eleutherai", "amountUSD": null, "verified": false },

    { "type": "grant", "source": "survival-and-flourishing-fund", "target": "far-ai", "amountUSD": null, "verified": true, "sourceUrl": "https://survivalandflourishing.fund/recommendations" },
    { "type": "grant", "source": "survival-and-flourishing-fund", "target": "cais", "amountUSD": null, "verified": true, "sourceUrl": "https://survivalandflourishing.fund/recommendations" },
    { "type": "grant", "source": "survival-and-flourishing-fund", "target": "metr", "amountUSD": null, "verified": false },

    { "type": "grant", "source": "ltff", "target": "timaeus", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "ltff", "target": "mats", "amountUSD": null, "verified": false },

    { "type": "grant", "source": "uk-aisi", "target": "far-ai", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "aria", "target": "eleutherai", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "nsf", "target": "cmu-focal", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "schmidt-sciences", "target": "far-ai", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "frontier-model-forum-aisf", "target": "apollo-research", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "openai-programs", "target": "promptfoo", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "anthropic-programs", "target": "timaeus", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "future-of-life-institute", "target": "cais", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "manifund", "target": "timaeus", "amountUSD": null, "verified": false },
    { "type": "grant", "source": "foresight-institute", "target": "timaeus", "amountUSD": null, "verified": false },

    { "type": "investment", "source": "sequoia-capital", "target": "irregular", "amountUSD": 80000000, "year": 2025, "round": "Series B (co-led with Redpoint)", "sourceUrl": "https://thenextweb.com/news/openai-acquires-promptfoo-ai-security-frontier", "verified": true },
    { "type": "investment", "source": "insight-partners", "target": "promptfoo", "amountUSD": 18400000, "year": 2025, "round": "Series A", "sourceUrl": "https://thenextweb.com/news/openai-acquires-promptfoo-ai-security-frontier", "verified": true },
    { "type": "investment", "source": "menlo-ventures", "target": "promptfoo", "amountUSD": null, "verified": false },

    { "type": "affiliation", "source": "austin-chen", "target": "manifund", "role": "Co-founder", "current": true, "sourceUrl": "https://manifund.org/about" },
    { "type": "affiliation", "source": "allison-duettmann", "target": "foresight-institute", "role": "CEO", "current": true, "sourceUrl": "https://foresight.org/about-us/" },
    { "type": "affiliation", "source": "anthony-aguirre", "target": "future-of-life-institute", "role": "Executive Director", "current": true, "sourceUrl": "https://futureoflife.org/person/anthony-aguirre/" }
  ]
}
```

Note on data honesty: `verified: false` edges are *believed* relationships rendered dashed; the plan-2 pipeline confirms-or-drops each one. Do not add dollar figures anywhere in this file that aren't in the table above.

- [ ] **Step 3: Write `src/data/funding.ts`** (complete file):

```ts
/* Single source of truth for the /funding map. funding.json is hand-seeded for
 * now (plan 1) and regenerated by experiments/funding/build_funding.py (plan 2);
 * this module types it, validates it at Astro build time, and re-exports —
 * mirrors src/data/companies.ts.
 *
 * The private overlay (pipeline stage + warm paths) is NOT imported here — it is
 * read from private/funding-overlay.json in FundingGraph.astro, dev-only. */

import rawData from "./funding.json";
import rawCompanies from "./companies.json";
import type { FundingData, FundingNode, FundingEdge, FundingMeta } from "./funding-types";
import { FUNDER_KINDS, DOMAINS, FUNDING_STAGES } from "./funding-types";

export * from "./funding-types";

const data = rawData as unknown as FundingData;
export const fundingNodes: FundingNode[] = data.nodes;
export const fundingEdges: FundingEdge[] = data.edges;
export const fundingMeta: FundingMeta = data.meta;

/* Fail at build time, not in front of a researcher hunting for money. */
const kindIds = new Set(FUNDER_KINDS.map((k) => k.id));
const domainIds = new Set(DOMAINS.map((d) => d.id));
const stageIds = new Set(FUNDING_STAGES.map((s) => s.id));
const applyModes = new Set(["rolling", "rounds", "invite-only", "closed"]);
const granteeKinds = new Set(["research-org", "university", "startup", "fieldbuilding"]);
const companyIds = new Set((rawCompanies as { companies: { id: string }[] }).companies.map((c) => c.id));
void stageIds; // stages validate overlay entries in dev only (FundingGraph.astro)

if (!fundingMeta?.generatedAt) throw new Error("funding.json: meta.generatedAt is required (drives open-now)");

const ids = new Set<string>();
for (const n of fundingNodes) {
  if (ids.has(n.id)) throw new Error(`funding.json: duplicate id "${n.id}"`);
  ids.add(n.id);
  if (!n.sources?.length) throw new Error(`funding.json: "${n.id}" has no sources`);
  if (typeof n.priorityRank !== "number") throw new Error(`funding.json: "${n.id}" missing numeric priorityRank`);
  if (typeof n.fieldDollarsUSD !== "number" || n.fieldDollarsUSD < 0)
    throw new Error(`funding.json: "${n.id}" fieldDollarsUSD must be a number >= 0`);
  for (const t of n.domainTags ?? [])
    if (!domainIds.has(t)) throw new Error(`funding.json: "${n.id}" unknown domain tag "${t}"`);
  if (n.networksId && !companyIds.has(n.networksId))
    throw new Error(`funding.json: "${n.id}" networksId "${n.networksId}" not in companies.json`);
  if (n.kind === "funder") {
    if (!kindIds.has(n.funderKind)) throw new Error(`funding.json: "${n.id}" unknown funderKind "${n.funderKind}"`);
    if (!n.apply || !applyModes.has(n.apply.mode))
      throw new Error(`funding.json: "${n.id}" apply.mode missing/unknown`);
    if (n.apply.mode === "rounds" && n.apply.deadline && n.apply.deadline < fundingMeta.generatedAt)
      throw new Error(`funding.json: "${n.id}" rounds deadline ${n.apply.deadline} is in the past — re-verify or set mode "closed"`);
    if (n.annualFieldGivingUSD != null) {
      if (n.annualFieldGivingUSD < 0) throw new Error(`funding.json: "${n.id}" negative annual giving`);
      if (!n.annualFieldGivingBasis?.sourceUrl?.startsWith("http"))
        throw new Error(`funding.json: "${n.id}" annualFieldGivingUSD has no basis.sourceUrl — every $ needs a source`);
    }
  }
  if (n.kind === "grantee" && !granteeKinds.has(n.granteeKind))
    throw new Error(`funding.json: "${n.id}" unknown granteeKind "${n.granteeKind}"`);
  if (n.kind === "person" && !n.title) throw new Error(`funding.json: person "${n.id}" missing public title`);
}

const kindOf = (id: string) => fundingNodes.find((n) => n.id === id)?.kind;
const personHasAffil = new Set<string>();
for (const e of fundingEdges) {
  if (!ids.has(e.source)) throw new Error(`funding.json: edge from unknown node "${e.source}"`);
  if (!ids.has(e.target)) throw new Error(`funding.json: edge to unknown node "${e.target}"`);
  if (e.source === e.target) throw new Error(`funding.json: self-loop on "${e.source}"`);
  if (e.type === "grant" || e.type === "investment") {
    if (kindOf(e.source) !== "funder") throw new Error(`funding.json: ${e.type} edge source "${e.source}" is not a funder`);
    if (kindOf(e.target) !== "grantee") throw new Error(`funding.json: ${e.type} edge target "${e.target}" is not a grantee`);
    if (e.amountUSD != null && !e.sourceUrl?.startsWith("http"))
      throw new Error(`funding.json: ${e.source}→${e.target} has a $ amount but no sourceUrl — every $ needs a source`);
    if (e.type === "grant" && e.regrantOf && !ids.has(e.regrantOf))
      throw new Error(`funding.json: ${e.source}→${e.target} regrantOf "${e.regrantOf}" unknown`);
  }
  if (e.type === "affiliation") {
    if (kindOf(e.source) !== "person") throw new Error(`funding.json: affiliation source "${e.source}" is not a person`);
    if (kindOf(e.target) !== "funder") throw new Error(`funding.json: affiliation target "${e.target}" is not a funder`);
    personHasAffil.add(e.source);
  }
}
for (const n of fundingNodes)
  if (n.kind === "person" && !personHasAffil.has(n.id))
    throw new Error(`funding.json: person "${n.id}" has no affiliation edge`);
```

- [ ] **Step 4: Prove the validator bites, then that the dataset passes**

1. Temporarily change one grant's `amountUSD` to `123` (leaving `sourceUrl` absent) → run `npm run build` → Expected: build FAILS with `has a $ amount but no sourceUrl`.
2. Revert the sabotage.
3. Run `npm run build` → Expected: PASS (funding.ts imports nothing into a page yet — add `import "../data/funding";` temporarily to `src/pages/index.astro` frontmatter if the module isn't reached, verify, then REMOVE that import; Task 3's page makes it permanent).
4. Run `npm test` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data/funding.json src/data/funding.ts
git commit -m "funding: hand-seeded starter dataset + build-time validator"
```

---

### Task 3: Page shells + nav

**Files:**
- Create: `src/pages/funding.astro`
- Create: `src/components/FundingGraph.astro`
- Modify: `src/layouts/Base.astro` (lines 19, 34, 38-41, 47 — see Step 3)

**Interfaces:**
- Consumes: `funding.json` via the script island; `FundingOverlayEntry` shape from Task 1.
- Produces: DOM contract for Tasks 4–7 — element ids `fund-graph, fund-tip, fund-detail, fund-search, fund-kinds, fund-domains, fund-stages, fund-lenses, fund-lens-open, fund-download, fund-view-map, fund-view-dir, fund-directory, fund-legend, fund-usd-range, fund-usd-n, fund-pathctl, fund-path-detail, fund-overlay`; calls `initFundingGraph(entries)` from `../scripts/funding-graph`.

- [ ] **Step 1: Write `src/pages/funding.astro`** (complete file, clone of `networks.astro`):

```astro
---
import Base from "../layouts/Base.astro";
import FundingGraph from "../components/FundingGraph.astro";
---

<Base
  title="Funding — Agents of Chaos"
  description="Find your funder: a dollar-weighted map of who pays for AI safety and agent security — philanthropy, government, venture, and corporate programs."
>
  <FundingGraph />
</Base>
```

- [ ] **Step 2: Write `src/components/FundingGraph.astro`**

Frontmatter + markup + script island (complete below). The `<style is:global>` block: copy `NetworkGraph.astro` lines 103–343 verbatim, then apply these mechanical renames and additions:

Renames (global within the copied block): `.net-figure→.fund-figure`, `.net-controls→.fund-controls`, `#net-search→#fund-search`, `.net-chips→.fund-chips`, `.net-chip→.fund-chip` (all compounds too: `-toggle`, `-warm`, `-lens`, `-priv`), `.net-viewtoggle→.fund-viewtoggle`, `.net-vtab→.fund-vtab`, `.net-action→.fund-action`, `#net-graph→#fund-graph`, `.net-hide→.fund-hide`, `.net-label→.fund-label`, `#net-detail→#fund-detail`, `.net-directory→.fund-directory`, `#net-legend→#fund-legend`, `.net-leg-→.fund-leg-`, `#net-tip→#fund-tip`, `#net-directory→#fund-directory`. Prefix every `.dir-*` selector with `.fund-directory ` (descendant) so the two pages' directory styles can't collide. Delete the `.net-priority/.net-prio-*` rules and the `#net-lens-comp/#net-lens-cust` rules (replaced below). Keep the `#net-detail .d-*` rules (renamed to `#fund-detail .d-*`) — the dossier reuses those class names. Comment header should say "/funding map chrome" and reference `FUNDER_KINDS / FUNDING_STAGES in src/data/funding-types.ts`.

Then APPEND these new rules inside the same `<style is:global>`:

```css
/* $ floor bar — "money floor": drag right to keep only funders giving ≥ $X/yr */
.fund-usdbar {
  width: 100%; display: flex; align-items: center; gap: 0.6rem;
  padding: 0 0 0.5rem; margin-bottom: 0.15rem; border-bottom: 1px solid var(--rule-soft);
}
.fund-usd-label {
  font-variant: small-caps; letter-spacing: 0.06em; font-size: 0.8rem;
  color: var(--accent); font-weight: 600; flex: none;
}
.fund-usd-range { flex: 1 1 auto; max-width: 440px; accent-color: var(--accent); cursor: pointer; }
.fund-usd-readout { font-size: 0.74rem; color: var(--muted); flex: none; }
.fund-usd-readout b { color: var(--fg); font-variant-numeric: tabular-nums; }

/* open-now lens chip */
#fund-lens-open.on { opacity: 1; color: #4f6f4e; border-color: #9fbf9e; background: #eef3ee; }

/* path finder — two type-ahead slots (ported from the coauthorship pair finder) */
#fund-pathctl { display: inline-flex; align-items: center; gap: 6px; }
.pp-label { font-variant: small-caps; letter-spacing: 0.06em; font-size: 0.78rem; color: var(--muted); }
.pp-slot {
  position: relative; min-width: 130px; border: 1px solid var(--rule-soft); border-radius: 4px;
  background: #fff; padding: 3px 8px; font-size: 0.78rem; cursor: text; line-height: 1.35;
}
.pp-slot.armed { border-color: var(--accent); }
.pp-slot .pp-input {
  font-family: var(--font); font-size: 0.78rem; border: none; outline: none;
  width: 100%; background: transparent; color: var(--fg);
}
.pp-slot .pp-pick { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.pp-slot .pp-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.pp-menu {
  position: absolute; top: calc(100% + 2px); left: -1px; z-index: 8; min-width: 210px;
  background: var(--bg); border: 1px solid var(--rule-soft); border-radius: 3px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08); max-height: 240px; overflow-y: auto;
}
.pp-menu button {
  display: flex; align-items: center; gap: 6px; width: 100%; text-align: left;
  background: none; border: none; cursor: pointer; padding: 4px 9px;
  font-family: var(--font); font-size: 0.76rem; color: var(--fg);
}
.pp-menu button:hover { background: var(--accent-soft); }
.pp-arrow { color: var(--muted-2); }
.pp-clear { background: none; border: none; color: var(--muted-2); cursor: pointer; font-size: 0.8rem; }
.pp-clear:hover { color: var(--accent); }
/* path breadcrumb card (renders above the dossier, same visual family) */
#fund-path-detail:empty { display: none; }
#fund-path-detail {
  position: absolute; top: 12px; left: 12px; z-index: 5; max-width: 320px;
  background: var(--bg); border: 1px solid var(--rule-soft); border-radius: 3px;
  padding: 9px 12px; font-size: 0.76rem; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}
#fund-path-detail .pd-title { font-weight: 700; margin-bottom: 3px; }
#fund-path-detail .pd-chain { line-height: 1.6; }
#fund-path-detail .pd-end { font-weight: 600; }
#fund-path-detail .pd-arrow { color: var(--accent); padding: 0 3px; }
#fund-path-detail .pd-none { color: var(--muted); font-style: italic; }

/* legend: dotted ring = no public $; green ring = open now */
.fund-leg-dotted { width: 10px; height: 10px; border-radius: 50%; border: 1.6px dotted var(--muted-2); display: inline-block; }
/* directory extras */
.fund-directory .dir-usd { flex: none; font-size: 0.65rem; color: var(--muted-2); font-variant-numeric: tabular-nums; }
.fund-directory .dir-pill-open { color: #3f5f3e; background: #dfe9df; }
@media (max-width: 640px) {
  #fund-path-detail { position: static; max-width: none; margin-top: 0.6rem; box-shadow: none; }
}
```

Frontmatter + markup + island (complete — this replaces NetworkGraph's frontmatter/markup 1:1):

```astro
---
// Markup shell for the /funding landscape map. All behavior lives in
// ../scripts/funding-graph.ts (default processed <script> so bundled d3 + data
// imports work).
//
// The PRIVATE overlay (OUR pipeline stage + warm paths per funder) is read here
// from private/funding-overlay.json — ONLY under `import.meta.env.DEV`. A prod
// build dead-eliminates the read; the file is gitignored (/private/). Same
// mechanism as NetworkGraph.astro — see the privacy invariant in
// docs/superpowers/specs/2026-07-02-funding-map-design.md.

let overlayEntries: unknown[] = [];
if (import.meta.env.DEV) {
  try {
    const { readFileSync, existsSync } = await import("node:fs");
    if (existsSync("private/funding-overlay.json")) {
      const raw = JSON.parse(readFileSync("private/funding-overlay.json", "utf8"));
      overlayEntries = Array.isArray(raw) ? raw : (raw.entries ?? []);
    }
  } catch {
    /* overlay is optional — absence just means the public view */
  }
}
const isPrivate = overlayEntries.length > 0;
// guard against </script> breaking out of the JSON island
const overlayJson = JSON.stringify(overlayEntries).replace(/</g, "\\u003c");
---

<figure class="fund-figure">
  <div class="fund-controls">
    <div class="fund-usdbar" role="group" aria-label="dollar floor">
      <span class="fund-usd-label">money floor</span>
      <input
        id="fund-usd-range"
        class="fund-usd-range"
        type="range"
        min="0"
        max="100"
        value="0"
        aria-label="hide funders giving less than this per year"
      />
      <span class="fund-usd-readout" aria-live="polite">funders giving ≥ <b id="fund-usd-n">any amount</b> per year</span>
    </div>
    <div class="fund-viewtoggle" role="group" aria-label="view">
      <button id="fund-view-map" class="fund-vtab on" type="button" aria-pressed="true">map</button>
      <button id="fund-view-dir" class="fund-vtab" type="button" aria-pressed="false">directory</button>
    </div>
    <input
      id="fund-search"
      type="search"
      placeholder="search funders, grantees, people…"
      autocomplete="off"
      spellcheck="false"
    />
    <div id="fund-pathctl" role="group" aria-label="path finder"></div>
    <div id="fund-kinds" class="fund-chips" aria-label="filter by funder kind"></div>
    <div id="fund-domains" class="fund-chips" aria-label="filter by domain funded"></div>
    {isPrivate && <div id="fund-stages" class="fund-chips fund-chips-priv" aria-label="filter by pipeline stage"></div>}
    <div id="fund-lenses" class="fund-chips" aria-label="lenses">
      <button id="fund-lens-open" class="fund-chip fund-chip-lens" type="button" aria-pressed="false">open now</button>
    </div>
    <button
      id="fund-download"
      class="fund-chip fund-action"
      type="button"
      aria-label="download the current view as a PNG image"
      title="download the current view as a PNG image"
    >
      <span class="ic" aria-hidden="true">↓</span> download
    </button>
  </div>

  <div class="fund-stage">
    <div id="fund-graph">
      <noscript><p class="graph-noscript">The map needs JavaScript — the landscape is interactive.</p></noscript>
    </div>
    <div id="fund-directory" class="fund-directory" hidden></div>
    <div id="fund-path-detail"></div>
    <div id="fund-detail"></div>
  </div>

  <figcaption id="fund-legend"></figcaption>
</figure>
<div id="fund-tip" class="gtooltip" aria-hidden="true"></div>

<script type="application/json" id="fund-overlay" is:inline set:html={overlayJson}></script>
<script>
  import { initFundingGraph } from "../scripts/funding-graph";
  let entries = [];
  try {
    const el = document.getElementById("fund-overlay");
    entries = el ? JSON.parse(el.textContent || "[]") : [];
  } catch {
    entries = [];
  }
  initFundingGraph(entries);
</script>
```

For THIS task only (funding-graph.ts arrives in Task 4), create `src/scripts/funding-graph.ts` as the minimal real entry point so the build passes and the data module is validated end-to-end:

```ts
import { fundingNodes, fundingEdges } from "../data/funding";
import type { FundingOverlayEntry } from "../data/funding-types";

export function initFundingGraph(_overlayEntries: FundingOverlayEntry[] = []): void {
  // Task 4 replaces this with the full map. Touch the data so the validator runs.
  console.info(`/funding: ${fundingNodes.length} nodes, ${fundingEdges.length} edges`);
}
```

- [ ] **Step 3: Edit `src/layouts/Base.astro`**

Replace line 19:
```ts
const isNetworks = path === "/networks" || path === "/networks/";
```
with:
```ts
// full-page maps: fill the viewport below the nav, no footer
const isFullPage = ["/networks", "/funding"].some((p) => path === p || path === p + "/");
```
Update the two usages: `<body class={isNetworks ? "full-page" : undefined}>` → `isFullPage`, and `{!isNetworks && <Footer />}` → `{!isFullPage && <Footer />}`. Update the comment above (line 18) to say "/networks and /funding are full-page maps". Add the nav link after the networks link (line 40):
```astro
<a href="/funding" aria-current={isCurrent("/funding") ? "page" : undefined}>funding</a>
```

- [ ] **Step 4: Verify**

Run: `npm run build` — Expected: PASS (funding page emitted at `dist/funding/index.html`).
Run: `npm run dev` and open `http://localhost:4321/funding` — Expected: masthead shows a `funding` entry; the page shows the money-floor bar, view toggle, search, empty chip rows, lens + download buttons, and an empty stage; console logs `/funding: 32 nodes, 29 edges`. No footer.
Run: `npm test` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pages/funding.astro src/components/FundingGraph.astro src/scripts/funding-graph.ts src/layouts/Base.astro
git commit -m "funding: page shell, controls markup, nav entry (dev-only overlay island)"
```

---

### Task 4: Graph core — territories, dollar-sized nodes, dossier, deep links

**Files:**
- Modify: `src/scripts/funding-graph.ts` (replace the Task-3 stub with the full module below)

**Interfaces:**
- Consumes: DOM ids from Task 3; everything from Tasks 1–2.
- Produces (later tasks extend, never restructure): module-level state and functions `applyFilter()`, `applyHighlight()`, `select(sel)`, `renderDetail()`, `fitToNodes(ids?, animate)`, `shown(d)`, `visibleSet`, `filters`, `route` + `routeLinks` (path finder state, null/empty until Task 6), `lensOpen` + `openSet` (Task 7 flips), `TODAY`, `rScale`, `wScale`, `nodes`, `links`, `byId`, `adj`, `view`, `setView(v)`, `renderDir()` (stub until Task 5).

**Design notes (why, so the implementer doesn't "fix" them):**
- `FLink = { e: FundingEdge; source: FNode; target: FNode }` — the edge union keeps its discriminant on `l.e`, avoiding distributive-Omit gymnastics; d3's forceLink only needs `source`/`target`.
- Only funders get territory pull (strength 0.25); grantees/people get a weak center pull (0.03) — grantees must settle BETWEEN their funders via link forces, that's the whole point of the layout.
- `TODAY = fundingMeta.generatedAt` — open-now is snapshot-dated (Global Constraints).
- `applyHighlight` already contains the route/lens branches reading `route`/`lensOpen`; Tasks 6–7 only set state and call it.

- [ ] **Step 1: Replace `src/scripts/funding-graph.ts`** (complete file):

```ts
/* Funding-landscape map for /funding. Clone-and-adapt of networks-graph.ts:
 * force layout with funder-kind "territories", zoom/pan, hover spotlight,
 * click-to-pin dossier, drag, deep links — plus what a MONEY map needs:
 * sqrt-dollar node/edge sizing (area ∝ field-relevant $), an open-now lens,
 * a public BFS path finder, and the dev-only overlay (stage + warm paths).
 *
 * Color = funder kind (grantees gray-tan, people small outlined dots).
 * Size = sqrt(field dollars). Red stays reserved for highlight/path/funded. */

import * as d3 from "d3";
import {
  fundingNodes, fundingEdges, fundingMeta,
  FUNDER_KINDS, FUNDING_STAGES, DOMAINS,
  GRANTEE_COLOR, PERSON_COLOR,
  funderColor, funderLabel, fundingStageColor, fundingStageLabel, domainLabel, nodeColor,
  escapeHtml as esc,
} from "../data/funding";
import type {
  FundingNode, FunderNode, FundingEdge, FunderKind, FundingStage, FundingOverlayEntry,
} from "../data/funding-types";
import {
  PERSON_R, UNKNOWN_R,
  makeSqrtScale, nodeDollars, radiusFor, edgeWidthFor,
  buildAdjacency, shortestPath, isOpenNow, computeVisible, sliderToUsd, formatUsd, topGrants,
} from "./funding-core.js";

type FNode = FundingNode & d3.SimulationNodeDatum;
type FLink = { e: FundingEdge; source: FNode; target: FNode };
type Sel = { id: string } | null;

const HALO = "#fffff8"; // --bg
const OPEN_RING = "#4f7a4e"; // open-now lens (green, same family as /networks customer ring)
const ADVANCED = new Set<FundingStage>(FUNDING_STAGES.filter((s) => s.id !== "cold").map((s) => s.id));

export function initFundingGraph(overlayEntries: FundingOverlayEntry[] = []): void {
  const graphEl = document.getElementById("fund-graph")!;
  const tooltip = document.getElementById("fund-tip")!;
  const detail = document.getElementById("fund-detail")!;
  const searchEl = document.getElementById("fund-search") as HTMLInputElement | null;
  const coarse = matchMedia("(pointer: coarse)").matches;
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TODAY = fundingMeta.generatedAt; // snapshot clock — never the wall clock

  let view: "map" | "directory" = "map";
  let lensOpen = false; // Task 7 wires the chip; highlight logic below already honors it
  let route: { ids: string[]; len: number } | null = null; // Task 6 sets; highlight honors
  let routeLinks = new Set<FLink>();
  const inRoute = (id: string) => !!route && route.ids.includes(id);

  const overlay = new Map(overlayEntries.map((e) => [e.id, e]));
  const isPrivate = overlay.size > 0;
  const stageOf = (id: string): FundingStage | undefined => overlay.get(id)?.stage;
  const warmOf = (id: string): string | undefined => overlay.get(id)?.warm_path;
  const ringColor = (id: string): string | undefined => {
    const st = stageOf(id);
    return isPrivate && st && ADVANCED.has(st) ? fundingStageColor(st) : undefined;
  };

  /* ---------- data: one pass, then static ---------- */
  const nodes: FNode[] = fundingNodes.map((n) => ({ ...n }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links: FLink[] = fundingEdges.flatMap((e) => {
    const source = byId.get(e.source), target = byId.get(e.target);
    return source && target ? [{ e, source, target }] : [];
  });
  const adj = buildAdjacency(fundingNodes, fundingEdges);

  /* dollar → pixel scales, domains from the data itself */
  const nodeDollarVals = nodes.map(nodeDollars).filter((d): d is number => d != null);
  const rScale = makeSqrtScale(
    [Math.min(...nodeDollarVals), Math.max(...nodeDollarVals)], [5, 26]);
  const flowVals = links
    .map((l) => (l.e.type === "affiliation" ? null : l.e.amountUSD))
    .filter((d): d is number => d != null);
  const wScale = flowVals.length
    ? makeSqrtScale([Math.min(...flowVals), Math.max(...flowVals)], [0.7, 6])
    : () => 0.9;
  const r = (d: FNode) => radiusFor(d, rScale);
  const openSet = new Set(nodes.filter((n) => isOpenNow(n, TODAY)).map((n) => n.id));
  const maxAnnual = Math.max(0, ...nodes.map((n) => (n.kind === "funder" ? n.annualFieldGivingUSD ?? 0 : 0)));

  const BASE_LABEL = 11;
  let inited = false;
  const confOpacity = (d: FNode) => (d.confidence === "low" ? 0.62 : d.confidence === "medium" ? 0.82 : 1);

  /* ---------- svg scaffold ---------- */
  const W = graphEl.clientWidth || 1100, H = graphEl.clientHeight || 700;
  const svg = d3.select(graphEl).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const root = svg.append("g");
  const linkG = root.append("g");
  const nodeG = root.append("g");
  svg.on("click", () => select(null));

  /* funder-kind "territories": 2×2 grid of centroids; ONLY funders are pulled
   * to them — grantees settle between their funders via the link force, and
   * people hug their funder via short strong affiliation links. */
  const present = FUNDER_KINDS.filter((k) => nodes.some((n) => n.kind === "funder" && n.funderKind === k.id));
  const cols = Math.min(2, Math.max(1, present.length));
  const rows = Math.max(1, Math.ceil(present.length / cols));
  const mx = W * 0.18, my = H * 0.2;
  const centroid = new Map<FunderKind, { x: number; y: number }>();
  present.forEach((k, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    centroid.set(k.id, {
      x: mx + (cols === 1 ? 0.5 : col / (cols - 1)) * (W - 2 * mx),
      y: my + (rows === 1 ? 0.5 : row / (rows - 1)) * (H - 2 * my),
    });
  });
  const kindOf = (d: FNode): FunderKind | null => (d.kind === "funder" ? d.funderKind : null);
  // deterministic seeding: funders spiral around their territory; grantees/people
  // start at their first neighbor's territory (or center) so the settle is short
  const perK = new Map<string, number>();
  const seedAt = (d: FNode): { x: number; y: number } => {
    const k = kindOf(d);
    if (k) return centroid.get(k)!;
    for (const nb of adj.get(d.id) ?? []) {
      const nbk = kindOf(byId.get(nb)!);
      if (nbk) return centroid.get(nbk)!;
    }
    return { x: W / 2, y: H / 2 };
  };
  nodes.forEach((n) => {
    const c = seedAt(n);
    const key = kindOf(n) ?? "float";
    const i = perK.get(key) ?? 0; perK.set(key, i + 1);
    const a = i * 2.399963; // golden-angle spiral — stable, no Math.random
    n.x = n.x ?? c.x + Math.cos(a) * (12 + 6 * i ** 0.5);
    n.y = n.y ?? c.y + Math.sin(a) * (12 + 6 * i ** 0.5);
  });

  const linkDist = (l: FLink) => (l.e.type === "affiliation" ? 26 : 58);
  const linkStrength = (l: FLink) => (l.e.type === "affiliation" ? 0.7 : l.e.type === "grant" ? 0.15 : 0.12);
  const sim = d3.forceSimulation<FNode>(nodes)
    .force("charge", d3.forceManyBody<FNode>().strength(-150).distanceMax(420))
    .force("x", d3.forceX<FNode>((d) => (kindOf(d) ? centroid.get(kindOf(d)!)!.x : W / 2))
      .strength((d) => (kindOf(d) ? 0.25 : 0.03)))
    .force("y", d3.forceY<FNode>((d) => (kindOf(d) ? centroid.get(kindOf(d)!)!.y : H / 2))
      .strength((d) => (kindOf(d) ? 0.25 : 0.03)))
    .force("link", d3.forceLink<FNode, FLink>(links).distance(linkDist).strength(linkStrength))
    .force("collide", d3.forceCollide<FNode>().radius((d) => r(d) + 4).strength(0.9))
    .on("tick", tick);

  /* ---------- edges: money flows ---------- */
  const edgeStroke = (l: FLink) =>
    l.e.type === "grant" ? "#9a958c" : l.e.type === "investment" ? "#bcc3b0" : "#c9c2b4";
  const edgeWidth = (l: FLink) => edgeWidthFor(l.e, wScale);
  const edgeDash = (l: FLink) => (l.e.type !== "affiliation" && !l.e.verified ? "2 3" : null);
  const edgeDirected = (l: FLink) => l.e.type === "grant" || l.e.type === "investment";

  const linkSel = linkG.selectAll<SVGLineElement, FLink>("line.edge").data(links).join("line")
    .attr("class", "edge").attr("stroke", edgeStroke).attr("stroke-width", edgeWidth)
    .attr("stroke-dasharray", edgeDash).attr("stroke-opacity", 0.5)
    .attr("marker-end", (l) => (edgeDirected(l) ? "url(#fund-arrow)" : null));
  const hitSel = linkG.selectAll<SVGLineElement, FLink>("line.hit").data(links).join("line")
    .attr("class", "hit").attr("stroke", "transparent").attr("stroke-width", 12).style("cursor", "pointer");

  svg.append("defs").append("marker").attr("id", "fund-arrow")
    .attr("viewBox", "0 -5 10 10").attr("refX", 18).attr("refY", 0)
    .attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
    .append("path").attr("d", "M0,-4L9,0L0,4").attr("fill", "#9a958c");

  /* ---------- nodes ---------- */
  const unknownDollar = (d: FNode) => d.kind !== "person" && nodeDollars(d) == null;
  const nodeSel = nodeG.selectAll<SVGGElement, FNode>("g.fnode").data(nodes).join("g")
    .attr("class", "fnode").style("cursor", "pointer");
  nodeSel.append("circle")
    .attr("r", (d) => r(d))
    .attr("fill", (d) => (d.kind === "person" ? HALO : nodeColor(d)))
    .attr("fill-opacity", (d) => (d.kind === "person" ? 1 : confOpacity(d)))
    .attr("stroke", (d) =>
      d.kind === "person" ? PERSON_COLOR : ringColor(d.id) ?? (unknownDollar(d) ? "#8a8475" : HALO))
    .attr("stroke-width", (d) => (d.kind === "person" ? 1.6 : ringColor(d.id) ? 2.5 : 1.4))
    .attr("stroke-dasharray", (d) => (unknownDollar(d) && !ringColor(d.id) ? "2 2" : null));
  nodeSel.append("text").attr("class", "fund-label").attr("y", (d) => -r(d) - 4)
    .text((d) => d.name);
  const labelSel = nodeSel.select<SVGTextElement>("text.fund-label");
  const labelW = new Map<string, number>();
  labelSel.each(function (d) { labelW.set(d.id, (this as SVGTextElement).getBBox().width); });
  const labelOrder = [...nodes].sort(
    (a, b) => (nodeDollars(b) ?? 0) - (nodeDollars(a) ?? 0) ||
      (a.kind === "person" ? 1 : 0) - (b.kind === "person" ? 1 : 0) ||
      (a.id < b.id ? -1 : 1));
  nodeSel.on("click", (ev: MouseEvent, d) => { ev.stopPropagation(); onNodeClick(d); });

  // Task 6 routes clicks into the path finder when a slot is armed; select() otherwise.
  function onNodeClick(d: FNode): void {
    select({ id: d.id });
  }

  if (!coarse) {
    nodeSel.on("mousemove", nodeTip).on("mouseleave", leaveNode);
    hitSel.on("mousemove", edgeTip).on("mouseleave", leaveEdge);
    nodeSel.call(d3.drag<SVGGElement, FNode>()
      .on("start", (_ev, d) => { sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (_ev, d) => { sim.alphaTarget(0); d.fx = d.fy = null; }));
  }

  function tick() {
    for (const sel of [linkSel, hitSel])
      sel.attr("x1", (l) => l.source.x!).attr("y1", (l) => l.source.y!)
        .attr("x2", (l) => l.target.x!).attr("y2", (l) => l.target.y!);
    nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
  }

  /* ---------- zoom / pan ---------- */
  const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 6])
    .on("zoom", (ev) => {
      root.attr("transform", ev.transform.toString());
      if (inited) scheduleLabels();
    });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("dblclick", () => fitToNodes(null, true));

  /** Frame the whole graph (ids=null) or a subset (Task 6: fit-to-route). */
  function fitToNodes(ids: string[] | null, animate: boolean) {
    let x0: number, y0: number, x1: number, y1: number;
    if (ids?.length) {
      const pts = ids.map((id) => byId.get(id)!).filter((d) => d.x != null);
      if (!pts.length) return;
      x0 = Math.min(...pts.map((d) => d.x! - r(d)));
      x1 = Math.max(...pts.map((d) => d.x! + r(d)));
      y0 = Math.min(...pts.map((d) => d.y! - r(d)));
      y1 = Math.max(...pts.map((d) => d.y! + r(d)));
    } else {
      const b = (root.node() as SVGGElement).getBBox();
      if (!b.width || !b.height) return;
      x0 = b.x; y0 = b.y; x1 = b.x + b.width; y1 = b.y + b.height;
    }
    const pad = 40;
    const k = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0), 1.6);
    const tx = (W - (x1 - x0) * k) / 2 - x0 * k, ty = (H - (y1 - y0) * k) / 2 - y0 * k;
    const t = d3.zoomIdentity.translate(tx, ty).scale(k);
    if (animate) svg.transition().duration(450).call(zoom.transform, t);
    else svg.call(zoom.transform, t);
  }

  sim.stop();
  for (let i = 0; i < 220; i++) sim.tick();
  tick();
  fitToNodes(null, false);
  if (!calm) { sim.alpha(0.25).restart(); sim.on("end", () => fitToNodes(null, true)); }

  /* ---------- visibility (Task 5 wires controls into `filters`) ---------- */
  const filters = {
    kinds: new Set<FunderKind>(FUNDER_KINDS.map((k) => k.id)),
    domains: new Set<string>(),
    minUsd: 0,
    query: "",
  };
  let visibleSet = new Set<string>(nodes.map((n) => n.id));
  const shown = (d: FNode) => visibleSet.has(d.id) || inRoute(d.id); // active route is always shown

  function applyFilter() {
    filters.query = searchEl?.value ?? "";
    visibleSet = computeVisible(fundingNodes, fundingEdges, filters);
    if (isPrivate) { // stage chips (dev): Task 5 fills activeStages
      for (const id of [...visibleSet])
        if (!activeStages.has(stageOf(id) ?? "cold")) visibleSet.delete(id);
    }
    if (selected && !shown(byId.get(selected.id)!)) select(null);
    else if (selected) renderDetail();
    nodeSel.style("display", (d) => (shown(d) ? null : "none"));
    const edgeShown = (l: FLink) =>
      (shown(l.source) && shown(l.target)) || routeLinks.has(l) ? null : "none";
    linkSel.style("display", edgeShown);
    hitSel.style("display", edgeShown);
    applyHighlight();
    if (view === "directory") renderDir();
  }
  const activeStages = new Set<FundingStage>(FUNDING_STAGES.map((s) => s.id));

  /* Directory + view toggle land in Task 5; declared here so applyFilter compiles. */
  function renderDir(): void {}
  function setView(_v: "map" | "directory"): void {}
  void setView;

  /* ---------- highlight (route- and lens-aware from day one) ---------- */
  let selected: Sel = null, hover: Sel = null;
  function neigh(sel: Sel) {
    if (!sel) return null;
    const set = new Set<string>([sel.id]);
    for (const id of adj.get(sel.id) ?? []) set.add(id);
    return set;
  }
  function applyHighlight() {
    if (route) { // active path: route members pop, everything else recedes
      nodeSel.attr("opacity", (d) => (inRoute(d.id) ? 1 : shown(d) ? 0.06 : 0));
      nodeSel.select("circle")
        .attr("stroke", (d) => (inRoute(d.id) ? "#a00" : strokeFor(d)))
        .attr("stroke-width", (d) => (inRoute(d.id) ? 2.5 : strokeWidthFor(d)));
      linkSel
        .attr("stroke", (l) => (routeLinks.has(l) ? "#a00" : edgeStroke(l)))
        .attr("stroke-opacity", (l) => (routeLinks.has(l) ? 0.95 : shownEdge(l) ? 0.04 : 0))
        .attr("stroke-width", (l) => (routeLinks.has(l) ? edgeWidth(l) + 1 : edgeWidth(l)));
      refreshLabels();
      return;
    }
    nodeSel.select("circle")
      .attr("stroke", strokeFor).attr("stroke-width", strokeWidthFor)
      .attr("stroke-dasharray", (d) => (unknownDollar(d) && !ringColor(d.id) && !(lensOpen && openSet.has(d.id)) ? "2 2" : null));
    linkSel.attr("stroke", edgeStroke).attr("stroke-width", edgeWidth);
    const nb = neigh(hover ?? selected);
    const dimFor = (d: FNode) => // open-now lens dims what isn't actionable
      lensOpen && !openSet.has(d.id) ? (d.kind === "funder" ? 0.15 : 0.25) : 1;
    nodeSel.attr("opacity", (d) => (!shown(d) ? 0 : !nb ? dimFor(d) : nb.has(d.id) ? 1 : 0.12));
    linkSel.attr("stroke-opacity", (l) =>
      !shownEdge(l) ? 0
        : !nb ? (lensOpen ? 0.25 : 0.5) : nb.has(l.source.id) && nb.has(l.target.id) ? 0.9 : 0.04);
    refreshLabels();
  }
  const shownEdge = (l: FLink) => shown(l.source) && shown(l.target);
  const strokeFor = (d: FNode) =>
    d.kind === "person" ? PERSON_COLOR
      : lensOpen && openSet.has(d.id) ? OPEN_RING
        : ringColor(d.id) ?? (unknownDollar(d) ? "#8a8475" : HALO);
  const strokeWidthFor = (d: FNode) =>
    d.kind === "person" ? 1.6 : (lensOpen && openSet.has(d.id)) || ringColor(d.id) ? 2.5 : 1.4;

  let rafPending = false;
  function scheduleLabels() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => { rafPending = false; refreshLabels(); });
  }
  function refreshLabels() {
    const t = d3.zoomTransform(svg.node()!);
    labelSel.style("font-size", BASE_LABEL / t.k + "px");
    const nb = route ? new Set(route.ids) : neigh(hover ?? selected);
    const order = nb ? labelOrder.filter((d) => nb.has(d.id)) : labelOrder;
    const placed: number[][] = [];
    const show = new Set<string>();
    const PAD = 4;
    for (const d of order) {
      if (!shown(d)) continue;
      const w = labelW.get(d.id) ?? 40;
      const sx = d.x! * t.k + t.x;
      const baseY = (d.y! - r(d) - 4) * t.k + t.y;
      const box = [sx - w / 2 - PAD, baseY - BASE_LABEL - PAD, sx + w / 2 + PAD, baseY + PAD];
      const overlaps = placed.some((p) => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1]);
      if (overlaps && !(nb && nb.has(d.id))) continue;
      placed.push(box); show.add(d.id);
    }
    labelSel.style("display", (d) => (show.has(d.id) ? null : "none"));
  }

  /* ---------- edge hover ---------- */
  let hoverEdge: FLink | null = null;
  function emphasizeEdge(l: FLink) {
    const a = l.source.id, b = l.target.id;
    nodeSel.attr("opacity", (d) => (!shown(d) ? 0 : d.id === a || d.id === b ? 1 : 0.12));
    linkSel.attr("stroke-opacity", (x) => (x === l ? 0.95 : !shownEdge(x) ? 0 : 0.05));
    labelSel.style("display", (d) => (!shown(d) ? "none" : d.id === a || d.id === b ? null : "none"));
  }
  function describeEdge(e: FundingEdge): string {
    if (e.type === "affiliation") return esc(e.role);
    const kind = e.type === "grant" ? "grant" : `investment${e.round ? ` · ${esc(e.round)}` : ""}`;
    const amt = e.amountUSD != null ? ` · ${formatUsd(e.amountUSD)}` : " · undisclosed";
    const yr = e.year ? ` · ${e.year}` : "";
    return `${kind}${amt}${yr}${e.verified ? "" : " · inferred"}`;
  }
  function edgeTip(ev: MouseEvent, l: FLink) {
    if (selected && l.source.id !== selected.id && l.target.id !== selected.id) return;
    if (hoverEdge !== l) { hoverEdge = l; emphasizeEdge(l); }
    const arrow = edgeDirected(l) ? "→" : "—";
    showTip(ev, `<div class="t-name">${esc(l.source.name)} ${arrow} ${esc(l.target.name)}</div>
      <div class="t-sub">${describeEdge(l.e)}</div>`);
  }
  function leaveEdge() { hoverEdge = null; tooltip.style.opacity = "0"; applyHighlight(); }

  function select(sel: Sel) {
    selected = sel; hover = null;
    renderDetail(); applyHighlight();
    if (sel) location.hash = "f=" + encodeURIComponent(sel.id);
    else if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  }

  /* ---------- dossier ---------- */
  function applyBlock(f: FunderNode): string {
    const a = f.apply;
    const mode = a.mode === "rolling" ? "rolling" : a.mode === "rounds" ? "rounds" : a.mode;
    const open = openSet.has(f.id);
    const badge = open
      ? `<span class="d-badge" style="background:${OPEN_RING}">open now</span>`
      : `<span class="d-badge" style="background:#b3ab9c">${esc(mode)}</span>`;
    return `<div class="d-line"><span class="d-key">apply</span> ${badge}
      ${a.deadline ? ` closes ${esc(a.deadline)}` : ""}${a.notes ? ` — ${esc(a.notes)}` : ""}
      ${a.url ? ` <a href="${esc(a.url)}" target="_blank" rel="noopener">form →</a>` : ""}</div>`;
  }
  function moneyBlock(f: FunderNode): string {
    const annual = f.annualFieldGivingUSD != null
      ? `${formatUsd(f.annualFieldGivingUSD)}/yr${f.inKind ? " (incl. credits)" : ""}`
      : f.inKind ? "credits / in-kind" : "no public figure";
    const basis = f.annualFieldGivingBasis
      ? ` <a href="${esc(f.annualFieldGivingBasis.sourceUrl)}" target="_blank" rel="noopener" title="${esc(f.annualFieldGivingBasis.method)}">[${f.annualFieldGivingBasis.year}]</a>`
      : "";
    const check = f.checkSizeUSD
      ? `<div class="d-line"><span class="d-key">checks</span> ${formatUsd(f.checkSizeUSD.min)}–${formatUsd(f.checkSizeUSD.max)}</div>`
      : "";
    const grants = topGrants(fundingEdges, f.id, 5).map((g) => {
      const t = byId.get(g.target)!;
      return `<div class="d-row"><span class="swatch" style="background:${GRANTEE_COLOR}"></span>
        <div><button class="d-org d-jump" data-id="${esc(g.target)}" type="button">→ ${esc(t.name)}</button>
        <div class="d-meta">${describeEdge(g)}${g.sourceUrl ? ` · <a href="${esc(g.sourceUrl)}" target="_blank" rel="noopener">src</a>` : ""}</div></div></div>`;
    }).join("");
    return `<div class="d-line"><span class="d-key">gives</span> ${annual}${basis}</div>${check}
      ${grants ? `<div class="d-rels">${grants}</div>` : ""}`;
  }
  function peopleBlock(f: FNode): string {
    const rows = links.filter((l) => l.e.type === "affiliation" && l.target.id === f.id).map((l) => {
      const p = l.source;
      const role = l.e.type === "affiliation" ? l.e.role : "";
      const url = p.kind === "person" ? p.profileUrl : undefined;
      return `<div class="d-row"><span class="swatch" style="background:${PERSON_COLOR}"></span>
        <div><button class="d-org d-jump" data-id="${esc(p.id)}" type="button">${esc(p.name)}</button>
        <div class="d-meta">${esc(role)}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener">profile</a>` : ""}</div></div></div>`;
    }).join("");
    return rows ? `<div class="d-rels">${rows}</div>` : "";
  }
  function renderDetail() {
    if (!selected) { detail.innerHTML = ""; return; }
    const n = byId.get(selected.id)!;
    const kindLine =
      n.kind === "funder" ? `<span style="color:${funderColor(n.funderKind)}">${esc(funderLabel(n.funderKind))}</span>`
        : n.kind === "grantee" ? `grantee${n.fieldDollarsUSD > 0 ? ` · ${formatUsd(n.fieldDollarsUSD)} raised in-field` : ""}`
          : esc((n as Extract<FNode, { kind: "person" }>).title);
    const rels = n.kind === "funder" ? "" : links
      .filter((l) => l.source.id === n.id || l.target.id === n.id)
      .map((l) => {
        const other = l.source.id === n.id ? l.target : l.source;
        const arrow = edgeDirected(l) ? (l.source.id === n.id ? "→" : "←") : "—";
        return `<div class="d-row"><span class="swatch" style="background:${nodeColor(other)}"></span>
          <div><button class="d-org d-jump" data-id="${esc(other.id)}" type="button">${arrow} ${esc(other.name)}</button>
          <div class="d-meta">${describeEdge(l.e)}</div></div></div>`;
      }).join("");
    const ov = overlay.get(n.id);
    let priv = "";
    if (isPrivate && ov) {
      priv = `<div class="d-priv">
        ${ov.stage ? `<div class="d-row"><span class="d-key">stage</span>
          <span class="d-badge" style="background:${fundingStageColor(ov.stage)}">${esc(fundingStageLabel(ov.stage))}</span></div>` : ""}
        ${ov.warm_path ? `<div class="d-warm"><span class="d-key">warm path</span> ${esc(ov.warm_path)}</div>` : ""}
        ${ov.notes ? `<div class="d-note">${esc(ov.notes)}</div>` : ""}</div>`;
    }
    const tags = (n.domainTags ?? []).map((t) => `<span class="d-badge" style="background:#8a8475">${esc(domainLabel(t))}</span>`).join(" ");
    const crossLink = n.networksId
      ? `<div class="d-src"><a href="/networks?focus=${encodeURIComponent(n.networksId)}">→ view on the networks map</a></div>`
      : "";
    detail.innerHTML = `<span class="d-clear" title="clear">✕</span>
      <div class="d-title">${esc(n.name)}</div>
      <div class="d-sub">${kindLine}</div>
      <div class="d-blurb">${esc(n.blurb)}</div>
      ${n.kind === "funder" && n.thesis ? `<div class="d-line"><span class="d-key">thesis</span> ${esc(n.thesis)}</div>` : ""}
      ${n.kind === "funder" ? moneyBlock(n) : ""}
      ${n.kind === "funder" ? applyBlock(n) : ""}
      ${n.kind === "funder" ? peopleBlock(n) : ""}
      ${priv}
      ${rels ? `<div class="d-rels">${rels}</div>` : ""}
      ${tags ? `<div class="d-line">${tags}</div>` : ""}
      ${n.url ? `<div class="d-src"><a href="${esc(n.url)}" target="_blank" rel="noopener">→ ${esc(n.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}</a></div>` : ""}
      ${crossLink}`;
    detail.querySelector(".d-clear")!.addEventListener("click", () => select(null));
    detail.querySelectorAll<HTMLElement>(".d-jump").forEach((b) =>
      b.addEventListener("click", () => select({ id: b.dataset.id! })));
  }

  /* ---------- tooltip ---------- */
  function showTip(ev: MouseEvent, html: string) {
    tooltip.innerHTML = html; tooltip.style.opacity = "1";
    const pad = 14, w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    tooltip.style.left = Math.min(ev.clientX + pad, innerWidth - w - 8) + "px";
    tooltip.style.top = Math.min(ev.clientY + pad, innerHeight - h - 8) + "px";
  }
  function leaveNode() { tooltip.style.opacity = "0"; if (hover) { hover = null; applyHighlight(); } }
  function nodeTip(ev: MouseEvent, d: FNode) {
    if (!hover || hover.id !== d.id) { hover = { id: d.id }; applyHighlight(); }
    const st = isPrivate ? stageOf(d.id) : undefined;
    const stHtml = st ? ` <span class="t-badge" style="background:${fundingStageColor(st)}">${esc(fundingStageLabel(st))}</span>` : "";
    const warm = isPrivate ? warmOf(d.id) : undefined;
    const sub =
      d.kind === "funder"
        ? `<span style="color:${funderColor(d.funderKind)}">${esc(funderLabel(d.funderKind))}</span> · ${
            d.annualFieldGivingUSD != null ? `${formatUsd(d.annualFieldGivingUSD)}/yr` : d.inKind ? "credits" : "$ unknown"
          }${openSet.has(d.id) ? ` · <span style="color:${OPEN_RING}">open now</span>` : ""}`
        : d.kind === "grantee"
          ? `grantee${d.fieldDollarsUSD > 0 ? ` · ${formatUsd(d.fieldDollarsUSD)} in-field` : ""}`
          : esc((d as Extract<FNode, { kind: "person" }>).title);
    showTip(ev, `<div class="t-name">${esc(d.name)}${stHtml}</div>
      <div class="t-sub">${sub}</div>
      <div class="t-blurb">${esc(d.blurb)}</div>${warm ? `<div class="t-warm">↪ ${esc(warm)}</div>` : ""}`);
  }

  window.addEventListener("keydown", (ev) => { if (ev.key === "Escape") select(null); });

  /* ---------- deep links: #f= and ?focus= (Task 5 adds ?view, Task 7 ?lens/?min) ---------- */
  function selectFromHash() {
    const m = location.hash.match(/^#f=(.+)$/);
    if (m) { const id = decodeURIComponent(m[1]); if (byId.has(id)) select({ id }); }
  }
  const params = new URLSearchParams(location.search);
  const focus = params.get("focus");
  if (focus && byId.has(focus)) select({ id: focus });
  else selectFromHash();
  window.addEventListener("hashchange", selectFromHash);

  inited = true;
  refreshLabels();
  applyFilter();
  window.addEventListener("resize", () => fitToNodes(null, false));

  void maxAnnual; void sliderToUsd; void UNKNOWN_R; void PERSON_R; // consumed in Tasks 5–7
}
```

- [ ] **Step 2: Verify**

Run: `npm test && npm run build` — Expected: both PASS.
Run: `npm run dev` → `http://localhost:4321/funding`. Expected, concretely:
- Four territories: philanthropy top-left (Coefficient Giving is the biggest circle on the map), government top-right (UK AISI ~⅓ CG's area, ARIA smaller), venture bottom-left (Menlo large), corporate bottom-right.
- Grantees (gray-tan) sit between their funders; Cooperative AI Foundation and CMU FOCAL hug Macroscopic with visibly thick edges ($15M / $3M); Irregular is a big gray node tied to Sequoia by the thickest edge on the map ($80M).
- People are small white/tan-ringed dots next to Manifund, Foresight, FLI.
- NSF / LTFF / Sequoia render small with dotted outlines ($ unknown); unverified edges render dashed.
- Hover: neighborhood spotlight + tooltip with $/yr and (for CG, LTFF, Manifund, OpenAI programs) an "open now" note.
- Click Coefficient Giving: dossier shows gives $128M/yr [2025], checks $50k–$10M, notable grants (the two Macroscopic grants do NOT appear here — they're Macroscopic's), apply rolling badge, thesis, domain tags. Click Macroscopic: its two $-grants list with `src` links. Click METR: dossier shows a cross-link "→ view on the networks map".
- `/funding#f=metr` deep-link pre-selects METR; Escape clears; drag works; double-click re-fits.

- [ ] **Step 3: Commit**

```bash
git add src/scripts/funding-graph.ts
git commit -m "funding: territory force map — dollar-sized nodes/edges, dossier, deep links"
```

---

### Task 5: Filters, $ floor, directory view

**Files:**
- Create: `src/scripts/funding-directory.ts`
- Modify: `src/scripts/funding-graph.ts` (replace the Task-4 stubs; add control wiring)

**Interfaces:**
- Consumes: `filters`, `applyFilter`, `shown`, `openSet`, `maxAnnual`, `activeStages`, `onNodeClick`, `byId`, `nodes` from Task 4; `sliderToUsd`, `formatUsd`, `nodeDollars` from funding-core.
- Produces: `renderFundingDirectory(container, visible, opts)`; working `renderDir()`/`setView(v)`; `downloadBtn` (wired in Task 7); rows carry class `is-open` when the funder is open (Task 7's directory lens dims the rest).

- [ ] **Step 1: Write `src/scripts/funding-directory.ts`** (complete file):

```ts
/* Directory view for /funding — the same landscape as scannable text.
 * Funder kind → rows sorted by $/yr (unknown last), then grantees grouped by
 * primary domain. People stay on the map + dossiers; a text roster of program
 * officers would read as a call sheet, which is not the public page's job.
 *
 * Pure module: no graph state. funding-graph.ts hands it the visible node list
 * + predicates + an onSelect callback (opens the shared dossier). */

import type { FundingNode, FunderNode, GranteeNode, DomainMeta } from "../data/funding-types";
import { FUNDER_KINDS, GRANTEE_COLOR, escapeHtml as esc } from "../data/funding-types";

export interface FundingDirectoryOpts {
  domains: DomainMeta[];
  onSelect: (id: string) => void;
  isOpen: (f: FunderNode) => boolean; // open-now (snapshot-dated)
  usdOf: (n: FundingNode) => number | null; // funding-core nodeDollars
  fmt: (n: number | null) => string; // funding-core formatUsd
  warmOf?: (id: string) => string | undefined; // dev-only; undefined in prod
}

/** (Re)render the grouped directory of `visible` nodes into `container`. */
export function renderFundingDirectory(
  container: HTMLElement, visible: FundingNode[], opts: FundingDirectoryOpts,
): void {
  const funders = visible.filter((n): n is FunderNode => n.kind === "funder");
  const grantees = visible.filter((n): n is GranteeNode => n.kind === "grantee");
  const maxUsd = Math.max(1, ...funders.map((f) => opts.usdOf(f) ?? 0), ...grantees.map((g) => opts.usdOf(g) ?? 0));
  const dotPx = (usd: number | null) => (usd == null ? 5 : 5 + Math.round(8 * Math.sqrt(usd / maxUsd)));
  const byUsd = (a: FundingNode, b: FundingNode) =>
    (opts.usdOf(b) ?? -1) - (opts.usdOf(a) ?? -1) || (a.name < b.name ? -1 : 1);

  const parts: string[] = [];
  for (const k of FUNDER_KINDS) {
    const rows = funders.filter((f) => f.funderKind === k.id).sort(byUsd);
    if (!rows.length) continue;
    parts.push(
      `<section class="dir-v"><h3 class="dir-vhead"><span class="dir-vname" style="color:${k.color}">${esc(
        k.label,
      )}</span><span class="dir-vcount">${rows.length}</span></h3><div class="dir-sub">`,
    );
    for (const f of rows) parts.push(funderRow(f, k.color, dotPx, opts));
    parts.push(`</div></section>`);
  }
  if (grantees.length) {
    parts.push(
      `<section class="dir-v"><h3 class="dir-vhead"><span class="dir-vname" style="color:${GRANTEE_COLOR}">grantees</span><span class="dir-vcount">${grantees.length}</span></h3>`,
    );
    for (const dm of opts.domains) {
      const rows = grantees.filter((g) => (g.domainTags ?? [])[0] === dm.id).sort(byUsd);
      if (!rows.length) continue;
      parts.push(`<div class="dir-sub"><div class="dir-shead"><span class="dir-slabel">${esc(dm.label)}</span></div>`);
      for (const g of rows) parts.push(granteeRow(g, dotPx, opts));
      parts.push(`</div>`);
    }
    const untagged = grantees.filter((g) => !(g.domainTags ?? []).length).sort(byUsd);
    if (untagged.length) {
      parts.push(`<div class="dir-sub"><div class="dir-shead"><span class="dir-slabel">other</span></div>`);
      for (const g of untagged) parts.push(granteeRow(g, dotPx, opts));
      parts.push(`</div>`);
    }
    parts.push(`</section>`);
  }

  // columns on an auto-height inner wrapper — a definite-height multicol
  // overflows sideways instead of scrolling down (same fix as /networks).
  container.innerHTML = parts.length
    ? `<div class="dir-cols">${parts.join("")}</div>`
    : `<p class="dir-empty">Nothing matches the current filters.</p>`;

  container.onclick = (ev) => {
    const el = (ev.target as HTMLElement).closest<HTMLElement>(".dir-row");
    if (el?.dataset.id) opts.onSelect(el.dataset.id);
  };
}

function funderRow(
  f: FunderNode, color: string, dotPx: (u: number | null) => number, opts: FundingDirectoryOpts,
): string {
  const usd = opts.usdOf(f);
  const open = opts.isOpen(f);
  const warm = opts.warmOf?.(f.id);
  const cls = ["dir-row", open ? "is-open" : ""].filter(Boolean).join(" ");
  const px = dotPx(usd);
  const ann = usd != null ? `<span class="dir-usd">${opts.fmt(usd)}/yr</span>` : `<span class="dir-usd">$ ?</span>`;
  return (
    `<button class="${cls}" data-id="${esc(f.id)}" type="button">` +
    `<span class="dir-dot" style="width:${px}px;height:${px}px;background:${color}"></span>` +
    `<span class="dir-name">${esc(f.name)}</span>` +
    (open ? `<span class="dir-pill dir-pill-open">open</span>` : "") +
    ann +
    (warm ? `<span class="dir-warm">↪ ${esc(warm)}</span>` : "") +
    `</button>`
  );
}

function granteeRow(
  g: GranteeNode, dotPx: (u: number | null) => number, opts: FundingDirectoryOpts,
): string {
  const usd = opts.usdOf(g);
  const px = dotPx(usd);
  const ann = usd != null ? `<span class="dir-usd">${opts.fmt(usd)}</span>` : "";
  return (
    `<button class="dir-row" data-id="${esc(g.id)}" type="button">` +
    `<span class="dir-dot" style="width:${px}px;height:${px}px;background:${GRANTEE_COLOR}"></span>` +
    `<span class="dir-name">${esc(g.name)}</span>${ann}</button>`
  );
}
```

Note: the copied `.dir-ann` CSS rule from /networks hides annotations outside a lens (`.fund-directory:not(.dir-lens-cust) .dir-ann`); the funding directory uses its own `.dir-usd` class (always visible), so delete that `:not(.dir-lens-cust)` rule from FundingGraph.astro's copied CSS if it was carried over.

- [ ] **Step 2: Wire controls in `src/scripts/funding-graph.ts`**

Add the import at the top:
```ts
import { renderFundingDirectory } from "./funding-directory";
```

Replace the Task-4 stub block:
```ts
  /* Directory + view toggle land in Task 5; declared here so applyFilter compiles. */
  function renderDir(): void {}
  function setView(_v: "map" | "directory"): void {}
  void setView;
```
with (complete):
```ts
  /* ---------- directory view + view toggle ---------- */
  const dirEl = document.getElementById("fund-directory");
  const viewMapBtn = document.getElementById("fund-view-map");
  const viewDirBtn = document.getElementById("fund-view-dir");
  const downloadBtn = document.getElementById("fund-download") as HTMLButtonElement | null;

  function renderDir() {
    if (!dirEl) return;
    renderFundingDirectory(dirEl, nodes.filter(shown), {
      domains: DOMAINS,
      onSelect: (id) => { const d = byId.get(id); if (d) onNodeClick(d); },
      isOpen: (f) => openSet.has(f.id),
      usdOf: nodeDollars,
      fmt: formatUsd,
      warmOf: isPrivate ? warmOf : undefined, // undefined in prod → no warm strings shipped
    });
  }
  function setView(v: "map" | "directory") {
    view = v;
    const dir = v === "directory";
    dirEl?.toggleAttribute("hidden", !dir);
    graphEl.classList.toggle("fund-hide", dir);
    viewMapBtn?.classList.toggle("on", !dir);
    viewDirBtn?.classList.toggle("on", dir);
    viewMapBtn?.setAttribute("aria-pressed", String(!dir));
    viewDirBtn?.setAttribute("aria-pressed", String(dir));
    downloadBtn?.toggleAttribute("hidden", dir); // download exports the map view only
    if (dir) renderDir();
    else fitToNodes(null, false); // re-frame after display:none
  }
  viewMapBtn?.addEventListener("click", () => setView("map"));
  viewDirBtn?.addEventListener("click", () => setView("directory"));

  /* ---------- chips: funder kinds (default all on), domains (default off = no filter) ---------- */
  function buildChips<T extends string>(
    container: HTMLElement, items: { id: T; label: string; color: string }[], active: Set<T>,
    onChange?: () => void,
  ): void {
    for (const it of items) {
      const chip = document.createElement("button");
      chip.className = active.has(it.id) ? "fund-chip on" : "fund-chip";
      chip.dataset.id = it.id;
      chip.innerHTML = `<span class="sw" style="background:${it.color}"></span>${esc(it.label)}`;
      chip.addEventListener("click", () => {
        active.has(it.id) ? active.delete(it.id) : active.add(it.id);
        chip.classList.toggle("on", active.has(it.id));
        applyFilter();
        onChange?.();
      });
      container.appendChild(chip);
    }
  }
  const kindChipsEl = document.getElementById("fund-kinds")!;
  const domainChipsEl = document.getElementById("fund-domains")!;
  const presentKinds = FUNDER_KINDS.filter((k) => nodes.some((n) => n.kind === "funder" && n.funderKind === k.id));
  const allBtn = document.createElement("button");
  allBtn.className = "fund-chip fund-chip-toggle";
  const refreshAllBtn = () => { allBtn.textContent = filters.kinds.size === 0 ? "show all" : "hide all"; };
  allBtn.addEventListener("click", () => {
    if (filters.kinds.size === 0) presentKinds.forEach((k) => filters.kinds.add(k.id));
    else filters.kinds.clear();
    kindChipsEl.querySelectorAll<HTMLElement>(".fund-chip[data-id]")
      .forEach((c) => c.classList.toggle("on", filters.kinds.has(c.dataset.id as FunderKind)));
    refreshAllBtn();
    applyFilter();
  });
  kindChipsEl.appendChild(allBtn);
  refreshAllBtn();
  buildChips(kindChipsEl, presentKinds, filters.kinds, refreshAllBtn);
  buildChips(
    domainChipsEl,
    DOMAINS.map((d) => ({ id: d.id, label: d.label, color: "#8a8475" })),
    filters.domains,
  );

  /* stage chips + warm-only (dev/private layer) */
  const stageChipsEl = document.getElementById("fund-stages");
  let warmOnly = false;
  void warmOnly;
  if (isPrivate && stageChipsEl) {
    const warmChip = document.createElement("button");
    warmChip.className = "fund-chip fund-chip-warm";
    warmChip.textContent = "warm paths only";
    warmChip.addEventListener("click", () => {
      warmOnly = !warmOnly;
      warmChip.classList.toggle("on", warmOnly);
      applyFilter();
    });
    stageChipsEl.appendChild(warmChip);
    buildChips(stageChipsEl, FUNDING_STAGES, activeStages);
  }

  /* ---------- $ floor slider ---------- */
  const usdRange = document.getElementById("fund-usd-range") as HTMLInputElement | null;
  const usdN = document.getElementById("fund-usd-n");
  const updateUsdReadout = () => {
    if (usdN) usdN.textContent = filters.minUsd <= 0 ? "any amount" : formatUsd(filters.minUsd);
    usdRange?.setAttribute(
      "aria-valuetext",
      filters.minUsd <= 0 ? "any amount" : `at least ${formatUsd(filters.minUsd)} per year`,
    );
  };
  usdRange?.addEventListener("input", () => {
    filters.minUsd = sliderToUsd(Number(usdRange.value), maxAnnual);
    updateUsdReadout();
    applyFilter();
  });
  updateUsdReadout();
  searchEl?.addEventListener("input", applyFilter);
```

Extend `applyFilter`'s private-stage pass to honor warm-only — replace the `if (isPrivate) {` block inside `applyFilter` with:
```ts
    if (isPrivate) { // dev-only: stage chips + warm-only narrow further
      for (const id of [...visibleSet]) {
        if (!activeStages.has(stageOf(id) ?? "cold")) visibleSet.delete(id);
        else if (warmOnly && !warmOf(id)) visibleSet.delete(id);
      }
    }
```
(and delete the now-obsolete `void warmOnly;` line). NOTE: `warmOnly` must be declared BEFORE `applyFilter` runs — move the `let warmOnly = false;` declaration up next to `const activeStages…` if TS complains about use-before-assign.

In the deep-links section (after `window.addEventListener("hashchange", selectFromHash);`), add:
```ts
  if (params.get("view") === "directory") setView("directory");
```

Remove `void maxAnnual; void sliderToUsd;` from the Task-4 tail (now consumed); keep `void UNKNOWN_R; void PERSON_R;` (consumed by Task 7's legend note — or delete if unused after Task 7).

- [ ] **Step 3: Verify**

`npm test && npm run build` → PASS. In the dev server:
- Kind chips toggle territories off/on; turning philanthropy off removes CG *and* its sole-funder grantees *and* its people; "hide all" empties the map (directory shows the empty state).
- Domain chips: `agent security` alone leaves Menlo/Sequoia/Insight/OpenAI-programs (+ FMF, Anthropic, Schmidt) and the security startups; CG disappears.
- Money floor: drag right — small/unknown-$ funders drop out progressively (readout shows e.g. `funders giving ≥ $18M per year`); at far right only Coefficient Giving and Menlo survive.
- Search `open philanthropy` finds CG (alias); search `austin` shows Austin Chen + Manifund.
- Directory view: funders grouped by kind, sorted by $/yr with `$128M/yr`-style annotations, `open` pills on CG/LTFF/Manifund/OpenAI-programs/Menlo/Sequoia/Insight; grantees grouped by domain; clicking a row opens the dossier. `/funding?view=directory` deep-links in.

- [ ] **Step 4: Commit**

```bash
git add src/scripts/funding-directory.ts src/scripts/funding-graph.ts
git commit -m "funding: kind/domain chips, money-floor slider, search, directory view"
```

---

### Task 6: Public path finder

**Files:**
- Modify: `src/scripts/funding-graph.ts`

**Interfaces:**
- Consumes: `route`, `routeLinks`, `inRoute`, `applyFilter`, `applyHighlight`, `fitToNodes`, `adj`, `byId`, `nodes`, `onNodeClick` from Tasks 4–5; `shortestPath` from funding-core; `#fund-pathctl` / `#fund-path-detail` from Task 3.
- Produces: `pathPair`, `setPathEnd(id)`, `clearPath()` — and the final `onNodeClick` / Escape behavior.

- [ ] **Step 1: Add the path-finder block** (insert after the `$ floor slider` block, before `/* ---------- highlight ... */` is fine anywhere at module scope inside init; keep it adjacent to the other control wiring):

```ts
  /* ---------- path finder: how do you get from any node to any other? ----------
   * Two type-ahead slots (ported from alex-loftus.com's coauthorship pair
   * finder). BFS runs over the FULL graph — filters never hide a route; route
   * members are force-shown by shown() and restored when the path clears. */
  const pathCtl = document.getElementById("fund-pathctl");
  const pathDetail = document.getElementById("fund-path-detail")!;
  const pathPair: { from: string | null; to: string | null; armed: "from" | "to" | null } =
    { from: null, to: null, armed: null };
  const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  const linkByPair = new Map<string, FLink>();
  for (const l of links) {
    const k = pairKey(l.source.id, l.target.id);
    if (!linkByPair.has(k)) linkByPair.set(k, l);
  }

  function setPathEnd(id: string) {
    if (pathPair.armed === "from" || (!pathPair.armed && !pathPair.from)) pathPair.from = id;
    else pathPair.to = id;
    pathPair.armed = pathPair.from && !pathPair.to ? "to" : null;
    if (pathPair.from && pathPair.to) computePairPath();
    else { route = null; routeLinks = new Set(); renderPairDetail(); applyFilter(); }
    renderPathPanel();
  }
  function computePairPath() {
    route = shortestPath(adj, pathPair.from!, pathPair.to!);
    routeLinks = new Set();
    if (route)
      for (let i = 0; i < route.ids.length - 1; i++) {
        const l = linkByPair.get(pairKey(route.ids[i], route.ids[i + 1]));
        if (l) routeLinks.add(l);
      }
    renderPairDetail();
    applyFilter(); // re-applies display (route force-shown) + the route highlight
    if (route) fitToNodes(route.ids, true);
  }
  function clearPath() {
    pathPair.from = pathPair.to = null;
    pathPair.armed = null;
    route = null;
    routeLinks = new Set();
    renderPairDetail();
    renderPathPanel();
    applyFilter();
    fitToNodes(null, true);
  }
  function renderPairDetail() {
    if (!pathPair.from || !pathPair.to) { pathDetail.innerHTML = ""; return; }
    if (!route) {
      pathDetail.innerHTML = `<div class="pd-title">no path</div>
        <div class="pd-none">No public funding path connects these two.</div>`;
      return;
    }
    const chain = route.ids.map((id, i) => {
      const name = esc(byId.get(id)!.name);
      const cls = i === 0 || i === route!.ids.length - 1 ? "pd-end" : "";
      return `<span class="${cls}">${name}</span>`;
    }).join(`<span class="pd-arrow">→</span>`);
    pathDetail.innerHTML = `<div class="pd-title">${route.len} hop${route.len === 1 ? "" : "s"}</div>
      <div class="pd-chain">${chain}</div>`;
  }
  function renderPathPanel() {
    if (!pathCtl) return;
    pathCtl.innerHTML = `<span class="pp-label">path</span>`;
    (["from", "to"] as const).forEach((end, i) => {
      if (i === 1) {
        const arrow = document.createElement("span");
        arrow.className = "pp-arrow";
        arrow.textContent = "→";
        pathCtl.appendChild(arrow);
      }
      const slot = document.createElement("div");
      slot.className = "pp-slot" + (pathPair.armed === end ? " armed" : "");
      const val = pathPair[end];
      if (val) {
        const d = byId.get(val)!;
        slot.innerHTML = `<span class="pp-pick"><span class="pp-dot" style="background:${nodeColor(d)}"></span>${esc(d.name)}</span>`;
        slot.addEventListener("click", () => { // re-open: clear this end, arm it
          pathPair[end] = null;
          pathPair.armed = end;
          route = null; routeLinks = new Set();
          renderPairDetail(); renderPathPanel(); applyFilter();
        });
      } else {
        const input = document.createElement("input");
        input.className = "pp-input";
        input.placeholder = end;
        input.autocomplete = "off";
        input.spellcheck = false;
        const menu = document.createElement("div");
        menu.className = "pp-menu";
        menu.hidden = true;
        const other = end === "from" ? pathPair.to : pathPair.from;
        const refreshMenu = () => {
          const q = input.value.trim().toLowerCase();
          const hits = nodes
            .filter((n) => n.id !== other && (!q || n.name.toLowerCase().includes(q) ||
              (n.aliases ?? []).some((a) => a.toLowerCase().includes(q))))
            .slice(0, 8);
          menu.innerHTML = hits.map((n) =>
            `<button type="button" data-id="${esc(n.id)}"><span class="pp-dot" style="background:${nodeColor(n)}"></span>${esc(n.name)}</button>`,
          ).join("");
          menu.hidden = !hits.length;
          // mousedown (not click) so the pick beats the input's blur
          menu.querySelectorAll<HTMLElement>("button").forEach((b) =>
            b.addEventListener("mousedown", (ev) => { ev.preventDefault(); setPathEnd(b.dataset.id!); }));
        };
        input.addEventListener("focus", () => { pathPair.armed = end; slot.classList.add("armed"); refreshMenu(); });
        input.addEventListener("input", refreshMenu);
        input.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            const first = menu.querySelector<HTMLElement>("button");
            if (first?.dataset.id) setPathEnd(first.dataset.id);
          }
        });
        input.addEventListener("blur", () => setTimeout(() => { menu.hidden = true; }, 120));
        slot.appendChild(input);
        slot.appendChild(menu);
      }
      pathCtl.appendChild(slot);
    });
    if (pathPair.from || pathPair.to) {
      const clear = document.createElement("button");
      clear.className = "pp-clear";
      clear.type = "button";
      clear.title = "clear path";
      clear.textContent = "✕";
      clear.addEventListener("click", clearPath);
      pathCtl.appendChild(clear);
    }
  }
  renderPathPanel();
```

- [ ] **Step 2: Route node clicks + Escape through the path finder**

Replace the Task-4 `onNodeClick`:
```ts
  function onNodeClick(d: FNode): void {
    select({ id: d.id });
  }
```
with:
```ts
  function onNodeClick(d: FNode): void {
    if (pathPair.armed) { setPathEnd(d.id); return; } // armed slot captures the click
    if (route) clearPath(); // normal selection exits path mode
    select({ id: d.id });
  }
```
NOTE: `onNodeClick` is referenced before the path block declares `pathPair` — that's fine (function body runs on click, long after init), but if TS flags use-before-declaration on `pathPair`, hoist the `const pathPair = …` declaration up next to the `filters` declaration and leave the rest of the block where it is.

Replace the Task-4 Escape handler:
```ts
  window.addEventListener("keydown", (ev) => { if (ev.key === "Escape") select(null); });
```
with:
```ts
  window.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (pathPair.armed || pathPair.from || pathPair.to) { clearPath(); return; } // path first
    select(null);
  });
```

- [ ] **Step 3: Verify**

`npm test && npm run build` → PASS. Dev server:
- Type `alli` in the *from* slot → menu shows Allison Duettmann; Enter picks her. Click Irregular on the map → it lands in the *to* slot (armed-click capture).
- Route Allison → Foresight → Timaeus → …: the chain highlights in red, everything else fades to ~6%, the camera frames the route, the breadcrumb card shows `N hops` + `Allison Duettmann → Foresight Institute → Timaeus → …` with bold ends.
- Path ignores filters: set the money floor to max (only CG + Menlo visible), then path Allison → Irregular — the route still renders through hidden nodes (force-shown).
- Disconnected pair: filter nothing, path `Austin Chen → Anthony Aguirre` — both slots fill; if no chain exists the card reads "No public funding path connects these two." (with the starter data Manifund→timaeus→…→FLI likely connects them — verify whichever behavior matches the data, and check the no-path message by pathing to a node you've confirmed isolated, if any).
- ✕ clears; Escape clears; clicking a filled slot re-arms it.

- [ ] **Step 4: Commit**

```bash
git add src/scripts/funding-graph.ts
git commit -m "funding: public BFS path finder with type-ahead slots + route highlight"
```

---

### Task 7: Open-now lens, legend, PNG download, remaining deep links

**Files:**
- Modify: `src/scripts/funding-graph.ts`
- Modify: `src/components/FundingGraph.astro` (one CSS rule)

- [ ] **Step 1: Wire the lens** (insert with the other control wiring):

```ts
  /* ---------- open-now lens: highlight, never filter ---------- */
  const lensOpenBtn = document.getElementById("fund-lens-open");
  function setLensOpen(on: boolean) {
    lensOpen = on;
    lensOpenBtn?.classList.toggle("on", on);
    lensOpenBtn?.setAttribute("aria-pressed", String(on));
    dirEl?.classList.toggle("dir-lens-open", on);
    applyHighlight();
    if (view === "directory") renderDir();
  }
  lensOpenBtn?.addEventListener("click", () => setLensOpen(!lensOpen));
```

Append to FundingGraph.astro's `<style is:global>` (directory side of the lens — `is-open` rows come from Task 5):
```css
  .fund-directory.dir-lens-open .dir-row:not(.is-open) { opacity: 0.35; }
```

- [ ] **Step 2: Legend** (insert after the lens block):

```ts
  /* ---------- legend ---------- */
  const legendEl = document.getElementById("fund-legend")!;
  legendEl.innerHTML =
    `<span class="fund-leg-item">color · funder kind</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-dot" style="width:6px;height:6px"></span>` +
    `<span class="fund-leg-dot" style="width:14px;height:14px"></span> size · $ into the field</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-dotted"></span> no public $</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-ln"></span> verified</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-ln dash"></span> inferred</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-ring" style="border-color:${OPEN_RING}"></span> open now</span>` +
    `<span class="fund-leg-item fund-leg-dim">zoom in for more names</span>` +
    (isPrivate ? `<span class="fund-leg-item fund-leg-priv">● ring · our stage (dev)</span>` : "");
```

- [ ] **Step 3: PNG download** — copy `downloadPng` from `networks-graph.ts:308-352` verbatim with three changes: the injected style rule targets `.fund-label` (not `.net-label`), the download filename is `"agents-of-chaos-funding.png"`, and wire it to the Task-5 `downloadBtn`:
```ts
  downloadBtn?.addEventListener("click", downloadPng);
```

- [ ] **Step 4: Deep links** (append inside the deep-links section, after the `?view` line):

```ts
  if (params.get("lens") === "open") setLensOpen(true);
  const minParam = params.get("min");
  if (minParam && /^\d+$/.test(minParam) && usdRange) {
    filters.minUsd = Math.min(Number(minParam), maxAnnual);
    // invert sliderToUsd so the thumb matches: v = (100/k)·ln(1 + min·(eᵏ−1)/max)
    const K = 6;
    usdRange.value = String(Math.round((100 / K) * Math.log1p((filters.minUsd * Math.expm1(K)) / maxAnnual)));
    updateUsdReadout();
    applyFilter();
  }
```
Delete any remaining `void …` suppressions from the Task-4 tail that are now consumed.

- [ ] **Step 5: Verify**

`npm test && npm run build` → PASS. Dev server:
- Lens on: CG/LTFF/Manifund/OpenAI-programs/Menlo/Sequoia/Insight (rolling) get green rings and stay at full opacity; rounds-without-deadline funders (SFF, UK AISI, NSF, FLI, Foresight, ARIA, FMF, Anthropic) and closed Schmidt dim to ~15%; grantees/people dim to ~25%; edges fade. Directory rows dim except `open`-pilled ones. Lens NEVER removes nodes.
- Legend shows all seven keys (+ stage note only in dev).
- Download produces a PNG of the current view with labels and cream background.
- `/funding?lens=open&min=10000000&view=directory` deep-links all three states.

- [ ] **Step 6: Commit**

```bash
git add src/scripts/funding-graph.ts src/components/FundingGraph.astro
git commit -m "funding: open-now lens, legend, PNG download, lens/min deep links"
```

---

### Task 8: Private overlay, privacy proof, docs, final gates

**Files:**
- Create: `private/funding-overlay.json` (gitignored — NEVER `git add` this)
- Modify: `CLAUDE.md` (repo root), `README.md` (only if it lists site pages)

- [ ] **Step 1: Create `private/funding-overlay.json`** (dev-only sample; edit freely later — it's yours, not the repo's):

```json
{
  "entries": [
    { "id": "coefficient-giving", "stage": "warm", "warm_path": "Stella → CG technical-AI-safety program", "notes": "EleutherAI package in flight" },
    { "id": "schmidt-sciences", "stage": "cold", "notes": "watch the joint agent-ecosystems call (Schmidt + DeepMind + ARIA) — squarely our lane" },
    { "id": "menlo-ventures", "stage": "cold", "warm_path": "Anthology Fund intake" },
    { "id": "frontier-model-forum-aisf", "stage": "in-convo" }
  ]
}
```

- [ ] **Step 2: Verify the dev/prod split**

1. `npm run dev` → `/funding`: stage rings on CG (warm=tan) and FMF (in-convo=rust); stage chips row + "warm paths only" chip appear; CG's dossier and tooltip show the warm path; directory rows show `↪` warm annotations; legend shows the stage note.
2. Confirm git ignores it: `git status --short private/` → empty output.
3. Privacy grep (the proof that matters):
```bash
npm run build && grep -ri "warm_path\|funding-overlay\|warm path" dist/ ; echo "exit=$? (1 = clean)"
```
Expected: no matches (`exit=1`).

- [ ] **Step 3: Update repo docs**

Append to `CLAUDE.md` (root), after the `## /networks` section:

```markdown
## /funding

Dollar-weighted funder landscape ("find your funder"). Size = sqrt(field-relevant $)
— every non-null $ in src/data/funding.json carries a source URL (validator-enforced);
never add a figure without one. Open-now derives from meta.generatedAt, not the wall
clock. The private overlay (private/funding-overlay.json: stage + warm paths) loads
only in `astro dev` — same rule as /networks. Pure math lives in
src/scripts/funding-core.js (node --test covered); dataset is regenerated by
experiments/funding (plan 2) — node ids are frozen, never re-slugged.
```

Check `README.md`: if it enumerates pages/routes, add a one-line `/funding` entry in the same style; otherwise leave it.

- [ ] **Step 4: Final gates + review**

```bash
npm test && npm run build
git status --short   # must show NO private/ files staged
```
Both green → commit docs:
```bash
git add CLAUDE.md README.md
git commit -m "funding: document the /funding page + privacy rules"
```
Then run the superpowers:requesting-code-review flow for the whole branch diff before any merge/PR.

---

## Plan self-review notes (already applied)

- Spec coverage: territories ✓ (T4), $-sizing ✓ (T1/T4), map+directory ✓ (T5), controls ✓ (T5), open-now lens ✓ (T7), path finder ✓ (T6), dossier ✓ (T4), cross-links ✓ (T2/T4), private overlay ✓ (T3/T8), deep links ✓ (T4/T5/T7), $-provenance validator ✓ (T2), snapshot-dated open-now ✓ (T1/T4). Nightly loop + pipeline are plans 2–3 by design.
- Type consistency: `initFundingGraph(FundingOverlayEntry[])` (T3 island ↔ T4), `renderFundingDirectory(container, visible, opts)` (T5), `fitToNodes(ids|null, animate)` (T4 ↔ T6), `onNodeClick` override contract (T4 ↔ T6), `is-open` row class (T5 ↔ T7 CSS), `FLink = { e, source, target }` throughout.
- Known wart accepted: Task 4 ships two tiny stubs (`renderDir`/`setView`) so `applyFilter` compiles before Task 5 — each intermediate commit still builds and renders a working page.
