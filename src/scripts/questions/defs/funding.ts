// The five /funding questions (P3): funder-shortlist · rivals-money ·
// warm-routes · within-reach · funding-bridges. Re-aim math follows
// experiments/analyses/prep_questions.py's kernel rules 13-16 exactly
// (fixtures.json's "funding" namespace is the parity oracle).
//
// THE STALENESS RULE (hard, funding-only): names, dollar amounts, and
// apply-status ALWAYS render from the LIVE funding.json records (ctx.byId
// labels + ctx.raw.companies, which the host fills with the pristine funding
// nodes) — never from baked strings. Baked default blocks contribute ids,
// scores, ranks, and hop counts ONLY; a baked id gone from the live graph is
// dropped silently (nightly funding churn must degrade, never crash —
// enforced by tests/question-funding-degrade.test.mjs). The one sanctioned
// exception: assets.rivalJoins carries COMPANIES-graph rival names, which
// this client cannot derive from funding.json — that is the asset's reason
// to exist.
//
// Node-importable: type imports only (erased by node's type stripping) plus
// funding-core.js — the degrade test imports this module untranspiled.

import { formatUsd } from "../../funding-core.js";
import type {
  BakedQuestion,
  Callout,
  QColumn,
  QComputeCtx,
  QuestionDef,
  QuestionResult,
} from "../types";

/** The default protagonist: AoC is not a funding node, so the seat is our
 *  nearest funded proxy — assets.sources[0] (the AoC entry grantee). Must
 *  match the seat prep_questions.py bakes into every default block; the defs
 *  key on `b.default.seat`, so a mismatch degrades to the live re-aim path
 *  instead of breaking (the degrade test asserts equality). */
export const FUNDING_DEFAULT_SEAT = "gray-swan-ai";

/* ---------- live-data views (the staleness rule's machinery) ---------- */

/** The live funding.json record shape this module reads (ctx.raw.companies
 *  holds the full pristine nodes; the frozen ctx type only promises `id`). */
interface LiveNode {
  id: string;
  kind: "funder" | "grantee" | "person";
  name: string;
  funderKind?: string;
  title?: string;
  annualFieldGivingUSD?: number | null;
  fieldDollarsUSD?: number;
  apply?: { mode: string; deadline?: string };
}

const liveCache = new WeakMap<object, Map<string, LiveNode>>();
function liveMap(ctx: QComputeCtx): Map<string, LiveNode> {
  let m = liveCache.get(ctx.raw);
  if (!m) {
    m = new Map((ctx.raw.companies as LiveNode[]).map((n) => [n.id, n]));
    liveCache.set(ctx.raw, m);
  }
  return m;
}

const alive = (ctx: QComputeCtx, id: string): boolean => ctx.byId.has(id);

function labelOf(ctx: QComputeCtx, id: string): string {
  // live label or the id itself — NEVER the baked payload's label array
  return ctx.byId.get(id)?.label ?? liveMap(ctx).get(id)?.name ?? id;
}

/** Field-relevant dollars, live: funders give, grantees have raised. */
function givesOf(n: LiveNode | undefined): number | null {
  if (!n) return null;
  if (n.kind === "funder") return n.annualFieldGivingUSD ?? null;
  if (n.kind === "grantee") return n.fieldDollarsUSD || null;
  return null;
}

/** Apply-door state, live (mode only — open-now needs the snapshot clock). */
function doorOf(n: LiveNode | undefined): string {
  return n?.kind === "funder" ? (n.apply?.mode ?? "—") : "";
}

const kindOf = (ctx: QComputeCtx, id: string): string | undefined =>
  liveMap(ctx).get(id)?.kind;

// buildGraph is O(E) and reused by every re-aim — one graph per raw dataset
// (rule 13: the funding kernel graph is rules 1-3 over funding.json verbatim)
type KernelGraph = ReturnType<QComputeCtx["kernels"]["buildGraph"]>;
const graphCache = new WeakMap<object, KernelGraph>();
function kernelGraph(ctx: QComputeCtx): KernelGraph {
  let g = graphCache.get(ctx.raw);
  if (!g) {
    g = ctx.kernels.buildGraph(ctx.raw); // raw already has {companies, edges}
    graphCache.set(ctx.raw, g);
  }
  return g;
}

