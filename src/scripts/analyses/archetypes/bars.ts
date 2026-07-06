// Ranked bars (lollipop rows): label left, hairline track, value dot + number.
// Pure HTML/CSS — no SVG needed for ranked magnitude.

import type { AnalysesCtx, BarsSpec, BlockHandle } from "../../../data/analyses-types";

export function renderBars(el: HTMLElement, spec: BarsSpec, ctx: AnalysesCtx): BlockHandle {
  if (!spec.rows.length) {
    ctx.empty(el, "no values to chart.");
    return { highlight() {} };
  }
  const max = Math.max(...spec.rows.map((r) => r.value), 0) || 1;
  const wrap = document.createElement("div");
  wrap.className = "an-bars";
  const byId = new Map<string, HTMLElement>();

  const fmtVal = (v: number): string =>
    spec.format === "usd" ? ctx.fmt.usd(v) : spec.format === "pct" ? ctx.fmt.pct(v) : ctx.fmt.num(v);

  spec.rows.forEach((row) => {
    const r = document.createElement("div");
    r.className = "an-bar-row";
    const stale = row.id != null && ctx.staleIds.has(row.id);
    if (stale) r.classList.add("an-stale");
    const label = document.createElement("span");
    label.className = "an-bar-label";
    label.textContent = row.label + (stale ? " †" : "");
    const track = document.createElement("span");
    track.className = "an-bar-track";
    const fill = document.createElement("span");
    fill.className = "an-bar-fill";
    fill.style.width = `${Math.max((100 * row.value) / max, 0.5)}%`;
    track.appendChild(fill);
    const val = document.createElement("span");
    val.className = "an-bar-val";
    val.textContent = fmtVal(row.value);
    r.append(label, track, val);
    if (row.id) {
      const id = row.id;
      byId.set(id, r);
      r.addEventListener("mouseenter", () => ctx.hover.set(id));
      r.addEventListener("mouseleave", () => ctx.hover.set(null));
    }
    wrap.appendChild(r);
  });
  el.appendChild(wrap);

  let lit: HTMLElement | null = null;
  const handle: BlockHandle = {
    highlight(id) {
      if (lit) {
        lit.classList.remove("an-lit");
        lit = null;
      }
      const r = id ? byId.get(id) : undefined;
      if (r) {
        r.classList.add("an-lit");
        lit = r;
      }
    },
  };
  ctx.hover.on((id) => handle.highlight(id));
  return handle;
}
