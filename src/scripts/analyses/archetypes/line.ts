// Line archetype: sweep chart (e.g. Leiden γ-sweep, funding by year). Plain
// SVG polylines, direct series labels at the right edge, optional annotation.

import type { AnalysesCtx, BlockHandle, LineSpec } from "../../../data/analyses-types";
import { extent, linearScale, minimalTicks } from "../../analyses-core.js";
import { svgEl } from "../shared";

const H = 260;
const PAD = { t: 14, r: 110, b: 34, l: 46 };
const SERIES_COLORS = ["#4c6b8a", "#a6611a", "#5a7d5a", "#8a6d9b"];

export function renderLine(el: HTMLElement, spec: LineSpec, ctx: AnalysesCtx): BlockHandle {
  const { sweep } = spec;
  if (!sweep.x.length || !sweep.series.length) {
    ctx.empty(el, "no sweep data.");
    return { highlight() {} };
  }
  const W = Math.max(el.clientWidth || 520, 300);
  const [x0, x1] = extent(sweep.x);
  const allY = sweep.series.flatMap((s) => s.y).filter((v): v is number => v != null);
  const [y0, y1] = extent(allY);
  const sx = linearScale(x0, x1, PAD.l, W - PAD.r);
  const sy = linearScale(y0, y1, H - PAD.b, PAD.t);

  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "an-line" });
  svg.style.width = "100%";

  svg.appendChild(svgEl("line", { x1: PAD.l, y1: H - PAD.b, x2: W - PAD.r, y2: H - PAD.b, stroke: ctx.colors.hair }));
  for (const t of minimalTicks(x0, x1)) {
    const tx = svgEl("text", { x: sx(t), y: H - PAD.b + 16, class: "an-axis", "text-anchor": "middle" });
    tx.textContent = ctx.fmt.num(t, 2);
    svg.appendChild(tx);
  }
  for (const t of minimalTicks(y0, y1)) {
    const ty = svgEl("text", { x: PAD.l - 6, y: sy(t) + 3, class: "an-axis", "text-anchor": "end" });
    ty.textContent = ctx.fmt.num(t, 2);
    svg.appendChild(ty);
  }
  if (sweep.xLabel) {
    const t = svgEl("text", { x: (PAD.l + W - PAD.r) / 2, y: H - 4, class: "an-axis", "text-anchor": "middle" });
    t.textContent = sweep.xLabel;
    svg.appendChild(t);
  }

  sweep.series.forEach((s, si) => {
    const color = SERIES_COLORS[si % SERIES_COLORS.length]!;
    const segs: string[] = [];
    let seg: string[] = [];
    s.y.forEach((v, i) => {
      if (v == null) {
        if (seg.length > 1) segs.push(seg.join(" "));
        seg = [];
      } else {
        seg.push(`${sx(sweep.x[i]!)},${sy(v)}`);
      }
    });
    if (seg.length > 1) segs.push(seg.join(" "));
    for (const points of segs) {
      svg.appendChild(svgEl("polyline", { points, fill: "none", stroke: color, "stroke-width": 1.6 }));
    }
    const lastIdx = s.y.map((v) => v != null).lastIndexOf(true);
    if (lastIdx >= 0) {
      const t = svgEl("text", {
        x: sx(sweep.x[lastIdx]!) + 6, y: sy(s.y[lastIdx]!) + 3,
        class: "an-label", fill: color,
      });
      t.textContent = s.label;
      svg.appendChild(t);
    }
  });

  if (sweep.annotate) {
    const ax = sx(sweep.annotate.x);
    svg.appendChild(svgEl("line", {
      x1: ax, y1: PAD.t, x2: ax, y2: H - PAD.b,
      stroke: ctx.colors.accent, "stroke-width": 1, "stroke-dasharray": "3 3",
    }));
    const t = svgEl("text", { x: ax + 5, y: PAD.t + 10, class: "an-note", fill: ctx.colors.accent });
    t.textContent = sweep.annotate.text;
    svg.appendChild(t);
  }

  el.appendChild(svg);
  return { highlight() {} };
}