function bakedQ(ctx: QComputeCtx, slug: string): BakedQuestion {
  const q = ctx.payload.questions[slug];
  if (!q) throw new Error(`questions payload is missing "${slug}"`);
  return q;
}

/** Baked default rows, live-filtered to {id, baked numeric fields} — the
 *  ids/scores/ranks the staleness rule allows through. */
function bakedIds(ctx: QComputeCtx, b: BakedQuestion): Record<string, unknown>[] {
  return b.default.rows.filter((r) => typeof r.id === "string" && alive(ctx, r.id as string));
}

/* ---------- P3 assets & params (frozen types.ts doesn't carry them;
 * shapes follow prep_questions.py's "Funding asset formats" section) ---------- */

interface FunderFitAsset {
  d: number;
  funders: { ids: string[]; X: number[][] };
  grantees: { ids: string[]; X: number[][] };
  seeds: string[];
}
interface RivalJoin {
  id: string; // funding-graph funder
  rivalId: string; // companies-graph — NOT a funding node
  rivalLabel: string; // sanctioned baked name (client can't derive it)
  usd: number | null;
  live: boolean;
}
interface P3Assets {
  funderFit?: FunderFitAsset;
  rivalJoins?: RivalJoin[];
  sources?: { id: string; label: string; aocDistance: number }[];
}
interface P3Params {
  ffTopN?: number;
  doorIds?: string[];
}
const p3Assets = (ctx: QComputeCtx): P3Assets => ctx.payload.assets as P3Assets;
const p3Params = (ctx: QComputeCtx): P3Params => ctx.payload.params as unknown as P3Params;
const frictionOf = (ctx: QComputeCtx): Record<string, number> =>
  ctx.payload.params?.friction ?? {};

const uniq = <T>(xs: T[]): T[] => [...new Set(xs)];

function isolatedResult(sentence: string, columns: QColumn[], seat: string): QuestionResult {
  return {
    litIds: [],
    anchorIds: [],
    sentence,
    callouts: [],
    marks: {},
    rows: [],
    columns,
    focusIds: [seat],
  };
}

/* ---------- columns (all display fields live; scores/ranks/hops are the
 * only baked-or-kernel numbers) ---------- */

const SHORTLIST_COLS: QColumn[] = [
  { key: "label", label: "funder", format: "text" },
  { key: "kind", label: "kind", format: "text" },
  { key: "score", label: "fit", format: "num", digits: 3 },
  { key: "gives", label: "gives", format: "usd" },
  { key: "door", label: "door", format: "text" },
];
const RIVAL_COLS: QColumn[] = [
  { key: "label", label: "funder", format: "text" },
  { key: "kind", label: "kind", format: "text" },
  { key: "backs", label: "rivals backed", format: "text" },
  { key: "rivalUsd", label: "rival $", format: "usd" },
  { key: "door", label: "door", format: "text" },
];
const ROUTE_COLS: QColumn[] = [
  { key: "label", label: "funder", format: "text" },
  { key: "via", label: "via", format: "text" },
  { key: "hops", label: "handshakes", format: "num", digits: 0 },
];
const REACH_COLS: QColumn[] = [
  { key: "label", label: "funder", format: "text" },
  { key: "reach", label: "reach", format: "num", digits: 4 },
  { key: "hops", label: "handshakes", format: "num", digits: 0 },
  { key: "gives", label: "gives", format: "usd" },
  { key: "door", label: "door", format: "text" },
];
const BRIDGE_BAKED_COLS: QColumn[] = [
  { key: "label", label: "person", format: "text" },
  { key: "role", label: "role", format: "text" },
  { key: "funder", label: "door to", format: "text" },
  { key: "gates", label: "gates", format: "usd" },
  { key: "hops", label: "handshakes", format: "num", digits: 0 },
];
const BRIDGE_LIVE_COLS: QColumn[] = [
  { key: "label", label: "who", format: "text" },
  { key: "kind", label: "kind", format: "text" },
  { key: "doors", label: "doors gated", format: "num", digits: 0 },
  { key: "hops", label: "handshakes", format: "num", digits: 0 },
];

