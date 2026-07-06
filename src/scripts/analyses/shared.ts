// AnalysesCtx — the one shared context every panel renders through.
// Colors come from the canonical palettes (network-types / funding-types),
// never hand-copied hex. No d3 on this page: layouts are baked in shared.json,
// so plain SVG DOM + the pure helpers in analyses-core.js are enough.

import type {
  AnalysesCtx,
  BlockHandle,
  GraphKey,
  MinimapOpts,
  SharedData,
  SharedNode,
} from "../../data/analyses-types";
import { escapeHtml, VERTICALS } from "../../data/network-types";
import { FUNDER_KINDS, GRANTEE_COLOR, PERSON_COLOR } from "../../data/funding-types";
import { fmt } from "../analyses-core.js";
import { renderTable } from "./archetypes/table";
import { renderDots } from "./archetypes/dots";
import { renderBars } from "./archetypes/bars";
import { renderMatrix } from "./archetypes/matrix";
import { renderChain } from "./archetypes/chain";
import { renderLine } from "./archetypes/line";

const INK = "#111";
const MUTED = "#6b6b6b";
const HAIR = "#e3ddcf";
const ACCENT = "#a00";
const PERIPHERY = "#cfc9b9";

const verticalColor = new Map(VERTICALS.map((v) => [v.id as string, v.color]));
const verticalLabel = new Map(VERTICALS.map((v) => [v.id as string, v.label]));
const funderColor = new Map(FUNDER_KINDS.map((k) => [k.id as string, k.color]));
const funderLabel = new Map(FUNDER_KINDS.map((k) => [k.id as string, k.label]));

function groupColor(graph: GraphKey, group: string): string {
  if (graph === "companies") return verticalColor.get(group) ?? PERIPHERY;
  if (group === "grantee") return GRANTEE_COLOR;
  if (group === "person") return PERSON_COLOR;
  return funderColor.get(group) ?? PERIPHERY;
}

function groupLabel(graph: GraphKey, group: string): string {
  if (graph === "companies") return verticalLabel.get(group) ?? group;
  if (group === "grantee") return "grantee";
  if (group === "person") return "person";
  return funderLabel.get(group) ?? group;
}

// ── one-id hover bus: every archetype publishes + subscribes automatically ──
function makeHoverBus() {
  const subs: ((id: string | null) => void)[] = [];
  return {
    set(id: string | null) {
      for (const fn of subs) fn(id);
    },
    on(fn: (id: string | null) => void) {
      subs.push(fn);
    },
  };
}

// ── the one tooltip (reuses the site's .gtooltip base style) ────────────────
function makeTooltip() {
  let el = document.getElementById("an-tip");
  if (!el) {
    el = document.createElement("div");
    el.id = "an-tip";
    el.className = "gtooltip";
    el.setAttribute("aria-hidden", "true");
    document.body.appendChild(el);
  }
  const tip = el;
  return {
    show(html: string, evt: MouseEvent) {
      tip.innerHTML = html;
      tip.style.opacity = "1";
      const pad = 12;
      const w = tip.offsetWidth;
      const x = Math.min(evt.clientX + pad, window.innerWidth - w - pad);
      const y = Math.max(evt.clientY - tip.offsetHeight - pad, pad);
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    },
    hide() {
      tip.style.opacity = "0";
    },
  };
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number> = {},
): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

