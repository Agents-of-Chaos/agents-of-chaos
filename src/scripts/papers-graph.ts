// papers-graph.ts — the interactive paper-relevance graph for /papers.
//
// Ports the proven rendering core from the original co-authorship map (d3-force over
// SVG, pre-settle-then-fit, zoom/drag) and re-skins it to the site palette. The new
// ideas live here:
//   • solid nodes  = papers in your set (read / curated)
//   • ghost nodes  = unread candidates the discovery slider nominates (vertex nomination)
//   • hover-heat   = shade every node by relevance to the hovered one (relative-scaled,
//                    because SPECTER2 cosines sit in a narrow high band)
//   • add a paper  = fetch its SPECTER2 vector and drop it in (no re-embedding)
// All graph math is in papers-core.js; this file is DOM + d3 + state only.

import {
  forceSimulation, forceLink, forceManyBody, forceCollide, forceCenter, forceX, forceY,
  select, zoom, zoomIdentity, drag, scaleSqrt, min as d3min, max as d3max,
} from "d3";
import { buildEdges, edgeWeight, vnRank, toNode, BATCH_FIELDS, REC_FIELDS } from "./papers-core.js";

type Vec = number[] | null;
interface PaperNode {
  id: string; title: string; authors: string[]; year: number | null;
  citationCount: number; url: string; arxiv: string | null; vec: Vec; refs: string[];
  tldr?: string | null; abstract?: string | null;
  ghost?: boolean; vnScore?: number; nearestId?: string | null;
  x?: number; y?: number; fx?: number | null; fy?: number | null;
}
interface Edge { source: any; target: any; w: number; ghost?: boolean; }

const ADDS_KEY = "aoc.papers.adds.v1";
const REMOVED_KEY = "aoc.papers.removed.v1"; // baked papers the curator has removed
const ACCENT = "#a00", INK = "#37332e", FAR = "#d7d1c2", BG = "#fffff8", GHOST = "#b9b09a";
const PROXY = "/api/paper";
const S2 = "https://api.semanticscholar.org";
const MAX_REVEAL = 40; // most ghost candidates the discovery slider will reveal
const CITE_WEIGHT = 0.25; // how much a paper's (log) citations nudge its nomination rank — small: relevance stays primary
const LABEL_GHOST_CAP = 16; // name at most this many candidates at once (the most relevant)
let labelSet = new Set<string>(); // node ids that currently get a name above them

// ── module state ────────────────────────────────────────────────────────────────
let baked: PaperNode[] = [];          // shipped canonical set (public/papers.json)
let read: PaperNode[] = [];           // baked ∪ your local adds (solid nodes)
let candidates: PaperNode[] = [];     // ranked unread frontier (all of it)
let revealCount = 0;                  // how many candidates the slider reveals
let frontierLoaded = false, frontierBusy = false;
let editing = false;                  // edit mode: clicking a read node removes it
let focusIds: string[] = [];          // discovery focus set: nominate near ALL these papers (click / shift-click)
let explainers: Record<string, { url: string; title: string; kind?: string }> = {}; // paperId → its explainer page
const pos = new Map<string, { x: number; y: number }>(); // persist positions across renders

let sim: any, svg: any, g: any, linkG: any, linkHitG: any, nodeG: any, labelG: any, zoomB: any;
let W = 800, H = 560;
const el = (id: string) => document.getElementById(id)!;

// ── boot ────────────────────────────────────────────────────────────────────────
export async function initPapersGraph() {
  const host = el("papers-graph");
  const [data, exp] = await Promise.all([
    fetch("/papers.json").then((r) => r.json()).catch(() => ({})),
    fetch("/papers/explainers.json").then((r) => r.json()).catch(() => ({})), // which papers have explainers
  ]);
  baked = data.nodes || [];
  explainers = exp;
  const removed = loadRemoved();
  read = mergeAdds(baked.filter((n) => !removed.has(n.id)), loadAdds());
  // Seed the discovery frontier from the baked snapshot so the FIRST slider tick reveals a paper
  // instantly — even if you drag before the live refresh lands. (Filter out papers you've already
  // added or removed.) The background refresh below replaces this with embedding-ranked candidates.
  const bakedFrontier: PaperNode[] = (data.frontier || []).filter(
    (c: PaperNode) => !read.some((n) => n.id === c.id) && !removed.has(c.id));
  if (bakedFrontier.length) { candidates = bakedFrontier; frontierLoaded = true; }
  await new Promise(requestAnimationFrame); // let the layout settle so the box has real dimensions
  const rect = host.getBoundingClientRect();
  W = Math.round(rect.width) || 800; H = Math.round(rect.height) || 560;
  buildSvg(host);
  rebuildEdges();
  firstRender();
  wireControls();
  renderReadList();
  setStatus(`${read.length} papers · drag the slider to nominate more`);
  // Preload the discovery frontier in the background so the FIRST slider tick reveals a paper
  // instantly (later ticks are already synchronous). Silent — no ghosts or status change until
  // you drag. Skipped if the set has no Semantic-Scholar-id papers to seed recommendations on.
  if (read.some((n) => /^[0-9a-f]{40}$/i.test(n.id))) loadFrontier(false, frontierLoaded); // refresh past the baked snapshot
  // Escape clears the current selection (and closes the paper panel)
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { hideDetail(); clearFocus(); } });
  // ResizeObserver's contentRect is the authoritative box size (and corrects any
  // first-paint measurement); re-fit the viewBox + forces whenever it changes.
  new ResizeObserver((entries) => {
    const cr = entries[0].contentRect;
    const w = Math.round(cr.width) || W, h = Math.round(cr.height) || H;
    if (w === W && h === H) return;
    W = w; H = h;
    svg.attr("viewBox", `0 0 ${W} ${H}`);
    sim.force("center", forceCenter(W / 2, H / 2));
    sim.force("x", forceX(W / 2).strength(0.03));
    sim.force("y", forceY(H / 2).strength(0.03));
    sim.alpha(0.2).restart();
    fit(0);
  }).observe(host);
}

