// The question strip: wires the SSR skeleton from QuestionStrip.astro
// (.net-q-item buttons + .net-q-thumb canvases) and draws each question's
// thumbnail — the big map in miniature, from a QuestionResult + the payload's
// baked layout (or ASE coords for morph questions). Hover previews the
// question's lit set on the map; click toggles; the active question collapses
// the strip to a one-line breadcrumb.

import type { QuestionDef, QuestionHost, QuestionPayload, QuestionResult } from "./types";

const THUMB_W = 96; // CSS px (backing store is dpr-scaled)
const THUMB_H = 64;
const PAD = 5;
const FADE = "#e6e2da";
const LIT = "#e07a5f";
const ANCHOR = "#c8442c";
const ACCENT = "#a00";
const GHOST = "#b4602f"; // predicted-not-observed hue — matches annotate.ts

export interface StripCallbacks {
  onToggle(slug: string): void;
  preview(ids: Set<string> | null): void;
}

export interface StripHandle {
  setActive(slug: string | null): void;
  drawAll(computeResult: (def: QuestionDef) => QuestionResult, payload: QuestionPayload): void;
  setStale(on: boolean): void;
}

// P2 signature-mark hints (S1 rule: every thumbnail leads with a MARK —
// recolor alone is illegible at 96×64). The bake may name the mark explicitly
// via thumb.mark; until that hint lands in questions-companies.json the def id
// implies it — keep in sync with experiments/analyses/prep_questions.py.
// (hull needs no hint: it draws whenever the result carries marks.hull.)
type ThumbMark = "hull" | "ellipse" | "annulus";
const DEF_THUMB_MARK: Record<string, ThumbMark> = {
  "rival-orbit": "ellipse",
  "core-crust": "annulus",
};

/** Angular sort around the centroid — the S1-spike hull: for blob-shaped
 *  groups this IS the convex hull; concave clouds get a star polygon, which
 *  still reads as "this region" at 96×64. */
function hullPoints(pts: [number, number][]): [number, number][] {
  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  return [...pts].sort(
    (a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx),
  );
}

function centroid(pts: [number, number][]): [number, number] {
  return [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ];
}

/** Percentile-fit scale: q02/q98 with clamping (S1 spike), into [r0, r1]. */
function fitScale(vals: number[], r0: number, r1: number): (v: number) => number {
  const sorted = [...vals].sort((a, b) => a - b);
  const n = sorted.length;
  const lo = sorted[Math.floor(0.02 * (n - 1))];
  const hi = sorted[Math.floor(0.98 * (n - 1))];
  if (!(hi > lo)) return () => (r0 + r1) / 2;
  return (v) => r0 + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * (r1 - r0);
}