/** One live funder row (shared by shortlist / rivals / within-reach). */
function funderRow(ctx: QComputeCtx, id: string, extra: Record<string, unknown> = {}) {
  const n = liveMap(ctx).get(id);
  return {
    id,
    label: labelOf(ctx, id),
    kind: n?.funderKind ?? n?.kind ?? "",
    gives: givesOf(n),
    door: doorOf(n),
    ...extra,
  };
}

const givesNote = (ctx: QComputeCtx, id: string): string => {
  const g = givesOf(liveMap(ctx).get(id));
  return g != null ? ` · gives ${formatUsd(g)}` : "";
};

const handshakes = (ctx: QComputeCtx, n: number): string =>
  ctx.kernels.fmtCount(n, "handshake", "handshakes");

/* ---------- funder-shortlist: Which funders should we apply to now? ----------
 * Default seat = the baked funder-fit ranking (ids + scores). Re-aim = spec
 * rule 15: seat's own embedding row (grantee or funder) dotted against every
 * funder via kernels.dotRank, top ffTopN. Seats outside the money matrix are
 * unrankable → isolated template. */

function computeFunderShortlist(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "funder-shortlist");
  const k = ctx.kernels;
  const seatName = labelOf(ctx, seat);
  const ff = p3Assets(ctx).funderFit;

  let ranked: { id: string; score: number | null }[];
  let embeddable = ff ? ff.funders.ids.length : 0;
  if (seat === b.default.seat || !ff) {
    // the virtual-AoC shortlist, ids+scores only, dead rows dropped
    ranked = bakedIds(ctx, b).map((r) => ({
      id: r.id as string,
      score: typeof r.score === "number" ? r.score : null,
    }));
  } else {
    const gi = ff.grantees.ids.indexOf(seat);
    const fi = ff.funders.ids.indexOf(seat);
    if (gi < 0 && fi < 0)
      return isolatedResult(
        k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
        SHORTLIST_COLS,
        seat,
      );
    const v = gi >= 0 ? ff.grantees.X[gi] : ff.funders.X[fi];
    if (fi >= 0) embeddable -= 1; // candidates = funders.ids minus the seat
    ranked = k
      .dotRank(ff.funders.X, ff.funders.ids, v, p3Params(ctx).ffTopN ?? 15, seat)
      .filter((r) => alive(ctx, r.id))
      .map((r) => ({ id: r.id, score: r.s }));
  }
  if (!ranked.length)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      SHORTLIST_COLS,
      seat,
    );

  // self variant: the seat is itself on the baked structural shortlist
  const selfIdx =
    seat !== b.default.seat ? b.default.rows.findIndex((r) => r.id === seat) : -1;
  const sentence =
    selfIdx >= 0
      ? k.fillTemplate(b.templates.self, {
          seat: seatName,
          rank: selfIdx + 1,
          n: embeddable || b.default.rows.length,
        })
      : k.fillTemplate(b.templates.default, {
          top: labelOf(ctx, ranked[0].id),
          // "…orgs shaped like {name}": the default ranking is the virtual-AoC
          // seat, not the proxy grantee — "us" is the honest fill
          name: seat === b.default.seat ? "us" : seatName,
          seat: seatName,
          n: embeddable || ranked.length,
        });

  const litIds = ranked.map((r) => r.id);
  const anchorIds = litIds.slice(0, 3);
  return {
    litIds,
    anchorIds,
    sentence,
    callouts: anchorIds.map((id, i) => ({
      id,
      text: `#${i + 1} structural fit${givesNote(ctx, id)}`,
    })),
    marks: {},
    rows: ranked.map((r) => funderRow(ctx, r.id, { score: r.score })),
    columns: SHORTLIST_COLS,
    focusIds: uniq([...litIds, seat]).filter((id) => alive(ctx, id)),
  };
}

