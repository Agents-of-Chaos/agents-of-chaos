// Canvas annotations for the active question: marks (route ribbons + ghost
// predicted edges) in host.marksLayer() UNDER the nodes, and ≤3 text callouts
// with leader lines in host.calloutsLayer() ABOVE them. Everything lives
// inside the zoomed root, so pan/zoom is free; sizes counter-scale by 1/k.
// Callouts reserve their screen boxes via host.reserveLabelBoxes so the map's
// label declutter flows around them and the anchors' own labels hide (the
// callout carries the name — S3 spike showed double-labeling without this).

import type { QEdge, QMarks, QuestionHost, QuestionResult } from "./types";

/** Edge-provenance context for route ribbons: the engine's typed adjacency
 *  plus the graph kind (affiliation hops are source-backed on funding but
 *  carry no `verified` field — the engine coerces missing to false). */
export interface PathProvenance {
  adjT: Map<string, QEdge[]>;
  graph: "companies" | "funding";
}

const SVG_NS = "http://www.w3.org/2000/svg";
const BG = "#fffff8"; // page cream (global.css --bg) — the text halo
const INK = "#111";
const MUTED = "#666";
const PATH_STROKE = "#a00"; // site accent — route ribbons
const GHOST_STROKE = "#b4602f"; // distinct hue: predicted, not observed
const LEADER = "#9a958c";
const NAME_PX = 12.5; // on-screen font sizes (divided by k in sim space)
const FACT_PX = 11;

// quadrants tried in order: NE, NW, SE, SW (screen y grows downward)
const QUADS: readonly [number, number][] = [
  [1, -1],
  [-1, -1],
  [1, 1],
  [-1, 1],
];

interface Mark {
  el: SVGElement;
  kind: "path" | "ghost" | "hull";
  ids: string[];
  /** path segments only: an untrusted hop (no verified edge) draws dashed
   *  "2 3" — the base map's inferred-edge style */
  dashed?: boolean;
}

/* ---------- route-hop provenance (pure — node --test imports this) ---------- */

/** trust[i] ⇔ the hop path[i]→path[i+1] rides at least one verified edge, OR
 *  (funding only) an affiliation edge — affiliations are source-backed but
 *  carry no `verified` field, which the engine coerces to false. A pair with
 *  no edge at all in adjT is untrusted (the route claims a tie the adjacency
 *  cannot show). A pair can carry up to three parallel typed edges with mixed
 *  flags, so the check aggregates: any trustworthy edge trusts the hop. */
export function pathHopTrusted(
  path: string[],
  adjT: Map<string, QEdge[]>,
  graph: "companies" | "funding",
): boolean[] {
  const trust: boolean[] = [];
  for (let i = 0; i + 1 < path.length; i++) {
    const next = path[i + 1];
    trust.push(
      (adjT.get(path[i]) ?? []).some(
        (e) => e.to === next && (e.verified || (graph === "funding" && e.type === "affiliation")),
      ),
    );
  }
  return trust;
}

/** Do any of these route ribbons cross an untrusted hop? (marksNote trigger) */
export function pathsHaveUntrustedHop(
  paths: string[][] | undefined,
  prov: PathProvenance | undefined,
): boolean {
  if (!paths?.length || !prov) return false;
  return paths.some((p) => pathHopTrusted(p, prov.adjT, prov.graph).includes(false));
}

/** Angular sort around the centroid — same treatment as the thumbnails
 *  (strip.ts hullPoints): the cheap hull, right for blob-shaped groups. */
function hullOrder(pts: { x: number; y: number }[]): { x: number; y: number }[] {
  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
  return [...pts].sort((a, b) => Math.atan2(a.y - cy, a.x - cx) - Math.atan2(b.y - cy, b.x - cx));
}

interface CalloutEl {
  id: string;
  g: SVGGElement;
  leader: SVGLineElement;
  text: SVGTextElement;
  nameSpan: SVGTSpanElement;
  factSpan: SVGTSpanElement;
  quad: number;
  pxW: number; // screen-space text box, constant across zoom
  pxH: number;
  box: number[] | null; // current screen box [x0,y0,x1,y1]
}

