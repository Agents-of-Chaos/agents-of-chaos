// Type contract for /networks/analyses — the TS mirror of
// experiments/analyses/CONTRACT.md. Python emits envelopes; the Astro shell
// server-renders the prose; panel modules render `data` via the archetype ctx.

export type AnalysisGraph = "companies" | "funding" | "both";
export type GraphKey = "companies" | "funding";

export interface AnalysisEnvelope {
  slug: string; // == filename stem, kebab-case
  graph: AnalysisGraph; // sidebar section
  title: string; // short sidebar label
  sub: string; // one-line sidebar teaser
  headline: string; // finding sentence, key number in <strong> (trusted build-time HTML)
  prose: { intro: string; how: string; method: string }; // trusted build-time HTML
  caveat?: string; // honest-data note, shown under the headline
  inputs: Partial<Record<GraphKey, { nodes: number; edges: number }>>; // bake-time stamps
  data: Record<string, unknown>; // named blocks in the standard shapes below
}

// ── standard data shapes (see CONTRACT.md) ─────────────────────────────────
export interface NodeRef {
  id: string;
  label: string;
  graph?: GraphKey; // only needed on graph:"both" panels
}

export type RankedRow = { id?: string; label: string; flag?: string } & Record<
  string,
  string | number | boolean | null | undefined
>;

export interface Point {
  id: string;
  label: string;
  x: number;
  y: number;
  group?: string; // vertical id / funder-kind id → palette
  r?: number;
}

export interface Matrix {
  rows: string[];
  cols: string[];
  cells?: (number | null)[][];
  layers?: { label: string; cells: (number | null)[][] }[];
}

export interface Chain {
  score?: number;
  nodes: NodeRef[];
  edges: { label?: string; verified?: boolean }[]; // edges[i] joins nodes[i]→nodes[i+1]
}

export interface Sweep {
  x: number[];
  xLabel?: string;
  series: { label: string; y: (number | null)[] }[];
  annotate?: { x: number; text: string };
}

// ── shared.json (baked by prep_shared.py) ──────────────────────────────────
export interface SharedNode {
  label: string;
  group: string;
  degree: number;
  x: number; // [0,1]
  y: number; // [0,1]
}

export interface SharedGraph {
  stamp: { nodes: number; edges: number };
  dataDate?: string;
  nodes: Record<string, SharedNode>;
  edges: [string, string][];
}

export interface SharedData {
  graphs: Record<GraphKey, SharedGraph>;
}

// ── panel/archetype runtime contract ────────────────────────────────────────
export interface BlockHandle {
  highlight(id: string | null): void;
}

export interface HoverBus {
  set(id: string | null): void;
  on(fn: (id: string | null) => void): void;
}

export interface Column {
  key: string;
  label: string;
  format: "num" | "usd" | "pct" | "sig" | "text" | "flag";
  hint?: string; // title attr on the header
  digits?: number; // for "num"
}

export interface TableSpec {
  rows: RankedRow[];
  columns: Column[];
  rankStart?: number; // default 1; omit rank column with 0
  maxRows?: number;
  graph?: GraphKey; // for hover-bus id resolution on "both" panels
}

export interface DotsSpec {
  points: Point[];
  xLabel?: string;
  yLabel?: string;
  polar?: boolean; // interpret x as angle (radians), y as radius
  quadrants?: { labels: [string, string, string, string] }; // TL, TR, BL, BR
  star?: string[]; // ids drawn as the accent star (AoC)
  labelTop?: number; // direct-label the N most extreme points
  graphKey?: GraphKey; // palette + hover context (default companies)
}

export interface BarsSpec {
  rows: { id?: string; label: string; value: number }[];
  format: Column["format"];
  annotateTop?: number;
}

export interface MatrixSpec extends Matrix {
  format?: Column["format"];
  scale?: "seq" | "div";
}

export interface ChainSpec {
  chains: Chain[];
}

export interface LineSpec {
  sweep: Sweep;
}

export interface MinimapOpts {
  colorFn?: (id: string) => string | null; // null → periphery grey
  radiusFn?: (id: string) => number;
  opacityFn?: (id: string) => number;
  extraEdges?: { a: string; b: string }[]; // drawn accented (e.g. proposed ties)
  width?: number;
  height?: number;
}

export interface BlocksHandle {
  block(flexBasis: string, title?: string): HTMLElement;
}

export interface AnalysesCtx {
  colors: {
    ink: string;
    muted: string;
    hair: string;
    accent: string;
    group(graph: GraphKey, group: string): string;
    groupLabel(graph: GraphKey, group: string): string;
  };
  fmt: {
    num(x: number | null, digits?: number): string;
    usd(x: number | null): string;
    pct(x: number | null): string;
    sig(p: number | null): string;
  };
  esc(s: string): string;
  node(graph: GraphKey, id: string): SharedNode | undefined;
  labelOf(graph: GraphKey, id: string, fallback?: string): string;
  hover: HoverBus;
  tooltip: { show(html: string, evt: MouseEvent): void; hide(): void };
  staleIds: Set<string>; // ids shipped by this panel but gone from the live graphs
  blocks(el: HTMLElement): BlocksHandle;
  empty(el: HTMLElement, msg: string): void;
  table(el: HTMLElement, spec: TableSpec): BlockHandle;
  dots(el: HTMLElement, spec: DotsSpec): BlockHandle;
  bars(el: HTMLElement, spec: BarsSpec): BlockHandle;
  matrix(el: HTMLElement, spec: MatrixSpec): BlockHandle;
  chain(el: HTMLElement, spec: ChainSpec): BlockHandle;
  line(el: HTMLElement, spec: LineSpec): BlockHandle;
  minimap(el: HTMLElement, graph: GraphKey, opts?: MinimapOpts): BlockHandle;
}

export interface PanelModule {
  slug: string;
  render(el: HTMLElement, env: AnalysisEnvelope, ctx: AnalysesCtx): void;
}

// Ordered by business usefulness (find customers, understand rivals, reach
// people, raise money) — the panel number doubles as a usefulness rank.
export const ANALYSES_ORDER: string[] = [
  "competitor-nominations", // who to sell to, who to watch
  "funder-shortlist", // who to ask for money this quarter
  "intro-chains", // how to reach each target
  "best-new-edge", // the one relationship to build next
  "missing-edges", // unmapped prospects + what to verify
  "proximity-rank", // who we can actually reach today
  "shared-investors", // funds with appetite, minus conflicts
  "brokers", // who can make real introductions
  "core-periphery", // financed but not yet embedded
  "market-map", // orientation: who plays our role
  "block-structure", // do the verticals match the wiring
  "layer-shift", // partner/investor/rival lenses disagree
];

export const GRAPH_SECTIONS: { id: AnalysisGraph; label: string }[] = [
  { id: "companies", label: "the company graph" },
  { id: "funding", label: "the funding graph" },
  { id: "both", label: "across both graphs" },
];
