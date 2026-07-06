// SERVER-ONLY manifest for /networks/analyses: eager-loads the baked envelopes,
// validates them (fail the build, not the reader — the companies.ts philosophy),
// fixes the display order, groups sidebar sections, and computes per-panel
// staleness against the LIVE graphs. Never import from client code.

import type { AnalysisEnvelope, AnalysisGraph } from "./analyses-types";
import { ANALYSES_ORDER, GRAPH_SECTIONS } from "./analyses-types";
import companiesData from "./companies.json";
import fundingData from "./funding.json";

const PRIVATE_KEYS = ["warm_path", "stage", "notes"];
const modules = import.meta.glob<{ default: AnalysisEnvelope }>("./analyses/*.json", {
  eager: true,
});

const liveIds = new Set<string>([
  ...companiesData.companies.map((c) => c.id),
  ...fundingData.nodes.map((n: { id: string }) => n.id),
]);

const liveStamps = {
  companies: { nodes: companiesData.companies.length, edges: companiesData.edges.length },
  funding: { nodes: fundingData.nodes.length, edges: fundingData.edges.length },
};

function fail(slug: string, msg: string): never {
  throw new Error(`analyses-manifest: ${slug}: ${msg}`);
}

function collectIds(value: unknown, out: Set<string>): void {
  if (Array.isArray(value)) for (const v of value) collectIds(v, out);
  else if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      if (k === "id" && typeof v === "string") out.add(v);
      else collectIds(v, out);
    }
  }
}

function validate(env: AnalysisEnvelope, slug: string): void {
  if (env.slug !== slug) fail(slug, `slug mismatch: ${env.slug}`);
  if (!["companies", "funding", "both"].includes(env.graph)) fail(slug, `bad graph ${env.graph}`);
  for (const k of ["title", "sub", "headline"] as const)
    if (!env[k]) fail(slug, `missing ${k}`);
  for (const k of ["intro", "how", "method"] as const)
    if (!env.prose?.[k]?.startsWith("<p>")) fail(slug, `prose.${k} missing or not <p> html`);
  if (!env.headline.includes("<strong>")) fail(slug, "headline has no <strong> number");
  if (env.headline.includes("<script")) fail(slug, "script tag in headline");
  const raw = JSON.stringify(env);
  for (const k of PRIVATE_KEYS)
    if (raw.includes(`"${k}"`)) fail(slug, `private key ${k} leaked into baked analysis`);
}

export interface PanelEntry {
  env: AnalysisEnvelope;
  index: number; // 1-based, in ANALYSES_ORDER
  staleIds: string[]; // shipped ids gone from the live graphs (build-time view)
  drift: boolean; // inputs stamps no longer match the live graphs
}

const present = new Map<string, AnalysisEnvelope>();
for (const [path, mod] of Object.entries(modules)) {
  const stem = path.replace(/^\.\/analyses\//, "").replace(/\.json$/, "");
  if (stem === "shared") continue;
  validate(mod.default, stem);
  present.set(stem, mod.default);
}

for (const stem of present.keys())
  if (!ANALYSES_ORDER.includes(stem)) fail(stem, "not in ANALYSES_ORDER (analyses-types.ts)");

export const panels: PanelEntry[] = ANALYSES_ORDER.filter((s) => present.has(s)).map((slug) => {
  const env = present.get(slug)!;
  const shipped = new Set<string>();
  collectIds(env.data, shipped);
  const staleIds = [...shipped].filter((id) => !liveIds.has(id));
  const drift = Object.entries(env.inputs).some(([g, s]) => {
    const live = liveStamps[g as "companies" | "funding"];
    return !live || !s || s.nodes !== live.nodes || s.edges !== live.edges;
  });
  if (staleIds.length)
    console.warn(`[analyses] ${slug}: ${staleIds.length} shipped id(s) gone from live graphs — rerun bake.sh`);
  return { env, index: ANALYSES_ORDER.indexOf(slug) + 1, staleIds, drift };
});

export const sections: { id: AnalysisGraph; label: string; panels: PanelEntry[] }[] =
  GRAPH_SECTIONS.map((s) => ({
    ...s,
    panels: panels.filter((p) => p.env.graph === s.id),
  })).filter((s) => s.panels.length > 0);

export const totalCount = panels.length;
