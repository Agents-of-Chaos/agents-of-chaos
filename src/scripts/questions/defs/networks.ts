// The three P1 /networks questions (bridges · meet-first · market-shape).
// Each compute() returns the baked default VERBATIM for the default seat —
// default-seat numbers come only from the baked envelopes — and re-aims with
// the pure kernels (kernels.js) for any other seat. Row shapes and template
// slots mirror experiments/analyses/prep_questions.py exactly.

import type {
  BakedQuestion,
  Callout,
  QColumn,
  QComputeCtx,
  QuestionDef,
  QuestionPayload,
  QuestionResult,
} from "../types";

/* ---------- shared helpers ---------- */

// buildGraph is O(E) and reused by every re-aim — cache one graph per raw
// dataset (the pristine records object is stable for the page's lifetime).
type KernelGraph = ReturnType<QComputeCtx["kernels"]["buildGraph"]>;
const graphCache = new WeakMap<object, KernelGraph>();
function kernelGraph(ctx: QComputeCtx): KernelGraph {
  let g = graphCache.get(ctx.raw);
  if (!g) {
    g = ctx.kernels.buildGraph(ctx.raw);
    graphCache.set(ctx.raw, g);
  }
  return g;
}

function labelOf(ctx: QComputeCtx, id: string): string {
  const n = ctx.byId.get(id);
  if (n) return n.label;
  const i = ctx.payload.nodes.ids.indexOf(id);
  return i >= 0 ? ctx.payload.nodes.label[i] : id;
}

/** Distinct verticals among a node's direct ties — brokers.py's `spans`. */
function spansOf(ctx: QComputeCtx, id: string): number {
  const groups = new Set<string>();
  for (const e of ctx.adjT.get(id) ?? []) {
    const g = ctx.byId.get(e.to)?.group;
    if (g) groups.add(g);
  }
  return groups.size;
}

function bakedQ(ctx: QComputeCtx, slug: string): BakedQuestion {
  const q = ctx.payload.questions[slug];
  if (!q) throw new Error(`questions payload is missing "${slug}"`);
  return q;
}

/** The baked default answer, verbatim (anchors = the callouts' nodes). */
function bakedDefault(b: BakedQuestion, columns: QColumn[], focusIds: string[]): QuestionResult {
  return {
    litIds: b.default.ids,
    anchorIds: b.default.callouts.map((c) => c.id),
    sentence: b.default.sentence,
    callouts: b.default.callouts,
    marks: b.default.marks,
    rows: b.default.rows,
    columns,
    focusIds,
  };
}

function isolated(ctx: QComputeCtx, b: BakedQuestion, seat: string, columns: QColumn[]): QuestionResult {
  const tpl = b.templates.isolated ?? b.templates.default;
  const name = labelOf(ctx, seat);
  return {
    litIds: [],
    anchorIds: [],
    sentence: ctx.kernels.fillTemplate(tpl, { seat: name, name }),
    callouts: [],
    marks: {},
    rows: [],
    columns,
    focusIds: [seat],
  };
}

/* ---------- columns (baked-row shapes read from the emitter/envelopes) ---------- */

const BRIDGES_BAKED_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "degree", label: "ties", format: "num", digits: 0 },
  { key: "constraint", label: "constraint", format: "num", digits: 3 },
  { key: "effSize", label: "eff. size", format: "num", digits: 1 },
  { key: "spans", label: "spans", format: "num", digits: 0 },
];
const BRIDGES_LIVE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "constraint", label: "constraint", format: "num", digits: 3 },
  { key: "degree", label: "ties", format: "num", digits: 0 },
];
const MEET_BAKED_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "via", label: "via", format: "text" },
  { key: "hops", label: "handshakes", format: "num", digits: 0 },
  { key: "rank", label: "reach rank", format: "num", digits: 0 },
];
const MEET_LIVE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "via", label: "via", format: "text" },
  { key: "hops", label: "handshakes", format: "num", digits: 0 },
  { key: "cost", label: "friction", format: "num", digits: 0 },
];
const SHAPE_BAKED_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "distance", label: "distance", format: "num", digits: 3 },
  { key: "intensity", label: "intensity", format: "num", digits: 0 },
  { key: "flag", label: "", format: "flag" },
];
const SHAPE_LIVE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "d", label: "distance", format: "num", digits: 3 },
];

/* ---------- bridges: Who bridges the market? (brokers) ---------- */

function computeBridges(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "bridges");
  if (seat === ctx.defaultSeat)
    return bakedDefault(b, BRIDGES_BAKED_COLS, [...new Set([...b.default.ids, seat])]);

  const k = ctx.kernels;
  const g = kernelGraph(ctx);
  const si = g.idx.get(seat);
  if (si === undefined || g.deg[si] === 0) return isolated(ctx, b, seat, BRIDGES_LIVE_COLS);
  const top = k.constraintTop10(g, si, ctx.payload.params.minDegree);
  if (!top.length) return isolated(ctx, b, seat, BRIDGES_LIVE_COLS);

  const rows = top.map((r) => ({
    id: r.id,
    label: labelOf(ctx, r.id),
    constraint: r.c,
    degree: r.degree,
  }));
  // self variant: the seat is itself one of the market's baked top brokers
  const selfIdx = b.default.rows.findIndex((r) => r.id === seat);
  const sentence =
    selfIdx >= 0
      ? k.fillTemplate(b.templates.self, {
          seat: labelOf(ctx, seat),
          rank: selfIdx + 1,
          n: b.default.rows.length,
          spans: b.default.rows[selfIdx].spans as number,
        })
      : k.fillTemplate(b.templates.default, {
          name: labelOf(ctx, top[0].id),
          seat: labelOf(ctx, seat),
          spans: spansOf(ctx, top[0].id),
        });

  const litIds = top.map((r) => r.id);
  const anchorIds = litIds.slice(0, 3);
  const callouts: Callout[] = anchorIds.map((id, i) => ({
    id,
    text: `#${i + 1} bridge · spans ${spansOf(ctx, id)} verticals`,
  }));
  return {
    litIds,
    anchorIds,
    sentence,
    callouts,
    marks: {},
    rows,
    columns: BRIDGES_LIVE_COLS,
    focusIds: [...new Set([...litIds, seat])],
  };
}

