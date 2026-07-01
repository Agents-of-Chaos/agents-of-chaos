/* Directory view for /networks — the "list orgs as text" companion to the map
 * (inspired by alex-loftus.com/networks/affiliations). Groups the SAME company
 * set the map shows into: vertical → "what they do" sub-category → companies as
 * compact text rows. Built to answer two questions at a glance:
 *   1. who are our DIRECT COMPETITORS  → the `competitor` flag lights rows up in
 *      accent red wherever they sit (red-teamers are scattered across buckets).
 *   2. where are PATHS TO CUSTOMERS    → buyer sub-categories are tagged, likely
 *      customers (high deployment intensity) show their buyer persona inline, and
 *      the dev-only warm path rides along.
 *
 * Pure module: no graph state. networks-graph.ts hands it the filtered company
 * list + a few predicates + an onSelect callback (which opens the shared dossier). */

import type { Company, Vertical, SubcategoryTable } from "../data/network-types";
import { VERTICALS, escapeHtml as esc } from "../data/network-types";

const AOC_ID = "agents-of-chaos";
// intensity (0..5) → a small left dot, so deployment scale reads without leaving text
const dotPx = (i: number) => 5 + Math.round(Math.sqrt(Math.max(0, i)) * 3.2);

export interface DirectoryOpts {
  subcats: SubcategoryTable;
  onSelect: (id: string) => void;
  isLikelyCustomer: (c: Company) => boolean; // buyer sub-category + high intensity
  rankOf?: (c: Company) => number | undefined; // "#k" learn-about rank (when priority bar engaged)
  warmOf?: (id: string) => string | undefined; // dev-only; undefined in prod
}

/** (Re)render the grouped directory of `visible` companies into `container`. */
export function renderDirectory(container: HTMLElement, visible: Company[], opts: DirectoryOpts): void {
  // bucket the visible set: vertical → subcategory key → companies
  const byV = new Map<Vertical, Map<string, Company[]>>();
  for (const c of visible) {
    let m = byV.get(c.vertical);
    if (!m) byV.set(c.vertical, (m = new Map()));
    let arr = m.get(c.subcategory);
    if (!arr) m.set(c.subcategory, (arr = []));
    arr.push(c);
  }

  const parts: string[] = [];
  for (const v of VERTICALS) {
    const m = byV.get(v.id);
    if (!m) continue;
    const total = [...m.values()].reduce((s, a) => s + a.length, 0);
    parts.push(
      `<section class="dir-v"><h3 class="dir-vhead"><span class="dir-vname" style="color:${v.color}">${esc(
        v.label,
      )}</span><span class="dir-vcount">${total}</span></h3>`,
    );
    // sub-categories in canonical order; skip empty ones
    for (const sc of opts.subcats[v.id] ?? []) {
      const rows = m.get(sc.key);
      if (!rows || !rows.length) continue;
      rows.sort((a, b) => b.intensity - a.intensity || (a.name < b.name ? -1 : 1));
      const hasAoc = rows.some((c) => c.id === AOC_ID);
      const tag = hasAoc
        ? `<span class="dir-tag dir-tag-here">your space</span>`
        : sc.isBuyer
          ? `<span class="dir-tag dir-tag-buyer">likely buyers</span>`
          : "";
      parts.push(
        `<div class="dir-sub"><div class="dir-shead"><span class="dir-slabel"${
          sc.what ? ` title="${esc(sc.what)}"` : ""
        }>${esc(sc.label)}</span>${tag}</div>`,
      );
      for (const c of rows) parts.push(row(c, v.color, opts));
      parts.push(`</div>`);
    }
    parts.push(`</section>`);
  }

  // columns live on an inner auto-height wrapper, NOT on the fixed-height scroll
  // container — a multicol element with a definite block-size overflows sideways
  // instead of scrolling down (verticals would run off-screen).
  container.innerHTML = parts.length
    ? `<div class="dir-cols">${parts.join("")}</div>`
    : `<p class="dir-empty">No companies match the current filters.</p>`;

  // one delegated listener → open the shared dossier
  container.onclick = (ev) => {
    const el = (ev.target as HTMLElement).closest<HTMLElement>(".dir-row");
    if (el?.dataset.id) opts.onSelect(el.dataset.id);
  };
}

function row(c: Company, color: string, opts: DirectoryOpts): string {
  const isComp = c.competitor === true;
  const isCust = opts.isLikelyCustomer(c);
  const warm = opts.warmOf?.(c.id);
  const cls = ["dir-row", isComp ? "is-comp" : "", isCust ? "is-cust" : ""].filter(Boolean).join(" ");
  const marks =
    (isComp ? `<span class="dir-pill dir-pill-comp">competitor</span>` : "") +
    (isCust ? `<span class="dir-pill dir-pill-cust">target</span>` : "");
  // annotation: for a likely customer, who to talk to (buyer persona); in dev, the warm path
  const ann =
    (isCust && c.buyer_persona ? `<span class="dir-ann">${esc(c.buyer_persona)}</span>` : "") +
    (warm ? `<span class="dir-warm">↪ ${esc(warm)}</span>` : "");
  const px = dotPx(c.intensity);
  const rank = opts.rankOf?.(c);
  const rankHtml = rank ? `<span class="dir-rank">#${rank}</span>` : "";
  return (
    `<button class="${cls}" data-id="${esc(c.id)}" type="button">` +
    rankHtml +
    `<span class="dir-dot" style="width:${px}px;height:${px}px;background:${color}"></span>` +
    `<span class="dir-name">${esc(c.name)}</span>${marks}${ann}</button>`
  );
}
