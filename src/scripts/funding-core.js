/* Pure graph/dollar math for the /funding landscape map.
 * NO DOM, NO d3, NO fetch — mirrors src/scripts/papers-core.js so `node --test`
 * imports it untranspiled. funding-graph.ts (view) owns all rendering.
 *
 * Sizing philosophy: AREA is proportional to field-relevant dollars (sqrt radius,
 * Tufte-honest). People are NEVER dollar-sized; unknown dollars render small with
 * a dotted outline (the view reads UNKNOWN_R).
 *
 * @typedef {import("../data/funding-types").FundingNode} FundingNode
 * @typedef {import("../data/funding-types").FundingEdge} FundingEdge
 * @typedef {import("../data/funding-types").FunderNode} FunderNode
 */

export const PERSON_R = 4; // px — constant, regardless of any dollar field
export const UNKNOWN_R = 5; // px — "no public $" nodes (dotted outline in the view)

/** Clamped sqrt scale: dollars → pixels. Degenerate domains collapse to r0. */
export function makeSqrtScale([d0, d1], [r0, r1]) {
  const s0 = Math.sqrt(Math.max(0, d0));
  const s1 = Math.sqrt(Math.max(0, d1));
  if (!(s1 > s0)) return () => r0;
  return (x) => {
    const t = (Math.sqrt(Math.max(0, x)) - s0) / (s1 - s0);
    return r0 + (r1 - r0) * Math.min(1, Math.max(0, t));
  };
}

/** The dollars a node is sized by, or null when unknown. People are always null. */
export function nodeDollars(node) {
  if (node.kind === "person") return null;
  return node.fieldDollarsUSD > 0 ? node.fieldDollarsUSD : null;
}

/** Node radius under a dollar scale (see PERSON_R / UNKNOWN_R above). */
export function radiusFor(node, scale) {
  if (node.kind === "person") return PERSON_R;
  const d = nodeDollars(node);
  return d == null ? UNKNOWN_R : scale(d);
}

/** Edge stroke width: affiliations fixed-thin, undisclosed grants hairline. */
export function edgeWidthFor(edge, scale) {
  if (edge.type === "affiliation") return 0.8;
  return edge.amountUSD == null ? 0.7 : scale(edge.amountUSD);
}

/** Undirected adjacency over ALL nodes (isolates get empty sets). */
export function buildAdjacency(nodes, edges) {
  const adj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const e of edges) {
    if (!adj.has(e.source) || !adj.has(e.target)) continue;
    adj.get(e.source).add(e.target);
    adj.get(e.target).add(e.source);
  }
  return adj;
}

/** BFS shortest path a→b. Returns { ids, len } or null (unreachable / a===b). */
export function shortestPath(adj, a, b) {
  if (a === b || !adj.has(a) || !adj.has(b)) return null;
  const prev = new Map([[a, null]]);
  let frontier = [a];
  while (frontier.length) {
    const next = [];
    for (const id of frontier) {
      for (const nb of adj.get(id) ?? []) {
        if (prev.has(nb)) continue;
        prev.set(nb, id);
        if (nb === b) {
          const ids = [b];
          for (let cur = id; cur !== null; cur = prev.get(cur)) ids.push(cur);
          ids.reverse();
          return { ids, len: ids.length - 1 };
        }
        next.push(nb);
      }
    }
    frontier = next;
  }
  return null;
}

/** Is this funder accepting applications as of the dataset snapshot date?
 *  Snapshot-dated (meta.generatedAt), never the wall clock — a static page
 *  must not silently claim freshness it doesn't have. */
export function isOpenNow(node, todayIso) {
  if (node.kind !== "funder" || !node.apply) return false;
  const { mode, deadline } = node.apply;
  if (mode === "rolling") return true;
  if (mode === "rounds") return !!deadline && deadline.slice(0, 10) >= todayIso.slice(0, 10);
  return false; // invite-only | closed
}