export function initStrip(
  _host: QuestionHost,
  stripEl: HTMLElement,
  defs: QuestionDef[],
  callbacks: StripCallbacks,
): StripHandle {
  const items = new Map<string, { btn: HTMLButtonElement; canvas: HTMLCanvasElement | null }>();
  for (const btn of stripEl.querySelectorAll<HTMLButtonElement>(".net-q-item")) {
    const slug = btn.dataset.q;
    if (!slug) continue;
    items.set(slug, { btn, canvas: btn.querySelector<HTMLCanvasElement>(".net-q-thumb") });
  }

  // last-drawn lit ∪ anchor set per question — what hover previews on the map
  const lastSets = new Map<string, Set<string>>();
  let activeSlug: string | null = null;

  for (const [slug, { btn }] of items) {
    const over = () => callbacks.preview(lastSets.get(slug) ?? null);
    const out = () => callbacks.preview(null);
    btn.addEventListener("mouseenter", over);
    btn.addEventListener("mouseleave", out);
    btn.addEventListener("focus", over);
    btn.addEventListener("blur", out);
    btn.addEventListener("click", () => {
      callbacks.preview(null);
      callbacks.onToggle(slug);
    });
  }

  const crumb = stripEl.querySelector<HTMLElement>(".net-q-crumb");
  crumb?.querySelector<HTMLButtonElement>(".net-q-x")?.addEventListener("click", () => {
    if (activeSlug) callbacks.onToggle(activeSlug);
  });

  function draw(def: QuestionDef, res: QuestionResult, payload: QuestionPayload): void {
    const canvas = items.get(def.id)?.canvas;
    if (!canvas) return;
    const dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    if (canvas.width !== THUMB_W * dpr || canvas.height !== THUMB_H * dpr) {
      canvas.width = THUMB_W * dpr;
      canvas.height = THUMB_H * dpr;
    }
    const g = canvas.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, THUMB_W, THUMB_H);

    const { ids, x, y } = payload.nodes;
    const thumb = payload.questions[def.id]?.thumb;
    const ase = payload.assets.ase;
    const useAse = !!thumb?.useAse && !!ase;
    const xs = useAse ? ase!.all.map((row) => row[0]) : x;
    const ys = useAse ? ase!.all.map((row) => row[1]) : y;
    const fx = fitScale(xs, PAD, THUMB_W - PAD);
    const fy = fitScale(ys, PAD, THUMB_H - PAD);
    const at = new Map(ids.map((id, i) => [id, [fx(xs[i]), fy(ys[i])] as const]));

    const pointsOf = (nodeIds: string[]): [number, number][] =>
      nodeIds.flatMap((id) => {
        const p = at.get(id);
        return p ? [[p[0], p[1]] as [number, number]] : [];
      });

    // fade dots: every node, 1px
    g.fillStyle = FADE;
    for (const [px, py] of at.values()) g.fillRect(px - 0.5, py - 0.5, 1, 1);

    // marks: block hulls — one tinted dashed polygon per group; the gap
    // BETWEEN the hulls is the answer, so they sit under the dots
    if (res.marks.hull?.length) {
      g.strokeStyle = ACCENT;
      g.fillStyle = "rgba(170, 0, 0, 0.10)"; // ACCENT (#a00) at 0.10 alpha
      g.lineWidth = 1;
      g.setLineDash([3, 2]);
      for (const group of res.marks.hull) {
        const pts = pointsOf(group);
        if (pts.length < 3) continue;
        g.beginPath();
        hullPoints(pts).forEach(([px, py], i) => (i ? g.lineTo(px, py) : g.moveTo(px, py)));
        g.closePath();
        g.fill();
        g.stroke();
      }
      g.setLineDash([]);
    }

    // marks: route ribbons
    if (res.marks.paths?.length) {
      g.strokeStyle = ACCENT;
      g.lineWidth = 1.2;
      g.globalAlpha = 0.85;
      g.lineJoin = "round";
      for (const path of res.marks.paths) {
        g.beginPath();
        let started = false;
        for (const id of path) {
          const p = at.get(id);
          if (!p) continue;
          if (started) g.lineTo(p[0], p[1]);
          else {
            g.moveTo(p[0], p[1]);
            started = true;
          }
        }
        g.stroke();
      }
      g.globalAlpha = 1;
    }

    // marks: ghost predicted/proposed ties — dotted, distinct hue (S1 rule:
    // best-handshake / missing-ties lead with these; baked thumb.edges hint)
    if (res.marks.edges?.length) {
      g.strokeStyle = GHOST;
      g.lineWidth = 1;
      g.setLineDash([2, 2]);
      g.globalAlpha = 0.9;
      for (const [a, b] of res.marks.edges) {
        const pa = at.get(a);
        const pb = at.get(b);
        if (!pa || !pb) continue;
        g.beginPath();
        g.moveTo(pa[0], pa[1]);
        g.lineTo(pb[0], pb[1]);
        g.stroke();
      }
      g.setLineDash([]);
      g.globalAlpha = 1;
    }

    const dot = (id: string, r: number) => {
      const p = at.get(id);
      if (!p) return;
      g.beginPath();
      g.arc(p[0], p[1], r, 0, Math.PI * 2);
      g.fill();
    };
    g.fillStyle = LIT;
    for (const id of res.litIds) dot(id, 2.3);
    g.fillStyle = ANCHOR;
    for (const id of res.anchorIds) dot(id, 3.3);

    // rings around the anchors, for questions whose baked thumb carries rings
    if (thumb?.rings?.length) {
      g.strokeStyle = ANCHOR;
      g.lineWidth = 1;
      for (const id of res.anchorIds) {
        const p = at.get(id);
        if (!p) continue;
        g.beginPath();
        g.arc(p[0], p[1], 4.6, 0, Math.PI * 2);
        g.stroke();
      }
    }

    // P2 signature marks, drawn AFTER the dots so they never drown
    const markHint =
      (thumb as { mark?: ThumbMark } | undefined)?.mark ?? DEF_THUMB_MARK[def.id];
    if (markHint === "ellipse") {
      // rival-orbit: dashed orbit through the lit cloud around the anchors
      const anchors = pointsOf(res.anchorIds);
      const lit = pointsOf(res.litIds);
      if (anchors.length && lit.length >= 2) {
        const [cx, cy] = centroid(anchors);
        let sx = 0;
        let sy = 0;
        for (const [px, py] of lit) {
          sx += (px - cx) ** 2;
          sy += (py - cy) ** 2;
        }
        const rx = Math.max(8, 1.15 * Math.sqrt(sx / lit.length));
        const ry = Math.max(6, 1.15 * Math.sqrt(sy / lit.length));
        g.strokeStyle = ACCENT;
        g.lineWidth = 1;
        g.setLineDash([4, 3]);
        g.globalAlpha = 0.85;
        g.beginPath();
        g.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        g.stroke();
        g.setLineDash([]);
        g.globalAlpha = 1;
      }
    } else if (markHint === "annulus") {
      // core-crust: the core/crust boundary — circle at 1.35×rms radius,
      // clamped to ≥40% of the box's min dimension (P1 review: it drowned at 1×)
      const lit = pointsOf(res.litIds);
      if (lit.length >= 2) {
        const [cx, cy] = centroid(lit);
        let s2 = 0;
        for (const [px, py] of lit) s2 += (px - cx) ** 2 + (py - cy) ** 2;
        const r = Math.max(
          0.4 * Math.min(THUMB_W, THUMB_H),
          1.35 * Math.sqrt(s2 / lit.length),
        );
        g.strokeStyle = ACCENT;
        g.lineWidth = 1.2;
        g.setLineDash([5, 3]);
        g.globalAlpha = 0.85;
        g.beginPath();
        g.arc(cx, cy, r, 0, Math.PI * 2);
        g.stroke();
        g.setLineDash([]);
        g.globalAlpha = 1;
      }
    }
  }

  return {
    setActive(slug) {
      activeSlug = slug;
      stripEl.classList.toggle("net-q-collapsed", slug !== null);
      for (const [s, { btn }] of items) {
        btn.classList.toggle("on", s === slug);
        btn.setAttribute("aria-pressed", String(s === slug));
      }
      if (crumb) {
        crumb.hidden = slug === null;
        const cap = crumb.querySelector("span");
        if (cap) cap.textContent = slug ? (defs.find((d) => d.id === slug)?.question ?? slug) : "";
      }
    },
    drawAll(computeResult, payload) {
      for (const def of defs) {
        try {
          const res = computeResult(def);
          lastSets.set(def.id, new Set([...res.litIds, ...res.anchorIds]));
          draw(def, res, payload);
        } catch (err) {
          console.error(`[questions] thumbnail for "${def.id}" failed:`, err);
        }
      }
    },
    setStale(on) {
      stripEl.classList.toggle("net-q-stale", on);
    },
  };
}