// ── persistence ───────────────────────────────────────────────────────────────--
function loadAdds(): PaperNode[] {
  try { return JSON.parse(localStorage.getItem(ADDS_KEY) || "[]"); } catch { return []; }
}
function saveAdds(nodes: PaperNode[]) {
  localStorage.setItem(ADDS_KEY, JSON.stringify(nodes));
}
function mergeAdds(base: PaperNode[], adds: PaperNode[]): PaperNode[] {
  const seen = new Set(base.map((n) => n.id));
  return base.concat(adds.filter((a) => a && a.id && !seen.has(a.id)));
}
function localAdds(): PaperNode[] {
  const bakedIds = new Set(baked.map((n) => n.id));
  return read.filter((n) => !bakedIds.has(n.id));
}
function loadRemoved(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(REMOVED_KEY) || "[]")); } catch { return new Set(); }
}
function saveRemoved(ids: Set<string>) {
  localStorage.setItem(REMOVED_KEY, JSON.stringify([...ids]));
}

// ── data fetch (proxy, with direct-S2 fallback for dev / no-proxy) ────────────────
async function s2(body: any): Promise<any> {
  try {
    const r = await fetch(PROXY, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (r.ok) return await r.json();
  } catch { /* fall through to direct */ }
  if (Array.isArray(body.ids)) {
    return fetch(`${S2}/graph/v1/paper/batch?fields=${BATCH_FIELDS}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: body.ids }),
    }).then((r) => r.json());
  }
  return fetch(`${S2}/recommendations/v1/papers/?fields=${REC_FIELDS}&limit=${body.limit || 40}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ positivePaperIds: body.positivePaperIds, negativePaperIds: body.negativePaperIds || [] }),
  }).then((r) => r.json());
}

// The discovery frontier is keyed by the current focus set ("" = your whole set). Sorted so
// the key is order-independent; capturing it as `myKey` lets an in-flight fetch notice the
// focus changed and chase the new one.
function frontierKey(): string { return focusIds.slice().sort().join(","); }

function focusLabel(nodes: PaperNode[]): string {
  return nodes.length > 1 ? `all ${nodes.length} selected papers`
    : nodes.length === 1 ? `“${short(nodes[0].title)}”` : "your set";
}

// Only papers you haven't read AND haven't deliberately removed may be nominated —
// every path that stages candidates goes through this one gate.
function nominable(list: PaperNode[]): PaperNode[] {
  const removed = loadRemoved();
  return list.filter((c) => c && c.id && !read.some((n) => n.id === c.id) && !removed.has(c.id));
}

// Re-rank the candidates we already hold around the current focus (or the whole set).
// After the first enrichment the pool carries SPECTER2 vectors, so this is synchronous —
// a click / shift-click / clear / add re-aims discovery instantly instead of waiting on a
// network fetch. Returns false when the pool can't support it (no vectors yet, e.g. only
// the baked snapshot) → the caller falls back to fetching.
function localNominate(): boolean {
  const focusNodes = focusIds.map((id) => read.find((n) => n.id === id)).filter(Boolean) as PaperNode[];
  const seeds = (focusNodes.length ? focusNodes : read).filter((n) => n.vec);
  const pool = nominable(candidates).filter((c) => c.vec);
  if (!seeds.length || !pool.length) return false;
  const agg: "min" | "max" = focusNodes.length >= 2 ? "min" : "max";
  candidates = vnRank(pool, seeds, { agg, citeWeight: CITE_WEIGHT }) as PaperNode[];
  candidates.forEach((c) => { c.ghost = true; });
  frontierLoaded = true;
  return true;
}

// After an action that re-aims discovery, reveal at least a taste (6) — and keep the
// slider thumb in agreement with revealCount so the next drag continues from there.
function autoReveal() {
  revealCount = Math.max(revealCount, Math.min(6, candidates.length));
  syncSlider();
}
function syncSlider() {
  const s = el("discover") as HTMLInputElement;
  const cap = Math.min(candidates.length, MAX_REVEAL);
  s.value = String(cap ? Math.round((revealCount / cap) * 100) : 0);
}

