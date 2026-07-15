// The eight /networks questions (P1: bridges · meet-first · market-shape;
// P2: best-handshake · missing-ties · empty-quarter · core-crust ·
// rival-orbit). Each compute() returns the baked default VERBATIM for the
// default seat — default-seat numbers come only from the baked envelopes —
// and re-aims with the pure kernels (kernels.js) or a per-seat prebaked
// lookup for any other seat. Row shapes and template slots mirror
// experiments/analyses/prep_questions.py exactly.

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

/* ---------- P2 assets & params (frozen types.ts doesn't carry them yet;
 * shapes follow the prep_questions.py docstring "Asset formats" section) --- */

interface P2Assets {
  ase?: { d: number; all: number[][]; verified?: number[][] };
  /** blocks = short labels (blockP rows); vertBlock: vertical → block label */
  sbm?: { blocks: string[]; vertBlock: Record<string, string>; B: number[][] };
  /** Rombach coreness per layer, nodes.ids-aligned; null = no edges in layer */
  coreness?: {
    full: (number | null)[];
    business: (number | null)[];
    investor: (number | null)[];
  };
  /** per-seat best-new-edge prebake: top[i] = [candIdx, dPct][] for ids[i];
   *  candIdx indexes nodes.ids (NOT the LCC list) */
  handshakes?: { ids: string[]; top: [number, number][][] };
  /** block-structure.json data.blocks verbatim (short labels + 3 layers) */
  blockLayers?: { rows: string[]; cols: string[]; layers: { label: string; cells: number[][] }[] };
}
interface P2Params {
  rrfK?: number;
  svnSeeds?: string[];
}
const p2Assets = (ctx: QComputeCtx): P2Assets => ctx.payload.assets as P2Assets;
const p2Params = (ctx: QComputeCtx): P2Params => ctx.payload.params as unknown as P2Params;

/** node id → vertical, for the sbmRank kernel (pure record, no Map). */
function vertOfMap(ctx: QComputeCtx): Record<string, string> {
  const rec: Record<string, string> = {};
  for (const [id, n] of ctx.byId) rec[id] = n.group;
  return rec;
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

function isolated(
  ctx: QComputeCtx,
  b: BakedQuestion,
  seat: string,
  columns: QColumn[],
  tplKey = "isolated",
): QuestionResult {
  const tpl = b.templates[tplKey] ?? b.templates.isolated ?? b.templates.default;
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
const HANDSHAKE_BAKED_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "dAocPct", label: "Δ reach %", format: "num", digits: 2 },
  { key: "dGlobalPct", label: "Δ market %", format: "num", digits: 2 },
  { key: "persona", label: "who to call", format: "text" },
];
const HANDSHAKE_LIVE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "dPct", label: "Δ reach %", format: "num", digits: 2 },
];
const MISSING_BAKED_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "prospect", label: "prospect", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "phat", label: "p̂", format: "num", digits: 4 },
  { key: "crossCheck", label: "cross-check", format: "text" },
  { key: "flag", label: "", format: "flag" },
];
const MISSING_LIVE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "p", label: "p̂ (block)", format: "num", digits: 4 },
];
const QUARTER_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "shelved", label: "shelved as", format: "text" },
  { key: "wiredWith", label: "wired with", format: "text" },
  { key: "modalShare", label: "modal share", format: "pct" },
  { key: "degree", label: "ties", format: "num", digits: 0 },
  { key: "flag", label: "", format: "flag" },
];
const CORE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "x", label: "business core", format: "num", digits: 3 },
  { key: "y", label: "investor core", format: "num", digits: 3 },
  { key: "group", label: "group", format: "text" },
];
const RIVAL_BAKED_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "borda", label: "borda", format: "num", digits: 0 },
  { key: "rrf", label: "rrf", format: "num", digits: 0 },
  { key: "deg", label: "ties", format: "num", digits: 0 },
  { key: "persona", label: "who to call", format: "text" },
  { key: "flag", label: "", format: "flag" },
];
const RIVAL_LIVE_COLS: QColumn[] = [
  { key: "label", label: "company", format: "text" },
  { key: "s", label: "rrf score", format: "num", digits: 4 },
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

/* ---------- best-handshake: Which single handshake matters most? ----------
 * Default = baked (marks.edges = the proposed ties). Re-aim = pure LOOKUP into
 * assets.handshakes — the bake pre-ranks the top-10 effective-resistance
 * candidates for every LCC seat, so there is no client math to drift. */

function computeBestHandshake(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "best-handshake");
  if (seat === ctx.defaultSeat)
    return bakedDefault(b, HANDSHAKE_BAKED_COLS, [...new Set([...b.default.ids, seat])]);

  const hs = p2Assets(ctx).handshakes;
  if (!hs) throw new Error("questions payload is missing assets.handshakes");
  const si = hs.ids.indexOf(seat);
  // outside the LCC: effective resistance to the core is undefined
  if (si < 0) return isolated(ctx, b, seat, HANDSHAKE_LIVE_COLS);
  const nodeIds = ctx.payload.nodes.ids;
  const top = hs.top[si].map(([ci, dPct]) => ({ id: nodeIds[ci], dPct }));
  if (!top.length) return isolated(ctx, b, seat, HANDSHAKE_LIVE_COLS);

  const name = labelOf(ctx, seat);
  const rows = top.map((r) => ({ id: r.id, label: labelOf(ctx, r.id), dPct: r.dPct }));
  // self variant: the seat is itself one of the default seat's baked handshakes
  const selfIdx = b.default.rows.findIndex((r) => r.id === seat);
  const sentence =
    selfIdx >= 0
      ? ctx.kernels.fillTemplate(b.templates.self, {
          seat: name,
          name: labelOf(ctx, ctx.defaultSeat),
          rank: selfIdx + 1,
          pct: b.default.rows[selfIdx].dAocPct as number,
        })
      : ctx.kernels.fillTemplate(b.templates.default, {
          name,
          seat: name,
          winner: labelOf(ctx, top[0].id),
          pct: top[0].dPct, // baked at 2dp — shown exactly as baked
        });
  const podium = top.slice(0, 3);
  const litIds = top.map((r) => r.id);
  return {
    litIds,
    anchorIds: podium.map((r) => r.id),
    sentence,
    callouts: podium.map((r, k) => ({
      id: r.id,
      text: `#${k + 1} handshake · −${r.dPct}% distance`,
    })),
    marks: { edges: podium.map((r) => [seat, r.id] as [string, string]) },
    rows,
    columns: HANDSHAKE_LIVE_COLS,
    focusIds: [...new Set([seat, ...litIds])],
  };
}

