// Parity + unit tests for the question kernels (src/scripts/questions/
// kernels.js). The parity half asserts the JS kernels reproduce the Python
// bake (experiments/analyses/prep_questions.py) BIT-IDENTICALLY against
// src/data/questions/fixtures.json: same ids in the same order, and cFull /
// sFull equal under Object.is. The unit half needs no fixtures.

import { existsSync, readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  buildGraph,
  constraintTop10,
  dijkstra,
  fillTemplate,
  fmtCount,
  knn,
  pathTo,
  pprTop10,
  twoHop,
} from "../src/scripts/questions/kernels.js";

const companies = JSON.parse(
  readFileSync(new URL("../src/data/companies.json", import.meta.url), "utf8"),
);
const FIXTURES_URL = new URL("../src/data/questions/fixtures.json", import.meta.url);
// TODO(bake): this skip guard exists ONLY because prep_questions.py hasn't
// landed fixtures.json yet. REMOVE the guard (make missing fixtures a hard
// failure) as soon as the bake lands — a silently-skipped parity test is
// worthless.
const haveFixtures = existsSync(FIXTURES_URL);
const skipMsg = haveFixtures
  ? false
  : "src/data/questions/fixtures.json not baked yet — run experiments/analyses/prep_questions.py (TODO: remove this skip once it lands)";

/* ---------- parity vs the Python bake ---------- */

test("kernel graph matches the bake's node/edge counts", { skip: skipMsg }, () => {
  const fx = JSON.parse(readFileSync(FIXTURES_URL, "utf8"));
  const g = buildGraph(companies);
  assert.equal(g.n, fx.meta.nodes);
  const undirected = g.deg.reduce((a, b) => a + b, 0) / 2;
  assert.equal(undirected, fx.meta.undirectedEdges);
  assert.equal(fx.meta.seats.length, 6);
  for (const seat of fx.meta.seats) assert.ok(g.idx.has(seat), `fixture seat ${seat} on the map`);
});

test("constraintTop10 reproduces the baked fixtures bit-identically", { skip: skipMsg }, () => {
  const fx = JSON.parse(readFileSync(FIXTURES_URL, "utf8"));
  const g = buildGraph(companies);
  for (const [seatId, want] of Object.entries(fx.constraint)) {
    const got = constraintTop10(g, g.idx.get(seatId), fx.meta.minDegree);
    assert.deepEqual(
      got.map((r) => r.id),
      want.map((r) => r.id),
      `constraint top-10 ids for seat ${seatId}`,
    );
    want.forEach((w, i) => {
      assert.ok(
        Object.is(got[i].cFull, w.cFull),
        `cFull bit-identical @${seatId}/${w.id}: js=${got[i].cFull} py=${w.cFull}`,
      );
      assert.equal(got[i].c, w.c, `c (round6) @${seatId}/${w.id}`);
    });
  }
});

test("pprTop10 reproduces the baked fixtures bit-identically", { skip: skipMsg }, () => {
  const fx = JSON.parse(readFileSync(FIXTURES_URL, "utf8"));
  const g = buildGraph(companies);
  for (const [seatId, want] of Object.entries(fx.ppr)) {
    const got = pprTop10(g, g.idx.get(seatId), fx.meta.alpha, fx.meta.iterations);
    assert.deepEqual(
      got.map((r) => r.id),
      want.map((r) => r.id),
      `ppr top-10 ids for seat ${seatId}`,
    );
    want.forEach((w, i) => {
      assert.ok(
        Object.is(got[i].sFull, w.sFull),
        `sFull bit-identical @${seatId}/${w.id}: js=${got[i].sFull} py=${w.sFull}`,
      );
      assert.equal(got[i].s, w.s, `s (round9) @${seatId}/${w.id}`);
    });
  }
});

/* ---------- buildGraph / twoHop ---------- */

test("buildGraph dedupes reversed and repeated edges into a simple graph", () => {
  const g = buildGraph({
    companies: [{ id: "b" }, { id: "a" }, { id: "c" }],
    edges: [
      { source: "a", target: "b" },
      { source: "b", target: "a" }, // reverse dupe
      { source: "a", target: "b" }, // exact dupe
      { source: "b", target: "c" },
    ],
  });
  assert.deepEqual(g.ids, ["a", "b", "c"]); // sorted ascending
  assert.deepEqual(g.deg, [1, 2, 1]);
  assert.deepEqual(g.adj[1], [0, 2]); // neighbor lists ascending
});

test("twoHop covers exactly dist<=2, seat included, ascending", () => {
  // path graph a-b-c-d-e; from a: {a,b,c}
  const g = buildGraph({
    companies: ["a", "b", "c", "d", "e"].map((id) => ({ id })),
    edges: [
      { source: "a", target: "b" },
      { source: "b", target: "c" },
      { source: "c", target: "d" },
      { source: "d", target: "e" },
    ],
  });
  assert.deepEqual(twoHop(g, g.idx.get("a")), [0, 1, 2]);
});

