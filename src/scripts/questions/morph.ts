// The market-shape morph: tween the live sim nodes to latent (ASE) positions
// and back. The ONE lens that moves nodes. Contract (P0-S2 spike): park the
// sim, snapshot {x,y,vx,vy,fx,fy}, tween 650ms cubic-in-out driving node x/y +
// host.redraw() per frame; exit restores the snapshot values VERBATIM on the
// final frame (never the last interpolation step). prefers-reduced-motion
// (host.calm) jumps in one frame.
//
// REQUIREMENT ON THE HOST: host.nodes must be the LIVE simulation node
// objects (mutating their x/y and calling host.redraw() must move the map).
// A mapped copy silently breaks the morph.

import type { QuestionHost } from "./types";

type SimNode = {
  id: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
};

interface Snap {
  x: number;
  y: number;
  vx: number | undefined;
  vy: number | undefined;
  fx: number | null | undefined;
  fy: number | null | undefined;
}

const DURATION = 650; // ms
const easeCubicInOut = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

let snapshot: Map<SimNode, Snap> | null = null;
let cancelTween: (() => void) | null = null;

/** rAF tween; resolves at the end. Cancelling resolves immediately (the next
 * tween takes over from wherever the nodes are). */
function tween(host: QuestionHost, apply: (e: number) => void): Promise<void> {
  cancelTween?.();
  if (host.calm) {
    apply(1);
    host.redraw();
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const t0 = performance.now();
    let raf = 0;
    const stop = () => {
      cancelAnimationFrame(raf);
      cancelTween = null;
      resolve();
    };
    cancelTween = stop;
    const frame = (now: number) => {
      const t = Math.min(1, (now - t0) / DURATION);
      apply(easeCubicInOut(t));
      host.redraw();
      if (t >= 1) stop();
      else raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
  });
}

/** Best of the 4 (±x, ±y) reflections of the target coords, each affine-fit
 * (uniform scale, centered) into the current position bounding box; pick the
 * one minimizing total squared travel. */
function fitTargets(
  pts: { n: SimNode; tx: number; ty: number }[],
): Map<SimNode, { x: number; y: number }> {
  const xs = pts.map((p) => p.n.x ?? 0);
  const ys = pts.map((p) => p.n.y ?? 0);
  const cur = {
    x0: Math.min(...xs),
    x1: Math.max(...xs),
    y0: Math.min(...ys),
    y1: Math.max(...ys),
  };
  const cw = Math.max(1e-9, cur.x1 - cur.x0);
  const ch = Math.max(1e-9, cur.y1 - cur.y0);
  const ccx = (cur.x0 + cur.x1) / 2;
  const ccy = (cur.y0 + cur.y1) / 2;

  let best: Map<SimNode, { x: number; y: number }> | null = null;
  let bestCost = Infinity;
  for (const [sx, sy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]] as const) {
    const rx = pts.map((p) => sx * p.tx);
    const ry = pts.map((p) => sy * p.ty);
    const tw = Math.max(1e-9, Math.max(...rx) - Math.min(...rx));
    const th = Math.max(1e-9, Math.max(...ry) - Math.min(...ry));
    const tcx = (Math.min(...rx) + Math.max(...rx)) / 2;
    const tcy = (Math.min(...ry) + Math.max(...ry)) / 2;
    const s = Math.min(cw / tw, ch / th);
    let cost = 0;
    const fitted = new Map<SimNode, { x: number; y: number }>();
    pts.forEach((p, i) => {
      const fx = ccx + (rx[i] - tcx) * s;
      const fy = ccy + (ry[i] - tcy) * s;
      fitted.set(p.n, { x: fx, y: fy });
      const dx = (p.n.x ?? 0) - fx;
      const dy = (p.n.y ?? 0) - fy;
      cost += dx * dx + dy * dy;
    });
    if (cost < bestCost) {
      bestCost = cost;
      best = fitted;
    }
  }
  return best!;
}

export function enterMorph(host: QuestionHost, targets: Map<string, { x: number; y: number }>): Promise<void> {
  const nodes = host.nodes as unknown as SimNode[];
  host.parkSim();
  if (!snapshot)
    snapshot = new Map(
      nodes.map((n) => [n, { x: n.x ?? 0, y: n.y ?? 0, vx: n.vx, vy: n.vy, fx: n.fx, fy: n.fy }]),
    );
  host.setDragEnabled(false);
  host.setLabelsVisible(false);

  const pts = nodes.flatMap((n) => {
    const t = targets.get(n.id);
    return t && n.x != null && n.y != null ? [{ n, tx: t.x, ty: t.y }] : [];
  });
  if (!pts.length) return Promise.resolve();
  const fitted = fitTargets(pts);
  const starts = new Map(pts.map((p) => [p.n, { x: p.n.x ?? 0, y: p.n.y ?? 0 }]));
  // freeze any residual sim motion so exit resumes cleanly
  for (const n of nodes) {
    n.vx = 0;
    n.vy = 0;
  }
  return tween(host, (e) => {
    for (const [n, to] of fitted) {
      const from = starts.get(n)!;
      n.x = e >= 1 ? to.x : from.x + (to.x - from.x) * e;
      n.y = e >= 1 ? to.y : from.y + (to.y - from.y) * e;
    }
  });
}

export function exitMorph(host: QuestionHost): Promise<void> {
  const snap = snapshot;
  if (!snap) return Promise.resolve();
  snapshot = null;
  const starts = new Map([...snap.keys()].map((n) => [n, { x: n.x ?? 0, y: n.y ?? 0 }]));
  return tween(host, (e) => {
    for (const [n, s] of snap) {
      if (e >= 1) {
        // FINAL FRAME: snapshot values verbatim — byte-exact restore
        n.x = s.x;
        n.y = s.y;
        n.vx = s.vx;
        n.vy = s.vy;
        n.fx = s.fx;
        n.fy = s.fy;
      } else {
        const from = starts.get(n)!;
        n.x = from.x + (s.x - from.x) * e;
        n.y = from.y + (s.y - from.y) * e;
      }
    }
  }).then(() => {
    host.setLabelsVisible(true);
    host.setDragEnabled(true);
    host.resumeSimOnNextDrag();
  });
}