/* ---------- missing-ties: Which ties should exist but don't? ----------
 * Default = baked (missing-edges finding). Re-aim = kernels.sbmRank: block-
 * probability lookup over the live adjacency (spec rule 11 — no arithmetic,
 * cross-language exact by construction). */

function computeMissingTies(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "missing-ties");
  if (seat === ctx.defaultSeat)
    return bakedDefault(b, MISSING_BAKED_COLS, [...new Set([...b.default.ids, seat])]);

  const sbm = p2Assets(ctx).sbm;
  if (!sbm) throw new Error("questions payload is missing assets.sbm");
  const g = kernelGraph(ctx);
  const si = g.idx.get(seat);
  if (si === undefined) return isolated(ctx, b, seat, MISSING_LIVE_COLS);
  // vertBlock maps vertical → block LABEL; the kernel wants vertical → index
  const blockIdx: Record<string, number> = {};
  for (const [vert, label] of Object.entries(sbm.vertBlock)) {
    const k = sbm.blocks.indexOf(label);
    if (k >= 0) blockIdx[vert] = k;
  }
  const adjSet = new Set(g.adj[si].map((i) => g.ids[i]));
  const top = ctx.kernels.sbmRank(vertOfMap(ctx), sbm.B, blockIdx, adjSet, g.ids, seat);
  if (!top.length) return isolated(ctx, b, seat, MISSING_LIVE_COLS);

  const rows = top.map((r) => ({
    id: r.id,
    label: labelOf(ctx, r.id),
    vertical: ctx.byId.get(r.id)?.group ?? "",
    p: r.p,
  }));
  const pctOf = (r: { pFull: number }) => (r.pFull * 100).toFixed(2);
  const name = labelOf(ctx, seat);
  // variant ladder: no ties at all → isolated wording; the seat is itself a
  // baked unmapped vendor → self (its baked prospect); else the base rates
  const selfRow = g.deg[si] > 0 ? b.default.rows.find((r) => r.id === seat) : undefined;
  const tpl =
    g.deg[si] === 0 ? b.templates.isolated : selfRow ? b.templates.self : b.templates.default;
  const sentence = ctx.kernels.fillTemplate(tpl, {
    name,
    seat: name,
    top: selfRow ? String(selfRow.prospect) : labelOf(ctx, top[0].id),
    pct: pctOf(top[0]),
  });
  const podium = top.slice(0, 3);
  const litIds = top.map((r) => r.id);
  return {
    litIds,
    anchorIds: podium.map((r) => r.id),
    sentence,
    callouts: podium.map((r, k) => ({
      id: r.id,
      text: `#${k + 1} predicted · ${pctOf(r)}% base rate`,
    })),
    marks: { edges: podium.map((r) => [seat, r.id] as [string, string]) },
    rows,
    columns: MISSING_LIVE_COLS,
    focusIds: [...new Set([seat, ...litIds])],
  };
}

