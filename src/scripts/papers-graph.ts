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

// ── module state ────────────────────────────────────────────────────────────────
let baked: PaperNode[] = [];          // shipped canonical set (public/papers.json)
let read: PaperNode[] = [];           // baked ∪ your local adds (solid nodes)
let candidates: PaperNode[] = [];     // ranked unread frontier (all of it)
let revealCount = 0;                  // how many candidates the slider reveals
let frontierLoaded = false, frontierBusy = false;
let editing = false;                  // edit mode: clicking a read node removes it
const pos = new Map<string, { x: number; y: number }>(); // persist positions across renders

let sim: any, svg: any, g: any, linkG: any, nodeG: any, labelG: any, zoomB: any;
let W = 800, H = 560;
const el = (id: string) => document.getElementById(id)!;

// ── boot ────────────────────────────────────────────────────────────────────────
export async function initPapersGraph() {
  const host = el("papers-graph");
  baked = await fetch("/papers.json").then((r) => r.json()).then((d) => d.nodes || []).catch(() => []);
  const removed = loadRemoved();
  read = mergeAdds(baked.filter((n) => !removed.has(n.id)), loadAdds());
  await new Promise(requestAnimationFrame); // let the layout settle so the box has real dimensions
  const rect = host.getBoundingClientRect();
  W = Math.round(rect.width) || 800; H = Math.round(rect.height) || 560;
  buildSvg(host);
  rebuildEdges();
  firstRender();
  wireControls();
  renderReadList();
  setStatus(`${read.length} papers · drag the slider to nominate more`);
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

async function loadFrontier() {
  if (frontierBusy || frontierLoaded || !read.length) return;
  frontierBusy = true; setStatus("finding papers you should read…");
  try {
    const readIds = read.map((n) => n.id);
    const rec = await s2({ positivePaperIds: readIds, limit: 80 });
    const recIds: string[] = (rec.recommendedPapers || [])
      .map((p: any) => p && p.paperId).filter(Boolean)
      .filter((id: string) => !read.some((r) => r.id === id));
    let raw: any[] = [];
    if (recIds.length) {
      const b = await s2({ ids: recIds.slice(0, 100) });
      raw = Array.isArray(b) ? b : [];
    }
    const cand = raw.map(toNode).filter((n: PaperNode | null) => n && n.vec) as PaperNode[];
    candidates = vnRank(cand, read) as PaperNode[];
    candidates.forEach((c) => (c.ghost = true));
    frontierLoaded = true;
    revealCount = Math.max(revealCount, Math.min(6, candidates.length));
    (el("discover") as HTMLInputElement).disabled = false;
  } catch (e) {
    setStatus("couldn't reach Semantic Scholar — try again");
  } finally {
    frontierBusy = false;
    if (frontierLoaded) setStatus(`${read.length} in your set · ${candidates.length} unread papers nominated`);
    syncReveal(); renderReadList();
  }
}

// ── graph assembly ────────────────────────────────────────────────────────────--
function revealed(): PaperNode[] { return candidates.slice(0, revealCount); }
function nodes(): PaperNode[] { return read.concat(revealed()); }

let readEdges: Edge[] = [];
function rebuildEdges() { rebuildRadius(); readEdges = buildEdges(read, { k: 6 }) as Edge[]; }
function links(): Edge[] {
  // edges among read papers + a tether from each ghost to its nearest read paper
  const ghostLinks: Edge[] = revealed().map((c) => ({ source: c.nearestId, target: c.id, w: Math.max(0, c.vnScore || 0), ghost: true }));
  return readEdges.concat(ghostLinks);
}

// ── svg + forces ────────────────────────────────────────────────────────────────
function buildSvg(host: HTMLElement) {
  select(host).selectAll("*").remove();
  svg = select(host).append("svg").attr("width", "100%").attr("height", "100%").attr("viewBox", `0 0 ${W} ${H}`);
  g = svg.append("g");
  linkG = g.append("g").attr("fill", "none");
  nodeG = g.append("g");
  labelG = g.append("g");

  zoomB = zoom().scaleExtent([0.2, 5]).on("zoom", (e: any) => g.attr("transform", e.transform));
  svg.call(zoomB).on("dblclick.zoom", null);
  svg.on("dblclick", () => fit(400));

  sim = forceSimulation<PaperNode>([])
    .force("link", forceLink<PaperNode, Edge>([]).id((d: any) => d.id).distance((l: Edge) => 50 + 26 / Math.sqrt((l.w || 0.1) + 0.05)).strength((l: Edge) => (l.ghost ? 0.25 : 0.55)))
    .force("charge", forceManyBody().strength(-260))
    .force("collide", forceCollide().radius((d: any) => r(d) + 6))
    .force("center", forceCenter(W / 2, H / 2))
    .force("x", forceX(W / 2).strength(0.03))
    .force("y", forceY(H / 2).strength(0.03))
    .on("tick", tick);
}

// bounded sqrt radius (citation counts span 3+ orders of magnitude — an unbounded
// sqrt makes a 2700-cite paper a 90px blob; clamp to a sane range like the original)
const radiusScale = scaleSqrt().domain([0, 1]).range([7, 22]).clamp(true);
function rebuildRadius() { radiusScale.domain([0, (d3max(read, (n) => n.citationCount) as number) || 1]); }
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

  const nodeSel = nodeG.selectAll<SVGGElement, PaperNode>("g.node")
    .data(nd, (d: any) => d.id)
    .join((enter: any) => {
      const gg = enter.append("g").attr("class", "node").style("cursor", "pointer");
      gg.append("circle");
      gg.call(drag<SVGGElement, PaperNode>().on("start", dStart).on("drag", dMove).on("end", dEnd) as any);
      gg.on("mouseenter", (_e: any, d: PaperNode) => heat(d))
        .on("mouseleave", () => unheat())
        .on("click", (_e: any, d: PaperNode) => {
          if (d.ghost) promote(d);
          else if (editing) removePaper(d.id);
          else window.open(d.url, "_blank");
        });
      return gg;
    });
  nodeSel.select("circle")
    .attr("r", r)
    .attr("fill", (d: PaperNode) => (d.ghost ? BG : INK))
    // in edit mode, read nodes get a red dashed ring — click to remove
    .attr("stroke", (d: PaperNode) => (d.ghost ? GHOST : editing ? ACCENT : BG))
    .attr("stroke-width", (d: PaperNode) => (d.ghost ? 1.3 : editing ? 1.8 : 1.5))
    .attr("stroke-dasharray", (d: PaperNode) => (d.ghost ? "2.5 2.5" : editing ? "2 2" : null));

  labelG.selectAll<SVGTextElement, PaperNode>("text")
    .data(nd.filter((n) => !n.ghost), (d: any) => d.id)
    .join("text")
    .attr("class", "node-label")
    .attr("text-anchor", "middle")
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
  slider.disabled = true;
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
  const b = await s2({ ids: [id] });
  const node = (Array.isArray(b) ? b.map(toNode).filter(Boolean)[0] : null) as PaperNode | null;
  if (!node) { setStatus(`couldn't find "${input.value}"`); return; }
  if (read.some((n) => n.id === node.id)) { setStatus("already in your graph"); input.value = ""; return; }
  addNode(node); input.value = "";
}

