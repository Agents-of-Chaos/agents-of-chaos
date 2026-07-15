// SERVER-ONLY validator/bridge for the on-map questions UI (/networks,
// /funding): eager-loads the baked question data (src/data/questions/
// questions-*.json), validates schema + leakage at build time (fail the
// build, not the reader — the analyses-manifest philosophy), and computes
// staleness against the LIVE graphs WITHOUT failing (nightly funding churn
// dims answers, it never breaks the build). P1 ships the companies file only;
// questions-funding.json joins in P3 — its absence is tolerated, its presence
// is validated. Never import from client code.
//
// Rebaked by experiments/analyses/bake.sh (prep_questions.py); the schema is
// documented there and enforced twice: _shared.emit_questions() at bake time,
// this module at build time.

import companiesData from "./companies.json";
import fundingData from "./funding.json";

export type QuestionGraph = "companies" | "funding";

export interface QuestionStamp {
  nodes: number;
  edges: number;
}

/** Aligned arrays: x/y/label[i] describe ids[i]; ids sorted ascending. */
export interface QuestionNodes {
  ids: string[];
  x: number[];
  y: number[];
  label: string[];
}

export interface QuestionCallout {
  id: string;
  text: string;
}

/** The baked default-seat answer — final strings, zero compute on first paint. */
export interface QuestionDefault {
  seat: string;
  sentence: string;
  callouts: QuestionCallout[];
  ids: string[];
  rows: Record<string, unknown>[];
  marks: { paths?: string[][] } & Record<string, unknown>;
}

/** Thumbnail paint: cls[i] classifies ids[i] — 0 fade · 1 context · 2 lit · 3 anchor. */
export interface QuestionThumb {
  cls: number[];
  rings?: string[];
  paths?: string[][];
  useAse?: boolean;
}

export interface QuestionBlock {
  question: string;
  source: string[];
  templates: Record<string, string>;
  thumb: QuestionThumb;
  default: QuestionDefault;
}

export interface QuestionData {
  kind: "question-data";
  graph: QuestionGraph;
  inputs: Partial<Record<QuestionGraph, QuestionStamp>>;
  nodes: QuestionNodes;
  assets: Record<string, unknown>;
  params: Record<string, unknown>;
  questions: Record<string, QuestionBlock>;
}

export interface QuestionEntry {
  data: QuestionData;
  staleIds: string[]; // nodes.ids gone from the live graph (build-time view)
  drift: boolean; // inputs stamp no longer matches the live graph
}

const PRIVATE_KEYS = ["warm_path", "stage", "notes", "priority"];

const modules = import.meta.glob<{ default: QuestionData }>("./questions/questions-*.json", {
  eager: true,
});

const liveIds: Record<QuestionGraph, Set<string>> = {
  companies: new Set(companiesData.companies.map((c) => c.id)),
  funding: new Set(fundingData.nodes.map((n: { id: string }) => n.id)),
};

const liveStamps: Record<QuestionGraph, QuestionStamp> = {
  companies: { nodes: companiesData.companies.length, edges: companiesData.edges.length },
  funding: { nodes: fundingData.nodes.length, edges: fundingData.edges.length },
};

function fail(name: string, msg: string): never {
  throw new Error(`questions: ${name}: ${msg} — rerun experiments/analyses/bake.sh`);
}

function validate(d: QuestionData, name: string): void {
  if (d.kind !== "question-data") fail(name, `bad kind ${String(d.kind)}`);
  if (d.graph !== "companies" && d.graph !== "funding") fail(name, `bad graph ${String(d.graph)}`);
  if (!d.inputs?.[d.graph]) fail(name, `missing inputs.${d.graph} stamp`);

  const n = d.nodes?.ids?.length ?? 0;
  if (!n) fail(name, "empty nodes.ids");
  for (const k of ["x", "y", "label"] as const)
    if (d.nodes[k]?.length !== n) fail(name, `nodes.${k} misaligned`);
  const idSet = new Set(d.nodes.ids);
  if (idSet.size !== n) fail(name, "duplicate nodes.ids");

  const slugs = Object.keys(d.questions ?? {});
  if (!slugs.length) fail(name, "no questions baked");
  for (const slug of slugs) {
    const q = d.questions[slug];
    if (!q.question?.trim()) fail(name, `${slug}: missing question text`);
    if (!Array.isArray(q.source) || !q.source.length) fail(name, `${slug}: missing source`);
    if (!q.templates?.default || !q.templates?.isolated)
      fail(name, `${slug}: templates need default + isolated`);
    if (!Array.isArray(q.thumb?.cls) || q.thumb.cls.length !== n)
      fail(name, `${slug}: thumb.cls misaligned`);
    if (q.thumb.cls.some((c) => !Number.isInteger(c) || c < 0 || c > 3))
      fail(name, `${slug}: thumb.cls value out of 0..3`);
    const def = q.default;
    if (!def) fail(name, `${slug}: missing default block`);
    if (!def.sentence?.trim() || def.sentence.includes("{"))
      fail(name, `${slug}: default.sentence must be a final baked string`);
    if (!idSet.has(def.seat)) fail(name, `${slug}: seat ${def.seat} not in nodes.ids`);
    if (!Array.isArray(def.callouts) || def.callouts.length > 3)
      fail(name, `${slug}: default.callouts must be ≤3`);
    const refs = [
      ...def.callouts.map((c) => c.id),
      ...(def.ids ?? []),
      ...(q.thumb.rings ?? []),
      ...(q.thumb.paths ?? []).flat(),
      ...(def.marks?.paths ?? []).flat(),
    ];
    for (const id of refs)
      if (!idSet.has(id)) fail(name, `${slug}: referenced id ${id} not in nodes.ids`);
    if (!Array.isArray(def.rows) || !def.rows.length) fail(name, `${slug}: empty default.rows`);
  }

  const raw = JSON.stringify(d);
  for (const k of PRIVATE_KEYS)
    if (raw.includes(`"${k}":`)) fail(name, `private key ${k} leaked into baked question data`);
}

export const questionData: Partial<Record<QuestionGraph, QuestionEntry>> = {};

for (const [path, mod] of Object.entries(modules)) {
  const stem = path.replace(/^\.\/questions\//, "").replace(/\.json$/, "");
  const m = stem.match(/^questions-(companies|funding)$/);
  if (!m) fail(stem, "unexpected file in src/data/questions/ (want questions-<graph>.json)");
  const graph = m[1] as QuestionGraph;
  const d = mod.default;
  validate(d, stem);
  if (d.graph !== graph) fail(stem, `graph ${d.graph} does not match filename`);

  // staleness/drift are TOLERATED (nightly churn): warn + expose, never throw
  const staleIds = d.nodes.ids.filter((id) => !liveIds[graph].has(id));
  const baked = d.inputs[graph];
  const live = liveStamps[graph];
  const drift = !baked || baked.nodes !== live.nodes || baked.edges !== live.edges;
  if (staleIds.length)
    console.warn(
      `[questions] ${stem}: ${staleIds.length} baked node(s) gone from the live graph — rerun bake.sh`,
    );
  if (drift)
    console.warn(`[questions] ${stem}: inputs stamp drifted from the live graph — rerun bake.sh`);
  questionData[graph] = { data: d, staleIds, drift };
}

// P1 ships /networks questions — a missing companies file is a broken bake,
// not churn. The funding entry stays optional until P3 bakes it.
if (!questionData.companies)
  throw new Error(
    "questions: questions-companies.json missing — run experiments/analyses/bake.sh",
  );