/* ---------- empty-quarter: Where is the market empty? ----------
 * The map-wide gap IS the answer (noFade; hulls baked into marks.hull), so a
 * re-aim keeps the hulls, rows, and callouts and only re-words the sentence
 * around the SEAT's vertical row, counted from the live adjacency. */

function computeEmptyQuarter(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "empty-quarter");
  const base = bakedDefault(b, QUARTER_COLS, []); // reframe "all": focusIds unused
  if (seat === ctx.defaultSeat) return base;

  const { sbm, blockLayers } = p2Assets(ctx);
  const group = ctx.byId.get(seat)?.group;
  // sentence prose uses block-structure's short labels (the baked sentence
  // says "labs"); sbm.vertBlock carries missing-edges' labels — the two sets
  // agree except one name ("frontier" ↔ "labs"), repaired by elimination
  const bsLabelOf: Record<string, string> = {};
  if (sbm && blockLayers) {
    const rowSet = new Set(blockLayers.rows);
    const covered = new Set(Object.values(sbm.vertBlock));
    const orphanRow = blockLayers.rows.find((r) => !covered.has(r));
    for (const [vert, label] of Object.entries(sbm.vertBlock))
      bsLabelOf[vert] = rowSet.has(label) ? label : (orphanRow ?? label);
  }
  const seatBlock = group ? bsLabelOf[group] : undefined;
  // unmapped vertical: keep the baked answer whole — the hulls carry it
  if (!seatBlock) return base;

  const name = labelOf(ctx, seat);
  // self variant: the seat is itself one of the mis-shelved companies
  const selfRow = b.default.rows.find((r) => r.id === seat);
  if (selfRow)
    return {
      ...base,
      sentence: ctx.kernels.fillTemplate(b.templates.self, {
        seat: name,
        name,
        wiredWith: String(selfRow.wiredWith),
        shelved: String(selfRow.shelved),
      }),
    };
  // isolated: no ties → no corridor to measure; the hulls still carry the gap
  if (!ctx.adjT.get(seat)?.length)
    return {
      ...base,
      sentence: ctx.kernels.fillTemplate(b.templates.isolated, { seat: name, name }),
    };

  // the seat's vertical row of the business-layer block matrix, from the LIVE
  // adjacency: tie counts + block sizes → zero cells and the loudest corridor
  const LAYER = "business";
  const blockOf = (id: string) => bsLabelOf[ctx.byId.get(id)?.group ?? ""];
  const size = new Map<string, number>();
  for (const [, node] of ctx.byId) {
    const bl = bsLabelOf[node.group];
    if (bl) size.set(bl, (size.get(bl) ?? 0) + 1);
  }
  const count = new Map<string, number>();
  for (const [a, edges] of ctx.adjT) {
    const ga = blockOf(a);
    for (const e of edges) {
      if (e.type !== LAYER || a >= e.to) continue; // undirected: count once
      const gb = blockOf(e.to);
      if (!ga || !gb) continue;
      if (ga === seatBlock) count.set(gb, (count.get(gb) ?? 0) + 1);
      if (gb === seatBlock && ga !== seatBlock) count.set(ga, (count.get(ga) ?? 0) + 1);
    }
  }
  const cols = blockLayers?.rows ?? [...size.keys()];
  const nSeat = size.get(seatBlock) ?? 0;
  const empties = cols.filter((c) => c !== seatBlock && !(count.get(c) ?? 0) && size.get(c));
  let loud = "";
  let loudDensity = -1;
  for (const c of cols) {
    const possible =
      c === seatBlock ? (nSeat * (nSeat - 1)) / 2 : nSeat * (size.get(c) ?? 0);
    if (!possible) continue;
    const density = (count.get(c) ?? 0) / possible;
    if (density > loudDensity) {
      loudDensity = density;
      loud = `${seatBlock} × ${c}`;
    }
  }
  // no empty cell in this seat's row (or no corridor at all): the baked
  // map-wide sentence stays truthful — keep the whole default answer
  if (!empties.length || !loud) return base;
  // the most glaring gap: the biggest block this row never touches
  const empty = empties.sort((x, y) => (size.get(y) ?? 0) - (size.get(x) ?? 0))[0];
  const sentence = ctx.kernels.fillTemplate(b.templates.default, {
    name: labelOf(ctx, seat),
    seat: labelOf(ctx, seat),
    block: seatBlock,
    layer: LAYER,
    empty,
    loud,
  });
  return { ...base, sentence };
}