function promote(c: PaperNode) {
  candidates = candidates.filter((x) => x.id !== c.id);
  const clean = { ...c }; delete clean.ghost; delete clean.vnScore; delete clean.nearestId;
  addNode(clean);
}

function addNode(node: PaperNode) {
  read.push(node);
  const rm = loadRemoved(); if (rm.delete(node.id)) saveRemoved(rm); // un-remove if re-adding a removed paper
  saveAdds(localAdds());
  rebuildEdges();
  frontierLoaded = false; candidates = []; // your interests changed → re-nominate
  (el("discover") as HTMLInputElement).disabled = false;
  render(0.7); renderReadList();
  setStatus(`added · ${node.title.slice(0, 48)}`);
  loadFrontier();
}

// Remove a paper from your set. Removing a baked (shipped) paper is remembered in the
// REMOVED set so it stays gone across reloads; removing one you added just drops it from
// the persisted adds. Either way the change is permanent (per browser) — there's no reset.
function removePaper(id: string) {
  read = read.filter((n) => n.id !== id);
  pos.delete(id);
  if (baked.some((n) => n.id === id)) { const rm = loadRemoved(); rm.add(id); saveRemoved(rm); }
  saveAdds(localAdds());
  rebuildEdges();
  frontierLoaded = false; candidates = []; // your interests changed → re-nominate
  render(0.6); renderReadList();
  setStatus(read.length ? `removed · ${read.length} in your set` : "graph empty — add a paper to begin");
  if (read.length) loadFrontier();
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
  if (!frontierLoaded) { host.innerHTML = `<p class="rl-empty">Drag the discovery slider to nominate unread papers ranked by relevance to your set.</p>`; return; }
  const top = revealed();
  if (!top.length) { host.innerHTML = `<p class="rl-empty">No nominations yet — slide right.</p>`; return; }
  const lo = top[top.length - 1].vnScore ?? 0, hi = top[0].vnScore ?? 1, span = (hi - lo) || 1;
  host.innerHTML = top.map((c, i) => {
    const rel = Math.round(((c.vnScore! - lo) / span) * 100);
    const near = read.find((n) => n.id === c.nearestId);
    return `<div class="rl-row">
      <span class="rl-rank">${i + 1}</span>
      <span class="rl-main"><a href="${c.url}" target="_blank" rel="noopener">${esc(c.title)}</a>
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
  const dx = x1 - x0 || 1, dy = y1 - y0 || 1, pad = 70;
  const s = Math.min(3, 0.92 / Math.max(dx / (W - pad), dy / (H - pad)));
  const tx = W / 2 - s * (x0 + x1) / 2, ty = H / 2 - s * (y0 + y1) / 2;
  svg.transition().duration(dur).call(zoomB.transform, zoomIdentity.translate(tx, ty).scale(s));
}

let tipEl: HTMLElement | null = null;
function showTip(d: PaperNode) {
  if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "graph-tip"; el("papers-graph").appendChild(tipEl); }
  tipEl.innerHTML = `<strong>${esc(d.title)}</strong><span>${esc(d.authors.slice(0, 3).join(", "))}${d.authors.length > 3 ? " et al." : ""} · ${d.year ?? ""} · ${d.citationCount} cites</span>`;
  tipEl.style.display = "block";
  const p = pos.get(d.id);
  const t = zoomTransform();
  if (p) { tipEl.style.left = `${t.applyX(p.x) + 12}px`; tipEl.style.top = `${t.applyY(p.y) + 12}px`; }
}
function hideTip() { if (tipEl) tipEl.style.display = "none"; }
function zoomTransform(): any { const t = (g.node() as any).__zoom || zoomIdentity; return t; }

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
