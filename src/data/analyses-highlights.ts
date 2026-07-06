// SERVER-ONLY: derives the /networks analyses-rail entries from the baked
// envelopes — which company-map nodes each analysis points at (hover-highlight)
// plus its title/sub preview. Order, text, and ids all flow from the envelopes
// via the manifest, so a rebake, rewrite, or reorder shows up here with zero
// edits. Never import from client code (companies.json + all envelopes).
//
// Extraction picks each analysis's FINDING set — the ranked table its headline
// is about — not every id in the envelope: three envelopes carry whole-graph
// tables (market-map's map, proximity-rank's percentile, competitor-nominations'
// percentile) that would light up the entire map. If a bake renames a data key,
// the slug falls back to a generic ordered walk, capped — degraded, never broken.

import { orderedIdsIn, prospectQuadrantIds } from "../scripts/analyses-core.js";
import { panels, totalCount } from "./analyses-manifest";
import type { AnalysisGraph } from "./analyses-types";
import companiesData from "./companies.json";
import fundingData from "./funding.json";

const companyIds = new Set(companiesData.companies.map((c) => c.id));
const fundingIds = new Set((fundingData.nodes as { id: string }[]).map((n) => n.id));
const CAP = 30; // a hover should spotlight a finding, not repaint the map

type Data = Record<string, unknown>;
const pick = (data: Data, ...keys: string[]): string[] =>
  keys.flatMap((k) => orderedIdsIn(data[k]));

// per-slug finding set (the rows the headline talks about); absent slugs and
// missing keys fall through to the generic walk below
const FINDING: Record<string, (data: Data) => string[]> = {
  "competitor-nominations": (d) => pick(d, "prospects", "rivals"),
  "intro-chains": (d) => pick(d, "companyChains", "leaderboard"),
  "missing-edges": (d) => pick(d, "unmapped"),
  "shared-investors": (d) => pick(d, "backersPerRival"),
  "market-map": (d) => pick(d, "neighbors"),
  "proximity-rank": (d) => pick(d, "reach"),
  "block-structure": (d) => pick(d, "misShelved"),
  "core-periphery": (d) =>
    prospectQuadrantIds(d.quadrant as { id: string; x: number; y: number }[]),
  brokers: (d) => pick(d, "brokers"),
  "layer-shift": (d) => pick(d, "shifts"),
  "best-new-edge": (d) => pick(d, "candidates"),
  // funding-slate panels (2026-07): the finding sets their headlines rank —
  // whole-graph blocks (calendar sweeps, rank-rank scatters, the full map)
  // deliberately excluded so a hover spotlights, not repaints
  "deadline-calendar": (d) => pick(d, "actionList", "doors"),
  "funder-fit": (d) => pick(d, "ranked"),
  "funding-gaps": (d) => pick(d, "predicted", "warm"),
  "co-funding-cliques": (d) => pick(d, "entry"),
  "money-brokers": (d) => pick(d, "gatekeepers"),
  upstream: (d) => pick(d, "chains"),
  "rivals-money": (d) => pick(d, "rivalBackers", "cleanTargets"),
  "money-map": (d) => pick(d, "misfits", "declarers"),
};

export interface SidebarAnalysis {
  slug: string;
  index: number; // 1-based, ANALYSES_ORDER position
  title: string;
  sub: string;
  graph: AnalysisGraph;
  ids: string[]; // company-map nodes this analysis points at (ordered, capped)
  fundingIds: string[]; // funding-map nodes ditto — feeds the /funding rail
}

export const sidebarAnalyses: SidebarAnalysis[] = panels.map(({ env, index }) => {
  const data = env.data as Data;
  const found = FINDING[env.slug]?.(data) ?? [];
  const pool = found.length ? found : orderedIdsIn(data);
  const ids = pool.filter((id) => companyIds.has(id)).slice(0, CAP);
  const fIds = pool.filter((id) => fundingIds.has(id)).slice(0, CAP);
  return { slug: env.slug, index, title: env.title, sub: env.sub, graph: env.graph, ids, fundingIds: fIds };
});

// a build where NOTHING highlights means the extraction rotted — fail loudly
if (!sidebarAnalyses.some((a) => a.ids.length))
  throw new Error("analyses-highlights: no analysis yields any company ids");
if (!sidebarAnalyses.some((a) => a.fundingIds.length))
  throw new Error("analyses-highlights: no analysis yields any funding ids");

export { totalCount };