/* ---------- core-crust: Who runs the core — who's still outside? ----------
 * Default = baked. Re-aim = pure LOOKUP: the seat's coreness triple from
 * assets.coreness + its percentile among all embedded nodes; quadrant phrasing
 * comes from the baked templates (coreness is bimodal — ≤0.25 / ≥0.75 — so a
 * 0.5 threshold splits the layers cleanly; null layer = crust side). */

function computeCoreCrust(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "core-crust");
  if (seat === ctx.defaultSeat)
    return bakedDefault(b, CORE_COLS, [...new Set([...b.default.ids, seat])]);

  const cor = p2Assets(ctx).coreness;
  if (!cor) throw new Error("questions payload is missing assets.coreness");
  const i = ctx.payload.nodes.ids.indexOf(seat);
  const full = i >= 0 ? cor.full[i] : null;
  if (full == null) return isolated(ctx, b, seat, CORE_COLS);
  const biz = cor.business[i];
  const inv = cor.investor[i];

  // percentile of the seat's full-graph coreness among all scored nodes
  const pool = cor.full.filter((v): v is number => v != null);
  const below = pool.filter((v) => v < full).length;
  const pct = Math.round((100 * below) / Math.max(1, pool.length - 1));

  // variant ladder: baked prospect-corner member → self; no shared-investor
  // ties → offcore (no money axis); else the corner sentence. Coreness is
  // bimodal (≤0.25 / ≥0.75 — core-periphery.py's GAP band), so 0.5 splits.
  const name = labelOf(ctx, seat);
  const corner =
    (biz ?? 0) >= 0.5 && (inv ?? 0) >= 0.5
      ? "business-core, money-core"
      : (inv ?? 0) >= 0.5
        ? "money-core, business-crust"
        : (biz ?? 0) >= 0.5
          ? "business-core, money-crust"
          : "business-crust, money-crust";
  const fmtC = (v: number | null) => (v == null ? "—" : v.toFixed(2));
  const tpl = b.default.ids.includes(seat)
    ? b.templates.self
    : inv == null
      ? b.templates.offcore
      : b.templates.default;
  const sentence = ctx.kernels.fillTemplate(tpl, {
    name,
    seat: name,
    corner,
    bc: fmtC(biz),
    ic: fmtC(inv),
  });
  return {
    litIds: b.default.ids,
    anchorIds: [seat],
    sentence,
    // "full-graph" disambiguates: a node can be full-graph core (competitor
    // edges count there) while sitting in the business/money crust corner
    callouts: [{ id: seat, text: `${pct}th percentile · full-graph coreness` }],
    marks: b.default.marks,
    rows: b.default.rows,
    columns: CORE_COLS,
    focusIds: [...new Set([...b.default.ids, seat])],
  };
}

/* ---------- rival-orbit: Who else looks like a rival? ----------
 * Default = baked. Re-aim = kernels.rivalOrbitRank (spec rule 12): seeds are
 * the seat's competitor-typed neighbors (verified-embedded, ascending), else
 * the baked seed-vertex-nomination seeds; RRF-fused distance ranks over the
 * verified ASE cloud. */

