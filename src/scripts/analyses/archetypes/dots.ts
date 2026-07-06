// Scatter archetype: cartesian or polar, optional quadrant guides, star ids
// (AoC), direct labels on the most extreme points. Plain SVG, baked data.

import type { AnalysesCtx, BlockHandle, DotsSpec, Point } from "../../../data/analyses-types";
import { extent, linearScale, minimalTicks, polarToXY } from "../../analyses-core.js";
import { svgEl, PERIPHERY } from "../shared";

const H = 340;
const PAD = { t: 14, r: 16, b: 34, l: 46 };

export function renderDots(el: HTMLElement, spec: DotsSpec, ctx: AnalysesCtx): BlockHandle {
  if (!spec.points.length) {
    ctx.empty(el, "no points to plot.");
    return { highlight() {} };
  }
  const graph = spec.graphKey ?? "companies";
  const W = Math.max(el.clientWidth || 520, 280);

  const pts: (Point & { px: number; py: number })[] = spec.points.map((p) => {
    if (spec.polar) {
      const [x, y] = polarToXY(p.x, p.y);
      return { ...p, px: x, py: y };
    }
    return { ...p, px: p.x, py: p.y };
  });

  const [x0, x1] = extent(pts.map((p) => p.px));
  const [y0, y1] = extent(pts.map((p) => p.py));
  const sx = linearScale(x0, x1, PAD.l, W - PAD.r);
  const sy = linearScale(y0, y1, H - PAD.b, PAD.t);

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "an-dots" });
  svg.style.width = "100%";

  if (spec.quadrants) {
    const mx = sx((x0 + x1) / 2);
    const my = sy((y0 + y1) / 2);
    svg.appendChild(svgEl("line", { x1: mx, y1: PAD.t, x2: mx, y2: H - PAD.b, stroke: ctx.colors.hair }));
    svg.appendChild(svgEl("line", { x1: PAD.l, y1: my, x2: W - PAD.r, y2: my, stroke: ctx.colors.hair }));
    const corners: [number, number, string][] = [
      [PAD.l + 4, PAD.t + 10, spec.quadrants.labels[0]],
      [W - PAD.r - 4, PAD.t + 10, spec.quadrants.labels[1]],
      [PAD.l + 4, H - PAD.b - 6, spec.quadrants.labels[2]],
      [W - PAD.r - 4, H - PAD.b - 6, spec.quadrants.labels[3]],
    ];
    corners.forEach(([x, y, text], i) => {
      if (!text) return;
      const t = svgEl("text", { x, y, class: "an-note", "text-anchor": i % 2 ? "end" : "start" });
      t.textContent = text;
      svg.appendChild(t);
    });
  }

  // hairline axes with minimal ticks (skip in polar mode — radius rings instead)
  if (!spec.polar) {
    for (const tx of minimalTicks(x0, x1)) {
      const t = svgEl("text", { x: sx(tx), y: H - PAD.b + 16, class: "an-axis", "text-anchor": "middle" });
      t.textContent = ctx.fmt.num(tx, 2);
      svg.appendChild(t);
    }
    for (const ty of minimalTicks(y0, y1)) {
      const t = svgEl("text", { x: PAD.l - 6, y: sy(ty) + 3, class: "an-axis", "text-anchor": "end" });
      t.textContent = ctx.fmt.num(ty, 2);
      svg.appendChild(t);
    }
    svg.appendChild(svgEl("line", { x1: PAD.l, y1: H - PAD.b, x2: W - PAD.r, y2: H - PAD.b, stroke: ctx.colors.hair }));
    svg.appendChild(svgEl("line", { x1: PAD.l, y1: PAD.t, x2: PAD.l, y2: H - PAD.b, stroke: ctx.colors.hair }));
    if (spec.xLabel) {
      const t = svgEl("text", { x: (PAD.l + W - PAD.r) / 2, y: H - 4, class: "an-axis", "text-anchor": "middle" });
      t.textContent = spec.xLabel;
      svg.appendChild(t);
    }
    if (spec.yLabel) {
      const t = svgEl("text", {
        x: 12, y: (PAD.t + H - PAD.b) / 2, class: "an-axis", "text-anchor": "middle",
        transform: `rotate(-90 12 ${(PAD.t + H - PAD.b) / 2})`,
      });
      t.textContent = spec.yLabel;
      svg.appendChild(t);
    }
  }

  const starSet = new Set(spec.star ?? []);
  const marks = new Map<string, SVGElement>();
  for (const p of pts) {
    const color = p.group ? ctx.colors.group(graph, p.group) : PERIPHERY;
    let mark: SVGElement;
    if (starSet.has(p.id)) {
      const cx = sx(p.px);
      const cy = sy(p.py);
      const s = 7;
      const path = Array.from({ length: 10 }, (_, i) => {
        const r = i % 2 ? s / 2.4 : s;
        const a = (Math.PI / 5) * i - Math.PI / 2;
        return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
      }).join(" ");
      mark = svgEl("polygon", { points: path, fill: ctx.colors.accent, stroke: "#fffff8", "stroke-width": 1 });
    } else {
      mark = svgEl("circle", {
        cx: sx(p.px), cy: sy(p.py), r: p.r ?? 3.4, fill: color,
        opacity: 0.85, stroke: "#fffff8", "stroke-width": 0.6,
      });
    }
    mark.addEventListener("mouseenter", (evt) => {
      ctx.hover.set(p.id);
      const sub = p.group ? `<div class="t-sub">${ctx.esc(ctx.colors.groupLabel(graph, p.group))}</div>` : "";
      ctx.tooltip.show(`<div class="t-name">${ctx.esc(p.label)}</div>${sub}`, evt as MouseEvent);
    });
    mark.addEventListener("mouseleave", () => {
      ctx.hover.set(null);
      ctx.tooltip.hide();
    });
    marks.set(p.id, mark);
    svg.appendChild(mark);
  }

  // direct labels: the N most extreme points (by distance from centroid) + stars
  const labelN = spec.labelTop ?? 0;
  if (labelN > 0 || starSet.size) {
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const rx = x1 - x0 || 1;
    const ry = y1 - y0 || 1;
    const scored = pts
      .map((p) => ({ p, d: ((p.px - cx) / rx) ** 2 + ((p.py - cy) / ry) ** 2 }))
      .sort((a, b) => b.d - a.d);
    const chosen = new Set(scored.slice(0, labelN).map((s) => s.p.id));
    for (const id of starSet) chosen.add(id);
    for (const p of pts) {
      if (!chosen.has(p.id)) continue;
      const t = svgEl("text", {
        x: sx(p.px) + 6, y: sy(p.py) - 5, class: "an-label",
      });
      t.textContent = p.label;
      svg.appendChild(t);
    }
  }

  el.appendChild(svg);

  let ringed: SVGElement | null = null;
  const handle: BlockHandle = {
    highlight(id) {
      if (ringed) {
        ringed.setAttribute("stroke", "#fffff8");
        ringed.setAttribute("stroke-width", "0.6");
        ringed = null;
      }
      const m = id ? marks.get(id) : undefined;
      if (m && m.tagName === "circle") {
        m.setAttribute("stroke", ctx.colors.accent);
        m.setAttribute("stroke-width", "2");
        ringed = m;
      }
    },
  };
  ctx.hover.on((id) => handle.highlight(id));
  return handle;
}