// ── minimap: the page's visual anchor, drawn from baked shared.json layout ──
function renderMinimap(
  el: HTMLElement,
  shared: SharedData,
  graph: GraphKey,
  ctx: AnalysesCtx,
  opts: MinimapOpts = {},
): BlockHandle {
  const g = shared.graphs[graph];
  const W = opts.width ?? 300;
  const H = opts.height ?? 240;
  const pad = 12;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "an-minimap" });
  svg.style.width = "100%";
  svg.style.maxWidth = `${W}px`;

  const px = (n: SharedNode) => pad + n.x * (W - 2 * pad);
  const py = (n: SharedNode) => pad + n.y * (H - 2 * pad);

  for (const [a, b] of g.edges) {
    const na = g.nodes[a];
    const nb = g.nodes[b];
    if (!na || !nb) continue;
    svg.appendChild(
      svgEl("line", {
        x1: px(na), y1: py(na), x2: px(nb), y2: py(nb),
        stroke: HAIR, "stroke-width": 0.5, opacity: 0.6,
      }),
    );
  }
  for (const e of opts.extraEdges ?? []) {
    const na = g.nodes[e.a];
    const nb = g.nodes[e.b];
    if (!na || !nb) continue;
    svg.appendChild(
      svgEl("line", {
        x1: px(na), y1: py(na), x2: px(nb), y2: py(nb),
        stroke: ACCENT, "stroke-width": 1.4, "stroke-dasharray": "4 3",
      }),
    );
  }

  const dots = new Map<string, SVGCircleElement>();
  for (const [id, n] of Object.entries(g.nodes)) {
    const color = opts.colorFn ? (opts.colorFn(id) ?? PERIPHERY) : groupColor(graph, n.group);
    const c = svgEl("circle", {
      cx: px(n), cy: py(n),
      r: opts.radiusFn?.(id) ?? 2.2,
      fill: color,
      opacity: opts.opacityFn?.(id) ?? (opts.colorFn && !opts.colorFn(id) ? 0.35 : 0.85),
    });
    c.addEventListener("mouseenter", (evt) => {
      ctx.hover.set(id);
      ctx.tooltip.show(`<div class="t-name">${ctx.esc(n.label)}</div>`, evt);
    });
    c.addEventListener("mouseleave", () => {
      ctx.hover.set(null);
      ctx.tooltip.hide();
    });
    dots.set(id, c);
    svg.appendChild(c);
  }
  el.appendChild(svg);

  let ringed: SVGCircleElement | null = null;
  const handle: BlockHandle = {
    highlight(id) {
      if (ringed) {
        ringed.setAttribute("stroke", "none");
        ringed = null;
      }
      const c = id ? dots.get(id) : undefined;
      if (c) {
        c.setAttribute("stroke", ACCENT);
        c.setAttribute("stroke-width", "1.6");
        ringed = c;
      }
    },
  };
  ctx.hover.on((id) => handle.highlight(id));
  return handle;
}

export function makeCtx(shared: SharedData, staleIds: Set<string>): AnalysesCtx {
  const ctx: AnalysesCtx = {
    colors: { ink: INK, muted: MUTED, hair: HAIR, accent: ACCENT, group: groupColor, groupLabel },
    fmt,
    esc: escapeHtml,
    node: (graph, id) => shared.graphs[graph]?.nodes[id],
    labelOf: (graph, id, fallback) => shared.graphs[graph]?.nodes[id]?.label ?? fallback ?? id,
    hover: makeHoverBus(),
    tooltip: makeTooltip(),
    staleIds,
    blocks(el) {
      const wrap = document.createElement("div");
      wrap.className = "an-blocks";
      el.appendChild(wrap);
      return {
        block(flexBasis, title) {
          const b = document.createElement("div");
          b.className = "an-block";
          b.style.flex = `1 1 ${flexBasis}`;
          if (title) {
            const h = document.createElement("div");
            h.className = "an-block-title";
            h.textContent = title;
            b.appendChild(h);
          }
          wrap.appendChild(b);
          return b;
        },
      };
    },
    empty(el, msg) {
      const d = document.createElement("p");
      d.className = "an-empty";
      d.textContent = msg;
      el.appendChild(d);
    },
    table: (el, spec) => renderTable(el, spec, ctx),
    dots: (el, spec) => renderDots(el, spec, ctx),
    bars: (el, spec) => renderBars(el, spec, ctx),
    matrix: (el, spec) => renderMatrix(el, spec, ctx),
    chain: (el, spec) => renderChain(el, spec, ctx),
    line: (el, spec) => renderLine(el, spec, ctx),
    minimap: (el, graph, opts) => renderMinimap(el, shared, graph, ctx, opts),
  };
  return ctx;
}

export { svgEl, PERIPHERY };