const matchText = (n, q) =>
  n.name.toLowerCase().includes(q) ||
  n.blurb.toLowerCase().includes(q) ||
  (n.aliases ?? []).some((a) => a.toLowerCase().includes(q)) ||
  n.id.toLowerCase().includes(q);

/** Two-pass visible set. Funders pass on their own merits; grantees are visible
 *  iff at least one VISIBLE funder feeds them; people follow their funder.
 *  `filters = { kinds:Set<FunderKind>, domains:Set<string>, minUsd:number, query:string }`.
 *  The open-now lens is NOT here — it highlights, it never filters. */
export function computeVisible(nodes, edges, filters) {
  const q = (filters.query ?? "").trim().toLowerCase();
  const domainPass = (n) =>
    filters.domains.size === 0 ||
    !n.domainTags?.length || // untagged nodes follow their neighbors, not the chips
    n.domainTags.some((t) => filters.domains.has(t));
  // funder-domain chips are strict: a tagged-or-not funder must match when chips are active
  const funderDomainPass = (f) =>
    filters.domains.size === 0 || (f.domainTags ?? []).some((t) => filters.domains.has(t));

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const peopleOf = new Map(); // funder id → person nodes (via affiliation edges)
  for (const e of edges) {
    if (e.type !== "affiliation") continue;
    const p = byId.get(e.source);
    if (!p) continue;
    if (!peopleOf.has(e.target)) peopleOf.set(e.target, []);
    peopleOf.get(e.target).push(p);
  }

  // pass 1 — funders
  const visible = new Set();
  for (const n of nodes) {
    if (n.kind !== "funder") continue;
    if (!filters.kinds.has(n.funderKind)) continue;
    if (!funderDomainPass(n)) continue;
    if (filters.minUsd > 0 && !(n.annualFieldGivingUSD != null && n.annualFieldGivingUSD >= filters.minUsd)) continue;
    if (q && !matchText(n, q) && !(peopleOf.get(n.id) ?? []).some((p) => matchText(p, q))) continue;
    visible.add(n.id);
  }

  // pass 2 — grantees: need at least one visible funding edge
  for (const n of nodes) {
    if (n.kind !== "grantee") continue;
    if (!domainPass(n)) continue;
    if (q && !matchText(n, q)) continue;
    const fed = edges.some(
      (e) => (e.type === "grant" || e.type === "investment") && e.target === n.id && visible.has(e.source),
    );
    if (fed) visible.add(n.id);
  }

  // pass 3 — people: follow their (visible) funder
  for (const e of edges) {
    if (e.type !== "affiliation" || !visible.has(e.target)) continue;
    const p = byId.get(e.source);
    if (!p) continue;
    if (q && !matchText(p, q) && !matchText(byId.get(e.target), q)) continue;
    visible.add(p.id);
  }
  return visible;
}

/** Slider position (0..100) → dollar floor. Exponential ramp so most of the
 *  slider's travel covers the small-check end where funders actually differ. */
export function sliderToUsd(v, maxUsd, k = 6) {
  if (v <= 0) return 0;
  if (v >= 100) return maxUsd;
  return (maxUsd * Math.expm1((k * v) / 100)) / Math.expm1(k);
}

/** "$1.2M" / "$350k" / "$40M" / "$1.5B" / "—". One formatter for graph,
 *  directory, dossier, and tooltip — they must never disagree. */
export function formatUsd(n) {
  if (n == null) return "—";
  const trim = (x) => String(Number(x.toFixed(1))); // 1.0 → "1"
  if (n >= 1e9) return `$${trim(n / 1e9)}B`;
  if (n >= 1e6) return n < 1e7 ? `$${trim(n / 1e6)}M` : `$${Math.round(n / 1e6)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${Math.round(n)}`;
}

/** A funder's notable grants: $ desc (undisclosed last), then year desc. */
export function topGrants(edges, funderId, n = 5) {
  return edges
    .filter((e) => e.type === "grant" && e.source === funderId)
    .sort((a, b) => (b.amountUSD ?? -1) - (a.amountUSD ?? -1) || (b.year ?? 0) - (a.year ?? 0))
    .slice(0, n);
}
