// Client orchestrator for /networks/analyses. The Astro shell server-renders
// all prose; this script only activates panels and draws visualizations.
// DOM is the state: sidebar items + panels carry data-slug.

import type { AnalysisEnvelope, PanelModule, SharedData } from "../../data/analyses-types";
import sharedJson from "../../data/analyses/shared.json";
import { makeCtx } from "./shared";
import { loadData, loadPanel, prefetch } from "./registry";
import { staleIdsIn } from "../analyses-core.js";

const shared = sharedJson as unknown as SharedData;

interface ActivePanel {
  slug: string;
  env: AnalysisEnvelope;
  module: PanelModule;
  viz: HTMLElement;
}

export function initAnalyses(): void {
  const items = [...document.querySelectorAll<HTMLElement>(".an-nav-item")];
  const panels = new Map(
    [...document.querySelectorAll<HTMLElement>(".an-panel")].map((p) => [p.dataset.slug!, p]),
  );
  if (!items.length || !panels.size) return;

  const liveIds = new Set<string>([
    ...Object.keys(shared.graphs.companies.nodes),
    ...Object.keys(shared.graphs.funding.nodes),
  ]);

  let active: ActivePanel | null = null;

  function draw(slug: string, env: AnalysisEnvelope, module: PanelModule, panel: HTMLElement): void {
    const viz = panel.querySelector<HTMLElement>("[data-viz]");
    if (!viz) return;
    viz.innerHTML = "";
    // stale = shipped ids gone from the CURRENT graphs (nightly churn); the
    // build stamps a set too, but recompute here so a stale bundle still dims.
    const stale = staleIdsIn(env.data, liveIds) as Set<string>;
    const ctx = makeCtx(shared, stale);
    try {
      module.render(viz, env, ctx);
    } catch (err) {
      viz.innerHTML = `<p class="an-empty">this panel failed to draw — ${String(err)}</p>`;
      console.error(`[analyses] ${slug}:`, err);
    }
    active = { slug, env, module, viz };
  }

  async function activate(slug: string, push: boolean): Promise<void> {
    const panel = panels.get(slug);
    if (!panel) return;
    for (const [s, p] of panels) p.hidden = s !== slug;
    for (const it of items) it.classList.toggle("sel", it.dataset.slug === slug);
    if (push) history.pushState(null, "", `?a=${slug}`);
    if (active?.slug === slug) return;
    active = null;
    const viz = panel.querySelector<HTMLElement>("[data-viz]");
    if (viz) viz.innerHTML = '<p class="an-empty">computing the picture…</p>';
    try {
      const [module, env] = await Promise.all([loadPanel(slug), loadData(slug)]);
      draw(slug, env, module, panel);
    } catch (err) {
      if (viz) viz.innerHTML = '<p class="an-empty">could not load this analysis.</p>';
      console.error(`[analyses] load ${slug}:`, err);
    }
  }

  for (const it of items) {
    const slug = it.dataset.slug!;
    it.addEventListener("click", (e) => {
      e.preventDefault();
      void activate(slug, true);
    });
    it.addEventListener("mouseenter", () => prefetch(slug));
  }

  window.addEventListener("popstate", () => {
    const slug = new URLSearchParams(location.search).get("a");
    if (slug && panels.has(slug)) void activate(slug, false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    const idx = items.findIndex((it) => it.classList.contains("sel"));
    const next = items[idx + (e.key === "ArrowDown" ? 1 : -1)];
    if (next) {
      e.preventDefault();
      void activate(next.dataset.slug!, true);
    }
  });

  let resizeTimer: ReturnType<typeof setTimeout> | undefined;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (active) {
        const panel = panels.get(active.slug);
        if (panel) draw(active.slug, active.env, active.module, panel);
      }
    }, 180);
  });

  const requested = new URLSearchParams(location.search).get("a") ?? location.hash.replace(/^#/, "");
  const first = panels.has(requested) ? requested : items[0]?.dataset.slug;
  if (first) void activate(first, false);
}
