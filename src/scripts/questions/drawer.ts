// The evidence drawer: the active question's ranked table, collapsed by
// default behind a one-line handle. Reuses the analyses table archetype with a
// synthesized minimal ctx; rows hover-link to the map through opts.onHover.
// Styling lives in QuestionStrip.astro (.net-q-dwr, global).

import type { AnalysesCtx, RankedRow } from "../../data/analyses-types";
import { escapeHtml } from "../../data/network-types";
import { fmt } from "../analyses-core.js";
import { renderTable } from "../analyses/archetypes/table";
import type { QuestionDef, QuestionResult } from "./types";

export interface DrawerHandle {
  /** map-side hover → light the matching row */
  highlight(id: string | null): void;
}

export function mountDrawer(
  drawerEl: HTMLElement,
  def: QuestionDef,
  result: QuestionResult,
  opts: {
    onHover(id: string | null): void;
    appendixPath: string;
    /** the baked question's fine print — what this map can't see */
    blindSpot?: string;
  },
): DrawerHandle {
  drawerEl.classList.add("net-q-dwr");
  drawerEl.classList.remove("open");
  drawerEl.innerHTML = "";

  const n = Math.min(result.rows.length, 25);
  const handleBtn = document.createElement("button");
  handleBtn.type = "button";
  handleBtn.className = "net-q-dhandle";
  handleBtn.setAttribute("aria-expanded", "false");
  const setHandleText = (open: boolean) => {
    handleBtn.textContent = `evidence · ${n} ${n === 1 ? "row" : "rows"} ${open ? "▾" : "▴"}`;
  };
  setHandleText(false);

  const body = document.createElement("div");
  body.className = "net-q-dbody";
  body.hidden = true;

  handleBtn.addEventListener("click", () => {
    body.hidden = !body.hidden;
    drawerEl.classList.toggle("open", !body.hidden);
    handleBtn.setAttribute("aria-expanded", String(!body.hidden));
    setHandleText(!body.hidden);
  });

  const tableWrap = document.createElement("div");
  tableWrap.className = "net-q-dtable";
  body.appendChild(tableWrap);

  const footer = document.createElement("div");
  footer.className = "net-q-dfoot";
  // blind spot first (what the map can't see), then the methods link
  const blind = opts.blindSpot?.trim()
    ? `<span class="net-q-blind">${escapeHtml(opts.blindSpot)}</span>`
    : "";
  footer.innerHTML = `${blind}<a class="net-q-src" href="${escapeHtml(opts.appendixPath)}?a=${encodeURIComponent(def.source[0])}">how was this computed? →</a>`;
  body.appendChild(footer);

  drawerEl.append(handleBtn, body);

  // minimal ctx: only what renderTable touches (fmt/esc/empty/staleIds/hover)
  const subs: ((id: string | null) => void)[] = [];
  const ctx = {
    fmt,
    esc: escapeHtml,
    empty(el: HTMLElement, msg: string) {
      el.innerHTML = `<p class="net-q-empty">${escapeHtml(msg)}</p>`;
    },
    staleIds: new Set<string>(),
    hover: {
      set(id: string | null) {
        for (const fn of subs) fn(id); // lights the row itself
        opts.onHover(id); // and spotlights the node on the map
      },
      on(fn: (id: string | null) => void) {
        subs.push(fn);
      },
    },
  } as unknown as AnalysesCtx;

  const tableHandle = renderTable(
    tableWrap,
    { rows: result.rows as unknown as RankedRow[], columns: result.columns, maxRows: 25 },
    ctx,
  );

  drawerEl.hidden = false;
  return { highlight: (id) => tableHandle.highlight(id) };
}

export function clearDrawer(drawerEl: HTMLElement): void {
  drawerEl.hidden = true;
  drawerEl.classList.remove("open");
  drawerEl.innerHTML = "";
}
