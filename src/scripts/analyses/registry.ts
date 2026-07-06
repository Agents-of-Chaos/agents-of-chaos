// Lazy loaders: each panel module and each baked JSON is its own hashed chunk,
// fetched on first activation (prefetched on sidebar hover).

import type { AnalysisEnvelope, PanelModule } from "../../data/analyses-types";

const panelModules = import.meta.glob<{ default: PanelModule }>("./panels/*.ts");
const dataModules = import.meta.glob<{ default: AnalysisEnvelope }>("../../data/analyses/*.json");

export function loadPanel(slug: string): Promise<PanelModule> {
  const loader = panelModules[`./panels/${slug}.ts`];
  if (!loader) return Promise.reject(new Error(`no panel module for ${slug}`));
  return loader().then((m) => m.default);
}

export function loadData(slug: string): Promise<AnalysisEnvelope> {
  const loader = dataModules[`../../data/analyses/${slug}.json`];
  if (!loader) return Promise.reject(new Error(`no data for ${slug}`));
  return loader().then((m) => m.default);
}

export function prefetch(slug: string): void {
  void panelModules[`./panels/${slug}.ts`]?.();
  void dataModules[`../../data/analyses/${slug}.json`]?.();
}
