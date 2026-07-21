/* Funding-landscape map for /funding. Clone-and-adapt of networks-graph.ts:
 * force layout with funder-kind "territories", zoom/pan, hover spotlight,
 * click-to-pin dossier, drag, deep links — plus what a MONEY map needs:
 * sqrt-dollar node/edge sizing (area ∝ field-relevant $), an open-now lens,
 * a public BFS path finder, and the dev-only overlay (stage + warm paths).
 *
 * Color = funder kind (grantees gray-tan, people small outlined dots).
 * Size = sqrt(field dollars). Red stays reserved for highlight/path/funded. */

import * as d3 from "d3";
import {
  fundingNodes, fundingEdges, fundingMeta,
  FUNDER_KINDS, FUNDING_STAGES, DOMAINS,
  GRANTEE_COLOR, PERSON_COLOR,
  funderColor, funderLabel, fundingStageColor, fundingStageLabel, domainLabel, nodeColor,
  escapeHtml as esc,
} from "../data/funding";
import type {
  FundingNode, FunderNode, FundingEdge, FunderKind, FundingStage, FundingOverlayEntry,
} from "../data/funding-types";
import {
  makeSqrtScale, nodeDollars, radiusFor, edgeWidthFor,
  buildAdjacency, shortestPath, isOpenNow, computeVisible, sliderToUsd, formatUsd, topGrants,
} from "./funding-core.js";
import { renderFundingDirectory } from "./funding-directory";
import type { QuestionEngine, QuestionHost } from "./questions/types";

type FNode = FundingNode & d3.SimulationNodeDatum;
type FLink = { e: FundingEdge; source: FNode; target: FNode };
type Sel = { id: string } | null;

const HALO = "#fffff8"; // --bg
const OPEN_RING = "#4f7a4e"; // open-now lens (green, same family as /networks customer ring)
// pristine copy taken at module load, BEFORE anything touches the records —
// the question kernels (and their staleness rule: live names/dollars) must
// see clean data, same discipline as networks-graph.ts
const pristine = { nodes: structuredClone(fundingNodes), edges: structuredClone(fundingEdges) };
const ADVANCED = new Set<FundingStage>(FUNDING_STAGES.filter((s) => s.id !== "cold").map((s) => s.id));