/* ---------- dijkstra: friction weights + deterministic tie-break ---------- */

function toyAdjT() {
  // a—b (business 1), a—c (business 1), b—d (business 1), c—d (business 1),
  // a—d (competitor 10, a trap: the direct edge must LOSE to the 2-hop route),
  // a—e (shared-investor 2). Undirected: both directions listed.
  const edges = [
    ["a", "b", "business"],
    ["a", "c", "business"],
    ["b", "d", "business"],
    ["c", "d", "business"],
    ["a", "d", "competitor"],
    ["a", "e", "shared-investor"],
  ];
  const adjT = new Map();
  for (const [s, t, type] of edges) {
    if (!adjT.has(s)) adjT.set(s, []);
    if (!adjT.has(t)) adjT.set(t, []);
    adjT.get(s).push({ to: t, type, verified: true });
    adjT.get(t).push({ to: s, type, verified: true });
  }
  return adjT;
}
const FRICTION = { business: 1, "shared-investor": 2, competitor: 10 };

test("dijkstra respects friction weights (typed edges price differently)", () => {
  const { dist } = dijkstra(toyAdjT(), FRICTION, "a");
  assert.equal(dist.get("a"), 0);
  assert.equal(dist.get("b"), 1);
  assert.equal(dist.get("c"), 1);
  assert.equal(dist.get("d"), 2); // via b/c, NOT the direct competitor edge (10)
  assert.equal(dist.get("e"), 2); // shared-investor weight
});

test("dijkstra breaks equal-cost ties by the lexicographically smaller predecessor", () => {
  const { dist, prev } = dijkstra(toyAdjT(), FRICTION, "a");
  assert.equal(dist.get("d"), 2);
  assert.equal(prev.get("d"), "b"); // b < c, both give cost 2
  assert.deepEqual(pathTo(prev, "a", "d"), ["a", "b", "d"]);
});

test("pathTo returns null for unreachable targets", () => {
  const adjT = toyAdjT();
  adjT.set("z", []); // isolated
  const { prev } = dijkstra(adjT, FRICTION, "a");
  assert.equal(pathTo(prev, "a", "z"), null);
});

test("unknown edge types default to weight 1", () => {
  const adjT = new Map([
    ["a", [{ to: "b", type: "mystery", verified: false }]],
    ["b", [{ to: "a", type: "mystery", verified: false }]],
  ]);
  const { dist } = dijkstra(adjT, FRICTION, "a");
  assert.equal(dist.get("b"), 1);
});

/* ---------- knn ---------- */

test("knn ranks by euclidean distance over ALL dims, ties by id", () => {
  const ids = ["a", "b", "c", "d"];
  const coords = [
    [0, 0, 0],
    [1, 0, 0], // d=1
    [-1, 0, 0], // d=1 (tie with b → id order: b before c)
    [0, 2, 1], // d=sqrt(5)
  ];
  const nn = knn(coords, ids, 0, 3);
  assert.deepEqual(
    nn.map((r) => r.id),
    ["b", "c", "d"],
  );
  assert.equal(nn[0].d, 1);
  assert.equal(nn[2].d, Math.sqrt(5));
});

test("knn excludes the seat itself and caps at k", () => {
  const ids = ["a", "b", "c"];
  const coords = [
    [0, 0],
    [3, 4],
    [6, 8],
  ];
  const nn = knn(coords, ids, 0, 1);
  assert.deepEqual(nn, [{ id: "b", d: 5 }]);
});

/* ---------- fillTemplate / fmtCount ---------- */

test("fillTemplate fills known slots and leaves unknown ones verbatim", () => {
  assert.equal(fillTemplate("{a} meets {b}", { a: "X", b: "Y" }), "X meets Y");
  assert.equal(fillTemplate("{a} and {missing}", { a: "X" }), "X and {missing}");
  assert.equal(fillTemplate("{n} handshakes", { n: 3 }), "3 handshakes"); // numbers stringified
  assert.equal(fillTemplate("{a}{a}", { a: "z" }), "zz"); // repeated slot
  assert.equal(fillTemplate("no slots here", {}), "no slots here");
  assert.equal(fillTemplate("{a}", { a: "" }), ""); // empty string is a real value
});

test("fmtCount pluralizes", () => {
  assert.equal(fmtCount(1, "handshake", "handshakes"), "1 handshake");
  assert.equal(fmtCount(2, "handshake", "handshakes"), "2 handshakes");
  assert.equal(fmtCount(0, "tie", "ties"), "0 ties");
});
