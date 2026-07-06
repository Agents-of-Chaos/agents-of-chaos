// Pure math/formatting for /networks/analyses — no DOM, no d3, importable from
// node --test (tests/analyses-core.test.mjs) and from the browser modules.

/** Linear scale: maps [d0,d1] → [r0,r1]; degenerate domains map to the range midpoint. */
export function linearScale(d0, d1, r0, r1) {
  const span = d1 - d0;
  if (span === 0) return () => (r0 + r1) / 2;
  return (x) => r0 + ((x - d0) / span) * (r1 - r0);
}

/** Tufte-minimal ticks: lo, mid, hi of the domain, rounded sensibly. */
export function minimalTicks(lo, hi) {
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) return [lo];
  const mid = (lo + hi) / 2;
  const step = (hi - lo) / 2;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(step))));
  const r = (x) => Math.round(x / mag) * mag;
  return [...new Set([r(lo), r(mid), r(hi)])];
}

export function extent(values) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : [0, 1];
}

/** Polar → cartesian for the dots archetype's polar mode (angle rad, radius). */
export function polarToXY(angle, radius) {
  return [radius * Math.cos(angle), radius * Math.sin(angle)];
}

/** Quadrant index for quadrant scatters: 0 TL, 1 TR, 2 BL, 3 BR (y up). */
export function quadrantOf(x, y, xMid, yMid) {
  return (y >= yMid ? 0 : 2) + (x >= xMid ? 1 : 0);
}

/** Ids shipped in a panel's data that are gone from the live graphs. */
export function staleIdsIn(value, liveIds, out = new Set()) {
  if (Array.isArray(value)) for (const v of value) staleIdsIn(v, liveIds, out);
  else if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      if (k === "id" && typeof v === "string" && !liveIds.has(v)) out.add(v);
      else staleIdsIn(v, liveIds, out);
    }
  }
  return out;
}

export const fmt = {
  num(x, digits = 2) {
    if (x == null || !isFinite(x)) return "—";
    if (Number.isInteger(x) && digits === 2) return String(x);
    return x.toFixed(digits);
  },
  usd(x) {
    if (x == null || !isFinite(x)) return "—";
    const abs = Math.abs(x);
    if (abs >= 1e9) return `$${(x / 1e9).toFixed(1)}B`;
    if (abs >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `$${Math.round(x / 1e3)}k`;
    return `$${Math.round(x)}`;
  },
  pct(x) {
    if (x == null || !isFinite(x)) return "—";
    return `${(100 * x).toFixed(x >= 0.1 ? 0 : 1)}%`;
  },
  sig(p) {
    if (p == null || !isFinite(p)) return "—";
    if (p < 0.001) return "p<0.001";
    return `p=${p.toFixed(3)}`;
  },
};
