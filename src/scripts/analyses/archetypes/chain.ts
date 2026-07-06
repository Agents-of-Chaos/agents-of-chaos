// Chain archetype: intro-path breadcrumbs — node pills joined by arrows with
// edge-type labels; dashed arrow = unverified tie.

import type { AnalysesCtx, BlockHandle, ChainSpec } from "../../../data/analyses-types";

export function renderChain(el: HTMLElement, spec: ChainSpec, ctx: AnalysesCtx): BlockHandle {
  if (!spec.chains.length) {
    ctx.empty(el, "no chains found.");
    return { highlight() {} };
  }
  const wrap = document.createElement("div");
  wrap.className = "an-chains";
  const byId = new Map<string, HTMLElement[]>();

  for (const chain of spec.chains) {
    const row = document.createElement("div");
    row.className = "an-chain";
    chain.nodes.forEach((n, i) => {
      const pill = document.createElement("span");
      pill.className = "an-pill";
      const stale = ctx.staleIds.has(n.id);
      pill.textContent = n.label + (stale ? " †" : "");
      if (stale) pill.classList.add("an-stale");
      pill.addEventListener("mouseenter", () => ctx.hover.set(n.id));
      pill.addEventListener("mouseleave", () => ctx.hover.set(null));
      const list = byId.get(n.id) ?? [];
      list.push(pill);
      byId.set(n.id, list);
      row.appendChild(pill);
      const e = chain.edges[i];
      if (i < chain.nodes.length - 1 && e) {
        const arrow = document.createElement("span");
        arrow.className = "an-arrow" + (e.verified === false ? " an-arrow-dashed" : "");
        arrow.innerHTML = e.label ? `<i>${ctx.esc(e.label)}</i> →` : "→";
        row.appendChild(arrow);
      }
    });
    wrap.appendChild(row);
  }
  el.appendChild(wrap);

  let lit: HTMLElement[] = [];
  const handle: BlockHandle = {
    highlight(id) {
      for (const p of lit) p.classList.remove("an-lit");
      lit = (id ? byId.get(id) : undefined) ?? [];
      for (const p of lit) p.classList.add("an-lit");
    },
  };
  ctx.hover.on((id) => handle.highlight(id));
  return handle;
}
