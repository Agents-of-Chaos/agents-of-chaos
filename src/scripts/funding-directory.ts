/* Directory view for /funding — the same landscape as scannable text.
 * Funder kind → rows sorted by $/yr (unknown last), then grantees grouped by
 * primary domain. People stay on the map + dossiers; a text roster of program
 * officers would read as a call sheet, which is not the public page's job.
 *
 * Pure module: no graph state. funding-graph.ts hands it the visible node list
 * + predicates + an onSelect callback (opens the shared dossier). */

import type { FundingNode, FunderNode, GranteeNode, DomainMeta } from "../data/funding-types";
import { FUNDER_KINDS, GRANTEE_COLOR, escapeHtml as esc } from "../data/funding-types";

export interface FundingDirectoryOpts {
  domains: DomainMeta[];
  onSelect: (id: string) => void;
  isOpen: (f: FunderNode) => boolean; // open-now (snapshot-dated)
  usdOf: (n: FundingNode) => number | null; // funding-core nodeDollars
  fmt: (n: number | null) => string; // funding-core formatUsd
  warmOf?: (id: string) => string | undefined; // dev-only; undefined in prod
  isCommitment: (f: FunderNode) => boolean; // true → "committed" label instead of "/yr"
}

/** (Re)render the grouped directory of `visible` nodes into `container`. */
export function renderFundingDirectory(
  container: HTMLElement, visible: FundingNode[], opts: FundingDirectoryOpts,
): void {
  const funders = visible.filter((n): n is FunderNode => n.kind === "funder");
  const grantees = visible.filter((n): n is GranteeNode => n.kind === "grantee");
  const maxUsd = Math.max(1, ...funders.map((f) => opts.usdOf(f) ?? 0), ...grantees.map((g) => opts.usdOf(g) ?? 0));
  const dotPx = (usd: number | null) => (usd == null ? 5 : 5 + Math.round(8 * Math.sqrt(usd / maxUsd)));
  const byUsd = (a: FundingNode, b: FundingNode) =>
    (opts.usdOf(b) ?? -1) - (opts.usdOf(a) ?? -1) || (a.name < b.name ? -1 : 1);

  const parts: string[] = [];
  for (const k of FUNDER_KINDS) {
    const rows = funders.filter((f) => f.funderKind === k.id).sort(byUsd);
    if (!rows.length) continue;
    parts.push(
      `<section class="dir-v"><h3 class="dir-vhead"><span class="dir-vname" style="color:${k.color}">${esc(
        k.label,
      )}</span><span class="dir-vcount">${rows.length}</span></h3><div class="dir-sub">`,
    );
    for (const f of rows) parts.push(funderRow(f, k.color, dotPx, opts));
    parts.push(`</div></section>`);
  }
  if (grantees.length) {
    parts.push(
      `<section class="dir-v"><h3 class="dir-vhead"><span class="dir-vname" style="color:${GRANTEE_COLOR}">grantees</span><span class="dir-vcount">${grantees.length}</span></h3>`,
    );
    for (const dm of opts.domains) {
      const rows = grantees.filter((g) => (g.domainTags ?? [])[0] === dm.id).sort(byUsd);
      if (!rows.length) continue;
      parts.push(`<div class="dir-sub"><div class="dir-shead"><span class="dir-slabel">${esc(dm.label)}</span></div>`);
      for (const g of rows) parts.push(granteeRow(g, dotPx, opts));
      parts.push(`</div>`);
    }
    const untagged = grantees.filter((g) => !(g.domainTags ?? []).length).sort(byUsd);
    if (untagged.length) {
      parts.push(`<div class="dir-sub"><div class="dir-shead"><span class="dir-slabel">other</span></div>`);
      for (const g of untagged) parts.push(granteeRow(g, dotPx, opts));
      parts.push(`</div>`);
    }
    parts.push(`</section>`);
  }

  // columns on an auto-height inner wrapper — a definite-height multicol
  // overflows sideways instead of scrolling down (same fix as /networks).
  container.innerHTML = parts.length
    ? `<div class="dir-cols">${parts.join("")}</div>`
    : `<p class="dir-empty">Nothing matches the current filters.</p>`;

  container.onclick = (ev) => {
    const el = (ev.target as HTMLElement).closest<HTMLElement>(".dir-row");
    if (el?.dataset.id) opts.onSelect(el.dataset.id);
  };
}

function funderRow(
  f: FunderNode, color: string, dotPx: (u: number | null) => number, opts: FundingDirectoryOpts,
): string {
  const usd = opts.usdOf(f);
  const open = opts.isOpen(f);
  const warm = opts.warmOf?.(f.id);
  const cls = ["dir-row", open ? "is-open" : ""].filter(Boolean).join(" ");
  const px = dotPx(usd);
  const ann = usd != null
    ? `<span class="dir-usd">${opts.fmt(usd)}${opts.isCommitment(f) ? " committed" : "/yr"}</span>`
    : `<span class="dir-usd">$ ?</span>`;
  return (
    `<button class="${cls}" data-id="${esc(f.id)}" type="button">` +
    `<span class="dir-dot" style="width:${px}px;height:${px}px;background:${color}"></span>` +
    `<span class="dir-name">${esc(f.name)}</span>` +
    (open ? `<span class="dir-pill dir-pill-open">open</span>` : "") +
    ann +
    (warm ? `<span class="dir-warm">↪ ${esc(warm)}</span>` : "") +
    `</button>`
  );
}

function granteeRow(
  g: GranteeNode, dotPx: (u: number | null) => number, opts: FundingDirectoryOpts,
): string {
  const usd = opts.usdOf(g);
  const px = dotPx(usd);
  const ann = usd != null ? `<span class="dir-usd">${opts.fmt(usd)}</span>` : "";
  return (
    `<button class="dir-row" data-id="${esc(g.id)}" type="button">` +
    `<span class="dir-dot" style="width:${px}px;height:${px}px;background:${GRANTEE_COLOR}"></span>` +
    `<span class="dir-name">${esc(g.name)}</span>${ann}</button>`
  );
}
