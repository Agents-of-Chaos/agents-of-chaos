// Nightly crash gate for the /funding questions (P3). The funding-nightly
// workflow churns funding.json (new funders, re-verified statuses) WITHOUT
// rebaking questions-funding.json — baked ids can go stale at any time. The
// contract (defs/funding.ts): every def must DEGRADE under drift — drop dead
// baked ids, rebuild names/dollars from live data — and never crash. This
// test imports the ACTUAL defs (node strips the types natively) and runs
// compute() against the LIVE funding.json plus synthetic-drift variants; it
// fails the nightly PR only if a question would crash, never on mere drift.

import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { test } from "node:test";
import * as kernels from "../src/scripts/questions/kernels.js";
import {
  FUNDING_DEFAULT_SEAT,
  makeFundingDefs,
} from "../src/scripts/questions/defs/funding.ts";

const funding = JSON.parse(
  readFileSync(new URL("../src/data/funding.json", import.meta.url), "utf8"),
);
// a missing payload is a broken repo state, not churn — fail hard, the crash
// gate must never silently skip
const payload = JSON.parse(
  readFileSync(new URL("../src/data/questions/questions-funding.json", import.meta.url), "utf8"),
);
const skipMsg = false;

const defs = makeFundingDefs();

/** Synthesize the QComputeCtx exactly as engine.buildCtx does, from a live
 *  (or synthetically drifted) node/edge set. */
function makeCtx(nodes, edges, p, defaultSeat) {
  const byId = new Map(
    nodes.map((n) => [
      n.id,
      { id: n.id, label: n.name, group: n.kind === "funder" ? n.funderKind : n.kind },
    ]),
  );
  const adjT = new Map();
  const push = (a, e) => {
    const l = adjT.get(a);
    if (l) l.push(e);
    else adjT.set(a, [e]);
  };
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    push(e.source, { to: e.target, type: e.type, verified: e.verified ?? false });
    push(e.target, { to: e.source, type: e.type, verified: e.verified ?? false });
  }
  return {
    payload: p,
    defaultSeat,
    ids: nodes.map((n) => n.id).sort(),
    byId,
    adjT,
    raw: { companies: nodes, edges },
    kernels,
  };
}

/** Every rendered reference must resolve in the live graph (focusIds may
 *  keep the seat itself — the host's fitToIds skips unknown ids safely). */
function assertLiveOnly(res, liveIds, seat, tag) {
  const ok = (id, where) =>
    assert.ok(liveIds.has(id), `${tag}: ${where} references non-live id "${id}"`);
  for (const id of res.litIds) ok(id, "litIds");
  for (const id of res.anchorIds) ok(id, "anchorIds");
  for (const c of res.callouts) ok(c.id, "callouts");
  for (const p of res.marks.paths ?? []) for (const id of p) ok(id, "marks.paths");
  for (const [a, b] of res.marks.edges ?? []) {
    ok(a, "marks.edges");
    ok(b, "marks.edges");
  }
  for (const row of res.rows)
    if (typeof row.id === "string") ok(row.id, "rows");
  for (const id of res.focusIds)
    assert.ok(
      liveIds.has(id) || id === seat,
      `${tag}: focusIds references non-live id "${id}"`,
    );
  assert.ok(
    typeof res.sentence === "string" && res.sentence.trim().length > 0,
    `${tag}: sentence is a non-empty string`,
  );
  assert.ok(!res.sentence.includes("{"), `${tag}: sentence has no unfilled {slot}`);
  assert.ok(res.callouts.length <= 3, `${tag}: ≤3 callouts`);
}

test("def slugs cover the baked payload (and nothing else)", { skip: skipMsg }, () => {
  const defSlugs = defs.map((d) => d.id).sort();
  const baked = Object.keys(payload.questions).sort();
  assert.deepEqual(defSlugs, baked, "defs/funding.ts and the bake must agree on slugs");
});