/* ---------- meet-first: Who should we meet first? (intro-chains + proximity) ---------- */

function computeMeetFirst(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "meet-first");
  if (seat === ctx.defaultSeat)
    return bakedDefault(b, MEET_BAKED_COLS, b.default.marks.paths?.[0] ?? b.default.ids);

  const k = ctx.kernels;
  if (!ctx.adjT.get(seat)?.length) return isolated(ctx, b, seat, MEET_LIVE_COLS);
  const { dist, prev } = k.dijkstra(ctx.adjT, ctx.payload.params.friction, seat);

  // canonical target set = the baked default rows (the market's top prospects)
  const targets = b.default.rows
    .map((r) => r.id as string)
    .filter((id) => typeof id === "string" && id !== seat);
  const found: { id: string; label: string; via: string; hops: number; cost: number; path: string[] }[] = [];
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
  if (!found.length) return isolated(ctx, b, seat, MEET_LIVE_COLS);
  found.sort((a, z) => a.cost - z.cost || (a.id < z.id ? -1 : 1));

  const best = found[0];
  const paths = found.slice(0, 5).map((f) => f.path);
  const litIds: string[] = [];
  for (const f of found) for (const id of f.path) if (!litIds.includes(id)) litIds.push(id);

  const anchorIds = best.hops > 1 ? [best.id, best.path[1]] : [best.id];
  const callouts: Callout[] = [
    { id: best.id, text: `best route · ${k.fmtCount(best.hops, "handshake", "handshakes")}` },
  ];
  if (best.hops > 1) callouts.push({ id: best.path[1], text: "the route opens here" });
  const sentence = k.fillTemplate(b.templates.default, {
    target: best.label,
    via: best.hops === 1 ? "a direct tie" : labelOf(ctx, best.path[1]),
    hops: best.hops,
  });
  const rows = found.map(({ path: _path, ...row }) => row);
  return {
    litIds,
    anchorIds,
    sentence,
    callouts,
    marks: { paths },
    rows,
    columns: MEET_LIVE_COLS,
    focusIds: best.path,
  };
}

/* ---------- market-shape: What does the market really look like? (morph) ---------- */

function computeMarketShape(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "market-shape");
  if (seat === ctx.defaultSeat) {
    // nearest neighbors sit nearly coincident in latent space — one callout only
    // (the sentence names all three); more than one collides into noise
    const r = bakedDefault(b, SHAPE_BAKED_COLS, []);
    return { ...r, callouts: r.callouts.slice(0, 1) };
  }

  const k = ctx.kernels;
  const ase = ctx.payload.assets.ase;
  if (!ase) throw new Error("questions payload is missing assets.ase");
  const ids = ctx.payload.nodes.ids;
  const si = ids.indexOf(seat);
  if (si < 0) return isolated(ctx, b, seat, SHAPE_LIVE_COLS);
  const nn = k.knn(ase.all, ids, si, 20);
  if (nn.length < 2) return isolated(ctx, b, seat, SHAPE_LIVE_COLS);

  const rows = nn.map((r) => ({ id: r.id as string, label: labelOf(ctx, r.id), d: r.d as number }));
  const sentence = k.fillTemplate(b.templates.default, {
    name: labelOf(ctx, seat),
    n1: labelOf(ctx, nn[0].id),
    n2: labelOf(ctx, nn[1].id),
  });
  const anchorIds = nn.slice(0, 3).map((r) => r.id as string);
  const callouts: Callout[] = [
    { id: anchorIds[0], text: `#1 nearest · distance ${(nn[0].d as number).toFixed(3)}` },
  ];
  return {
    litIds: rows.map((r) => r.id),
    anchorIds,
    sentence,
    callouts,
    marks: {},
    rows,
    columns: SHAPE_LIVE_COLS,
    focusIds: [],
  };
}

/* ---------- exports ---------- */

/** Raw ASE dims 0-1 per node id — morph.ts affine-fits + reflection-picks. */
export function aseTargets(payload: QuestionPayload): Map<string, { x: number; y: number }> {
  const ase = payload.assets.ase;
  if (!ase) return new Map();
  return new Map(payload.nodes.ids.map((id, i) => [id, { x: ase.all[i][0], y: ase.all[i][1] }]));
}

export function makeNetworksDefs(): QuestionDef[] {
  return [
    {
      id: "bridges",
      question: "Who bridges the market?",
      source: ["brokers"],
      legacyAn: ["brokers"],
      reframe: "focus",
      compute: computeBridges,
    },
    {
      id: "meet-first",
      question: "Who should we meet first?",
      source: ["intro-chains", "proximity-rank"],
      legacyAn: ["intro-chains", "proximity-rank"],
      reframe: "focus",
      compute: computeMeetFirst,
    },
    {
      id: "market-shape",
      question: "What does the market really look like?",
      source: ["market-map"],
      legacyAn: ["market-map"],
      morph: true,
      noFade: true, // the whole cloud is the answer — nothing fades
      reframe: "all",
      compute: computeMarketShape,
    },
  ];
}
