// Ranked-table archetype: plain HTML <table>, hover-bus wired, stale rows
// dimmed with a dagger. The most-used block on the page.

import type { AnalysesCtx, BlockHandle, Column, TableSpec } from "../../../data/analyses-types";

function formatCell(ctx: AnalysesCtx, col: Column, v: unknown): string {
  if (v == null) return "—";
  switch (col.format) {
    case "num":
      return ctx.fmt.num(v as number, col.digits ?? 2);
    case "usd":
      return ctx.fmt.usd(v as number);
    case "pct":
      return ctx.fmt.pct(v as number);
    case "sig":
      return ctx.fmt.sig(v as number);
    case "flag":
      return v ? `<span class="an-flag">${ctx.esc(String(v))}</span>` : "";
    default:
      return ctx.esc(String(v));
  }
}

export function renderTable(el: HTMLElement, spec: TableSpec, ctx: AnalysesCtx): BlockHandle {
  const rows = spec.rows.slice(0, spec.maxRows ?? 25);
  if (!rows.length) {
    ctx.empty(el, "nothing cleared the bar for this table.");
    return { highlight() {} };
  }
  const rankStart = spec.rankStart ?? 1;
  const table = document.createElement("table");
  table.className = "an-table";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  if (rankStart > 0) hr.appendChild(document.createElement("th"));
  for (const col of spec.columns) {
    const th = document.createElement("th");
    th.textContent = col.label;
    if (col.hint) th.title = col.hint;
    if (col.format !== "text" && col.format !== "flag") th.className = "an-num";
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  const byId = new Map<string, HTMLTableRowElement>();
  rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    const stale = row.id != null && ctx.staleIds.has(row.id);
    if (stale) tr.className = "an-stale";
    if (rankStart > 0) {
      const td = document.createElement("td");
      td.className = "an-rank";
      td.textContent = `${rankStart + i}`;
      tr.appendChild(td);
    }
    for (const col of spec.columns) {
      const td = document.createElement("td");
      if (col.format !== "text" && col.format !== "flag") td.className = "an-num";
      let html = formatCell(ctx, col, row[col.key]);
      if (col.key === "label" && stale) html += ' <span class="an-dagger" title="no longer on the current map">†</span>';
      td.innerHTML = html;
      tr.appendChild(td);
    }
    if (row.id) {
      const id = row.id;
      byId.set(id, tr);
      tr.addEventListener("mouseenter", () => ctx.hover.set(id));
      tr.addEventListener("mouseleave", () => ctx.hover.set(null));
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  el.appendChild(table);

  let lit: HTMLTableRowElement | null = null;
  const handle: BlockHandle = {
    highlight(id) {
      if (lit) {
        lit.classList.remove("an-lit");
        lit = null;
      }
      const tr = id ? byId.get(id) : undefined;
      if (tr) {
        tr.classList.add("an-lit");
        lit = tr;
      }
    },
  };
  ctx.hover.on((id) => handle.highlight(id));
  return handle;
}
