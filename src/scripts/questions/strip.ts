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

export interface StripCallbacks {
  onToggle(slug: string): void;
  preview(ids: Set<string> | null): void;
}

export interface StripHandle {
  setActive(slug: string | null): void;
  drawAll(computeResult: (def: QuestionDef) => QuestionResult, payload: QuestionPayload): void;
  setStale(on: boolean): void;
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

    // fade dots: every node, 1px
    g.fillStyle = FADE;
    for (const [px, py] of at.values()) g.fillRect(px - 0.5, py - 0.5, 1, 1);

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