export function initFundingGraph(overlayEntries: FundingOverlayEntry[] = []): void {
  const graphEl = document.getElementById("fund-graph")!;
  const tooltip = document.getElementById("fund-tip")!;
  const detail = document.getElementById("fund-detail")!;
  const searchEl = document.getElementById("fund-search") as HTMLInputElement | null;
  const coarse = matchMedia("(pointer: coarse)").matches;
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TODAY = fundingMeta.generatedAt; // snapshot clock — never the wall clock

  let view: "map" | "directory" = "map";
  let lensOpen = false; // Task 7 wires the chip; highlight logic below already honors it
  let route: { ids: string[]; len: number } | null = null; // Task 6 sets; highlight honors
  let routeLinks = new Set<FLink>();
  const inRoute = (id: string) => !!route && route.ids.includes(id);

  const overlay = new Map(overlayEntries.map((e) => [e.id, e]));
  const isPrivate = overlay.size > 0;
  const stageOf = (id: string): FundingStage | undefined => overlay.get(id)?.stage;
  const warmOf = (id: string): string | undefined => overlay.get(id)?.warm_path;
  const ringColor = (id: string): string | undefined => {
    const st = stageOf(id);
    return isPrivate && st && ADVANCED.has(st) ? fundingStageColor(st) : undefined;
  };

  /* ---------- data: one pass, then static ---------- */
  const nodes: FNode[] = fundingNodes.map((n) => ({ ...n }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links: FLink[] = fundingEdges.flatMap((e) => {
    const source = byId.get(e.source), target = byId.get(e.target);
    return source && target ? [{ e, source, target }] : [];
  });
  const adj = buildAdjacency(fundingNodes, fundingEdges);

  /* dollar → pixel scales, domains from the data itself */
  const nodeDollarVals = nodes.map(nodeDollars).filter((d): d is number => d != null);
  const rScale = makeSqrtScale(
    [Math.min(...nodeDollarVals), Math.max(...nodeDollarVals)], [5, 26]);
  const flowVals = links
    .map((l) => (l.e.type === "affiliation" ? null : l.e.amountUSD))
    .filter((d): d is number => d != null);
  const wScale = flowVals.length
    ? makeSqrtScale([Math.min(...flowVals), Math.max(...flowVals)], [0.7, 6])
    : () => 0.9;
  const r = (d: FNode) => radiusFor(d, rScale);
  const openSet = new Set(nodes.filter((n) => isOpenNow(n, TODAY)).map((n) => n.id));
  const maxAnnual = Math.max(0, ...nodes.map((n) => (n.kind === "funder" ? n.annualFieldGivingUSD ?? 0 : 0)));

  const BASE_LABEL = 11;
  let inited = false;
  const confOpacity = (d: FNode) => (d.confidence === "low" ? 0.62 : d.confidence === "medium" ? 0.82 : 1);

  /* ---------- svg scaffold ---------- */
  const W = graphEl.clientWidth || 1100, H = graphEl.clientHeight || 700;
  const svg = d3.select(graphEl).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const root = svg.append("g");
  const linkG = root.append("g");
  const qMarksG = root.append("g").attr("class", "q-marks"); // question marks: above edges, below nodes
  const nodeG = root.append("g");
  const qCalloutsG = root.append("g").attr("class", "q-callouts"); // question callouts: above everything
  svg.on("click", () => select(null));

  /* funder-kind "territories": 2×2 grid of centroids; ONLY funders are pulled
   * to them — grantees settle between their funders via the link force, and
   * people hug their funder via short strong affiliation links. */
  const present = FUNDER_KINDS.filter((k) => nodes.some((n) => n.kind === "funder" && n.funderKind === k.id));
  const cols = Math.min(2, Math.max(1, present.length));
  const rows = Math.max(1, Math.ceil(present.length / cols));
  const mx = W * 0.18, my = H * 0.2;
  const centroid = new Map<FunderKind, { x: number; y: number }>();
  present.forEach((k, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    centroid.set(k.id, {
      x: mx + (cols === 1 ? 0.5 : col / (cols - 1)) * (W - 2 * mx),
      y: my + (rows === 1 ? 0.5 : row / (rows - 1)) * (H - 2 * my),
    });
  });
  const kindOf = (d: FNode): FunderKind | null => (d.kind === "funder" ? d.funderKind : null);
  // deterministic seeding: funders spiral around their territory; grantees/people
  // start at their first neighbor's territory (or center) so the settle is short
  const perK = new Map<string, number>();
  const seedAt = (d: FNode): { x: number; y: number } => {
    const k = kindOf(d);
    if (k) return centroid.get(k)!;
    for (const nb of adj.get(d.id) ?? []) {
      const nbk = kindOf(byId.get(nb)!);
      if (nbk) return centroid.get(nbk)!;
    }
    return { x: W / 2, y: H / 2 };
  };
  nodes.forEach((n) => {
    const c = seedAt(n);
    const key = kindOf(n) ?? "float";
    const i = perK.get(key) ?? 0; perK.set(key, i + 1);
    const a = i * 2.399963; // golden-angle spiral — stable, no Math.random
    n.x = n.x ?? c.x + Math.cos(a) * (12 + 6 * i ** 0.5);
    n.y = n.y ?? c.y + Math.sin(a) * (12 + 6 * i ** 0.5);
  });

  const linkDist = (l: FLink) => (l.e.type === "affiliation" ? 26 : 58);
  const linkStrength = (l: FLink) => (l.e.type === "affiliation" ? 0.7 : l.e.type === "grant" ? 0.15 : 0.12);
  const sim = d3.forceSimulation<FNode>(nodes)
    .force("charge", d3.forceManyBody<FNode>().strength(-150).distanceMax(420))
    .force("x", d3.forceX<FNode>((d) => (kindOf(d) ? centroid.get(kindOf(d)!)!.x : W / 2))
      .strength((d) => (kindOf(d) ? 0.25 : 0.03)))
    .force("y", d3.forceY<FNode>((d) => (kindOf(d) ? centroid.get(kindOf(d)!)!.y : H / 2))
      .strength((d) => (kindOf(d) ? 0.25 : 0.03)))
    .force("link", d3.forceLink<FNode, FLink>(links).distance(linkDist).strength(linkStrength))
    .force("collide", d3.forceCollide<FNode>().radius((d) => r(d) + 4).strength(0.9))
    .on("tick", tick);

  /* ---------- edges: money flows ---------- */
  const edgeStroke = (l: FLink) =>
    l.e.type === "grant" ? "#9a958c" : l.e.type === "investment" ? "#bcc3b0" : "#c9c2b4";
  const edgeWidth = (l: FLink) => edgeWidthFor(l.e, wScale);
  const edgeDash = (l: FLink) => (l.e.type !== "affiliation" && !l.e.verified ? "2 3" : null);
  const edgeDirected = (l: FLink) => l.e.type === "grant" || l.e.type === "investment";

  const linkSel = linkG.selectAll<SVGLineElement, FLink>("line.edge").data(links).join("line")
    .attr("class", "edge").attr("stroke", edgeStroke).attr("stroke-width", edgeWidth)
    .attr("stroke-dasharray", edgeDash).attr("stroke-opacity", 0.5)
    .attr("marker-end", (l) => (edgeDirected(l) ? "url(#fund-arrow)" : null));
  const hitSel = linkG.selectAll<SVGLineElement, FLink>("line.hit").data(links).join("line")
    .attr("class", "hit").attr("stroke", "transparent").attr("stroke-width", 12).style("cursor", "pointer");

  svg.append("defs").append("marker").attr("id", "fund-arrow")
    .attr("viewBox", "0 -5 10 10").attr("refX", 18).attr("refY", 0)
    .attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
    .append("path").attr("d", "M0,-4L9,0L0,4").attr("fill", "#9a958c");

  /* ---------- nodes ---------- */
  const unknownDollar = (d: FNode) => d.kind !== "person" && nodeDollars(d) == null;
  const nodeSel = nodeG.selectAll<SVGGElement, FNode>("g.fnode").data(nodes).join("g")
    .attr("class", "fnode").style("cursor", "pointer");
  nodeSel.append("circle")
    .attr("r", (d) => r(d))
    .attr("fill", (d) => (d.kind === "person" ? HALO : nodeColor(d)))
    .attr("fill-opacity", (d) => (d.kind === "person" ? 1 : confOpacity(d)))
    .attr("stroke", (d) =>
      d.kind === "person" ? PERSON_COLOR : ringColor(d.id) ?? (unknownDollar(d) ? "#8a8475" : HALO))
    .attr("stroke-width", (d) => (d.kind === "person" ? 1.6 : ringColor(d.id) ? 2.5 : 1.4))
    .attr("stroke-dasharray", (d) => (unknownDollar(d) && !ringColor(d.id) ? "2 2" : null));
  nodeSel.append("text").attr("class", "fund-label").attr("y", (d) => -r(d) - 4)
    .text((d) => d.name);
  const labelSel = nodeSel.select<SVGTextElement>("text.fund-label");
  const labelW = new Map<string, number>();
  labelSel.each(function (d) { labelW.set(d.id, (this as SVGTextElement).getBBox().width); });
  const labelOrder = [...nodes].sort(
    (a, b) => (nodeDollars(b) ?? 0) - (nodeDollars(a) ?? 0) ||
      (a.kind === "person" ? 1 : 0) - (b.kind === "person" ? 1 : 0) ||
      (a.id < b.id ? -1 : 1));
  nodeSel.on("click", (ev: MouseEvent, d) => { ev.stopPropagation(); onNodeClick(d); });

  /* ---------- questions: engine-owned paint channel + force-show ----------
   * The active question recolors/resizes nodes (fill/r); OPACITY stays owned
   * by applyHighlight, with the question's fade set as its baseline tier.
   * qForceShow keeps the seat + callout anchors visible past filters
   * (route precedent). Engine code lives in src/scripts/questions/. */
  let engineRef: QuestionEngine | null = null;
  let qPaint: { fill?(id: string): string | null; r?(id: string): number | null; fade: Set<string> | null } | null = null;
  let qForceShow: Set<string> | null = null;
  let dragEnabled = true;
  let labelsVisible = true;
  let qReserve: (() => { boxes: number[][]; hideIds: Set<string> }) | null = null;
  const tickHooks: (() => void)[] = [];
  const zoomHooks: (() => void)[] = [];
  function applyQuestionPaint() {
    nodeSel.select<SVGCircleElement>("circle")
      .attr("fill", (d) => qPaint?.fill?.(d.id) ?? (d.kind === "person" ? HALO : nodeColor(d)))
      .attr("r", (d) => qPaint?.r?.(d.id) ?? r(d));
    labelSel.attr("y", (d) => -(qPaint?.r?.(d.id) ?? r(d)) - 4);
  }

  // Task 6 routes clicks into the path finder when a slot is armed; select() otherwise.
  function onNodeClick(d: FNode): void {
    if (pathPair.armed) { setPathEnd(d.id); return; } // armed slot captures the click
    if (route) clearPath(); // normal selection exits path mode
    select({ id: d.id });
  }

  if (!coarse) {
    nodeSel.on("mousemove", nodeTip).on("mouseleave", leaveNode);
    hitSel.on("mousemove", edgeTip).on("mouseleave", leaveEdge);
    nodeSel.call(d3.drag<SVGGElement, FNode>()
      .filter((ev) => dragEnabled && !ev.ctrlKey && !ev.button) // questions may park the sim
      .on("start", (_ev, d) => { sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
      .on("end", (_ev, d) => { sim.alphaTarget(0); d.fx = d.fy = null; }));
  }

  function tick() {
    for (const sel of [linkSel, hitSel])
      sel.attr("x1", (l) => l.source.x!).attr("y1", (l) => l.source.y!)
        .attr("x2", (l) => l.target.x!).attr("y2", (l) => l.target.y!);
    nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
    for (const fn of tickHooks) fn(); // question marks/callouts track node motion
  }

  /* ---------- zoom / pan ---------- */
  const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 6])
    .on("zoom", (ev) => {
      root.attr("transform", ev.transform.toString());
      if (inited) scheduleLabels();
      for (const fn of zoomHooks) fn(); // question callouts counter-scale
    });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("dblclick", () => fitToNodes(null, true));

  /** Frame the whole graph (ids=null) or a subset (Task 6: fit-to-route). */
  function fitToNodes(ids: string[] | null, animate: boolean) {
    let x0: number, y0: number, x1: number, y1: number;
    if (ids?.length) {
      // ids may come from the question engine (focusIds) — unknown ids are
      // skipped, not crashed on (baked data can reference churned nodes)
      const pts = ids.flatMap((id) => {
        const d = byId.get(id);
        return d && d.x != null ? [d] : [];
      });
      if (!pts.length) return;
      x0 = Math.min(...pts.map((d) => d.x! - r(d)));
      x1 = Math.max(...pts.map((d) => d.x! + r(d)));
      y0 = Math.min(...pts.map((d) => d.y! - r(d)));
      y1 = Math.max(...pts.map((d) => d.y! + r(d)));
    } else {
      const b = (root.node() as SVGGElement).getBBox();
      if (!b.width || !b.height) return;
      x0 = b.x; y0 = b.y; x1 = b.x + b.width; y1 = b.y + b.height;
    }
    const pad = 40;
    const k = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0), 1.6);
    const tx = (W - (x1 - x0) * k) / 2 - x0 * k, ty = (H - (y1 - y0) * k) / 2 - y0 * k;
    const t = d3.zoomIdentity.translate(tx, ty).scale(k);
    if (animate) svg.transition().duration(450).call(zoom.transform, t);
    else svg.call(zoom.transform, t);
  }

  sim.stop();
  for (let i = 0; i < 220; i++) sim.tick();
  tick();
  fitToNodes(null, false);
  // No fit-on-settle: sim "end" re-fires after every drag-induced reheat and would
  // yank the viewport back out from under the user's zoom (same fix as networks-graph).
  if (!calm) sim.alpha(0.25).restart();

  /* ---------- visibility (Task 5 wires controls into `filters`) ---------- */
  const pathPair: { from: string | null; to: string | null; armed: "from" | "to" | null } =
    { from: null, to: null, armed: null };
  const filters = {
    kinds: new Set<FunderKind>(FUNDER_KINDS.map((k) => k.id)),
    domains: new Set<string>(),
    minUsd: 0,
    query: "",
  };
  let visibleSet = new Set<string>(nodes.map((n) => n.id));
  // active route and question force-shown ids (seat + callout anchors) stay visible past filters
  const shown = (d: FNode) => visibleSet.has(d.id) || inRoute(d.id) || (qForceShow?.has(d.id) ?? false);

  function applyFilter() {
    filters.query = searchEl?.value ?? "";
    visibleSet = computeVisible(fundingNodes, fundingEdges, filters);
    if (isPrivate) { // dev-only: stage chips + warm-only narrow further
      for (const id of [...visibleSet]) {
        if (!activeStages.has(stageOf(id) ?? "cold")) visibleSet.delete(id);
        else if (warmOnly && !warmOf(id)) visibleSet.delete(id);
      }
    }
    if (selected && !shown(byId.get(selected.id)!)) select(null);
    else if (selected) renderDetail();
    nodeSel.style("display", (d) => (shown(d) ? null : "none"));
    const edgeShown = (l: FLink) =>
      (shown(l.source) && shown(l.target)) || routeLinks.has(l) ? null : "none";
    linkSel.style("display", edgeShown);
    hitSel.style("display", edgeShown);
    applyHighlight();
    if (view === "directory") renderDir();
  }
  const activeStages = new Set<FundingStage>(FUNDING_STAGES.map((s) => s.id));

  /* ---------- directory view + view toggle ---------- */
  const dirEl = document.getElementById("fund-directory");
  const viewMapBtn = document.getElementById("fund-view-map");
  const viewDirBtn = document.getElementById("fund-view-dir");
  const downloadBtn = document.getElementById("fund-download") as HTMLButtonElement | null;

  function renderDir() {
    if (!dirEl) return;
    renderFundingDirectory(dirEl, nodes.filter(shown), {
      domains: DOMAINS,
      onSelect: (id) => { const d = byId.get(id); if (d) onNodeClick(d); },
      isOpen: (f) => openSet.has(f.id),
      usdOf: nodeDollars,
      fmt: formatUsd,
      warmOf: isPrivate ? warmOf : undefined, // undefined in prod → no warm strings shipped
      isCommitment: (f) => f.annualFieldGivingBasis?.kind === "commitment",
    });
  }
  function setView(v: "map" | "directory") {
    view = v;
    const dir = v === "directory";
    dirEl?.toggleAttribute("hidden", !dir);
    graphEl.classList.toggle("fund-hide", dir);
    viewMapBtn?.classList.toggle("on", !dir);
    viewDirBtn?.classList.toggle("on", dir);
    viewMapBtn?.setAttribute("aria-pressed", String(!dir));
    viewDirBtn?.setAttribute("aria-pressed", String(dir));
    downloadBtn?.toggleAttribute("hidden", dir); // download exports the map view only
    if (dir) renderDir();
    else fitToNodes(null, false); // re-frame after display:none
  }
  viewMapBtn?.addEventListener("click", () => setView("map"));
  viewDirBtn?.addEventListener("click", () => setView("directory"));

  /* ---------- chips: funder kinds (default all on), domains (default off = no filter) ---------- */
  function buildChips<T extends string>(
    container: HTMLElement, items: { id: T; label: string; color: string }[], active: Set<T>,
    onChange?: () => void,
  ): void {
    for (const it of items) {
      const chip = document.createElement("button");
      chip.className = active.has(it.id) ? "fund-chip on" : "fund-chip";
      chip.dataset.id = it.id;
      chip.innerHTML = `<span class="sw" style="background:${it.color}"></span>${esc(it.label)}`;
      chip.addEventListener("click", () => {
        active.has(it.id) ? active.delete(it.id) : active.add(it.id);
        chip.classList.toggle("on", active.has(it.id));
        applyFilter();
        onChange?.();
      });
      container.appendChild(chip);
    }
  }
  const kindChipsEl = document.getElementById("fund-kinds")!;
  const domainChipsEl = document.getElementById("fund-domains")!;
  const presentKinds = FUNDER_KINDS.filter((k) => nodes.some((n) => n.kind === "funder" && n.funderKind === k.id));
  const allBtn = document.createElement("button");
  allBtn.className = "fund-chip fund-chip-toggle";
  const refreshAllBtn = () => { allBtn.textContent = filters.kinds.size === 0 ? "show all" : "hide all"; };
  allBtn.addEventListener("click", () => {
    if (filters.kinds.size === 0) presentKinds.forEach((k) => filters.kinds.add(k.id));
    else filters.kinds.clear();
    kindChipsEl.querySelectorAll<HTMLElement>(".fund-chip[data-id]")
      .forEach((c) => c.classList.toggle("on", filters.kinds.has(c.dataset.id as FunderKind)));
    refreshAllBtn();
    applyFilter();
  });
  kindChipsEl.appendChild(allBtn);
  refreshAllBtn();
  buildChips(kindChipsEl, presentKinds, filters.kinds, refreshAllBtn);
  buildChips(
    domainChipsEl,
    DOMAINS.map((d) => ({ id: d.id, label: d.label, color: "#8a8475" })),
    filters.domains,
  );

  /* stage chips + warm-only (dev/private layer) */
  const stageChipsEl = document.getElementById("fund-stages");
  let warmOnly = false;
  if (isPrivate && stageChipsEl) {
    const warmChip = document.createElement("button");
    warmChip.className = "fund-chip fund-chip-warm";
    warmChip.textContent = "warm paths only";
    warmChip.addEventListener("click", () => {
      warmOnly = !warmOnly;
      warmChip.classList.toggle("on", warmOnly);
      applyFilter();
    });
    stageChipsEl.appendChild(warmChip);
    buildChips(stageChipsEl, FUNDING_STAGES, activeStages);
  }

  /* ---------- $ floor slider ---------- */
  const usdRange = document.getElementById("fund-usd-range") as HTMLInputElement | null;
  const usdN = document.getElementById("fund-usd-n");
  const updateUsdReadout = () => {
    if (usdN) usdN.textContent = filters.minUsd <= 0 ? "any amount" : formatUsd(filters.minUsd);
    usdRange?.setAttribute(
      "aria-valuetext",
      filters.minUsd <= 0 ? "any amount" : `at least ${formatUsd(filters.minUsd)} per year`,
    );
  };
  usdRange?.addEventListener("input", () => {
    filters.minUsd = sliderToUsd(Number(usdRange.value), maxAnnual);
    updateUsdReadout();
    applyFilter();
  });
  updateUsdReadout();
  searchEl?.addEventListener("input", applyFilter);

  /* ---------- open-now lens: highlight, never filter ---------- */
  const lensOpenBtn = document.getElementById("fund-lens-open");
  function setLensOpen(on: boolean) {
    lensOpen = on;
    lensOpenBtn?.classList.toggle("on", on);
    lensOpenBtn?.setAttribute("aria-pressed", String(on));
    dirEl?.classList.toggle("dir-lens-open", on);
    applyHighlight();
    if (view === "directory") renderDir();
  }
  lensOpenBtn?.addEventListener("click", () => setLensOpen(!lensOpen));

  /* ---------- legend ---------- */
  const legendEl = document.getElementById("fund-legend")!;
  legendEl.innerHTML =
    `<span class="fund-leg-item">color · funder kind</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-dot" style="width:6px;height:6px"></span>` +
    `<span class="fund-leg-dot" style="width:14px;height:14px"></span> size · $ into the field</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-dotted"></span> no public $</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-ln"></span> verified</span>` +
    `<span class="fund-leg-item" title="reported during AI-assisted research — not yet confirmed by a public source"><span class="fund-leg-ln dash"></span> inferred</span>` +
    `<span class="fund-leg-item"><span class="fund-leg-ring" style="border-color:${OPEN_RING}"></span> open now</span>` +
    `<span class="fund-leg-item fund-leg-dim">zoom in for more names</span>` +
    (isPrivate ? `<span class="fund-leg-item fund-leg-priv">● ring · our stage (dev)</span>` : "") +
    `<span class="fund-leg-item fund-leg-src">mapped from public sources — a missing tie isn't evidence of absence</span>`;

  /* ---------- PNG download ----------
   * WYSIWYG: current pan/zoom, filters, and decluttered labels carry over
   * (they're inline display:none / attributes). The catch: .fund-label gets
   * its fill/halo/anchor from external CSS a rasterized SVG can't see — so
   * we clone the svg, inject those rules as an internal <style>, lay a cream
   * background behind it, then draw onto a 2× canvas for a crisp image.
   * No external refs → canvas isn't tainted → toBlob() works. */
  function downloadPng() {
    const SVGNS = "http://www.w3.org/2000/svg";
    const clone = svg.node()!.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", SVGNS);
    clone.setAttribute("width", String(W));
    clone.setAttribute("height", String(H));

    // labels live on external CSS classes the rasterizer can't reach — inline
    // them. Question marks/callouts (.q-marks/.q-callouts) carry their paint
    // as presentation ATTRIBUTES, but the generic text{} rule below would
    // trump the callouts' font-family attribute — pin it back explicitly.
    const style = document.createElementNS(SVGNS, "style");
    style.textContent =
      `text{font-family:Palatino,"Palatino Linotype","Book Antiqua",Georgia,serif}` +
      `.fund-label{fill:#11100f;text-anchor:middle;paint-order:stroke;` +
      `stroke:${HALO};stroke-width:3px;stroke-linejoin:round}` +
      `.q-callouts text{font-family:Georgia,serif}` +
      `.q-marks{pointer-events:none}` +
      `.q-png-caption{font:700 15px Georgia,serif;fill:#11100f;paint-order:stroke;` +
      `stroke:${HALO};stroke-width:4px;stroke-linejoin:round}`;
    // cream page background, behind everything
    const bg = document.createElementNS(SVGNS, "rect");
    bg.setAttribute("x", "0"); bg.setAttribute("y", "0");
    bg.setAttribute("width", String(W)); bg.setAttribute("height", String(H));
    bg.setAttribute("fill", HALO);
    clone.insertBefore(bg, clone.firstChild);
    clone.insertBefore(style, clone.firstChild);
    // active question: stamp its answer sentence onto the export (screen
    // space, outside the zoomed root) so the PNG carries its own caption
    const sentence = engineRef?.active()
      ? document.getElementById("fund-q-answer")?.querySelector(".q-sentence")?.textContent
      : null;
    if (sentence) {
      const cap = document.createElementNS(SVGNS, "text");
      cap.setAttribute("x", "14");
      cap.setAttribute("y", "24");
      cap.setAttribute("class", "q-png-caption");
      cap.textContent = sentence;
      clone.appendChild(cap);
    }

    const xml = new XMLSerializer().serializeToString(clone);
    const svgUrl = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    img.onload = () => {
      const scale = 2; // crisp on retina / when scaled up in a deck
      const canvas = document.createElement("canvas");
      canvas.width = W * scale; canvas.height = H * scale;
      const ctx = canvas.getContext("2d")!;
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, W, H);
      URL.revokeObjectURL(svgUrl);
      canvas.toBlob((blob) => {
        if (!blob) return;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "agents-of-chaos-funding.png";
        a.click();
        URL.revokeObjectURL(a.href);
      }, "image/png");
    };
    img.onerror = () => URL.revokeObjectURL(svgUrl);
    img.src = svgUrl;
  }
  downloadBtn?.addEventListener("click", downloadPng);

  /* ---------- path finder: how do you get from any node to any other? ----------
   * Two type-ahead slots (ported from alex-loftus.com's coauthorship pair
   * finder). BFS runs over the FULL graph — filters never hide a route; route
   * members are force-shown by shown() and restored when the path clears. */
  const pathCtl = document.getElementById("fund-pathctl");
  const pathDetail = document.getElementById("fund-path-detail")!;
  const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  const linkByPair = new Map<string, FLink>();
  for (const l of links) {
    const k = pairKey(l.source.id, l.target.id);
    if (!linkByPair.has(k)) linkByPair.set(k, l);
  }

  // route-mode mutual exclusion, half 1: touching the path finder exits any
  // active question (the engine restores the question's entry camera itself);
  // half 2 lives in the host adapter's setQuestionPaint (question entry
  // dismisses the path finder without its camera refit).
  function exitActiveQuestion() {
    if (engineRef?.active()) engineRef.handleEscape();
  }

  function setPathEnd(id: string) {
    exitActiveQuestion();
    if (pathPair.armed === "from" || (!pathPair.armed && !pathPair.from)) pathPair.from = id;
    else pathPair.to = id;
    pathPair.armed = pathPair.from && !pathPair.to ? "to" : null;
    if (pathPair.from && pathPair.to) computePairPath();
    else { route = null; routeLinks = new Set(); renderPairDetail(); applyFilter(); }
    renderPathPanel();
  }
  function computePairPath() {
    route = shortestPath(adj, pathPair.from!, pathPair.to!);
    routeLinks = new Set();
    if (route)
      for (let i = 0; i < route.ids.length - 1; i++) {
        const l = linkByPair.get(pairKey(route.ids[i], route.ids[i + 1]));
        if (l) routeLinks.add(l);
      }
    renderPairDetail();
    applyFilter(); // re-applies display (route force-shown) + the route highlight
    if (route) fitToNodes(route.ids, true);
  }
  function clearPath(refit = true) {
    pathPair.from = pathPair.to = null;
    pathPair.armed = null;
    route = null;
    routeLinks = new Set();
    renderPairDetail();
    renderPathPanel();
    applyFilter();
    // question entry clears the path WITHOUT this refit — the engine owns the
    // camera on entry, and two competing zooms would fight
    if (refit) fitToNodes(null, true);
  }
  function renderPairDetail() {
    if (!pathPair.from || !pathPair.to) { pathDetail.innerHTML = ""; return; }
    if (!route) {
      pathDetail.innerHTML = `<div class="pd-title">no path</div>
        <div class="pd-none">No public funding path connects these two.</div>`;
      return;
    }
    const chain = route.ids.map((id, i) => {
      const name = esc(byId.get(id)!.name);
      const cls = i === 0 || i === route!.ids.length - 1 ? "pd-end" : "";
      return `<span class="${cls}">${name}</span>`;
    }).join(`<span class="pd-arrow">→</span>`);
    pathDetail.innerHTML = `<div class="pd-title">${route.len} hop${route.len === 1 ? "" : "s"}</div>
      <div class="pd-chain">${chain}</div>`;
  }
  function renderPathPanel() {
    if (!pathCtl) return;
    pathCtl.innerHTML = `<span class="pp-label">path</span>`;
    (["from", "to"] as const).forEach((end, i) => {
      if (i === 1) {
        const arrow = document.createElement("span");
        arrow.className = "pp-arrow";
        arrow.textContent = "→";
        pathCtl.appendChild(arrow);
      }
      const slot = document.createElement("div");
      slot.className = "pp-slot" + (pathPair.armed === end ? " armed" : "");
      const val = pathPair[end];
      if (val) {
        const d = byId.get(val)!;
        slot.innerHTML = `<span class="pp-pick"><span class="pp-dot" style="background:${nodeColor(d)}"></span>${esc(d.name)}</span>`;
        slot.addEventListener("click", () => { // re-open: clear this end, arm it
          exitActiveQuestion(); // arming a slot and an active question are exclusive
          pathPair[end] = null;
          pathPair.armed = end;
          route = null; routeLinks = new Set();
          renderPairDetail(); renderPathPanel(); applyFilter();
        });
      } else {
        const input = document.createElement("input");
        input.className = "pp-input";
        input.placeholder = end;
        input.autocomplete = "off";
        input.spellcheck = false;
        const menu = document.createElement("div");
        menu.className = "pp-menu";
        menu.hidden = true;
        const other = end === "from" ? pathPair.to : pathPair.from;
        const refreshMenu = () => {
          const q = input.value.trim().toLowerCase();
          const hits = nodes
            .filter((n) => n.id !== other && (!q || n.name.toLowerCase().includes(q) ||
              (n.aliases ?? []).some((a) => a.toLowerCase().includes(q))))
            .slice(0, 8);
          menu.innerHTML = hits.map((n) =>
            `<button type="button" data-id="${esc(n.id)}"><span class="pp-dot" style="background:${nodeColor(n)}"></span>${esc(n.name)}</button>`,
          ).join("");
          menu.hidden = !hits.length;
          // mousedown (not click) so the pick beats the input's blur
          menu.querySelectorAll<HTMLElement>("button").forEach((b) =>
            b.addEventListener("mousedown", (ev) => { ev.preventDefault(); setPathEnd(b.dataset.id!); }));
        };
        input.addEventListener("focus", () => {
          exitActiveQuestion(); // arming a slot and an active question are exclusive
          pathPair.armed = end; slot.classList.add("armed"); refreshMenu();
        });
        input.addEventListener("input", refreshMenu);
        input.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            const first = menu.querySelector<HTMLElement>("button");
            if (first?.dataset.id) setPathEnd(first.dataset.id);
          }
        });
        input.addEventListener("blur", () => setTimeout(() => { menu.hidden = true; }, 120));
        slot.appendChild(input);
        slot.appendChild(menu);
      }
      pathCtl.appendChild(slot);
    });
    if (pathPair.from || pathPair.to) {
      const clear = document.createElement("button");
      clear.className = "pp-clear";
      clear.type = "button";
      clear.title = "clear path";
      clear.textContent = "✕";
      clear.addEventListener("click", () => clearPath());
      pathCtl.appendChild(clear);
    }
  }
  renderPathPanel();

  /* ---------- highlight (route- and lens-aware from day one) ---------- */
  let selected: Sel = null, hover: Sel = null;
  // analyses rail: hovering a finding spotlights ITS set of funding nodes.
  // Live node hover beats a lingering spotlight; the route view beats both.
  let analysisHighlight: Set<string> | null = null;
  function neigh(sel: Sel) {
    if (!sel) return null;
    const set = new Set<string>([sel.id]);
    for (const id of adj.get(sel.id) ?? []) set.add(id);
    return set;
  }
  function applyHighlight() {
    if (route) { // active path: route members pop, everything else recedes
      nodeSel.attr("opacity", (d) => (inRoute(d.id) ? 1 : shown(d) ? 0.06 : 0));
      nodeSel.select("circle")
        .attr("stroke", (d) => (inRoute(d.id) ? "#a00" : strokeFor(d)))
        .attr("stroke-width", (d) => (inRoute(d.id) ? 2.5 : strokeWidthFor(d)));
      linkSel
        .attr("stroke", (l) => (routeLinks.has(l) ? "#a00" : edgeStroke(l)))
        .attr("stroke-opacity", (l) => (routeLinks.has(l) ? 0.95 : shownEdge(l) ? 0.04 : 0))
        .attr("stroke-width", (l) => (routeLinks.has(l) ? edgeWidth(l) + 1 : edgeWidth(l)));
      refreshLabels();
      return;
    }
    nodeSel.select("circle")
      .attr("stroke", strokeFor).attr("stroke-width", strokeWidthFor)
      .attr("stroke-dasharray", (d) => (unknownDollar(d) && !ringColor(d.id) && !(lensOpen && openSet.has(d.id)) ? "2 2" : null));
    linkSel.attr("stroke", edgeStroke).attr("stroke-width", edgeWidth);
    // live node hover beats a lingering preview spotlight; while a QUESTION is
    // active the question fade is the ruling context — the selected seat's
    // 1-hop neighborhood must NOT dim the lit set (re-aim washed out
    // otherwise), so the selection tier is skipped while qPaint is set.
    // Opacity precedence (top wins): route > edgeHover > nodeHover > preview >
    // selection-neighborhood > question fade > base (open-now dim).
    const nb = hover ? neigh(hover) : (analysisHighlight ?? (qPaint ? null : neigh(selected)));
    const qf = qPaint?.fade ?? null; // question fade = the baseline tier under any interaction set
    const dimFor = (d: FNode) => // open-now lens dims what isn't actionable
      lensOpen && !openSet.has(d.id) ? (d.kind === "funder" ? 0.15 : 0.25) : 1;
    nodeSel.attr("opacity", (d) =>
      !shown(d) ? 0 : nb ? (nb.has(d.id) ? 1 : 0.12) : qf ? (qf.has(d.id) ? 1 : 0.16) : dimFor(d));
    linkSel.attr("stroke-opacity", (l) =>
      !shownEdge(l) ? 0
        : nb ? (nb.has(l.source.id) && nb.has(l.target.id) ? 0.9 : 0.04)
        : qf ? (qf.has(l.source.id) && qf.has(l.target.id) ? 0.55 : 0.05)
        : lensOpen ? 0.25 : 0.5);
    refreshLabels();
  }
  const shownEdge = (l: FLink) => shown(l.source) && shown(l.target);
  const strokeFor = (d: FNode) =>
    d.kind === "person" ? PERSON_COLOR
      : lensOpen && openSet.has(d.id) ? OPEN_RING
        : ringColor(d.id) ?? (unknownDollar(d) ? "#8a8475" : HALO);
  const strokeWidthFor = (d: FNode) =>
    d.kind === "person" ? 1.6 : (lensOpen && openSet.has(d.id)) || ringColor(d.id) ? 2.5 : 1.4;

  let rafPending = false;
  function scheduleLabels() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => { rafPending = false; refreshLabels(); });
  }
  function refreshLabels() {
    if (!labelsVisible) { labelSel.style("display", "none"); return; } // question tween in flight
    const t = d3.zoomTransform(svg.node()!);
    labelSel.style("font-size", BASE_LABEL / t.k + "px");
    // selection tier skipped while a question paints (same rule as applyHighlight)
    const nb = route ? new Set(route.ids) : hover ? neigh(hover) : (analysisHighlight ?? (qPaint ? null : neigh(selected)));
    const order = nb ? labelOrder.filter((d) => nb.has(d.id)) : labelOrder;
    // a hovered node's ~5 neighbours always keep their labels; a preview set
    // (up to 25 nodes) gets label PRIORITY but not overlap-forcing — clutter
    const force = !!nb && nb !== analysisHighlight;
    // active-question callouts reserve their screen boxes first (labels flow
    // around them) and carry their anchors' names (those labels hide)
    const reserved = qReserve?.() ?? null;
    const placed: number[][] = reserved ? reserved.boxes.map((b) => b.slice()) : [];
    const qHide = reserved?.hideIds ?? null;
    const show = new Set<string>();
    const PAD = 4;
    for (const d of order) {
      if (!shown(d)) continue;
      if (qHide?.has(d.id)) continue; // the callout already names this node
      const w = labelW.get(d.id) ?? 40;
      const sx = d.x! * t.k + t.x;
      const baseY = (d.y! - r(d) - 4) * t.k + t.y;
      const box = [sx - w / 2 - PAD, baseY - BASE_LABEL - PAD, sx + w / 2 + PAD, baseY + PAD];
      const overlaps = placed.some((p) => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1]);
      if (overlaps && !(force && nb.has(d.id))) continue;
      placed.push(box); show.add(d.id);
    }
    labelSel.style("display", (d) => (show.has(d.id) ? null : "none"));
  }

  /* ---------- edge hover ---------- */
  let hoverEdge: FLink | null = null;
  function emphasizeEdge(l: FLink) {
    const a = l.source.id, b = l.target.id;
    nodeSel.attr("opacity", (d) => (!shown(d) ? 0 : d.id === a || d.id === b ? 1 : 0.12));
    linkSel.attr("stroke-opacity", (x) => (x === l ? 0.95 : !shownEdge(x) ? 0 : 0.05));
    labelSel.style("display", (d) => (!shown(d) ? "none" : d.id === a || d.id === b ? null : "none"));
  }
  function describeEdge(e: FundingEdge): string {
    if (e.type === "affiliation") return esc(e.role);
    const kind = e.type === "grant" ? "grant" : `investment${e.round ? ` · ${esc(e.round)}` : ""}`;
    const amt = e.amountUSD != null ? ` · ${formatUsd(e.amountUSD)}` : " · undisclosed";
    const yr = e.year ? ` · ${e.year}` : "";
    return `${kind}${amt}${yr}${e.verified ? "" : " · inferred"}`;
  }
  function edgeTip(ev: MouseEvent, l: FLink) {
    if (selected && l.source.id !== selected.id && l.target.id !== selected.id) return;
    if (hoverEdge !== l) { hoverEdge = l; emphasizeEdge(l); }
    const arrow = edgeDirected(l) ? "→" : "—";
    showTip(ev, `<div class="t-name">${esc(l.source.name)} ${arrow} ${esc(l.target.name)}</div>
      <div class="t-sub">${describeEdge(l.e)}</div>`);
  }
  function leaveEdge() { hoverEdge = null; tooltip.style.opacity = "0"; applyHighlight(); }

  function select(sel: Sel) {
    selected = sel; hover = null;
    renderDetail(); applyHighlight();
    if (sel) location.hash = "f=" + encodeURIComponent(sel.id);
    else if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    engineRef?.onSelectionChange(sel?.id ?? null); // re-aim the active question at the new seat
  }

  /* ---------- dossier ---------- */
  function applyBlock(f: FunderNode): string {
    const a = f.apply;
    const mode = a.mode === "rolling" ? "rolling" : a.mode === "rounds" ? "rounds" : a.mode;
    const open = openSet.has(f.id);
    const badge = open
      ? `<span class="d-badge" style="background:${OPEN_RING}">open now</span>`
      : `<span class="d-badge" style="background:#b3ab9c">${esc(mode)}</span>`;
    return `<div class="d-line"><span class="d-key">apply</span> ${badge}
      ${a.deadline ? ` closes ${esc(a.deadline)}` : ""}${a.notes ? ` — ${esc(a.notes)}` : ""}
      ${a.url ? ` <a href="${esc(a.url)}" target="_blank" rel="noopener">form →</a>` : ""}</div>`;
  }
  function moneyBlock(f: FunderNode): string {
    const isCommit = f.annualFieldGivingBasis?.kind === "commitment";
    const annual = f.annualFieldGivingUSD != null
      ? `${formatUsd(f.annualFieldGivingUSD)}${isCommit ? " committed" : "/yr"}${f.inKind ? " (incl. credits)" : ""}`
      : f.inKind ? "credits / in-kind" : "no public figure";
    const basis = f.annualFieldGivingBasis
      ? ` <a href="${esc(f.annualFieldGivingBasis.sourceUrl)}" target="_blank" rel="noopener" title="${esc(f.annualFieldGivingBasis.method)}">[${f.annualFieldGivingBasis.year}]</a>`
      : "";
    const check = f.checkSizeUSD
      ? `<div class="d-line"><span class="d-key">checks</span> ${formatUsd(f.checkSizeUSD.min)}–${formatUsd(f.checkSizeUSD.max)}</div>`
      : "";
    const grants = topGrants(fundingEdges, f.id, 5).map((g: FundingEdge) => {
      const t = byId.get(g.target)!;
      return `<div class="d-row"><span class="swatch" style="background:${GRANTEE_COLOR}"></span>
        <div><button class="d-org d-jump" data-id="${esc(g.target)}" type="button">→ ${esc(t.name)}</button>
        <div class="d-meta">${describeEdge(g)}${g.sourceUrl ? ` · <a href="${esc(g.sourceUrl)}" target="_blank" rel="noopener">src</a>` : ""}</div></div></div>`;
    }).join("");
    return `<div class="d-line"><span class="d-key">gives</span> ${annual}${basis}</div>${check}
      ${grants ? `<div class="d-rels">${grants}</div>` : ""}`;
  }
  function peopleBlock(f: FNode): string {
    const rows = links.filter((l) => l.e.type === "affiliation" && l.target.id === f.id).map((l) => {
      const p = l.source;
      const role = l.e.type === "affiliation" ? l.e.role : "";
      const url = p.kind === "person" ? p.profileUrl : undefined;
      return `<div class="d-row"><span class="swatch" style="background:${PERSON_COLOR}"></span>
        <div><button class="d-org d-jump" data-id="${esc(p.id)}" type="button">${esc(p.name)}</button>
        <div class="d-meta">${esc(role)}${url ? ` · <a href="${esc(url)}" target="_blank" rel="noopener">profile</a>` : ""}</div></div></div>`;
    }).join("");
    return rows ? `<div class="d-rels">${rows}</div>` : "";
  }
  function renderDetail() {
    if (!selected) { detail.innerHTML = ""; return; }
    const n = byId.get(selected.id)!;
    const kindLine =
      n.kind === "funder" ? `<span style="color:${funderColor(n.funderKind)}">${esc(funderLabel(n.funderKind))}</span>`
        : n.kind === "grantee" ? `grantee${n.fieldDollarsUSD > 0 ? ` · ${formatUsd(n.fieldDollarsUSD)} raised in-field` : ""}`
          : esc((n as Extract<FNode, { kind: "person" }>).title);
    const rels = n.kind === "funder" ? "" : links
      .filter((l) => l.source.id === n.id || l.target.id === n.id)
      .map((l) => {
        const other = l.source.id === n.id ? l.target : l.source;
        const arrow = edgeDirected(l) ? (l.source.id === n.id ? "→" : "←") : "—";
        return `<div class="d-row"><span class="swatch" style="background:${nodeColor(other)}"></span>
          <div><button class="d-org d-jump" data-id="${esc(other.id)}" type="button">${arrow} ${esc(other.name)}</button>
          <div class="d-meta">${describeEdge(l.e)}</div></div></div>`;
      }).join("");
    const ov = overlay.get(n.id);
    let priv = "";
    if (isPrivate && ov) {
      priv = `<div class="d-priv">
        ${ov.stage ? `<div class="d-row"><span class="d-key">stage</span>
          <span class="d-badge" style="background:${fundingStageColor(ov.stage)}">${esc(fundingStageLabel(ov.stage))}</span></div>` : ""}
        ${ov.warm_path ? `<div class="d-warm"><span class="d-key">warm path</span> ${esc(ov.warm_path)}</div>` : ""}
        ${ov.notes ? `<div class="d-note">${esc(ov.notes)}</div>` : ""}</div>`;
    }
    const tags = (n.domainTags ?? []).map((t) => `<span class="d-badge" style="background:#8a8475">${esc(domainLabel(t))}</span>`).join(" ");
    const crossLink = n.networksId
      ? `<div class="d-src"><a href="/networks?focus=${encodeURIComponent(n.networksId)}">→ view on the networks map</a></div>`
      : "";
    // question-aware line while a question is active; otherwise an invitation —
    // the seat is already this node (derived from selection), so the button
    // only needs to lead the eye to the strip
    const qLine = engineRef?.dossierContext(n.id);
    const askHere =
      engineRef && !engineRef.active()
        ? `<button type="button" class="d-askhere">ask the map about ${esc(n.name)} ↑</button>`
        : "";
    detail.innerHTML = `<span class="d-clear" title="clear">✕</span>
      <div class="d-title">${esc(n.name)}</div>
      <div class="d-sub">${kindLine}</div>
      ${qLine ? `<div class="d-qline">${esc(qLine)}</div>` : ""}
      <div class="d-blurb">${esc(n.blurb)}</div>
      ${n.kind === "funder" && n.thesis ? `<div class="d-line"><span class="d-key">thesis</span> ${esc(n.thesis)}</div>` : ""}
      ${n.kind === "funder" ? moneyBlock(n) : ""}
      ${n.kind === "funder" ? applyBlock(n) : ""}
      ${n.kind === "funder" ? peopleBlock(n) : ""}
      ${priv}
      ${rels ? `<div class="d-rels">${rels}</div>` : ""}
      ${tags ? `<div class="d-line">${tags}</div>` : ""}
      ${n.url ? `<div class="d-src"><a href="${esc(n.url)}" target="_blank" rel="noopener">→ ${esc(n.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}</a></div>` : ""}
      ${crossLink}
      ${askHere}`;
    detail.querySelector(".d-clear")!.addEventListener("click", () => select(null));
    detail.querySelectorAll<HTMLElement>(".d-jump").forEach((b) =>
      b.addEventListener("click", () => select({ id: b.dataset.id! })));
    detail.querySelector(".d-askhere")?.addEventListener("click", () => {
      const strip = document.getElementById("fund-questions");
      strip?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "nearest" });
      strip?.classList.add("net-q-pulse");
      setTimeout(() => strip?.classList.remove("net-q-pulse"), 1200);
    });
  }

  /* ---------- tooltip ---------- */
  function showTip(ev: MouseEvent, html: string) {
    tooltip.innerHTML = html; tooltip.style.opacity = "1";
    const pad = 14, w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    tooltip.style.left = Math.min(ev.clientX + pad, innerWidth - w - 8) + "px";
    tooltip.style.top = Math.min(ev.clientY + pad, innerHeight - h - 8) + "px";
  }
  function leaveNode() { tooltip.style.opacity = "0"; if (hover) { hover = null; applyHighlight(); } }
  function nodeTip(ev: MouseEvent, d: FNode) {
    if (!hover || hover.id !== d.id) { hover = { id: d.id }; applyHighlight(); }
    const st = isPrivate ? stageOf(d.id) : undefined;
    const stHtml = st ? ` <span class="t-badge" style="background:${fundingStageColor(st)}">${esc(fundingStageLabel(st))}</span>` : "";
    const warm = isPrivate ? warmOf(d.id) : undefined;
    const sub =
      d.kind === "funder"
        ? `<span style="color:${funderColor(d.funderKind)}">${esc(funderLabel(d.funderKind))}</span> · ${
            d.annualFieldGivingUSD != null
              ? `${formatUsd(d.annualFieldGivingUSD)}${d.annualFieldGivingBasis?.kind === "commitment" ? " committed" : "/yr"}`
              : d.inKind ? "credits" : "$ unknown"
          }${openSet.has(d.id) ? ` · <span style="color:${OPEN_RING}">open now</span>` : ""}`
        : d.kind === "grantee"
          ? `grantee${d.fieldDollarsUSD > 0 ? ` · ${formatUsd(d.fieldDollarsUSD)} in-field` : ""}`
          : esc((d as Extract<FNode, { kind: "person" }>).title);
    showTip(ev, `<div class="t-name">${esc(d.name)}${stHtml}</div>
      <div class="t-sub">${sub}</div>
      <div class="t-blurb">${esc(d.blurb)}</div>${warm ? `<div class="t-warm">↪ ${esc(warm)}</div>` : ""}`);
  }

  // ONE Escape ladder, one stratum per press: path finder → question →
  // preview spotlight → selection.
  window.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (pathPair.armed || pathPair.from || pathPair.to) { clearPath(); return; } // path first
    if (engineRef?.handleEscape()) return; // then the active question (exact camera restore)
    if (analysisHighlight) { setPreviewSet(null); return; } // then a lingering preview spotlight
    select(null);
  });

  /* ---------- questions: preview spotlight (strip-thumb hover) ----------
   * The old analyses-rail hover tier, now fed by the question strip. */
  function setPreviewSet(ids: Set<string> | null) {
    const live = ids ? new Set([...ids].filter((id) => byId.has(id))) : null;
    analysisHighlight = live?.size ? live : null;
    applyHighlight();
    // same spotlight in the directory view (rows re-render on filter changes,
    // and hover re-applies, so transient staleness self-corrects)
    dirEl?.querySelectorAll<HTMLElement>(".dir-row[data-id]").forEach((row) =>
      row.classList.toggle("dir-hi", analysisHighlight?.has(row.dataset.id!) ?? false));
  }

  /* ---------- deep links: #f= and ?focus= (Task 5 adds ?view, Task 7 ?lens/?min) ---------- */
  function selectFromHash() {
    const m = location.hash.match(/^#f=(.+)$/);
    if (m) { const id = decodeURIComponent(m[1]); if (byId.has(id)) select({ id }); }
  }
  const params = new URLSearchParams(location.search);
  const focus = params.get("focus");
  if (focus && byId.has(focus)) select({ id: focus });
  else selectFromHash();
  window.addEventListener("hashchange", selectFromHash);
  if (params.get("view") === "directory") setView("directory");
  if (params.get("lens") === "open") setLensOpen(true);
  // legacy ?an= deep links are redirected by the question engine below
  // (mapped question or the methods appendix)
  const minParam = params.get("min");
  if (minParam && /^\d+$/.test(minParam) && usdRange) {
    filters.minUsd = Math.min(Number(minParam), maxAnnual);
    // invert sliderToUsd so the thumb matches: v = (100/k)·ln(1 + min·(eᵏ−1)/max)
    const K = 6;
    usdRange.value = String(Math.round((100 / K) * Math.log1p((filters.minUsd * Math.expm1(K)) / maxAnnual)));
    updateUsdReadout();
    applyFilter();
  }

  /* ---------- questions: the strip above the map ----------
   * Thumbnail hover previews a spotlight (the old rail-hover tier, now fed by
   * the strip); clicking enters a question. All question behavior lives in
   * src/scripts/questions/ — this block only builds the host adapter. Legacy
   * ?an= deep links are redirected by the engine (mapped question or appendix). */
  void (async () => {
    const stripEl = document.getElementById("fund-questions");
    const answerEl = document.getElementById("fund-q-answer");
    const drawerEl = document.getElementById("fund-q-drawer");
    if (!stripEl || !answerEl || !drawerEl) return;
    // the payload rides import.meta.glob so a not-yet-baked
    // questions-funding.json degrades (no questions) instead of failing the
    // build — the nightly funding PR must never trip over a missing bake
    const payloadModules = import.meta.glob<{ default?: unknown }>(
      "../data/questions/questions-funding.json",
    );
    const loadPayload = payloadModules["../data/questions/questions-funding.json"];
    if (!loadPayload) return; // bake not landed — the SSR strip is empty too
    const [{ initQuestions }, { makeFundingDefs, FUNDING_DEFAULT_SEAT }] = await Promise.all([
      import("./questions/engine"),
      import("./questions/defs/funding"),
    ]);
    const host: QuestionHost = {
      // the LIVE sim nodes, aliased with label/group so the engine and the
      // annotations track drag/settle positions in place
      nodes: nodes.map((d) =>
        Object.assign(d, { label: d.name, group: d.kind === "funder" ? d.funderKind : d.kind })),
      posOf: (id) => {
        const n = byId.get(id);
        return n && n.x != null ? { x: n.x, y: n.y! } : null;
      },
      radiusOf: (id) => { const n = byId.get(id); return n ? r(n) : 6; },
      labelOf: (id) => byId.get(id)?.name ?? id,
      shownOf: (id) => { const n = byId.get(id); return n ? shown(n) : false; },
      zoomTransform: () => { const t = d3.zoomTransform(svg.node()!); return { k: t.k, x: t.x, y: t.y }; },
      setZoomTransform: (t, animate) => {
        const zt = d3.zoomIdentity.translate(t.x, t.y).scale(t.k);
        if (animate) svg.transition().duration(450).call(zoom.transform, zt);
        else svg.call(zoom.transform, zt);
      },
      fitToIds: fitToNodes,
      setQuestionPaint: (p) => {
        qPaint = p;
        // route-mode mutual exclusion, half 2: entering a question dismisses
        // the path finder — WITHOUT clearPath's camera refit (the engine owns
        // the camera on question entry)
        if (p && (route || pathPair.from || pathPair.to || pathPair.armed)) clearPath(false);
        applyQuestionPaint();
        applyHighlight();
      },
      setPreview: setPreviewSet,
      forceShow: (ids) => { qForceShow = ids; applyFilter(); },
      marksLayer: () => qMarksG.node()!,
      calloutsLayer: () => qCalloutsG.node()!,
      onTick: (fn) => { tickHooks.push(fn); },
      onZoom: (fn) => { zoomHooks.push(fn); },
      reserveLabelBoxes: (fn) => { qReserve = fn; refreshLabels(); },
      parkSim: () => sim.stop(),
      resumeSimOnNextDrag: () => {}, // drag start already reheats the sim
      setDragEnabled: (on) => { dragEnabled = on; },
      setLabelsVisible: (on) => { labelsVisible = on; refreshLabels(); },
      redraw: tick,
      select: (id) => select(id ? { id } : null),
      getSelected: () => selected?.id ?? null,
      calm,
    };
    engineRef = initQuestions(host, { strip: stripEl, answer: answerEl, drawer: drawerEl }, makeFundingDefs(), {
      // AoC isn't a funding node — the default seat is its nearest funded
      // proxy, and must match the seat prep_questions.py bakes (the defs key
      // on the payload's own default.seat, so a mismatch degrades gracefully)
      defaultSeat: FUNDING_DEFAULT_SEAT,
      raw: { companies: pristine.nodes, edges: pristine.edges },
      payloadLoader: () => loadPayload().then((m) => (m as { default?: unknown }).default ?? m),
      appendixPath: "/networks/analyses",
      legacyRedirect: {
        // funding analyses with an on-map question
        "funder-fit": "funder-shortlist",
        "funder-shortlist": "funder-shortlist",
        "rivals-money": "rivals-money",
        "intro-chains": "warm-routes",
        "proximity-rank": "within-reach",
        "money-brokers": "funding-bridges",
        // appendix-only on this page: everything else that ever had an ?an=
        "deadline-calendar": null, "funding-gaps": null, "co-funding-cliques": null,
        upstream: null, "money-map": null, "shared-investors": null, "layer-shift": null,
        brokers: null, "best-new-edge": null, "missing-edges": null,
        "block-structure": null, "core-periphery": null, "market-map": null,
        "competitor-nominations": null,
      },
    });
  })();

  inited = true;
  refreshLabels();
  applyFilter();
  window.addEventListener("resize", () => fitToNodes(null, false));

}