/* ---------- rivals-money: Who funds our rivals? ----------
 * The funder↔rival join is a CROSS-GRAPH fact (assets.rivalJoins exists
 * because this client can't derive companies-graph names); the flagged set
 * holds at every seat. Re-aiming re-words it: a backer seat gets the self
 * variant with ITS rivals; everyone else sees the top backer's exposure. */

function computeRivalsMoney(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "rivals-money");
  const k = ctx.kernels;
  const seatName = labelOf(ctx, seat);
  const joins = (p3Assets(ctx).rivalJoins ?? []).filter((j) => alive(ctx, j.id));
  const joinsBy = new Map<string, RivalJoin[]>();
  for (const j of joins) {
    const l = joinsBy.get(j.id);
    if (l) l.push(j);
    else joinsBy.set(j.id, [j]);
  }
  const rivalsOf = (id: string) =>
    uniq((joinsBy.get(id) ?? []).map((j) => j.rivalLabel)).join(", ");
  const rivalUsdOf = (id: string) => {
    const amounts = (joinsBy.get(id) ?? []).flatMap((j) => (j.usd != null ? [j.usd] : []));
    return amounts.length ? amounts.reduce((a, x) => a + x, 0) : null;
  };

  // rows keep the baked order: backers first, clean in-lane funders after
  const rowIds = bakedIds(ctx, b).map((r) => r.id as string);
  const backers = rowIds.filter((id) => joinsBy.has(id));
  const clean = rowIds.filter((id) => !joinsBy.has(id));
  if (!rowIds.length)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      RIVAL_COLS,
      seat,
    );

  const moneyDeg = (ctx.adjT.get(seat) ?? []).filter((e) => e.type !== "affiliation").length;
  let sentence: string;
  if (seat === b.default.seat) {
    sentence = `${backers.length} tracked checkbooks already fund a flagged rival — ${clean.length} clean funders back the same lanes without touching one.`;
  } else if (joinsBy.has(seat)) {
    sentence = k.fillTemplate(b.templates.self, { seat: seatName, rivals: rivalsOf(seat) });
  } else if (moneyDeg === 0) {
    sentence = k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName });
  } else if (backers.length) {
    sentence = k.fillTemplate(b.templates.default, {
      name: labelOf(ctx, backers[0]),
      seat: seatName,
      rivals: rivalsOf(backers[0]),
    });
  } else {
    sentence = `No live funder is behind a flagged rival right now — ${clean.length} clean doors back our lanes.`;
  }

  const anchorIds = joinsBy.has(seat)
    ? [seat]
    : [...backers.slice(0, 2), ...clean.slice(0, 1)].slice(0, 3);
  const callouts: Callout[] = anchorIds.map((id) => ({
    id,
    text: joinsBy.has(id)
      ? `backs ${rivalsOf(id)}`
      : `clean in-lane door${givesNote(ctx, id)}`,
  }));

  return {
    litIds: rowIds,
    anchorIds,
    sentence,
    callouts,
    marks: {},
    rows: rowIds.map((id) =>
      funderRow(ctx, id, { backs: rivalsOf(id) || "—", rivalUsd: rivalUsdOf(id) }),
    ),
    columns: RIVAL_COLS,
    focusIds: uniq([...rowIds, seat]).filter((id) => alive(ctx, id)),
  };
}

/* ---------- warm-routes: Who can introduce us to a funder? ----------
 * Default seat = the baked multi-source routes (ids/hops only; every path
 * with a dead hop is dropped whole). Re-aim = live dijkstra from the seat
 * (params.friction — every hop equal, priced from data) toward the baked
 * target funders; a route must never claim a dead hop. */