function computeRivalOrbit(seat: string, ctx: QComputeCtx): QuestionResult {
  const b = bakedQ(ctx, "rival-orbit");
  if (seat === ctx.defaultSeat)
    return bakedDefault(b, RIVAL_BAKED_COLS, [...new Set([...b.default.ids, seat])]);

  const verified = p2Assets(ctx).ase?.verified;
  if (!verified) throw new Error("questions payload is missing assets.ase.verified");
  const verifiedIds = new Set<string>();
  for (const [id, edges] of ctx.adjT) if (edges.some((e) => e.verified)) verifiedIds.add(id);
  // verified-isolates embed at the exact origin — no orbit to speak from
  if (!verifiedIds.has(seat)) return isolated(ctx, b, seat, RIVAL_LIVE_COLS);

  const own = [
    ...new Set(
      (ctx.adjT.get(seat) ?? []).filter((e) => e.type === "competitor").map((e) => e.to),
    ),
  ]
    .filter((u) => u !== seat && verifiedIds.has(u))
    .sort();
  const seeds = own.length
    ? own
    : (p2Params(ctx).svnSeeds ?? []).filter((u) => u !== seat);
  if (!seeds.length) return isolated(ctx, b, seat, RIVAL_LIVE_COLS);

  const k = ctx.kernels;
  const idsArr = ctx.payload.nodes.ids;
  const top = k.rivalOrbitRank(verified, idsArr, seeds, p2Params(ctx).rrfK ?? 60, seat, verifiedIds);
  if (!top.length) return isolated(ctx, b, seat, RIVAL_LIVE_COLS);

  // {k} of {n}: how many seeds rank the winner in their nearest 20 candidates
  // (prose only — the score itself is the kernel's, fixture-locked)
  const NEAR = 20;
  const pos = new Map(idsArr.map((id, j) => [id, j]));
  const seedSet = new Set(seeds);
  const candIdx: number[] = [];
  for (let j = 0; j < idsArr.length; j++)
    if (idsArr[j] !== seat && !seedSet.has(idsArr[j]) && verifiedIds.has(idsArr[j])) candIdx.push(j);
  const dist2 = (a: number, z: number) => {
    let d = 0;
    for (let m = 0; m < verified[a].length; m++) d += (verified[a][m] - verified[z][m]) ** 2;
    return d;
  };
  const topIdx = pos.get(top[0].id);
  let nearCount = 0;
  for (const s of seeds) {
    const sI = pos.get(s);
    if (sI === undefined || topIdx === undefined) continue;
    const dTop = dist2(sI, topIdx);
    let rank = 1;
    for (const cI of candIdx) {
      if (cI === topIdx) continue;
      const d = dist2(sI, cI);
      if (d < dTop || (d === dTop && idsArr[cI] < idsArr[topIdx])) rank++;
      if (rank > NEAR) break;
    }
    if (rank <= NEAR) nearCount++;
  }

  const rows = top.map((r) => ({ id: r.id, label: labelOf(ctx, r.id), s: r.s }));
  // self variant: the graph already nominates the seat into the rival orbit
  const tpl = b.default.ids.includes(seat) ? b.templates.self : b.templates.default;
  const sentence = k.fillTemplate(tpl, {
    seat: labelOf(ctx, seat),
    name: labelOf(ctx, seat),
    top: labelOf(ctx, top[0].id),
    k: nearCount,
    n: seeds.length,
  });
  const podium = top.slice(0, 3);
  const litIds = top.map((r) => r.id);
  return {
    litIds,
    anchorIds: podium.map((r) => r.id),
    sentence,
    callouts: podium.map((r, j) => ({
      id: r.id,
      text: `#${j + 1} looks-alike · rrf ${r.s.toFixed(3)}`,
    })),
    marks: {},
    rows,
    columns: RIVAL_LIVE_COLS,
    focusIds: [...new Set([seat, ...litIds])],
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
    {
      id: "best-handshake",
      question: "Which single handshake matters most?",
      source: ["best-new-edge"],
      legacyAn: ["best-new-edge"],
      reframe: "focus",
      compute: computeBestHandshake,
    },
    {
      id: "missing-ties",
      question: "Which ties should exist but don't?",
      source: ["missing-edges"],
      legacyAn: ["missing-edges"],
      reframe: "focus",
      compute: computeMissingTies,
    },
    {
      id: "empty-quarter",
      question: "Where is the market empty?",
      source: ["block-structure"],
      legacyAn: ["block-structure"],
      noFade: true, // the map-wide gap IS the answer — nothing fades
      reframe: "all",
      compute: computeEmptyQuarter,
    },
    {
      id: "core-crust",
      question: "Who runs the core — who's still outside?",
      source: ["core-periphery"],
      legacyAn: ["core-periphery"],
      reframe: "focus",
      compute: computeCoreCrust,
    },
    {
      id: "rival-orbit",
      question: "Who else looks like a rival?",
      source: ["competitor-nominations"],
      legacyAn: ["competitor-nominations"],
      reframe: "focus",
      compute: computeRivalOrbit,
    },
  ];
}