interface AState {
  marks: Mark[];
  callouts: CalloutEl[];
}

const states = new WeakMap<QuestionHost, AState>();

function stateFor(host: QuestionHost): AState {
  let s = states.get(host);
  if (!s) {
    s = { marks: [], callouts: [] };
    states.set(host, s);
    // hooks register once per host; they read current state (no unregister API)
    host.onTick(() => position(host));
    host.onZoom(() => position(host));
    host.reserveLabelBoxes(() => {
      const cur = states.get(host);
      return {
        boxes: cur ? cur.callouts.flatMap((c) => (c.box ? [c.box] : [])) : [],
        hideIds: new Set(cur ? cur.callouts.map((c) => c.id) : []),
      };
    });
  }
  return s;
}

function removeAll(s: AState): void {
  for (const m of s.marks) m.el.remove();
  for (const c of s.callouts) c.g.remove();
  s.marks = [];
  s.callouts = [];
}

/* ---------- geometry ---------- */

function calloutAnchor(
  host: QuestionHost,
  c: CalloutEl,
  quad: number,
  k: number,
): { tx: number; nameY: number; nr: number } | null {
  const p = host.posOf(c.id);
  if (!p) return null;
  const [qx, qy] = QUADS[quad];
  const nr = host.radiusOf(c.id) * 1.25;
  const gap = nr + 9 / k;
  const tx = p.x + qx * gap;
  const nameY = qy < 0 ? p.y - gap - (FACT_PX + 3) / k : p.y + gap + NAME_PX / k;
  return { tx, nameY, nr };
}

function screenBox(c: CalloutEl, quad: number, tx: number, nameY: number, t: { k: number; x: number; y: number }): number[] {
  const qx = QUADS[quad][0];
  const sx = tx * t.k + t.x;
  const top = nameY * t.k + t.y - NAME_PX; // name ascent above its baseline
  const P = 2;
  return qx > 0
    ? [sx - P, top - P, sx + c.pxW + P, top + c.pxH + P]
    : [sx - c.pxW - P, top - P, sx + P, top + c.pxH + P];
}

const overlapArea = (a: number[], b: number[]): number =>
  Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) *
  Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));

/* ---------- per-frame positioning (tick + zoom) ---------- */