test("every question renders from the LIVE graph at the baked default seat", { skip: skipMsg }, () => {
  const ctx = makeCtx(funding.nodes, funding.edges, payload, FUNDING_DEFAULT_SEAT);
  const liveIds = new Set(funding.nodes.map((n) => n.id));
  const firstDefault = Object.values(payload.questions)[0]?.default;
  assert.ok(firstDefault, "payload carries a default block");
  // the adapter's hardcoded seat must be the seat the bake used — a mismatch
  // silently forfeits the baked first paint
  assert.equal(
    firstDefault.seat,
    FUNDING_DEFAULT_SEAT,
    "FUNDING_DEFAULT_SEAT (defs/funding.ts) must match the payload's baked seat",
  );
  for (const def of defs) {
    const res = def.compute(FUNDING_DEFAULT_SEAT, ctx);
    assertLiveOnly(res, liveIds, FUNDING_DEFAULT_SEAT, def.id);
  }
});

test("re-aim at arbitrary live seats never throws (funder / grantee / person)", { skip: skipMsg }, () => {
  const ctx = makeCtx(funding.nodes, funding.edges, payload, FUNDING_DEFAULT_SEAT);
  const liveIds = new Set(funding.nodes.map((n) => n.id));
  const firstOf = (kind) =>
    funding.nodes
      .filter((n) => n.kind === kind)
      .sort((a, b) => (a.id < b.id ? -1 : 1))[0].id;
  const seats = [firstOf("funder"), firstOf("grantee"), firstOf("person")];
  for (const def of defs)
    for (const seat of seats) {
      const res = def.compute(seat, ctx);
      assertLiveOnly(res, liveIds, seat, `${def.id}@${seat}`);
    }
});

test("drift: baked ids gone from the live graph degrade — never crash, never render", { skip: skipMsg }, () => {
  // remove every question's single most-load-bearing baked id (the first row)
  // plus the first callout anchor — the exact shape of nightly churn
  const doomed = new Set();
  for (const q of Object.values(payload.questions)) {
    const first = q.default.rows.find((r) => typeof r.id === "string");
    if (first) doomed.add(first.id);
    if (q.default.callouts[0]) doomed.add(q.default.callouts[0].id);
  }
  assert.ok(doomed.size > 0, "found baked ids to drop");
  const nodes = funding.nodes.filter((n) => !doomed.has(n.id));
  const edges = funding.edges.filter((e) => !doomed.has(e.source) && !doomed.has(e.target));
  const ctx = makeCtx(nodes, edges, payload, FUNDING_DEFAULT_SEAT);
  const liveIds = new Set(nodes.map((n) => n.id));
  for (const def of defs) {
    const res = def.compute(FUNDING_DEFAULT_SEAT, ctx);
    assertLiveOnly(res, liveIds, FUNDING_DEFAULT_SEAT, `${def.id} (drifted)`);
  }
});

test("drift: even the default seat vanishing must not crash", { skip: skipMsg }, () => {
  const nodes = funding.nodes.filter((n) => n.id !== FUNDING_DEFAULT_SEAT);
  const edges = funding.edges.filter(
    (e) => e.source !== FUNDING_DEFAULT_SEAT && e.target !== FUNDING_DEFAULT_SEAT,
  );
  const ctx = makeCtx(nodes, edges, payload, FUNDING_DEFAULT_SEAT);
  const liveIds = new Set(nodes.map((n) => n.id));
  for (const def of defs) {
    const res = def.compute(FUNDING_DEFAULT_SEAT, ctx);
    assertLiveOnly(res, liveIds, FUNDING_DEFAULT_SEAT, `${def.id} (seatless)`);
  }
});

// runs even before the bake lands: the defs module itself must load and
// produce five well-formed defs (source → appendix slugs, unique ids)
test("makeFundingDefs shape (no payload needed)", () => {
  assert.equal(defs.length, 5);
  assert.deepEqual(
    defs.map((d) => d.id).sort(),
    ["funder-shortlist", "funding-bridges", "rivals-money", "warm-routes", "within-reach"],
  );
  for (const def of defs) {
    assert.ok(def.question.trim().length > 5, `${def.id}: has question text`);
    assert.ok(def.source.length >= 1, `${def.id}: names a methods appendix slug`);
    assert.equal(typeof def.compute, "function");
    assert.ok(!def.morph, `${def.id}: funding has no morph question`);
  }
});
