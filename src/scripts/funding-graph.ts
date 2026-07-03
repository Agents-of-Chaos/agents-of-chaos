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
  PERSON_R, UNKNOWN_R,
  makeSqrtScale, nodeDollars, radiusFor, edgeWidthFor,
  buildAdjacency, shortestPath, isOpenNow, computeVisible, sliderToUsd, formatUsd, topGrants,
} from "./funding-core.js";

type FNode = FundingNode & d3.SimulationNodeDatum;
type FLink = { e: FundingEdge; source: FNode; target: FNode };
type Sel = { id: string } | null;

const HALO = "#fffff8"; // --bg
const OPEN_RING = "#4f7a4e"; // open-now lens (green, same family as /networks customer ring)
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
  const nodeG = root.append("g");
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

  // Task 6 routes clicks into the path finder when a slot is armed; select() otherwise.
  function onNodeClick(d: FNode): void {
    select({ id: d.id });
  }

  if (!coarse) {
    nodeSel.on("mousemove", nodeTip).on("mouseleave", leaveNode);
    hitSel.on("mousemove", edgeTip).on("mouseleave", leaveEdge);
    nodeSel.call(d3.drag<SVGGElement, FNode>()
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

  /* ---------- zoom / pan ---------- */
  const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.2, 6])
    .on("zoom", (ev) => {
      root.attr("transform", ev.transform.toString());
      if (inited) scheduleLabels();
    });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("dblclick", () => fitToNodes(null, true));

  /** Frame the whole graph (ids=null) or a subset (Task 6: fit-to-route). */
  function fitToNodes(ids: string[] | null, animate: boolean) {
    let x0: number, y0: number, x1: number, y1: number;
    if (ids?.length) {
      const pts = ids.map((id) => byId.get(id)!).filter((d) => d.x != null);
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
  if (!calm) { sim.alpha(0.25).restart(); sim.on("end", () => fitToNodes(null, true)); }

  /* ---------- visibility (Task 5 wires controls into `filters`) ---------- */
  const filters = {
    kinds: new Set<FunderKind>(FUNDER_KINDS.map((k) => k.id)),
    domains: new Set<string>(),
    minUsd: 0,
    query: "",
  };
  let visibleSet = new Set<string>(nodes.map((n) => n.id));
  const shown = (d: FNode) => visibleSet.has(d.id) || inRoute(d.id); // active route is always shown

  function applyFilter() {
    filters.query = searchEl?.value ?? "";
    visibleSet = computeVisible(fundingNodes, fundingEdges, filters);
    if (isPrivate) { // stage chips (dev): Task 5 fills activeStages
      for (const id of [...visibleSet])
        if (!activeStages.has(stageOf(id) ?? "cold")) visibleSet.delete(id);
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

  /* Directory + view toggle land in Task 5; declared here so applyFilter compiles. */
  function renderDir(): void {}
  function setView(_v: "map" | "directory"): void {}
  void setView;

  /* ---------- highlight (route- and lens-aware from day one) ---------- */
  let selected: Sel = null, hover: Sel = null;
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
    const nb = neigh(hover ?? selected);
    const dimFor = (d: FNode) => // open-now lens dims what isn't actionable
      lensOpen && !openSet.has(d.id) ? (d.kind === "funder" ? 0.15 : 0.25) : 1;
    nodeSel.attr("opacity", (d) => (!shown(d) ? 0 : !nb ? dimFor(d) : nb.has(d.id) ? 1 : 0.12));
    linkSel.attr("stroke-opacity", (l) =>
      !shownEdge(l) ? 0
        : !nb ? (lensOpen ? 0.25 : 0.5) : nb.has(l.source.id) && nb.has(l.target.id) ? 0.9 : 0.04);
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
    const t = d3.zoomTransform(svg.node()!);
    labelSel.style("font-size", BASE_LABEL / t.k + "px");
    const nb = route ? new Set(route.ids) : neigh(hover ?? selected);
    const order = nb ? labelOrder.filter((d) => nb.has(d.id)) : labelOrder;
    const placed: number[][] = [];
    const show = new Set<string>();
    const PAD = 4;
    for (const d of order) {
      if (!shown(d)) continue;
      const w = labelW.get(d.id) ?? 40;
      const sx = d.x! * t.k + t.x;
      const baseY = (d.y! - r(d) - 4) * t.k + t.y;
      const box = [sx - w / 2 - PAD, baseY - BASE_LABEL - PAD, sx + w / 2 + PAD, baseY + PAD];
      const overlaps = placed.some((p) => box[0] < p[2] && box[2] > p[0] && box[1] < p[3] && box[3] > p[1]);
      if (overlaps && !(nb && nb.has(d.id))) continue;
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
    const annual = f.annualFieldGivingUSD != null
      ? `${formatUsd(f.annualFieldGivingUSD)}/yr${f.inKind ? " (incl. credits)" : ""}`
      : f.inKind ? "credits / in-kind" : "no public figure";
    const basis = f.annualFieldGivingBasis
      ? ` <a href="${esc(f.annualFieldGivingBasis.sourceUrl)}" target="_blank" rel="noopener" title="${esc(f.annualFieldGivingBasis.method)}">[${f.annualFieldGivingBasis.year}]</a>`
      : "";
    const check = f.checkSizeUSD
      ? `<div class="d-line"><span class="d-key">checks</span> ${formatUsd(f.checkSizeUSD.min)}–${formatUsd(f.checkSizeUSD.max)}</div>`
      : "";
    const grants = topGrants(fundingEdges, f.id, 5).map((g) => {
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
    detail.innerHTML = `<span class="d-clear" title="clear">✕</span>
      <div class="d-title">${esc(n.name)}</div>
      <div class="d-sub">${kindLine}</div>
      <div class="d-blurb">${esc(n.blurb)}</div>
      ${n.kind === "funder" && n.thesis ? `<div class="d-line"><span class="d-key">thesis</span> ${esc(n.thesis)}</div>` : ""}
      ${n.kind === "funder" ? moneyBlock(n) : ""}
      ${n.kind === "funder" ? applyBlock(n) : ""}
      ${n.kind === "funder" ? peopleBlock(n) : ""}
      ${priv}
      ${rels ? `<div class="d-rels">${rels}</div>` : ""}
      ${tags ? `<div class="d-line">${tags}</div>` : ""}
      ${n.url ? `<div class="d-src"><a href="${esc(n.url)}" target="_blank" rel="noopener">→ ${esc(n.url.replace(/^https?:\/\//, "").replace(/\/$/, ""))}</a></div>` : ""}
      ${crossLink}`;
    detail.querySelector(".d-clear")!.addEventListener("click", () => select(null));
    detail.querySelectorAll<HTMLElement>(".d-jump").forEach((b) =>
      b.addEventListener("click", () => select({ id: b.dataset.id! })));
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
            d.annualFieldGivingUSD != null ? `${formatUsd(d.annualFieldGivingUSD)}/yr` : d.inKind ? "credits" : "$ unknown"
          }${openSet.has(d.id) ? ` · <span style="color:${OPEN_RING}">open now</span>` : ""}`
        : d.kind === "grantee"
          ? `grantee${d.fieldDollarsUSD > 0 ? ` · ${formatUsd(d.fieldDollarsUSD)} in-field` : ""}`
          : esc((d as Extract<FNode, { kind: "person" }>).title);
    showTip(ev, `<div class="t-name">${esc(d.name)}${stHtml}</div>
      <div class="t-sub">${sub}</div>
      <div class="t-blurb">${esc(d.blurb)}</div>${warm ? `<div class="t-warm">↪ ${esc(warm)}</div>` : ""}`);
  }

  window.addEventListener("keydown", (ev) => { if (ev.key === "Escape") select(null); });

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

  inited = true;
  refreshLabels();
  applyFilter();
  window.addEventListener("resize", () => fitToNodes(null, false));

  void maxAnnual; void sliderToUsd; void UNKNOWN_R; void PERSON_R; // consumed in Tasks 5–7
}
