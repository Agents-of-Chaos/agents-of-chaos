// Types for the questions-on-the-map system (see docs/superpowers/specs/
// 2026-07-15-questions-on-the-map-design.md). The feature is named "question"
// everywhere in code — the word "lens" belongs to the pre-existing
// competitors/customers chips and must not be reused here.

export interface QNode {
  id: string;
  label: string;
  group: string; // vertical id
}

/** One typed adjacency entry (the friction-weighted kernels need edge types). */
export interface QEdge {
  to: string;
  type: string; // business | shared-investor | competitor
  verified: boolean;
}

/** The baked payload (src/data/questions/questions-companies.json). */
export interface QuestionPayload {
  kind: "question-data";
  graph: "companies" | "funding";
  inputs: Record<string, unknown>;
  nodes: { ids: string[]; x: number[]; y: number[]; label: string[] };
  assets: { ase?: { d: number; all: number[][] } };
  params: {
    friction: Record<string, number>;
    pprAlpha: number;
    pprIters: number;
    minDegree: number;
  };
  questions: Record<string, BakedQuestion>;
}

export interface BakedQuestion {
  question: string;
  source: string[]; // appendix slugs (methods links)
  templates: Record<string, string>; // default | self | isolated (+offcore later)
  thumb: { cls: number[]; rings?: string[]; paths?: string[][]; useAse?: boolean };
  default: {
    seat: string;
    sentence: string;
    callouts: Callout[];
    ids: string[];
    rows: Record<string, unknown>[];
    marks: QMarks;
  };
}

export interface Callout {
  id: string;
  text: string;
}

export interface QMarks {
  paths?: string[][]; // route ribbons through node ids
  /** ghost ties — ALWAYS hypothetical (proposed/predicted, never observed);
   *  rendered dotted with a "predicted, not observed" note in the answer bar */
  edges?: [string, string][];
  /** one tinted dashed hull per id-group (the gap BETWEEN hulls is the point) */
  hull?: string[][];
}

export interface QColumn {
  key: string;
  label: string;
  format: "num" | "usd" | "pct" | "sig" | "text" | "flag";
  digits?: number;
}

/** What compute(seat) returns — drives the map paint, thumbnail, bar, and drawer. */
export interface QuestionResult {
  /** ranked lit set, best first (drives fade + thumbnail lit dots) */
  litIds: string[];
  /** the few nodes drawn at full emphasis (rings on thumbs, callout anchors) */
  anchorIds: string[];
  sentence: string; // plain text, already slot-filled
  callouts: Callout[]; // ≤3 drawn on canvas
  marks: QMarks;
  rows: Record<string, unknown>[]; // evidence-drawer table rows
  columns: QColumn[];
  focusIds: string[]; // deliberate-reframe target (empty = no reframe)
}

export interface QComputeCtx {
  payload: QuestionPayload;
  defaultSeat: string;
  ids: string[]; // live graph ids (sorted)
  byId: Map<string, QNode>;
  /** typed adjacency over the live graph (undirected view) */
  adjT: Map<string, QEdge[]>;
  /** raw records for the simple-graph kernels (pristine, un-mutated by d3) */
  raw: { companies: { id: string }[]; edges: { source: string; target: string }[] };
  kernels: typeof import("./kernels.js");
}

export interface QuestionDef {
  id: string; // ?q= slug
  question: string;
  source: string[];
  legacyAn?: string[]; // old ?an= slugs that redirect into this question
  morph?: boolean; // market-shape only: positions morph to ASE coords
  /** skip the fade tier — for questions where the whole map IS the answer */
  noFade?: boolean;
  reframe: "focus" | "all" | null;
  compute(seat: string, ctx: QComputeCtx): QuestionResult;
}

/** What each graph script hands the engine. Everything already exists in the
 * page closure — the adapter only exposes it. The engine never touches the
 * camera except through fitToIds (deliberate acts) and entry-transform restore. */
export interface QuestionHost {
  nodes: QNode[];
  posOf(id: string): { x: number; y: number } | null;
  radiusOf(id: string): number;
  labelOf(id: string): string;
  shownOf(id: string): boolean;
  /** current zoom transform, read from the svg element (__zoom gotcha) */
  zoomTransform(): { k: number; x: number; y: number };
  setZoomTransform(t: { k: number; x: number; y: number }, animate: boolean): void;
  fitToIds(ids: string[] | null, animate: boolean): void;
  /** engine-owned paint channel: fill/radius override + baseline fade set.
   *  null restores base paint entirely. */
  setQuestionPaint(
    p: { fill?(id: string): string | null; r?(id: string): number | null; fade: Set<string> | null } | null,
  ): void;
  /** the old rail-hover tier: preview spotlight (thumb hover) */
  setPreview(ids: Set<string> | null): void;
  /** force-show these ids past filters (path-finder precedent); null clears */
  forceShow(ids: Set<string> | null): void;
  /** SVG layers for question marks: below nodes / above nodes */
  marksLayer(): SVGGElement;
  calloutsLayer(): SVGGElement;
  onTick(fn: () => void): void;
  onZoom(fn: () => void): void;
  /** callouts reserve screen boxes; refreshLabels seeds its placed[] from this
   *  and hides the anchor nodes' own labels */
  reserveLabelBoxes(fn: () => { boxes: number[][]; hideIds: Set<string> }): void;
  parkSim(): void;
  resumeSimOnNextDrag(): void;
  setDragEnabled(on: boolean): void;
  setLabelsVisible(on: boolean): void;
  redraw(): void; // host tick(): repositions edges/nodes from current x/y
  select(id: string | null): void;
  getSelected(): string | null;
  calm: boolean; // prefers-reduced-motion
}

export interface QuestionEls {
  strip: HTMLElement; // the strip container (SSR'd skeleton inside)
  answer: HTMLElement; // the HTML answer bar (hidden when no question)
  drawer: HTMLElement; // the evidence drawer container (hidden when no question)
}

export interface QuestionEngine {
  /** host calls from select() AFTER its own bookkeeping */
  onSelectionChange(id: string | null): void;
  /** returns true if the press was consumed (a question was exited) */
  handleEscape(): boolean;
  active(): string | null;
  /** one lens-aware dossier line for this node, or null */
  dossierContext(id: string): string | null;
}