// Fetch the unread candidates the slider nominates. Two modes:
//   • no focus  → recommendations for your whole read set, ranked by nearest-read cosine
//   • a focus   → recommendations seeded on that ONE paper, ranked by cosine to it (click a node)
// Two phases so a throttled embeddings call can't stall the reveal: show the recommended
// papers at once in S2's own relevance order, then re-rank by SPECTER2 in the background.
// `reveal = false` is a silent PRELOAD: fetch and stage the candidates but touch nothing on
// screen (no ghosts, no status, no read-list) until the user actually drags. That's what makes
// the first slider tick instant — the network round-trip already happened in the background.
async function loadFrontier(reveal = true, force = false) {
  if (frontierBusy || (frontierLoaded && !force)) return; // `force` refreshes past a baked/preloaded frontier
  const myKey = frontierKey();
  const focusNodes = focusIds.map((id) => read.find((n) => n.id === id)).filter(Boolean) as PaperNode[];
  const isS2 = (id: string) => /^[0-9a-f]{40}$/i.test(id);
  // recommendations need real S2 ids — locally-embedded nodes (e.g. the METR report) have a
  // synthetic id. Seed on the selected papers that have one, else the whole read set.
  const focusS2 = focusNodes.map((n) => n.id).filter(isS2);
  const seedIds = focusS2.length ? focusS2 : read.map((n) => n.id).filter(isS2);
  if (!seedIds.length) {
    if (reveal) {
      setStatus(focusNodes.length
        ? "can't nominate from this selection — no Semantic Scholar ids"
        : "add a paper by arXiv / DOI / S2 id to get recommendations");
      (el("discover") as HTMLInputElement).disabled = false;
    }
    return;
  }
  frontierBusy = true;
  if (reveal) setStatus(focusNodes.length ? `finding papers close to ${focusLabel(focusNodes)}…` : "finding papers you should read…");
  try {
    const rec = await s2({ positivePaperIds: seedIds, limit: 80 });
    const removed = loadRemoved();
    const recPapers = (rec.recommendedPapers || [])
      .filter((p: any) => p && p.paperId && !read.some((r) => r.id === p.paperId) && !removed.has(p.paperId));
    if (!recPapers.length) {
      // the (light) recommendations call itself failed/empty — usually rate-limiting. Stay
      // unloaded so a real drag retries (a silent preload just gives up quietly).
      if (reveal) setStatus("no papers found — Semantic Scholar may be rate-limiting; drag again to retry");
    } else if (frontierKey() === myKey) {
      const rankSeeds = focusNodes.filter((n) => n.vec).length ? focusNodes.filter((n) => n.vec) : read;
      const agg: "min" | "max" = focusNodes.length >= 2 ? "min" : "max"; // 2+ selected → closest to ALL
      const anchorId = (rankSeeds[0] && rankSeeds[0].id) || (read[0] && read[0].id) || null;
      // phase 1 — if nothing SPECTER2-ranked is on screen (baked snapshot / cold drag), stage
      // the recommendations at once in S2's own relevance order. When a local re-rank is already
      // showing, keep it — phase 2 folds these papers into that ranking instead of downgrading.
      if (!candidates.some((c) => c.vec)) {
        candidates = (recPapers.map(toNode).filter(Boolean) as PaperNode[])
          .map((c, i) => ({ ...c, ghost: true, vnScore: 1 - i / recPapers.length, nearestId: anchorId }));
      }
      frontierLoaded = true;
      if (reveal) revealCount = Math.max(revealCount, Math.min(6, candidates.length));
      (el("discover") as HTMLInputElement).disabled = false;
      enrichFrontier(recPapers, rankSeeds, anchorId, myKey, agg); // phase 2 — SPECTER2 re-rank, background
    }
  } catch {
    if (reveal) setStatus("couldn't reach Semantic Scholar — drag again to retry");
  } finally {
    frontierBusy = false;
    if (frontierKey() !== myKey) {   // focus changed while fetching → chase the current one
      loadFrontier(reveal, true);    // (force: a local re-rank may already be showing — refresh past it)
    } else if (reveal) {
      if (frontierLoaded) setStatus(frontierStatus(focusNodes));
      syncReveal(); renderReadList();
    } else if (frontierLoaded) {
      // silent preload finished. If the user already started dragging while it loaded, honor
      // the slider now; otherwise stay invisible until they do.
      const s = el("discover") as HTMLInputElement;
      const want = Math.round((+s.value / 100) * Math.min(candidates.length, MAX_REVEAL));
      if (want > 0) { revealCount = want; setStatus(frontierStatus(focusNodes)); syncReveal(); renderReadList(); }
    }
  }
}

// Phase 2: pull SPECTER2 vectors for the candidates and re-rank by cosine to the seed(s),
// aggregating with `agg` ("max" = close to any seed, "min" = close to all — multi-focus).
// Best-effort — if S2 throttles the (heavy) batch we keep phase 1's S2-order candidates.
async function enrichFrontier(recPapers: any[], rankSeeds: PaperNode[], anchorId: string | null, myKey: string, agg: "min" | "max") {
  try {
    const b = await s2({ ids: recPapers.map((p) => p.paperId).slice(0, 100) });
    if (!Array.isArray(b) || frontierKey() !== myKey) return;
    const enriched = new Map((b.map(toNode).filter((n) => n && n.vec) as PaperNode[]).map((n) => [n.id, n]));
    // pool = these recommendations ∪ the vector-carrying candidates we already hold, so a
    // focus change or refresh only ever widens recall. The freshly-batched node wins (it has
    // the abstract/tldr too); nominable() re-filters — `read` may have grown mid-flight.
    const byId = new Map<string, PaperNode>();
    for (const c of candidates) if (c.vec) byId.set(c.id, c);
    for (const p of recPapers.map(toNode).filter(Boolean) as PaperNode[]) {
      byId.set(p.id, enriched.get(p.id) || byId.get(p.id) || p);
    }
    const merged = nominable([...byId.values()]);
    const withVec = merged.filter((c) => c.vec);
    const without = merged.filter((c) => !c.vec);
    candidates = [
      ...(vnRank(withVec, rankSeeds, { agg, citeWeight: CITE_WEIGHT }) as PaperNode[]),
      ...without.map((c, i) => ({ ...c, vnScore: -1 - i, nearestId: anchorId })),
    ];
    candidates.forEach((c) => { c.ghost = true; if (!c.nearestId) c.nearestId = anchorId; });
    if (revealCount > 0) { syncReveal(); renderReadList(); } // nothing revealed yet (e.g. preload) → stay silent
  } catch { /* keep phase 1's S2-order candidates */ }
}

function frontierStatus(focusNodes: PaperNode[]): string {
  if (focusNodes.length >= 2) return `${candidates.length} papers close to all ${focusNodes.length} selected — drag to reveal`;
  if (focusNodes.length === 1) return `${candidates.length} papers like “${short(focusNodes[0].title)}” — drag to reveal`;
  return `${read.length} in your set · ${candidates.length} unread papers nominated`;
}

// Plain click → focus discovery on this ONE paper (replaces any selection).
function setFocus(node: PaperNode) {
  if (focusIds.length === 1 && focusIds[0] === node.id) return;
  focusIds = [node.id];
  reFocus();
}

// Shift-click → add/remove this paper from the focus set; the slider then nominates the papers
// closest to ALL of them at once. Emptying the set returns to whole-set nomination.
function toggleFocus(node: PaperNode) {
  const next = focusIds.includes(node.id) ? focusIds.filter((id) => id !== node.id) : [...focusIds, node.id];
  if (!next.length) { clearFocus(); return; }
  focusIds = next;
  reFocus();
}

// Re-nominate after the (non-empty) focus set changes. If the held pool carries vectors,
// re-aim instantly (synchronous re-rank) and widen recall in the background with the
// selection's own recommendations; only a vector-less pool waits on the network.
function reFocus() {
  updateDiscoverHint();
  if (localNominate()) {
    autoReveal(); // a click should show something, not just re-arm the slider
    const focusNodes = focusIds.map((id) => read.find((n) => n.id === id)).filter(Boolean) as PaperNode[];
    setStatus(frontierStatus(focusNodes));
    syncReveal(); renderReadList();
    loadFrontier(false, true);
  } else {
    frontierLoaded = false; candidates = [];
    render(0.4);      // draw/refresh the focus rings + glow; old ghosts clear
    loadFrontier();   // fetch papers near the selection
  }
}

