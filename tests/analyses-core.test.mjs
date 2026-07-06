import { test } from "node:test";
import assert from "node:assert/strict";
import {
  extent,
  fmt,
  linearScale,
  mentionRanges,
  minimalTicks,
  orderedIdsIn,
  polarToXY,
  prospectQuadrantIds,
  quadrantOf,
  staleIdsIn,
} from "../src/scripts/analyses-core.js";

test("linearScale maps domain to range", () => {
  const s = linearScale(0, 10, 100, 200);
  assert.equal(s(0), 100);
  assert.equal(s(10), 200);
  assert.equal(s(5), 150);
});

test("linearScale degenerate domain returns midpoint", () => {
  const s = linearScale(3, 3, 0, 10);
  assert.equal(s(3), 5);
  assert.equal(s(99), 5);
});

test("minimalTicks spans lo/mid/hi", () => {
  const t = minimalTicks(0, 100);
  assert.ok(t.length >= 2 && t.length <= 3);
  assert.ok(t[0] <= t[t.length - 1]);
});

test("extent skips null and non-finite", () => {
  assert.deepEqual(extent([3, null, 1, Infinity, 2]), [1, 3]);
  assert.deepEqual(extent([]), [0, 1]);
});

test("polarToXY at angle 0 lands on +x", () => {
  const [x, y] = polarToXY(0, 2);
  assert.equal(x, 2);
  assert.ok(Math.abs(y) < 1e-12);
});

test("quadrantOf: TL=0 TR=1 BL=2 BR=3 (y up)", () => {
  assert.equal(quadrantOf(-1, 1, 0, 0), 0);
  assert.equal(quadrantOf(1, 1, 0, 0), 1);
  assert.equal(quadrantOf(-1, -1, 0, 0), 2);
  assert.equal(quadrantOf(1, -1, 0, 0), 3);
});

test("staleIdsIn finds ids missing from live set", () => {
  const data = { rows: [{ id: "a", label: "A" }, { id: "gone", label: "G" }], nested: { id: "b" } };
  const stale = staleIdsIn(data, new Set(["a", "b"]));
  assert.deepEqual([...stale], ["gone"]);
});

test("orderedIdsIn keeps table order and dedupes", () => {
  const data = {
    rows: [{ id: "top", s: 9 }, { id: "second", s: 5 }],
    also: [{ id: "top" }, { id: "third", kids: [{ id: "fourth" }] }],
    notAnId: { ID: "x", id: 42 }, // wrong key case / non-string never collected
  };
  assert.deepEqual(orderedIdsIn(data), ["top", "second", "third", "fourth"]);
  assert.deepEqual(orderedIdsIn(undefined), []);
});

test("prospectQuadrantIds: upper-left of the extent midpoints (x low, y high)", () => {
  const pts = [
    { id: "prospect", x: 0.1, y: 0.9 }, // investor-core, business-crust → in
    { id: "core-both", x: 0.9, y: 0.9 }, // x >= mx → out
    { id: "crust-both", x: 0.1, y: 0.1 }, // y < my → out
    { id: "embedded", x: 0.9, y: 0.1 },
    { id: "on-y-mid", x: 0.1, y: 0.5 }, // y >= my boundary → in (matches the .py)
  ];
  assert.deepEqual(prospectQuadrantIds(pts), ["prospect", "on-y-mid"]);
  assert.deepEqual(prospectQuadrantIds([]), []);
});

test("mentionRanges: word boundaries, longest-first, case-sensitive", () => {
  const labels = ["Zenity", "Protect AI", "Protect AI (Palo Alto Networks)", "Box"];
  const text = "Protect AI (Palo Alto Networks) and Zenity beat the toolbox; Box too, but not box.";
  const found = mentionRanges(text, labels);
  assert.deepEqual(
    found.map((r) => r.label),
    ["Protect AI (Palo Alto Networks)", "Zenity", "Box"],
  );
  // ranges reproduce the exact source slices
  for (const r of found) assert.equal(text.slice(r.start, r.end), r.label);
});

test("mentionRanges: labels with regex metachars + empty inputs", () => {
  assert.equal(mentionRanges("Bolt (StackBlitz) ships.", ["Bolt (StackBlitz)"]).length, 1);
  assert.deepEqual(mentionRanges("", ["Zenity"]), []);
  assert.deepEqual(mentionRanges("no matches here", []), []);
  // sub-3-char labels are never matched (too collision-prone in prose)
  assert.deepEqual(mentionRanges("AI is everywhere", ["AI"]), []);
});

test("fmt.usd compresses magnitudes", () => {
  assert.equal(fmt.usd(2_500_000_000), "$2.5B");
  assert.equal(fmt.usd(1_200_000), "$1.2M");
  assert.equal(fmt.usd(45_000), "$45k");
  assert.equal(fmt.usd(null), "—");
});

test("fmt.num and fmt.pct handle null", () => {
  assert.equal(fmt.num(null), "—");
  assert.equal(fmt.pct(0.256), "26%");
  assert.equal(fmt.sig(0.0001), "p<0.001");
});
