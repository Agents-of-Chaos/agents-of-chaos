// Client orchestrator for /networks/analyses. The Astro shell server-renders
// all prose; this script only activates panels and draws visualizations.
// DOM is the state: sidebar items + panels carry data-slug.

import type { AnalysesCtx, AnalysisEnvelope, PanelModule, SharedData } from "../../data/analyses-types";
import sharedJson from "../../data/analyses/shared.json";
import { makeCtx, setNodeInfo, type NodeInfoMap } from "./shared";
import { loadData, loadPanel, prefetch } from "./registry";
import { mentionRanges, staleIdsIn } from "../analyses-core.js";

const shared = sharedJson as unknown as SharedData;

interface ActivePanel {
  slug: string;
  env: AnalysisEnvelope;
  module: PanelModule;
  viz: HTMLElement;
}

// ── prose mentions: wrap node names in the SSR'd text so hovering them shows
// the node's dossier (and cross-highlights the viz via the hover bus) ────────
const PROSE_SELECTOR = ".an-headline, .an-caveat, .an-intro, .an-how, .an-method";

function wrapMentions(panel: HTMLElement, labels: string[], labelToId: Map<string, string>): void {
  for (const container of panel.querySelectorAll<HTMLElement>(PROSE_SELECTOR)) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const texts: Text[] = [];
    let n: Node | null;
    while ((n = walker.nextNode())) {
      // never nest an interactive span inside a link or an existing mention
      if (!(n as Text).parentElement?.closest("a, .an-mention")) texts.push(n as Text);
    }
    for (const t of texts) {
      const ranges = mentionRanges(t.data, labels) as { start: number; end: number; label: string }[];
      if (!ranges.length) continue;
      const frag = document.createDocumentFragment();
      let pos = 0;
      for (const rg of ranges) {
        if (rg.start > pos) frag.appendChild(document.createTextNode(t.data.slice(pos, rg.start)));
        const span = document.createElement("span");
        span.className = "an-mention";
        span.dataset.id = labelToId.get(rg.label);
        span.textContent = rg.label;
        frag.appendChild(span);
        pos = rg.end;
      }
      if (pos < t.data.length) frag.appendChild(document.createTextNode(t.data.slice(pos)));
      t.replaceWith(frag);
    }
  }
}

function readNodeInfo(): NodeInfoMap | null {
  try {
    const el = document.getElementById("an-node-info");
    return el ? (JSON.parse(el.textContent || "null") as NodeInfoMap) : null;
  } catch {
    return null;
  }
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
  let currentCtx: AnalysesCtx | null = null;

  // node dossiers: hover any node reference (rows, dots, pills, prose
  // mentions) → the map-style tooltip. Info island is built from the live
  // graphs at build time; without it everything degrades to bare labels.
  const nodeInfo = readNodeInfo();
  if (nodeInfo) {
    setNodeInfo(nodeInfo);
    const labelToId = new Map<string, string>();
    for (const [id, d] of Object.entries(nodeInfo.funding)) {
      labelToId.set(d.l, id);
      for (const a of d.a ?? []) labelToId.set(a, id);
    }
    // companies win label collisions (the richer, map-native dossier)
    for (const [id, d] of Object.entries(nodeInfo.companies)) labelToId.set(d.l, id);
    const labels = [...labelToId.keys()];
    for (const panel of panels.values()) wrapMentions(panel, labels, labelToId);

    const main = document.querySelector<HTMLElement>(".an-main");
    main?.addEventListener("mouseover", (e) => {
      const m = (e.target as HTMLElement).closest?.(".an-mention") as HTMLElement | null;
      if (m?.dataset.id) currentCtx?.hover.set(m.dataset.id);
    });
    main?.addEventListener("mouseout", (e) => {
      if ((e.target as HTMLElement).closest?.(".an-mention")) currentCtx?.hover.set(null);
    });
  }

  function draw(slug: string, env: AnalysisEnvelope, module: PanelModule, panel: HTMLElement): void {
    const viz = panel.querySelector<HTMLElement>("[data-viz]");
    if (!viz) return;
    viz.innerHTML = "";
    // stale = shipped ids gone from the CURRENT graphs (nightly churn); the
    // build stamps a set too, but recompute here so a stale bundle still dims.
    const stale = staleIdsIn(env.data, liveIds) as Set<string>;
    const ctx = makeCtx(shared, stale);
    currentCtx = ctx;
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