// Back to whole-set nomination: ghosts tuck away (revealCount 0) but the pool is re-ranked
// around your whole set right here, so the next drag reveals instantly with no fetch.
function clearFocus() {
  if (!focusIds.length) return;
  focusIds = [];
  revealCount = 0;
  if (!localNominate()) { frontierLoaded = false; candidates = []; }
  syncSlider();
  updateDiscoverHint();
  setStatus(`${read.length} papers · drag the slider to nominate more`);
  syncReveal(); // renders: ghosts tuck away, focus rings clear
}

function updateDiscoverHint() {
  const h = document.getElementById("discover-hint");
  if (!h) return;
  const nodes = focusIds.map((id) => read.find((n) => n.id === id)).filter(Boolean) as PaperNode[];
  h.textContent = nodes.length >= 2
    ? `unread papers, ranked by closeness to all ${nodes.length} selected papers`
    : nodes.length === 1
      ? `unread papers, ranked by closeness to “${short(nodes[0].title)}”`
      : "unread papers, ranked by relevance to your set";
}

// ── graph assembly ────────────────────────────────────────────────────────────--
function revealed(): PaperNode[] { return candidates.slice(0, revealCount); }
function nodes(): PaperNode[] { return read.concat(revealed()); }

let readEdges: Edge[] = [];
function rebuildEdges() { readEdges = buildEdges(read, { k: 6 }) as Edge[]; }
function links(): Edge[] {
  // edges among read papers + a tether from each ghost to its nearest read paper
  const ghostLinks: Edge[] = revealed().map((c) => ({ source: c.nearestId, target: c.id, w: Math.max(0, c.vnScore || 0), ghost: true }));
  return readEdges.concat(ghostLinks);
}

// ── svg + forces ────────────────────────────────────────────────────────────────
function buildSvg(host: HTMLElement) {
  select(host).selectAll("*").remove();
  svg = select(host).append("svg").attr("width", "100%").attr("height", "100%").attr("viewBox", `0 0 ${W} ${H}`);
  // soft accent glow that highlights the focused node (applied to its circle in render())
  svg.append("defs").append("filter")
    .attr("id", "focus-glow").attr("x", "-80%").attr("y", "-80%").attr("width", "260%").attr("height", "260%")
    .append("feDropShadow").attr("dx", 0).attr("dy", 0).attr("stdDeviation", 6)
    .attr("flood-color", ACCENT).attr("flood-opacity", 0.9);
  g = svg.append("g");
  linkG = g.append("g").attr("fill", "none").style("pointer-events", "none");
  // transparent wide lines over the edges so thin edges are easy to hover for the tooltip
  linkHitG = g.append("g").attr("fill", "none").attr("stroke", "transparent").attr("stroke-width", 16).style("pointer-events", "stroke").style("cursor", "help");
  nodeG = g.append("g");
  labelG = g.append("g");

  zoomB = zoom().scaleExtent([0.2, 5]).on("zoom", (e: any) => g.attr("transform", e.transform));
  svg.call(zoomB).on("dblclick.zoom", null);
  svg.on("dblclick", () => fit(400));
  // click empty space (not a node, and not the tail of a pan) → clear the focus selection
  let downAt: [number, number] | null = null;
  svg.on("mousedown.clear", (e: any) => { downAt = [e.clientX, e.clientY]; });
  svg.on("click.clear", (e: any) => {
    const moved = downAt ? Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4 : false;
    downAt = null;
    if (moved || (e.target as Element).closest(".node")) return; // a pan, or a click on a node
    if (focusIds.length) { hideDetail(); clearFocus(); }
  });

  sim = forceSimulation<PaperNode>([])
    .force("link", forceLink<PaperNode, Edge>([]).id((d: any) => d.id).distance((l: Edge) => 78 + 26 / Math.sqrt((l.w || 0.1) + 0.05)).strength((l: Edge) => (l.ghost ? 0.2 : 0.5)))
    .force("charge", forceManyBody().strength(-460))
    // give named nodes extra clearance so their labels don't collide
    .force("collide", forceCollide().radius((d: any) => r(d) + (labelSet.has(d.id) ? 28 : 9)).strength(0.85))
    .force("center", forceCenter(W / 2, H / 2))
    .force("x", forceX(W / 2).strength(0.025))
    .force("y", forceY(H / 2).strength(0.025))
    .on("tick", tick);
}

// bounded sqrt radius (citation counts span 3+ orders of magnitude — an unbounded
// sqrt makes a 2700-cite paper a 90px blob; clamp to a sane range like the original)
// absolute sqrt scale on citation count, fixed reference (1000 ≈ "highly cited") — so a
// recent low-cite paper stays small and a seminal one is large regardless of the rest of
// the set. (A set-relative domain made whichever paper had the most cites max out, so two
// brand-new papers with 3–7 cites rendered as large as a 2700-cite classic.)
const radiusScale = scaleSqrt().domain([0, 1000]).range([8, 24]).clamp(true);
const r = (d: PaperNode) => (d.ghost ? 5 : radiusScale(d.citationCount));

