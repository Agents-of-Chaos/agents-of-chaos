/* Company-landscape map for /networks. Mirrors the /team evidence graph
 * (src/scripts/team-graph.ts) — force layout, hover highlight, click-to-pin
 * detail panel, node drag, deep links, reduced-motion handling — and adds what
 * a ~175-node market map needs: zoom/pan, category "territory" layout (each
 * vertical pulled toward its own region), provenance dashing (verified vs
 * AI-inferred edges), search + filter chips, and the dev-only PRIVATE overlay
 * (warm-intro paths + pipeline stage).
 *
 * Color = vertical. Size = deployment intensity. Red is reserved for highlight
 * and the customer end of the funnel. This module owns ALL client behavior on
 * the page; it must stay in a default processed <script> (no is:inline /
 * define:vars) so its bundled d3 + data imports work. */

import * as d3 from "d3";
import { companies, edges, VERTICALS, STAGES, verticalColor, verticalLabel, stageColor, stageLabel } from "../data/companies";
import type { Company, CompanyEdge, Vertical, Stage, PrivateOverlayEntry } from "../data/network-types";

type CNode = Company & d3.SimulationNodeDatum;
type CLink = Omit<CompanyEdge, "source" | "target"> & { source: CNode; target: CNode };
type Sel = { id: string } | null;