function position(host: QuestionHost): void {
  const s = states.get(host);
  if (!s || (!s.marks.length && !s.callouts.length)) return;
  const t = host.zoomTransform();
  const k = Math.max(1e-6, t.k);

  for (const m of s.marks) {
    m.el.setAttribute("stroke-width", String((m.kind === "hull" ? 1.5 : 1.6) / k));
    if (m.kind === "path") {
      const pts = m.ids
        .map((id) => host.posOf(id))
        .filter((p): p is { x: number; y: number } => !!p)
        .map((p) => `${p.x},${p.y}`)
        .join(" ");
      m.el.setAttribute("points", pts);
      // untrusted hop: the base map's inferred style ("2 3"), counter-scaled
      if (m.dashed) m.el.setAttribute("stroke-dasharray", `${2 / k} ${3 / k}`);
    } else if (m.kind === "hull") {
      // hull polygons follow the sim: recompute the angular order every frame
      const pts = m.ids
        .map((id) => host.posOf(id))
        .filter((p): p is { x: number; y: number } => !!p);
      if (pts.length < 3) {
        m.el.setAttribute("display", "none");
        continue;
      }
      m.el.removeAttribute("display");
      m.el.setAttribute(
        "points",
        hullOrder(pts)
          .map((p) => `${p.x},${p.y}`)
          .join(" "),
      );
      m.el.setAttribute("stroke-dasharray", `${6 / k} ${4 / k}`);
    } else {
      const a = host.posOf(m.ids[0]);
      const b = host.posOf(m.ids[1]);
      if (!a || !b) {
        m.el.setAttribute("display", "none");
        continue;
      }
      m.el.removeAttribute("display");
      m.el.setAttribute("x1", String(a.x));
      m.el.setAttribute("y1", String(a.y));
      m.el.setAttribute("x2", String(b.x));
      m.el.setAttribute("y2", String(b.y));
      m.el.setAttribute("stroke-dasharray", `${1 / k} ${5 / k}`);
    }
  }

  for (const c of s.callouts) {
    const a = calloutAnchor(host, c, c.quad, k);
    const p = host.posOf(c.id);
    if (!a || !p) {
      c.g.setAttribute("display", "none");
      c.box = null;
      continue;
    }
    c.g.removeAttribute("display");
    const [qx, qy] = QUADS[c.quad];
    c.text.setAttribute("x", String(a.tx));
    c.text.setAttribute("y", String(a.nameY));
    c.text.setAttribute("text-anchor", qx > 0 ? "start" : "end");
    c.text.setAttribute("font-size", String(NAME_PX / k));
    c.text.setAttribute("stroke-width", String(3.2 / k));
    c.nameSpan.setAttribute("x", String(a.tx));
    c.factSpan.setAttribute("x", String(a.tx));
    c.factSpan.setAttribute("dy", String((FACT_PX + 3) / k));
    c.factSpan.setAttribute("font-size", String(FACT_PX / k));
    c.leader.setAttribute("x1", String(p.x + qx * a.nr * 0.85));
    c.leader.setAttribute("y1", String(p.y + qy * a.nr * 0.85));
    c.leader.setAttribute("x2", String(a.tx - qx * (2 / k)));
    c.leader.setAttribute("y2", String(a.nameY - 4 / k));
    c.leader.setAttribute("stroke-width", String(1 / k));
    c.box = screenBox(c, c.quad, a.tx, a.nameY, t);
  }
}

/* ---------- public API ---------- */