// ── render (keyed joins; positions persist via `pos`) ─────────────────────────────
function render(alpha = 0.5) {
  const nd = nodes(), ld = links();
  // seed positions for new nodes near a neighbour (ghosts) or centre
  for (const n of nd) {
    if (n.x == null) {
      const anchor = n.ghost && n.nearestId ? pos.get(n.nearestId) : null;
      n.x = (anchor ? anchor.x : W / 2) + (Math.random() - 0.5) * 60;
      n.y = (anchor ? anchor.y : H / 2) + (Math.random() - 0.5) * 60;
    }
  }
  const lw = mkWidthScale(ld);

  linkG.selectAll<SVGLineElement, Edge>("line")
    .data(ld, (d: any) => keyOf(d))
    .join("line")
    .attr("stroke", (d: Edge) => (d.ghost ? GHOST : "#cdbfae"))
    .attr("stroke-width", (d: Edge) => lw(d.w))
    .attr("stroke-opacity", (d: Edge) => (d.ghost ? 0.4 : 0.55))
    .attr("stroke-dasharray", (d: Edge) => (d.ghost ? "3 4" : null));

  linkHitG.selectAll<SVGLineElement, Edge>("line")
    .data(ld, (d: any) => keyOf(d))
    .join("line")
    .on("mouseenter", (e: any, d: Edge) => showEdgeTip(d, e))
    .on("mousemove", (e: any) => positionEdgeTip(edgeTip(), e))
    .on("mouseleave", hideEdgeTip);

  const nodeSel = nodeG.selectAll<SVGGElement, PaperNode>("g.node")
    .data(nd, (d: any) => d.id)
    .join((enter: any) => {
      const gg = enter.append("g").attr("class", "node").style("cursor", "pointer");
      gg.append("circle");
      gg.call(drag<SVGGElement, PaperNode>().on("start", dStart).on("drag", dMove).on("end", dEnd) as any);
      gg.on("mouseenter", (_e: any, d: PaperNode) => heat(d))
        .on("mouseleave", () => unheat())
        .on("click", (e: any, d: PaperNode) => {
          if (d.ghost) promote(d);
          else if (editing) removePaper(d.id);
          else if (e.shiftKey) toggleFocus(d);   // shift-click → add/remove from the focus set
          else { showDetail(d); setFocus(d); }    // plain click → info + focus on just this one
        });
      return gg;
    });
  nodeSel.select("circle")
    .attr("r", r)
    .attr("fill", (d: PaperNode) => (d.ghost ? BG : INK))
    // focused paper gets a solid accent ring; in edit mode read nodes get a red dashed ring
    .attr("stroke", (d: PaperNode) => (focusIds.includes(d.id) ? ACCENT : d.ghost ? GHOST : editing ? ACCENT : BG))
    .attr("stroke-width", (d: PaperNode) => (focusIds.includes(d.id) ? 3 : d.ghost ? 1.3 : editing ? 1.8 : 1.5))
    .attr("stroke-dasharray", (d: PaperNode) => (focusIds.includes(d.id) ? null : d.ghost ? "2.5 2.5" : editing ? "2 2" : null))
    .attr("filter", (d: PaperNode) => (focusIds.includes(d.id) ? "url(#focus-glow)" : null)); // accent glow around each focused node

  // name read papers always + the most-relevant revealed candidates (importance =
  // vertex-nomination rank), capped so a fanned-out frontier doesn't turn to mush
  labelSet = new Set(read.map((n) => n.id));
  revealed().slice(0, LABEL_GHOST_CAP).forEach((c) => labelSet.add(c.id));
  labelG.selectAll<SVGTextElement, PaperNode>("text")
    .data(nd.filter((n) => labelSet.has(n.id)), (d: any) => d.id)
    .join("text")
    .attr("class", "node-label")
    .attr("text-anchor", "middle")
    .attr("fill", (d: PaperNode) => (d.ghost ? "#9b9588" : "#4a463f")) // candidates muted vs read
    .attr("font-size", (d: PaperNode) => (d.ghost ? "9px" : "10.5px"))
    .text((d: PaperNode) => shortTitle(d));

  sim.nodes(nd);
  (sim.force("link") as any).links(ld);
  sim.alpha(alpha).restart();
}

function firstRender() {
  render(0);
  sim.stop();
  for (let i = 0; i < 280; i++) sim.tick();
  nodes().forEach((n) => pos.set(n.id, { x: n.x!, y: n.y! }));
  tick();
  fit(0);
}

function tick() {
  linkG.selectAll<SVGLineElement, Edge>("line")
    .attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
    .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
  linkHitG.selectAll<SVGLineElement, Edge>("line")
    .attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
    .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
  nodeG.selectAll<SVGGElement, PaperNode>("g.node").attr("transform", (d: PaperNode) => `translate(${d.x},${d.y})`);
  labelG.selectAll<SVGTextElement, PaperNode>("text")
    .attr("x", (d: PaperNode) => d.x!).attr("y", (d: PaperNode) => d.y! - r(d) - 5);
  nodes().forEach((n) => pos.set(n.id, { x: n.x!, y: n.y! }));
}

// ── hover heat: shade every node by relevance to the hovered paper ───────────────
function heat(h: PaperNode) {
  const rsH = new Set(h.refs || []);
  const wById = new Map<string, number>(); // weight to h, computed once per node
  for (const n of nodes()) if (n.id !== h.id) wById.set(n.id, edgeWeight(h, n, rsH, new Set(n.refs || [])));
  const vals = [...wById.values()];
  const lo = d3min(vals) ?? 0, hi = d3max(vals) ?? 1;
  const span = hi - lo || 1;
  nodeG.selectAll<SVGGElement, PaperNode>("g.node").select("circle")
    .attr("fill", (d: PaperNode) => (d.id === h.id ? ACCENT : mix(FAR, ACCENT, ((wById.get(d.id) ?? lo) - lo) / span)));
  linkG.selectAll<SVGLineElement, Edge>("line")
    .attr("stroke-opacity", (d: any) => (d.source.id === h.id || d.target.id === h.id ? 0.85 : 0.08));
  showTip(h);
}
function unheat() {
  nodeG.selectAll<SVGGElement, PaperNode>("g.node").select("circle")
    .attr("fill", (d: PaperNode) => (d.ghost ? BG : INK));
  linkG.selectAll<SVGLineElement, Edge>("line").attr("stroke-opacity", (d: Edge) => (d.ghost ? 0.4 : 0.55));
  hideTip();
}

// ── controls ──────────────────────────────────────────────────────────────────--
function wireControls() {
  const slider = el("discover") as HTMLInputElement;
  // Keep it draggable from load: the frontier (S2 recommendations) is fetched lazily on the
  // first drag so page views stay API-free. It used to start disabled with nothing on the
  // no-interaction path to re-enable it — only add/remove did — so a fresh load left the
  // slider greyed-out and unusable. The first drag below triggers the lazy load.
  slider.disabled = false;
  slider.addEventListener("input", async () => {
    if (!frontierLoaded) { await loadFrontier(); }
    const next = Math.round((+slider.value / 100) * Math.min(candidates.length, MAX_REVEAL));
    if (next === revealCount) return; // a drag fires many events; only ~MAX_REVEAL distinct counts
    revealCount = next;
    syncReveal(); renderReadList();
  });

  el("add-btn").addEventListener("click", addFromInput);
  (el("add-id") as HTMLInputElement).addEventListener("keydown", (e: any) => { if (e.key === "Enter") addFromInput(); });
  el("export-btn").addEventListener("click", exportJson);
  const editBtn = el("edit-btn");
  editBtn.addEventListener("click", () => {
    editing = !editing;
    editBtn.textContent = editing ? "done" : "edit";
    editBtn.classList.toggle("on", editing);
    el("papers-graph").classList.toggle("editing", editing);
    render(0); // re-apply node styling for edit mode
    setStatus(editing ? "edit mode — click a paper to remove it" : `${read.length} in your set`);
  });
}

