// Heatmap archetype: single matrix or small-multiple layers. CSS grid of
// cells, sequential or diverging ink ramps on the site palette (no new hues).

import type { AnalysesCtx, BlockHandle, MatrixSpec } from "../../../data/analyses-types";
import { extent } from "../../analyses-core.js";

const SEQ = "76, 107, 138"; // #4c6b8a — magnitude = opacity ramp, not new hues
const DIV_NEG = "154, 106, 106"; // #9b6a6a
const DIV_POS = "90, 125, 90"; // #5a7d5a

function cellColor(v: number | null, lo: number, hi: number, scale: "seq" | "div"): string {
  if (v == null) return "transparent";
  if (scale === "div") {
    const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1;
    const t = Math.min(Math.abs(v) / m, 1);
    return `rgba(${v < 0 ? DIV_NEG : DIV_POS}, ${0.08 + 0.8 * t})`;
  }
  const t = hi === lo ? 0.5 : (v - lo) / (hi - lo);
  return `rgba(${SEQ}, ${0.06 + 0.82 * t})`;
}

function oneMatrix(
  el: HTMLElement,
  spec: MatrixSpec,
  cells: (number | null)[][],
  title: string | undefined,
  ctx: AnalysesCtx,
): void {
  const flat = cells.flat().filter((v): v is number => v != null);
  const [lo, hi] = extent(flat);
  const scale = spec.scale ?? "seq";
  const fmtVal = (v: number): string =>
    spec.format === "usd" ? ctx.fmt.usd(v) : spec.format === "pct" ? ctx.fmt.pct(v) : ctx.fmt.num(v, 3);

  const box = document.createElement("div");
  box.className = "an-matrix";
  if (title) {
    const h = document.createElement("div");
    h.className = "an-block-title";
    h.textContent = title;
    box.appendChild(h);
  }
  const grid = document.createElement("div");
  grid.className = "an-matrix-grid";
  grid.style.gridTemplateColumns = `minmax(60px, auto) repeat(${spec.cols.length}, 1fr)`;

  grid.appendChild(document.createElement("span"));
  for (const c of spec.cols) {
    const s = document.createElement("span");
    s.className = "an-matrix-col";
    s.textContent = c;
    grid.appendChild(s);
  }
  spec.rows.forEach((rLabel, i) => {
    const s = document.createElement("span");
    s.className = "an-matrix-row";
    s.textContent = rLabel;
    grid.appendChild(s);
    spec.cols.forEach((cLabel, j) => {
      const cell = document.createElement("span");
      cell.className = "an-matrix-cell";
      const v = cells[i]?.[j] ?? null;
      cell.style.background = cellColor(v, lo, hi, scale);
      if (v != null) {
        cell.addEventListener("mouseenter", (evt) =>
          ctx.tooltip.show(
            `<div class="t-name">${ctx.esc(rLabel)} × ${ctx.esc(cLabel)}</div><div class="t-sub">${fmtVal(v)}</div>`,
            evt,
          ),
        );
        cell.addEventListener("mouseleave", () => ctx.tooltip.hide());
      }
      grid.appendChild(cell);
    });
  });
  box.appendChild(grid);
  el.appendChild(box);
}

export function renderMatrix(el: HTMLElement, spec: MatrixSpec, ctx: AnalysesCtx): BlockHandle {
  if (spec.layers?.length) {
    const wrap = document.createElement("div");
    wrap.className = "an-matrix-layers";
    for (const layer of spec.layers) oneMatrix(wrap, spec, layer.cells, layer.label, ctx);
    el.appendChild(wrap);
  } else if (spec.cells) {
    oneMatrix(el, spec, spec.cells, undefined, ctx);
  } else {
    ctx.empty(el, "no matrix data.");
  }
  return { highlight() {} };
}