export function renderAnnotations(
  host: QuestionHost,
  result: QuestionResult,
  prov?: PathProvenance,
): void {
  const s = stateFor(host);
  removeAll(s); // idempotent: re-render replaces the previous question's marks
  const marksG = host.marksLayer();
  const calloutsG = host.calloutsLayer();

  // route ribbons draw per-hop (endpoints shared, same stroke/width) so an
  // untrusted hop — no verified edge under it — can carry the base map's
  // dashed inferred style while the rest of the route stays solid
  for (const path of result.marks.paths ?? []) {
    if (path.length < 2) continue;
    const trust = prov ? pathHopTrusted(path, prov.adjT, prov.graph) : null;
    for (let i = 0; i + 1 < path.length; i++) {
      const el = document.createElementNS(SVG_NS, "polyline");
      el.setAttribute("fill", "none");
      el.setAttribute("stroke", PATH_STROKE);
      el.setAttribute("stroke-opacity", "0.8");
      el.setAttribute("stroke-linejoin", "round");
      el.setAttribute("stroke-linecap", "round");
      el.setAttribute("pointer-events", "none");
      marksG.appendChild(el);
      s.marks.push({ el, kind: "path", ids: [path[i], path[i + 1]], dashed: trust ? !trust[i] : false });
    }
  }
  for (const [a, b] of result.marks.edges ?? []) {
    const el = document.createElementNS(SVG_NS, "line");
    el.setAttribute("stroke", GHOST_STROKE);
    el.setAttribute("stroke-opacity", "0.75");
    el.setAttribute("stroke-linecap", "round"); // dotted "1 5" ≠ the map's dashed inferred "2 3"
    el.setAttribute("pointer-events", "none");
    marksG.appendChild(el);
    s.marks.push({ el, kind: "ghost", ids: [a, b] });
  }
  // block hulls — same treatment as the thumbnails, scaled to the map:
  // tinted dashed polygon per group; the gap BETWEEN hulls is the point
  for (const group of result.marks.hull ?? []) {
    if (group.length < 3) continue;
    const el = document.createElementNS(SVG_NS, "polygon");
    el.setAttribute("fill", PATH_STROKE);
    el.setAttribute("fill-opacity", "0.06");
    el.setAttribute("stroke", PATH_STROKE);
    el.setAttribute("stroke-opacity", "0.6");
    el.setAttribute("stroke-linejoin", "round");
    el.setAttribute("pointer-events", "none");
    marksG.appendChild(el);
    s.marks.push({ el, kind: "hull", ids: group });
  }

  const t = host.zoomTransform();
  const k = Math.max(1e-6, t.k);
  for (const co of result.callouts.slice(0, 3)) {
    if (!host.posOf(co.id)) continue; // anchor is force-shown; missing = not on the map at all
    const g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("pointer-events", "none");
    const leader = document.createElementNS(SVG_NS, "line");
    leader.setAttribute("stroke", LEADER);
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("font-family", "Georgia, serif");
    text.setAttribute("paint-order", "stroke");
    text.setAttribute("stroke", BG);
    text.setAttribute("stroke-linejoin", "round");
    const nameSpan = document.createElementNS(SVG_NS, "tspan");
    nameSpan.setAttribute("font-weight", "700");
    nameSpan.setAttribute("fill", INK);
    nameSpan.textContent = host.labelOf(co.id);
    const factSpan = document.createElementNS(SVG_NS, "tspan");
    factSpan.setAttribute("fill", MUTED);
    factSpan.textContent = co.text;
    text.append(nameSpan, factSpan);
    g.append(leader, text);
    calloutsG.appendChild(g);

    const c: CalloutEl = { id: co.id, g, leader, text, nameSpan, factSpan, quad: 0, pxW: 0, pxH: 0, box: null };
    // measure once at the current zoom: bbox is in sim units → px = sim × k
    text.setAttribute("font-size", String(NAME_PX / k));
    factSpan.setAttribute("font-size", String(FACT_PX / k));
    factSpan.setAttribute("dy", String((FACT_PX + 3) / k));
    factSpan.setAttribute("x", "0");
    const bb = text.getBBox();
    c.pxW = bb.width * k;
    c.pxH = bb.height * k;
    s.callouts.push(c);
  }

  // greedy quadrant placement: first free quadrant, else least overlap
  const placed: number[][] = [];
  for (const c of s.callouts) {
    let bestQuad = 0;
    let bestOverlap = Infinity;
    for (let q = 0; q < QUADS.length; q++) {
      const a = calloutAnchor(host, c, q, k);
      if (!a) continue;
      const box = screenBox(c, q, a.tx, a.nameY, t);
      const ov = placed.reduce((sum, p) => sum + overlapArea(box, p), 0);
      if (ov < bestOverlap) {
        bestOverlap = ov;
        bestQuad = q;
      }
      if (ov === 0) break;
    }
    c.quad = bestQuad;
    const a = calloutAnchor(host, c, bestQuad, k);
    if (a) placed.push(screenBox(c, bestQuad, a.tx, a.nameY, t));
  }

  position(host);
}

export function clearAnnotations(host: QuestionHost): void {
  const s = states.get(host);
  if (!s) return;
  removeAll(s);
}

/** Answer-bar disclaimers. Two triggers: (1) ghost edges on the map —
 *  marks.edges are ALWAYS hypothetical (types.ts contract), never observed
 *  ties; (2) any rendered route hop is untrusted — a dashed hop rides an
 *  inferred edge, not a verified one. Returns ready-to-inject static HTML
 *  ("" when there is nothing to disclaim). */
export function marksNote(marks: QMarks, prov?: PathProvenance): string {
  const notes: string[] = [];
  if (marks.edges?.length)
    notes.push(`<span class="q-marks-note">⋯ proposed / predicted — not observed ties</span>`);
  if (pathsHaveUntrustedHop(marks.paths, prov))
    notes.push(
      `<span class="q-marks-note">⋯ a dashed hop is an inferred tie — not yet verified</span>`,
    );
  return notes.join("");
}