function syncReveal() {
  render(0.5);
  const c = revealed().length;
  el("discover-k").textContent = frontierLoaded ? `${c} of ${Math.min(candidates.length, MAX_REVEAL)} nominated` : "—";
}

async function addFromInput() {
  const input = el("add-id") as HTMLInputElement;
  const id = normalizeId(input.value.trim());
  if (!id) return;
  setStatus(`looking up ${id}…`);
  let b: any = null;
  try { b = await s2({ ids: [id] }); }
  catch { setStatus("couldn't reach Semantic Scholar — try again"); return; }
  const node = (Array.isArray(b) ? b.map(toNode).filter(Boolean)[0] : null) as PaperNode | null;
  if (!node) { setStatus(`couldn't find "${input.value}"`); return; }
  if (read.some((n) => n.id === node.id)) { setStatus("already in your graph"); input.value = ""; return; }
  addNode(node); input.value = "";
}

async function promote(c: PaperNode) {
  candidates = candidates.filter((x) => x.id !== c.id);
  let node: PaperNode = { ...c }; delete node.ghost; delete node.vnScore; delete node.nearestId;
  if (!node.vec) {
    // came from recommendations without an embedding — fetch the full paper so it joins
    // the set with relevance edges + abstract like the others
    setStatus(`adding ${node.title.slice(0, 40)}…`);
    try {
      const b = await s2({ ids: [c.id] });
      const full = Array.isArray(b) ? (b.map(toNode).filter(Boolean)[0] as PaperNode) : null;
      if (full && full.vec) node = full;
    } catch { /* fall back to the embedding-free node */ }
  }
  addNode(node);
}

function addNode(node: PaperNode) {
  read.push(node);
  const rm = loadRemoved(); if (rm.delete(node.id)) saveRemoved(rm); // un-remove if re-adding a removed paper
  saveAdds(localAdds());
  rebuildEdges();
  (el("discover") as HTMLInputElement).disabled = false;
  // your interests changed → re-nominate: instantly from the held pool when it has vectors
  // (the background refresh then brings recommendations for the grown set), else refetch.
  const instant = localNominate();
  if (instant) autoReveal();
  else { frontierLoaded = false; candidates = []; }
  syncReveal(); renderReadList();
  setStatus(`added · ${node.title.slice(0, 48)}`);
  loadFrontier(!instant, instant);
}

// Remove a paper from your set. Removing a baked (shipped) paper is remembered in the
// REMOVED set so it stays gone across reloads; removing one you added just drops it from
// the persisted adds. Either way the change is permanent (per browser) — there's no reset.
function removePaper(id: string) {
  read = read.filter((n) => n.id !== id);
  pos.delete(id);
  if (focusIds.includes(id)) { focusIds = focusIds.filter((f) => f !== id); updateDiscoverHint(); } // drop a removed paper from the focus set
  hideDetail();
  if (baked.some((n) => n.id === id)) { const rm = loadRemoved(); rm.add(id); saveRemoved(rm); }
  saveAdds(localAdds());
  rebuildEdges();
  // re-nominate for the shrunk set — instantly when the pool has vectors, silently either way
  // (removal shouldn't pop new ghosts; the current reveal just re-ranks)
  const instant = read.length ? localNominate() : false;
  if (!instant) { frontierLoaded = false; candidates = []; }
  syncReveal(); renderReadList();
  setStatus(read.length ? `removed · ${read.length} in your set` : "graph empty — add a paper to begin");
  if (read.length) loadFrontier(false, instant);
}