function computeWarmRoutes(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "warm-routes");
  const k = ctx.kernels;
  const seatName = labelOf(ctx, seat);

  if (seat === b.default.seat) {
    const rows = bakedIds(ctx, b)
      .filter((r) => typeof r.from === "string" && alive(ctx, r.from as string))
      .map((r) => ({
        id: r.id as string,
        label: labelOf(ctx, r.id as string),
        via: labelOf(ctx, r.from as string),
        hops: typeof r.hops === "number" ? r.hops : null,
      }));
    const paths = (b.default.marks.paths ?? []).filter((p) =>
      p.every((id) => alive(ctx, id)),
    );
    if (rows.length) {
      const best = rows[0];
      const litIds = uniq([...b.default.ids.filter((id) => alive(ctx, id)), ...paths.flat()]);
      return {
        litIds,
        anchorIds: [best.id],
        sentence: k.fillTemplate(b.templates.default, {
          target: best.label,
          from: best.via,
          hops: best.hops != null ? handshakes(ctx, best.hops) : "a short walk",
        }),
        callouts: [
          { id: best.id, text: `warmest door · ${best.hops != null ? handshakes(ctx, best.hops) : "nearest"} out` },
        ],
        marks: { paths },
        rows,
        columns: ROUTE_COLS,
        focusIds: paths[0] ?? litIds,
      };
    }
    // every baked route died — fall through to the live walk from the seat
  }

  if (!ctx.adjT.get(seat)?.length)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      ROUTE_COLS,
      seat,
    );

  // targets: the baked answer's funders, live-filtered; if all churned away,
  // the biggest live doors stand in
  let targets = uniq([
    ...b.default.rows.map((r) => r.id).filter((id): id is string => typeof id === "string"),
    ...b.default.ids,
  ]).filter((id) => id !== seat && alive(ctx, id) && kindOf(ctx, id) === "funder");
  if (!targets.length) {
    targets = [...liveMap(ctx).values()]
      .filter((n) => n.kind === "funder" && n.id !== seat && (n.annualFieldGivingUSD ?? 0) > 0)
      .sort(
        (a, z) =>
          (z.annualFieldGivingUSD ?? 0) - (a.annualFieldGivingUSD ?? 0) ||
          (a.id < z.id ? -1 : 1),
      )
      .slice(0, 8)
      .map((n) => n.id);
  }

  const { dist, prev } = k.dijkstra(ctx.adjT, frictionOf(ctx), seat);
  const found: {
    id: string;
    label: string;
    via: string;
    hops: number;
    cost: number;
    path: string[];
  }[] = [];
  for (const tid of targets) {
    const path = k.pathTo(prev, seat, tid);
    if (!path || path.length < 2) continue;
    const hops = path.length - 1;
    found.push({
      id: tid,
      label: labelOf(ctx, tid),
      via: hops === 1 ? "direct" : labelOf(ctx, path[1]),
      hops,
      cost: dist.get(tid) ?? Number.POSITIVE_INFINITY,
      path,
    });
  }
  if (!found.length)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      ROUTE_COLS,
      seat,
    );
  found.sort((a, z) => a.cost - z.cost || (a.id < z.id ? -1 : 1));

  const best = found[0];
  const litIds = uniq(found.flatMap((f) => f.path));
  const anchorIds = best.hops > 1 ? [best.id, best.path[1]] : [best.id];
  const callouts: Callout[] = [
    { id: best.id, text: `best route · ${handshakes(ctx, best.hops)}` },
  ];
  if (best.hops > 1) callouts.push({ id: best.path[1], text: "the route opens here" });
  return {
    litIds,
    anchorIds,
    sentence: k.fillTemplate(b.templates.default, {
      target: best.label,
      from: best.hops === 1 ? "a direct tie" : labelOf(ctx, best.path[1]),
      hops: handshakes(ctx, best.hops),
    }),
    callouts,
    marks: { paths: found.slice(0, 5).map((f) => f.path) },
    rows: found.map(({ path: _path, cost: _cost, ...row }) => row),
    columns: ROUTE_COLS,
    focusIds: best.path,
  };
}