const HALO = "#fffff8"; // --bg
// every stage past "cold" gets a colored ring; derived so a new stage can't drift out of sync
const ADVANCED = new Set<Stage>(STAGES.filter((s) => s.id !== "cold").map((s) => s.id));
const ESC_MAP: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const esc = (s: string) => String(s).replace(/[&<>"]/g, (c) => ESC_MAP[c]!);

export function initNetworkGraph(overlayEntries: PrivateOverlayEntry[] = []): void {
  const graphEl = document.getElementById("net-graph")!;
  const tooltip = document.getElementById("net-tip")!;
  const detail = document.getElementById("net-detail")!;
  const searchEl = document.getElementById("net-search") as HTMLInputElement | null;
  const vchips = document.getElementById("net-verticals")!;
  const schips = document.getElementById("net-stages"); // private; may be absent
  const legendEl = document.getElementById("net-legend")!;
  const coarse = matchMedia("(pointer: coarse)").matches;
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const overlay = new Map(overlayEntries.map((e) => [e.id, e]));
  const isPrivate = overlay.size > 0;
  const stageOf = (id: string): Stage | undefined => overlay.get(id)?.stage;
  const warmOf = (id: string): string | undefined => overlay.get(id)?.warm_path;
  // a node gets a colored stage ring only in the private view and only past "cold"
  const ringColor = (id: string): string | undefined => {
    const st = stageOf(id);
    return isPrivate && st && ADVANCED.has(st) ? stageColor(st) : undefined;
  };

  /* ---------- data: one pass, then static ---------- */
  const nodes: CNode[] = companies.map((c) => ({ ...c }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links: CLink[] = edges.flatMap((e) => {
    const source = byId.get(e.source), target = byId.get(e.target);
    return source && target ? [{ ...e, source, target }] : [];
  });

  // adjacency for neighborhood highlight
  const adj = new Map<string, Set<string>>(nodes.map((n) => [n.id, new Set<string>()]));
  for (const l of links) { adj.get(l.source.id)!.add(l.target.id); adj.get(l.target.id)!.add(l.source.id); }

  const r = d3.scaleSqrt().domain([1, 5]).range([4, 16]).clamp(true); // size = intensity
  // semantic zoom: zoomed out only the biggest get a standing label; zoom into a region and the
  // cutoff drops so more company names appear. Hover/selection still labels the focal node + neighbours.
  let zoomK = 1, inited = false;
  const labelCutoff = (k: number) => (k >= 3 ? 0 : k >= 1.8 ? 3 : k >= 1.1 ? 4 : 5);
  const labelled = (d: CNode) => d.intensity >= labelCutoff(zoomK);
  const confOpacity = (d: CNode) => (d.confidence === "low" ? 0.62 : d.confidence === "medium" ? 0.82 : 1);

  /* ---------- svg scaffold (fixed viewBox; CSS scales it) ---------- */
  const W = graphEl.clientWidth || 1100, H = graphEl.clientHeight || 700;
  const svg = d3.select(graphEl).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const root = svg.append("g"); // zoom/pan target
  const linkG = root.append("g");
  const nodeG = root.append("g");
  svg.on("click", () => select(null));

  /* category "territories": each vertical gets a centroid on a grid; the force
   * pulls its companies toward it, so position itself reads as market. Force
   * relaxes exact placement for an organic feel (hybrid). */
  const present = VERTICALS.filter((v) => nodes.some((n) => n.vertical === v.id));
  const cols = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(present.length))));
  const rows = Math.max(1, Math.ceil(present.length / cols));
  const mx = W * 0.14, my = H * 0.16;
  const centroid = new Map<Vertical, { x: number; y: number }>();
  present.forEach((v, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    centroid.set(v.id, {
      x: mx + (cols === 1 ? 0.5 : col / (cols - 1 || 1)) * (W - 2 * mx),
      y: my + (rows === 1 ? 0.5 : row / (rows - 1 || 1)) * (H - 2 * my),
    });
  });
  // deterministic seed near the vertical centroid (no Math.random — stable layout)
  const perV = new Map<Vertical, number>();
  nodes.forEach((n) => {
    const c = centroid.get(n.vertical) ?? { x: W / 2, y: H / 2 };
    const k = perV.get(n.vertical) ?? 0; perV.set(n.vertical, k + 1);
    const a = k * 2.399963; // golden-angle spiral for a tidy initial cluster
    n.x = n.x ?? c.x + Math.cos(a) * (10 + 6 * k ** 0.5);
    n.y = n.y ?? c.y + Math.sin(a) * (10 + 6 * k ** 0.5);
  });

  const sim = d3.forceSimulation<CNode>(nodes)
    .force("charge", d3.forceManyBody<CNode>().strength(-150).distanceMax(420))
    .force("x", d3.forceX<CNode>((d) => centroid.get(d.vertical)?.x ?? W / 2).strength(0.22))
    .force("y", d3.forceY<CNode>((d) => centroid.get(d.vertical)?.y ?? H / 2).strength(0.22))
    .force("link", d3.forceLink<CNode, CLink>(links).distance(58).strength(0.12))
    .force("collide", d3.forceCollide<CNode>().radius((d) => r(d.intensity) + 4).strength(0.9))
    .on("tick", tick);

  /* ---------- edges: type → color/width, provenance → dash ---------- */
  const edgeStroke = (l: CLink) =>
    l.type === "competitor" ? "#c7b0a8" : l.type === "shared-investor" ? "#bcc3b0" : "#9a958c";
  const edgeWidth = (l: CLink) => (l.type === "business" ? 1.4 : 0.9);
  const edgeDash = (l: CLink) =>
    !l.verified ? "2 3" : l.type === "competitor" ? "1 4" : null; // inferred OR competitor reads dashed

  const linkSel = linkG.selectAll<SVGLineElement, CLink>("line.edge").data(links).join("line")
    .attr("class", "edge").attr("stroke", edgeStroke).attr("stroke-width", edgeWidth)
    .attr("stroke-dasharray", edgeDash).attr("stroke-opacity", 0.5)
    .attr("marker-end", (l) => (l.directed ? "url(#net-arrow)" : null));
  // wide transparent "hit" lines make the thin edges easy to hover for the connection tooltip
  const hitSel = linkG.selectAll<SVGLineElement, CLink>("line.hit").data(links).join("line")
    .attr("class", "hit").attr("stroke", "transparent").attr("stroke-width", 12).style("cursor", "pointer");

  // arrowhead for directed business ties
  svg.append("defs").append("marker").attr("id", "net-arrow")
    .attr("viewBox", "0 -5 10 10").attr("refX", 18).attr("refY", 0)
    .attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
    .append("path").attr("d", "M0,-4L9,0L0,4").attr("fill", "#9a958c");

  /* ---------- nodes ---------- */
  const nodeSel = nodeG.selectAll<SVGGElement, CNode>("g.cnode").data(nodes).join("g")
    .attr("class", "cnode").style("cursor", "pointer");
  nodeSel.append("circle")
    .attr("r", (d) => r(d.intensity))
    .attr("fill", (d) => verticalColor(d.vertical))
    .attr("fill-opacity", confOpacity)
    .attr("stroke", (d) => ringColor(d.id) ?? HALO)
    .attr("stroke-width", (d) => (ringColor(d.id) ? 2.5 : 1.4));
  nodeSel.append("text").attr("class", "net-label").attr("y", (d) => -r(d.intensity) - 4)
    .text((d) => d.name).style("display", (d) => (labelled(d) ? null : "none"));
  const labelSel = nodeSel.select<SVGTextElement>("text.net-label"); // cache: reused on every highlight
  nodeSel.on("click", (ev: MouseEvent, d) => { ev.stopPropagation(); select({ id: d.id }); });

  if (!coarse) {
    nodeSel.on("mousemove", nodeTip).on("mouseleave", leaveNode);
    hitSel.on("mousemove", edgeTip).on("mouseleave", leaveEdge);
    nodeSel.call(d3.drag<SVGGElement, CNode>()
      .on("start", (_ev, d) => { sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (_ev, d) => { sim.alphaTarget(0); d.fx = d.fy = null; }));
  }

  function tick() {
    for (const sel of [linkSel, hitSel])
      sel.attr("x1", (l) => l.source.x!).attr("y1", (l) => l.source.y!)
        .attr("x2", (l) => l.target.x!).attr("y2", (l) => l.target.y!);
    nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
  }

  /* ---------- zoom / pan (fit after settle; double-click re-fits) ---------- */
  const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 6])
    .on("zoom", (ev) => {
      root.attr("transform", ev.transform.toString());
      const k = ev.transform.k;
      if (inited && labelCutoff(k) !== labelCutoff(zoomK)) { zoomK = k; refreshLabels(); }
      else zoomK = k;
    });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("dblclick", () => fit(true));

  function fit(animate: boolean) {
    const b = (root.node() as SVGGElement).getBBox();
    if (!b.width || !b.height) return;
    const pad = 40;
    const k = Math.min((W - 2 * pad) / b.width, (H - 2 * pad) / b.height, 1.6);
    const tx = (W - b.width * k) / 2 - b.x * k, ty = (H - b.height * k) / 2 - b.y * k;
    const t = d3.zoomIdentity.translate(tx, ty).scale(k);
    if (animate) svg.transition().duration(450).call(zoom.transform, t);
    else svg.call(zoom.transform, t);
  }

  // pre-settle synchronously so the FIRST paint is already framed
  sim.stop();
  for (let i = 0; i < 220; i++) sim.tick();
  tick();
  fit(false);
  if (!calm) { sim.alpha(0.25).restart(); sim.on("end", () => fit(true)); }

  /* ---------- filters: verticals (public) + stages / warm-only (private) ---------- */
  const activeVerticals = new Set<Vertical>(present.map((v) => v.id));
  const activeStages = new Set<Stage>(STAGES.map((s) => s.id));
  let warmOnly = false;
  let visibleSet = new Set<string>(); // recomputed once per filter change; read on every highlight

  function matches(d: CNode, q: string): boolean {
    if (!activeVerticals.has(d.vertical)) return false;
    if (q && !d.name.toLowerCase().includes(q) && !d.blurb.toLowerCase().includes(q)) return false;
    if (isPrivate) {
      if (warmOnly && !warmOf(d.id)) return false;
      if (!activeStages.has(stageOf(d.id) ?? "cold")) return false; // unstaged counts as cold
    }
    return true;
  }
  function recomputeVisible() {
    const q = searchEl?.value.trim().toLowerCase() ?? ""; // read the DOM once, not per-node
    visibleSet = new Set(nodes.filter((d) => matches(d, q)).map((d) => d.id));
  }
  const shown = (d: CNode) => visibleSet.has(d.id);
  recomputeVisible(); // initial fill (everything visible)

  function applyFilter() {
    recomputeVisible();
    nodeSel.style("display", (d) => (shown(d) ? null : "none"));
    const edgeShown = (l: CLink) => (shown(l.source) && shown(l.target) ? null : "none");
    linkSel.style("display", edgeShown);
    hitSel.style("display", edgeShown); // hidden edges must not be hoverable
    applyHighlight();
  }

  // build a row of toggle-chips over {id,label,color} items, each toggling membership in `active`
  function buildChips<T extends string>(
    container: HTMLElement, items: { id: T; label: string; color: string }[], active: Set<T>,
  ): void {
    for (const it of items) {
      const chip = document.createElement("button");
      chip.className = "net-chip on";
      chip.innerHTML = `<span class="sw" style="background:${it.color}"></span>${esc(it.label)}`;
      chip.addEventListener("click", () => {
        active.has(it.id) ? active.delete(it.id) : active.add(it.id);
        chip.classList.toggle("on", active.has(it.id));
        applyFilter();
      });
      container.appendChild(chip);
    }
  }

  buildChips(vchips, present, activeVerticals);
  if (isPrivate && schips) {
    const warmChip = document.createElement("button");
    warmChip.className = "net-chip net-chip-warm";
    warmChip.textContent = "warm paths only";
    warmChip.addEventListener("click", () => {
      warmOnly = !warmOnly;
      warmChip.classList.toggle("on", warmOnly);
      applyFilter();
    });
    schips.appendChild(warmChip);
    buildChips(schips, STAGES, activeStages);
  }

  searchEl?.addEventListener("input", applyFilter);

  /* ---------- legend: the minimalist key (color / size / lines) ---------- */
  legendEl.innerHTML =
    `<span class="net-leg-item">color · vertical</span>` +
    `<span class="net-leg-item"><span class="net-leg-dot" style="width:6px;height:6px"></span>` +
    `<span class="net-leg-dot" style="width:14px;height:14px"></span> size · agents in production</span>` +
    `<span class="net-leg-item"><span class="net-leg-ln"></span> verified tie</span>` +
    `<span class="net-leg-item"><span class="net-leg-ln dash"></span> inferred</span>` +
    `<span class="net-leg-item net-leg-dim">zoom in for more names</span>` +
    (isPrivate ? `<span class="net-leg-item net-leg-priv">● ring · stage (dev)</span>` : "");

  /* ---------- highlight ---------- */
  let selected: Sel = null, hover: Sel = null;
  function neigh(sel: Sel) {
    if (!sel) return null;
    const set = new Set<string>([sel.id]);
    for (const id of adj.get(sel.id) ?? []) set.add(id);
    return set;
  }
  function applyHighlight() {
    const nb = neigh(hover ?? selected);
    nodeSel.attr("opacity", (d) => (!shown(d) ? 0 : !nb ? 1 : nb.has(d.id) ? 1 : 0.12));
    linkSel.attr("stroke-opacity", (l) =>
      !shown(l.source) || !shown(l.target) ? 0
        : !nb ? 0.5 : nb.has(l.source.id) && nb.has(l.target.id) ? 0.9 : 0.04);
    refreshLabels();
  }
  // label visibility = highlight neighbours if any, else the zoom-dependent cutoff (semantic LOD)
  function refreshLabels() {
    const nb = neigh(hover ?? selected);
    labelSel.style("display", (d) =>
      !shown(d) ? "none" : nb ? (nb.has(d.id) ? null : "none") : labelled(d) ? null : "none");
  }

  // ---- edge hover: tooltip describing the connection + spotlight the two companies ----
  let hoverEdge: CLink | null = null;
  function emphasizeEdge(l: CLink) {
    const a = l.source.id, b = l.target.id;
    nodeSel.attr("opacity", (d) => (!shown(d) ? 0 : d.id === a || d.id === b ? 1 : 0.12));
    linkSel.attr("stroke-opacity", (x) => (x === l ? 0.95 : !shown(x.source) || !shown(x.target) ? 0 : 0.05));
    labelSel.style("display", (d) => (!shown(d) ? "none" : d.id === a || d.id === b ? null : "none"));
  }
  function edgeTip(ev: MouseEvent, l: CLink) {
    if (hoverEdge !== l) { hoverEdge = l; emphasizeEdge(l); }
    const arrow = l.directed ? "→" : "↔";
    const kind = l.type === "shared-investor" ? "shared investor" : l.type;
    showTip(ev, `<div class="t-name">${esc(l.source.name)} ${arrow} ${esc(l.target.name)}</div>
      <div class="t-sub">${esc(l.label ?? kind)}${l.verified ? "" : " · inferred"}</div>`);
  }
  function leaveEdge() { hoverEdge = null; tooltip.style.opacity = "0"; applyHighlight(); }

  function select(sel: Sel) {
    selected = sel; hover = null;
    renderDetail(); applyHighlight();
    if (sel) location.hash = "c=" + encodeURIComponent(sel.id);
    else if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  }

  /* ---------- detail dossier ---------- */
  const dots = (n: number) => { const k = Math.round(n); return "●".repeat(k) + "○".repeat(5 - k); };
  function renderDetail() {
    if (!selected) { detail.innerHTML = ""; return; }
    const c = byId.get(selected.id)!;
    const rels = links.filter((l) => l.source.id === c.id || l.target.id === c.id).map((l) => {
      const other = l.source.id === c.id ? l.target : l.source;
      const arrow = l.directed ? (l.source.id === c.id ? "→" : "←") : "↔";
      return `<div class="d-row"><span class="swatch" style="background:${verticalColor(other.vertical)}"></span>
        <div><span class="d-org">${arrow} ${esc(other.name)}</span>
        <div class="d-meta">${esc(l.label ?? l.type)}${l.verified ? "" : " · inferred"}</div></div></div>`;
    });
    const ov = overlay.get(c.id);
    let priv = "";
    if (isPrivate && ov) {
      priv = `<div class="d-priv">
        ${ov.stage ? `<div class="d-row"><span class="d-key">stage</span>
          <span class="d-badge" style="background:${stageColor(ov.stage)}">${esc(stageLabel(ov.stage))}</span></div>` : ""}
        ${ov.warm_path ? `<div class="d-warm"><span class="d-key">warm path</span> ${esc(ov.warm_path)}</div>` : ""}
        ${ov.notes ? `<div class="d-note">${esc(ov.notes)}</div>` : ""}</div>`;
    }
    detail.innerHTML = `<span class="d-clear" title="clear">✕</span>
      <div class="d-title">${esc(c.name)}</div>
      <div class="d-sub" style="color:${verticalColor(c.vertical)}">${esc(verticalLabel(c.vertical))} · <span class="d-int" title="deployment intensity">${dots(c.intensity)}</span></div>
      <div class="d-blurb">${esc(c.blurb)}</div>
      ${c.buyer_persona ? `<div class="d-line"><span class="d-key">buyer</span> ${esc(c.buyer_persona)}</div>` : ""}
      ${c.trigger ? `<div class="d-line"><span class="d-key">trigger</span> ${esc(c.trigger)}</div>` : ""}
      ${c.investors?.length ? `<div class="d-line"><span class="d-key">investors</span> ${esc(c.investors.join(", "))}</div>` : ""}
      ${priv}
      ${rels.length ? `<div class="d-rels">${rels.join("")}</div>` : ""}
      ${c.url ? `<div class="d-src"><a href="${esc(c.url)}" target="_blank" rel="noopener">→ ${esc(c.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}</a></div>` : ""}`;
    detail.querySelector(".d-clear")!.addEventListener("click", () => select(null));
  }

  /* ---------- tooltip ---------- */
  function showTip(ev: MouseEvent, html: string) {
    tooltip.innerHTML = html; tooltip.style.opacity = "1";
    const pad = 14, w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    tooltip.style.left = Math.min(ev.clientX + pad, innerWidth - w - 8) + "px";
    tooltip.style.top = Math.min(ev.clientY + pad, innerHeight - h - 8) + "px";
  }
  function leaveNode() { tooltip.style.opacity = "0"; if (hover) { hover = null; applyHighlight(); } }
  function nodeTip(ev: MouseEvent, d: CNode) {
    if (!hover || hover.id !== d.id) { hover = { id: d.id }; applyHighlight(); }
    const st = isPrivate ? stageOf(d.id) : undefined;
    const stHtml = st ? ` <span class="t-badge" style="background:${stageColor(st)}">${esc(stageLabel(st))}</span>` : "";
    const warm = isPrivate ? warmOf(d.id) : undefined;
    showTip(ev, `<div class="t-name">${esc(d.name)}${stHtml}</div>
      <div class="t-sub" style="color:${verticalColor(d.vertical)}">${esc(verticalLabel(d.vertical))} · ${dots(d.intensity)}</div>
      <div class="t-blurb">${esc(d.blurb)}</div>${warm ? `<div class="t-warm">↪ ${esc(warm)}</div>` : ""}`);
  }

  window.addEventListener("keydown", (ev) => { if (ev.key === "Escape") select(null); });

  /* ---------- ?focus= / #c= deep links ---------- */
  function selectFromHash() {
    const m = location.hash.match(/^#c=(.+)$/);
    if (m) { const id = decodeURIComponent(m[1]); if (byId.has(id)) select({ id }); }
  }
  const focus = new URLSearchParams(location.search).get("focus");
  if (focus && byId.has(focus)) select({ id: focus });
  else selectFromHash();
  window.addEventListener("hashchange", selectFromHash);

  // init done: now zoom changes may reveal more labels; sync once to the settled fit scale
  inited = true;
  refreshLabels();

  // resize: keep viewBox proportional; CSS already scales the svg
  window.addEventListener("resize", () => fit(false));
}