function exportJson() {
  const blob = new Blob([JSON.stringify({ nodes: read, builtAt: new Date().toISOString() })], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "papers.json"; a.click();
  setStatus(`exported ${read.length} papers → commit to public/papers.json`);
}

// ── read-list panel (the vertex-nomination "what to read next") ───────────────────
function renderReadList() {
  const host = el("readlist");
  if (!frontierLoaded) { host.innerHTML = ""; return; }
  const top = revealed();
  if (!top.length) { host.innerHTML = `<p class="rl-empty">No nominations yet — slide right.</p>`; return; }
  const lo = top[top.length - 1].vnScore ?? 0, hi = top[0].vnScore ?? 1, span = (hi - lo) || 1;
  host.innerHTML = top.map((c, i) => {
    const rel = Math.round(((c.vnScore! - lo) / span) * 100);
    const near = read.find((n) => n.id === c.nearestId);
    return `<div class="rl-row">
      <span class="rl-rank">${i + 1}</span>
      <span class="rl-main"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>
        <span class="rl-meta">${(c.authors[0] || "").split(" ").slice(-1)[0]}${c.authors.length > 1 ? " et al." : ""} · ${c.year ?? ""} · near ${esc(short(near?.title || ""))}</span></span>
      <span class="rl-rel" title="relative relevance">${rel}</span>
      <button class="rl-add" data-id="${c.id}">+ read</button>
    </div>`;
  }).join("");
  host.querySelectorAll<HTMLButtonElement>(".rl-add").forEach((btn) =>
    btn.addEventListener("click", () => { const c = candidates.find((x) => x.id === btn.dataset.id); if (c) promote(c); }));
}

// ── drag, zoom-fit, tooltip, helpers ─────────────────────────────────────────────
function dStart(e: any, d: PaperNode) { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dMove(e: any, d: PaperNode) { d.fx = e.x; d.fy = e.y; }
function dEnd(e: any, d: PaperNode) { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }

function fit(dur = 400) {
  const nd = nodes(); if (!nd.length) return;
  const xs = nd.map((n) => n.x!), ys = nd.map((n) => n.y!);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const dx = x1 - x0 || 1, dy = y1 - y0 || 1, pad = 120;
  // 0.78 (not ~0.95) leaves margin for node labels, which extend well beyond the nodes
  const s = Math.min(2.4, 0.78 / Math.max(dx / (W - pad), dy / (H - pad)));
  const tx = W / 2 - s * (x0 + x1) / 2, ty = H / 2 - s * (y0 + y1) / 2;
  svg.transition().duration(dur).call(zoomB.transform, zoomIdentity.translate(tx, ty).scale(s));
}

let tipEl: HTMLElement | null = null;
// a short blurb for the hover tooltip: the paper's TL;DR, else the first few sentences of
// its abstract. Empty for candidates not yet enriched with an abstract (they show title only).
function tipSummary(d: PaperNode): string {
  if (d.tldr) return esc(d.tldr);
  if (d.abstract) {
    const s = d.abstract.trim();
    return esc(s.length > 340 ? s.slice(0, 340).replace(/\s+\S*$/, "") + "…" : s);
  }
  return "";
}
function showTip(d: PaperNode) {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "graph-tip"; el("papers-graph").appendChild(tipEl); }
  const sum = tipSummary(d);
  tipEl.innerHTML =
    `<strong>${esc(d.title)}</strong>` +
    `<span>${esc(d.authors.slice(0, 3).join(", "))}${d.authors.length > 3 ? " et al." : ""} · ${d.year ?? ""} · ${d.citationCount} cites</span>` +
    (sum ? `<p class="gt-sum">${d.tldr ? "<b>TL;DR.</b> " : ""}${sum}</p>` : "");
  tipEl.style.display = "block";
  const p = pos.get(d.id);
  const t = zoomTransform();
  if (p) { tipEl.style.left = `${t.applyX(p.x) + 12}px`; tipEl.style.top = `${t.applyY(p.y) + 12}px`; }
}
function hideTip() { if (tipEl) tipEl.style.display = "none"; }
// d3 stores the current transform on the element zoom() was call()ed on — the svg, not g
// (g only carries it as a transform *attribute*). Reading g.__zoom returned identity forever,
// which drifted the hover tooltip off its node whenever the graph was zoomed or panned.
function zoomTransform(): any { return (svg.node() as any).__zoom || zoomIdentity; }

// Clicking a paper opens a persistent detail panel (à la alex-loftus.com/networks) — not a
// raw link. Shows title/authors/year/citations + a lazily-fetched TL;DR/abstract, and a link
// out. Stays until you close it (✕) or click another paper.
let detailEl: HTMLElement | null = null;
function showDetail(d: PaperNode) {
  if (!detailEl) {
    detailEl = document.createElement("div");
    detailEl.className = "paper-detail";
    el("papers-graph").appendChild(detailEl);
  }
  // label the source link by its real destination (arXiv id, else the link's host)
  let host = "source";
  try { host = new URL(d.url).hostname.replace(/^www\./, ""); } catch { /* keep default */ }
  const idLabel = d.arxiv ? `arXiv:${d.arxiv}` : host;
  let summary = "<i>No summary available.</i>";
  if (d.tldr) summary = `<b>TL;DR.</b> ${esc(d.tldr)}` + (d.abstract ? `<span class="pd-full">${esc(d.abstract)}</span>` : "");
  else if (d.abstract) summary = esc(d.abstract);
  detailEl.innerHTML =
    `<span class="pd-close" title="close">✕</span>` +
    `<a class="pd-title" href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a>` +
    `<div class="pd-meta">${esc(d.authors.join(", "))}${d.authors.length >= 6 ? " et al." : ""}</div>` +
    `<div class="pd-stats">${d.year ?? ""} · ${d.citationCount} citations · ` +
      `<a href="${esc(d.url)}" target="_blank" rel="noopener">${idLabel} ↗</a></div>` +
    explainerCard(d) +
    `<div class="pd-abstract">${summary}</div>`;
  detailEl.style.display = "block";
  (detailEl.querySelector(".pd-close") as HTMLElement).onclick = () => { hideDetail(); clearFocus(); };
}

// The one thing in the panel we most want you to notice: a link to our explainer of this
// paper, when one exists. Styled to pop (accent card, gentle entrance) — see papers.astro.
function explainerCard(d: PaperNode): string {
  const ex = explainers[d.id];
  if (!ex) return "";
  return `<a class="pd-explainer" href="${ex.url}" target="_blank" rel="noopener">` +
    `<span class="pdx-lab">✦ our explainer</span>` +
    `<span class="pdx-title">${esc(ex.title)}</span>` +
    `<span class="pdx-go">read it →</span></a>`;
}
function hideDetail() { if (detailEl) detailEl.style.display = "none"; }

// ── edge hover tooltip ────────────────────────────────────────────────────────────
// Hovering an edge (via the transparent wide hit-line) explains what relates the two
// papers. Solid read↔read edges: both titles, the relevance weight, the breakdown, and
// the actual shared references (titles lazily fetched). Dashed edges: candidate-specific.
let edgeTipEl: HTMLElement | null = null;
let openRefs: string[] = []; // shared-ref ids the open tooltip is showing (for async refresh)
const refTitle = new Map<string, string>(); // ref id → title, lazily fetched + cached

function edgeTip(): HTMLElement {
  if (!edgeTipEl) { edgeTipEl = document.createElement("div"); edgeTipEl.className = "edge-tip"; el("papers-graph").appendChild(edgeTipEl); }
  return edgeTipEl;
}
function positionEdgeTip(tip: HTMLElement, ev: MouseEvent) {
  const host = el("papers-graph").getBoundingClientRect();
  tip.style.left = `${Math.max(6, Math.min(ev.clientX - host.left + 14, host.width - 332))}px`;
  tip.style.top = `${Math.max(6, Math.min(ev.clientY - host.top + 14, host.height - 80))}px`;
}
function dotv(a: Vec, b: Vec) { if (!a || !b) return 0; let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; }

function showEdgeTip(d: Edge, ev: MouseEvent) {
  const a = d.source as any, b = d.target as any; // forceLink resolved these to node objects
  const tip = edgeTip();
  if (d.ghost) {
    const cand = a.ghost ? a : b, readEnd = a.ghost ? b : a;
    // report the candidate's *rank*, not a percentage — with the citation nudge the blended
    // score can top 1.0, so "score %" both overflowed and hid the top pick's standing
    const k = candidates.findIndex((x) => x.id === cand.id);
    const relText = k >= 0 && cand.vnScore != null && cand.vnScore >= 0
      ? `nominated #${k + 1} of ${candidates.length}` : "recommended by Semantic Scholar";
    openRefs = [];
    tip.innerHTML =
      `<div class="et-pair"><b>${esc(shortTitle(cand))}</b></div>` +
      `<div class="et-sub">nominated · nearest read paper <b>${esc(shortTitle(readEnd))}</b></div>` +
      `<div class="et-w">${relText}</div>`;
  } else {
    const cos = Math.max(0, dotv(a.vec, b.vec));
    const bset = new Set<string>(b.refs || []);
    const shared: string[] = (a.refs || []).filter((id: string) => bset.has(id));
    const direct = (a.refs || []).includes(b.id) || (b.refs || []).includes(a.id);
    openRefs = shared;
    tip.innerHTML =
      `<div class="et-pair"><b>${esc(shortTitle(a))}</b> ↔ <b>${esc(shortTitle(b))}</b></div>` +
      `<div class="et-w">relevance ${d.w.toFixed(2)}</div>` +
      `<div class="et-sub">cosine ${cos.toFixed(2)} · ${shared.length} shared reference${shared.length === 1 ? "" : "s"} · ${direct ? "one cites the other" : "no direct citation"}</div>` +
      (shared.length ? `<div class="et-refs">${renderSharedRefs(shared)}</div>` : "");
    if (shared.length) ensureRefTitles(shared);
  }
  tip.style.display = "block";
  positionEdgeTip(tip, ev);
  highlightEdge(d);
}
function hideEdgeTip() {
  if (edgeTipEl) edgeTipEl.style.display = "none";
  openRefs = [];
  linkG.selectAll<SVGLineElement, Edge>("line") // restore default link styling
    .attr("stroke", (l: Edge) => (l.ghost ? GHOST : "#cdbfae"))
    .attr("stroke-opacity", (l: Edge) => (l.ghost ? 0.4 : 0.55));
}
function highlightEdge(d: Edge) {
  const k = keyOf(d);
  linkG.selectAll<SVGLineElement, Edge>("line")
    .attr("stroke", (l: Edge) => (keyOf(l) === k ? ACCENT : l.ghost ? GHOST : "#cdbfae"))
    .attr("stroke-opacity", (l: Edge) => (keyOf(l) === k ? 0.95 : l.ghost ? 0.16 : 0.28));
}
function renderSharedRefs(ids: string[]): string {
  const items = ids.slice(0, 8).map((id) => `<li>${esc(refTitle.get(id) || "…")}</li>`).join("");
  const more = ids.length > 8 ? `<li class="et-more">+${ids.length - 8} more</li>` : "";
  return `<div class="et-refs-h">shared references</div><ul class="et-reflist">${items}${more}</ul>`;
}
async function ensureRefTitles(ids: string[]) {
  const missing = ids.slice(0, 8).filter((id) => !refTitle.has(id));
  if (missing.length) {
    try {
      const d = await s2({ ids: missing }); // through the proxy (retries on 429) → reliable in prod
      if (Array.isArray(d)) for (const p of d) if (p && p.paperId) refTitle.set(p.paperId, p.title || "(untitled)");
    } catch { /* leave as unavailable */ }
    for (const id of missing) if (!refTitle.has(id)) refTitle.set(id, "(title unavailable)");
  }
  // refresh only if the tooltip is still showing this very edge's references
  if (edgeTipEl && openRefs === ids && edgeTipEl.style.display === "block") {
    const refsDiv = edgeTipEl.querySelector(".et-refs") as HTMLElement | null;
    if (refsDiv) refsDiv.innerHTML = renderSharedRefs(ids);
  }
}

function mkWidthScale(ld: Edge[]) {
  const ws = ld.map((d) => d.w);
  const lo = d3min(ws) ?? 0, hi = d3max(ws) ?? 1;
  return scaleSqrt().domain([lo, hi]).range([0.6, 4.2]).clamp(true);
}
function keyOf(d: Edge) { const s = typeof d.source === "object" ? d.source.id : d.source; const t = typeof d.target === "object" ? d.target.id : d.target; return s < t ? `${s}|${t}` : `${t}|${s}`; }
function shortTitle(d: PaperNode) { const t = d.title.split(":")[0]; return t.length > 30 ? t.slice(0, 28) + "…" : t; }
function short(t: string) { return t.length > 34 ? t.slice(0, 32) + "…" : t; }
function setStatus(s: string) { const e = document.getElementById("graph-status"); if (e) e.textContent = s; }
function esc(s: string) { return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!)); }
function mix(a: string, b: string, t: number) {
  t = Math.max(0, Math.min(1, t));
  const pa = hex(a), pb = hex(b);
  return `rgb(${Math.round(pa[0] + (pb[0] - pa[0]) * t)},${Math.round(pa[1] + (pb[1] - pa[1]) * t)},${Math.round(pa[2] + (pb[2] - pa[2]) * t)})`;
}
function hex(h: string): [number, number, number] {
  let n = h.replace("#", "");
  if (n.length === 3) n = n[0] + n[0] + n[1] + n[1] + n[2] + n[2]; // #a00 → aa0000
  return [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
}
function normalizeId(s: string): string {
  if (!s) return "";
  const arx = s.match(/arxiv\.org\/abs\/([0-9.]+)/i) || s.match(/^([0-9]{4}\.[0-9]{4,5})$/);
  if (arx) return `ARXIV:${arx[1]}`;
  if (/^10\.\d{4,}/.test(s)) return `DOI:${s}`;
  const doi = s.match(/doi\.org\/(10\.[^\s]+)/i); if (doi) return `DOI:${doi[1]}`;
  if (/^[0-9a-f]{40}$/i.test(s)) return s; // raw S2 id
  return s; // let S2 try to resolve (e.g. "ARXIV:..", "CorpusId:..")
}