/* ---------- within-reach: Which funders are within reach? ----------
 * Default seat = the baked multi-seed walk (ids/scores/hops). Re-aim = spec
 * rule 14: single-seed PPR (kernels.ppr, the fixture-locked iteration) on
 * the rule-13 graph; funder-kind nodes with mass, top-25 by (-sFull, id),
 * hops from live BFS. No envelope exists — the appendix maps this to
 * proximity-rank. */

function computeWithinReach(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "within-reach");
  const k = ctx.kernels;
  const seatName = labelOf(ctx, seat);
  const live = liveMap(ctx);
  const nf = [...live.values()].filter((n) => n.kind === "funder").length;

  if (seat === b.default.seat) {
    const baked = bakedIds(ctx, b).map((r) => ({
      id: r.id as string,
      reach: typeof r.s === "number" ? r.s : null,
      hops: typeof r.hops === "number" ? r.hops : null,
    }));
    if (baked.length) {
      const litIds = baked.map((r) => r.id);
      const anchorIds = litIds.slice(0, 3);
      return {
        litIds,
        anchorIds,
        sentence: k.fillTemplate(b.templates.default, {
          seat: seatName,
          top: labelOf(ctx, baked[0].id),
          n: baked.length,
          nf,
        }),
        callouts: anchorIds.map((id, i) => {
          const h = baked[i].hops;
          return {
            id,
            text: `#${i + 1} within reach${h != null ? ` · ${h === 1 ? "one handshake" : handshakes(ctx, h)}` : ""}`,
          };
        }),
        marks: {},
        rows: baked.map((r) => funderRow(ctx, r.id, { reach: r.reach, hops: r.hops })),
        columns: REACH_COLS,
        focusIds: uniq([...litIds, seat]).filter((id) => alive(ctx, id)),
      };
    }
    // every baked row died — fall through to the live walk
  }

  const g = kernelGraph(ctx);
  const si = g.idx.get(seat);
  if (si === undefined || g.deg[si] === 0)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      REACH_COLS,
      seat,
    );

  const x = k.ppr(g, si, ctx.payload.params?.pprAlpha ?? 0.85, ctx.payload.params?.pprIters ?? 100);
  const hopsAll = k.bfsDist(g, si);
  const order = Array.from({ length: g.n }, (_, i) => i).sort((a, z) =>
    x[a] !== x[z] ? x[z] - x[a] : g.ids[a] < g.ids[z] ? -1 : 1,
  );
  const ranked: { id: string; reach: number; hops: number | null }[] = [];
  let reachableFunders = 0;
  for (const i of order) {
    const id = g.ids[i];
    if (id === seat || x[i] <= 0 || kindOf(ctx, id) !== "funder") continue;
    reachableFunders += 1;
    if (ranked.length < 25)
      ranked.push({ id, reach: k.round9(x[i]), hops: hopsAll[i] >= 0 ? hopsAll[i] : null });
  }
  if (!ranked.length)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      REACH_COLS,
      seat,
    );

  // self variant: the seat is a funder the baked walk already reaches
  const selfRow = seat !== b.default.seat ? b.default.rows.find((r) => r.id === seat) : undefined;
  const sentence = selfRow
    ? k.fillTemplate(b.templates.self, {
        seat: seatName,
        rank: b.default.rows.indexOf(selfRow) + 1,
        hops:
          typeof selfRow.hops === "number"
            ? handshakes(ctx, selfRow.hops)
            : "a short walk",
      })
    : k.fillTemplate(b.templates.default, {
        seat: seatName,
        top: labelOf(ctx, ranked[0].id),
        n: reachableFunders,
        nf,
      });

  const litIds = ranked.map((r) => r.id);
  const anchorIds = litIds.slice(0, 3);
  return {
    litIds,
    anchorIds,
    sentence,
    callouts: anchorIds.map((id, i) => {
      const h = ranked[i].hops;
      return {
        id,
        text: `#${i + 1} within reach${h != null ? ` · ${h === 1 ? "one handshake" : handshakes(ctx, h)}` : ""}`,
      };
    }),
    marks: {},
    rows: ranked.map((r) => funderRow(ctx, r.id, { reach: r.reach, hops: r.hops })),
    columns: REACH_COLS,
    focusIds: uniq([seat, ...litIds]),
  };
}

/* ---------- funding-bridges: Who gatekeeps the money? ----------
 * Default seat = the baked doorkeeper set (money-brokers' people; ids only —
 * the dollars a door gates are re-summed from live giving). Re-aim = spec
 * rule 16 (kernels.moneyPaths): who sits on the seat's shortest routes to
 * params.doorIds, all-integer math. */

function computeFundingBridges(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "funding-bridges");
  const k = ctx.kernels;
  const seatName = labelOf(ctx, seat);
  const live = liveMap(ctx);

  // live door facts per person: affiliated funders + the dollars they gate
  const doorsOf = (pid: string) =>
    uniq(
      (ctx.adjT.get(pid) ?? []).filter((e) => e.type === "affiliation").map((e) => e.to),
    ).filter((fid) => live.get(fid)?.kind === "funder");
  const gatesOf = (pid: string) =>
    doorsOf(pid).reduce((sum, fid) => sum + (live.get(fid)?.annualFieldGivingUSD ?? 0), 0);
  const mainDoor = (pid: string) => {
    const doors = doorsOf(pid);
    if (!doors.length) return null;
    return doors.sort(
      (a, z) =>
        (live.get(z)?.annualFieldGivingUSD ?? 0) - (live.get(a)?.annualFieldGivingUSD ?? 0) ||
        (a < z ? -1 : 1),
    )[0];
  };

  if (seat === b.default.seat) {
    const keeperIds = bakedIds(ctx, b)
      .map((r) => r.id as string)
      .filter((id) => live.get(id)?.kind === "person");
    if (keeperIds.length) {
      const g = kernelGraph(ctx);
      const si = g.idx.get(seat);
      const hopsAll = si !== undefined ? k.bfsDist(g, si) : null;
      const rows = keeperIds.map((id) => {
        const door = mainDoor(id);
        const hi = hopsAll ? hopsAll[g.idx.get(id)!] : -1;
        return {
          id,
          label: labelOf(ctx, id),
          role: live.get(id)?.title ?? "—",
          funder: door ? labelOf(ctx, door) : "—",
          doorId: door,
          gates: gatesOf(id),
          hops: hi >= 0 ? hi : null,
        };
      });
      // the dollars behind the doors, deduped across keepers sharing a funder
      const gatedTotal = uniq(keeperIds.flatMap(doorsOf)).reduce(
        (sum, fid) => sum + (live.get(fid)?.annualFieldGivingUSD ?? 0),
        0,
      );
      const top = rows[0];
      const litIds = uniq(rows.flatMap((r) => (r.doorId ? [r.id, r.doorId] : [r.id])));
      const anchorIds = rows.slice(0, 3).map((r) => r.id);
      return {
        litIds,
        anchorIds,
        sentence: `${rows.length} named people hold the doors to ${formatUsd(gatedTotal)} a year of tracked field money — ${top.label} holds the biggest at ${top.funder}.`,
        callouts: rows.slice(0, 3).map((r) => ({
          id: r.id,
          // a door with no public $ still gates it — never claim "$0/yr"
          text:
            r.gates > 0
              ? `holds ${formatUsd(r.gates)}/yr${r.funder !== "—" ? ` · ${r.funder}` : ""}`
              : `holds the door${r.funder !== "—" ? ` · ${r.funder}` : ""}`,
        })),
        marks: {},
        rows: rows.map(({ doorId: _d, ...row }) => row),
        columns: BRIDGE_BAKED_COLS,
        focusIds: uniq([...litIds, seat]).filter((id) => alive(ctx, id)),
      };
    }
    // every baked doorkeeper churned away — fall through to the live kernel
  }

  const g = kernelGraph(ctx);
  const si = g.idx.get(seat);
  const doorIds = (p3Params(ctx).doorIds ?? []).filter((id) => alive(ctx, id));
  const gaters = si !== undefined && doorIds.length ? k.moneyPaths(g, si, doorIds) : [];
  // self variant: the seat is itself one of the baked doorkeepers
  const selfRow = b.default.rows.find((r) => r.id === seat);
  if (selfRow) {
    const door = mainDoor(seat);
    return {
      litIds: uniq([seat, ...(door ? [door] : [])]),
      anchorIds: [seat],
      sentence: k.fillTemplate(b.templates.self, {
        seat: seatName,
        funder: door ? labelOf(ctx, door) : "its funder",
      }),
      callouts: [
        {
          id: seat,
          text: gatesOf(seat) > 0 ? `holds ${formatUsd(gatesOf(seat))}/yr` : "holds the door",
        },
      ],
      marks: {},
      rows: gaters.map((r) => ({
        id: r.id,
        label: labelOf(ctx, r.id),
        kind: kindOf(ctx, r.id) ?? "",
        doors: r.s,
        hops: r.d,
      })),
      columns: BRIDGE_LIVE_COLS,
      focusIds: uniq([seat, ...(door ? [door] : [])]),
    };
  }
  if (!gaters.length)
    return isolatedResult(
      k.fillTemplate(b.templates.isolated, { seat: seatName, name: seatName }),
      BRIDGE_LIVE_COLS,
      seat,
    );

  const top = gaters[0];
  // one route ribbon: the seat's shortest path through the top gater
  const { prev } = k.dijkstra(ctx.adjT, frictionOf(ctx), seat);
  const path = k.pathTo(prev, seat, top.id);
  const litIds = gaters.map((r) => r.id);
  const anchorIds = litIds.slice(0, 3);
  return {
    litIds,
    anchorIds,
    sentence: k.fillTemplate(b.templates.default, {
      name: labelOf(ctx, top.id),
      seat: seatName,
      doors: top.s,
    }),
    callouts: gaters.slice(0, 3).map((r) => ({
      id: r.id,
      text: `gates ${r.s} of ${doorIds.length} doors · ${handshakes(ctx, r.d)} out`,
    })),
    marks: path && path.length > 1 ? { paths: [path] } : {},
    rows: gaters.map((r) => ({
      id: r.id,
      label: labelOf(ctx, r.id),
      kind: kindOf(ctx, r.id) ?? "",
      doors: r.s,
      hops: r.d,
    })),
    columns: BRIDGE_LIVE_COLS,
    focusIds: uniq([seat, ...litIds]),
  };
}

/* ---------- exports ---------- */

export function makeFundingDefs(): QuestionDef[] {
  return [
    {
      id: "funder-shortlist",
      question: "Which funders should we apply to now?",
      source: ["funder-fit"],
      legacyAn: ["funder-fit", "funder-shortlist"],
      reframe: "focus",
      compute: computeFunderShortlist,
    },
    {
      id: "rivals-money",
      question: "Who funds our rivals?",
      source: ["rivals-money"],
      legacyAn: ["rivals-money"],
      reframe: "focus",
      compute: computeRivalsMoney,
    },
    {
      id: "warm-routes",
      question: "Who can introduce us to a funder?",
      source: ["intro-chains"],
      legacyAn: ["intro-chains"],
      reframe: "focus",
      compute: computeWarmRoutes,
    },
    {
      id: "within-reach",
      question: "Which funders are within reach?",
      source: ["proximity-rank"],
      legacyAn: ["proximity-rank"],
      reframe: "focus",
      compute: computeWithinReach,
    },
    {
      id: "funding-bridges",
      question: "Who gatekeeps the money?",
      source: ["money-brokers"],
      legacyAn: ["money-brokers"],
      reframe: "focus",
      compute: computeFundingBridges,
    },
  ];
}
