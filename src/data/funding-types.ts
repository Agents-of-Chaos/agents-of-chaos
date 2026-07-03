/* Types + display metadata for the /funding landscape map.
 *
 * Two-layer, exactly like /networks (see network-types.ts):
 *   - PUBLIC  (funding.json)  — funders, grantees, publicly-listed people; every
 *               dollar figure carries a source URL. Committed, shipped.
 *   - PRIVATE (private/funding-overlay.json, gitignored) — OUR pipeline stage +
 *               warm paths. Loaded ONLY in `astro dev`, never in a prod build.
 *
 * Color encodes FUNDER KIND, size encodes FIELD-RELEVANT DOLLARS (sqrt scale).
 * Red (#a00) stays reserved for highlight / the active path / a funded stage. */

export type NodeKind = "funder" | "grantee" | "person";
export type FunderKind = "philanthropy" | "government" | "vc" | "corporate";
export type GranteeKind = "research-org" | "university" | "startup" | "fieldbuilding";
export type ApplyMode = "rolling" | "rounds" | "invite-only" | "closed";
export type Confidence = "high" | "medium" | "low";

export interface SourceRef {
  url: string;
  title?: string;
  accessed: string; // ISO date
}

export interface Apply {
  mode: ApplyMode;
  url?: string;
  deadline?: string; // ISO date of the next known close (rounds only)
  notes?: string; // "reopens summer 2026"
  lastVerified: string; // ISO date — the nightly job's re-verification clock
}

export interface AnnualBasis {
  year: number; // basis year for the figure
  method: string; // e.g. "sum of AI-safety fund grants CY2025, multi-year amortized"
  sourceUrl: string;
}

interface NodeBase {
  id: string; // stable slug — node id, edge endpoint, #f= deep-link token. FROZEN once emitted.
  kind: NodeKind;
  name: string;
  aliases?: string[]; // for entity resolution + search ("Open Philanthropy")
  blurb: string; // one line
  domainTags?: string[]; // DOMAINS ids — what work this money touches
  confidence: Confidence; // research confidence → node opacity
  sources: SourceRef[]; // node-level provenance (validator: >= 1)
  networksId?: string; // companies.json id when the same entity is on /networks
  priorityRank: number; // "approach first" rank (1 = highest)
  url?: string;
  lastVerified: string; // ISO date
  /* Baked sizing value (sqrt → radius): funder = annualFieldGivingUSD ?? 0;
   * grantee = verified in-field $ received (regrant-deduped, amortized);
   * person = 0 (people are never dollar-sized). */
  fieldDollarsUSD: number;
  x?: number; // optional baked initial layout
  y?: number;
}

export interface FunderNode extends NodeBase {
  kind: "funder";
  funderKind: FunderKind; // → color + territory
  program?: string; // sub-group within the kind (directory grouping), e.g. "Technical AI Safety"
  annualFieldGivingUSD: number | null; // $ into THIS FIELD per year; null = no public figure
  annualFieldGivingBasis?: AnnualBasis; // REQUIRED (validator) whenever the figure is non-null
  checkSizeUSD?: { min: number; max: number };
  thesis?: string; // their theory of change, for the dossier
  apply: Apply;
  inKind?: boolean; // compute/API credits rather than cash
}

export interface GranteeNode extends NodeBase {
  kind: "grantee";
  granteeKind: GranteeKind;
}

export interface PersonNode extends NodeBase {
  kind: "person"; // publicly-listed program officers / fund managers ONLY
  title: string; // the publicly listed role
  profileUrl?: string;
}

export type FundingNode = FunderNode | GranteeNode | PersonNode;

export type FundingEdgeType = "grant" | "investment" | "affiliation";

export interface GrantEdge {
  type: "grant";
  source: string; // funder id
  target: string; // grantee id
  amountUSD: number | null; // null = undisclosed (hairline). Non-null REQUIRES sourceUrl.
  amountOriginal?: { value: number; currency: "GBP" | "EUR" | "USD" };
  year?: number;
  multiYear?: { start: number; end: number }; // sizing amortizes total across years
  program?: string; // "SFF-2025 Main Round"
  sourceUrl?: string;
  verified: boolean; // true = solid; false = inferred, dashed
  regrantOf?: string; // payer funder id (dedup key: SFF rows paid by Jaan Tallinn etc.)
}

export interface InvestmentEdge {
  type: "investment";
  source: string; // vc/corporate funder id
  target: string; // startup grantee id
  amountUSD: number | null; // disclosed round total (attribution upper bound)
  year?: number;
  round?: string; // "Series B (co-led)"
  sourceUrl?: string;
  verified: boolean;
}

export interface AffiliationEdge {
  type: "affiliation";
  source: string; // person id
  target: string; // funder id
  role: string; // "Co-founder", "Program Officer, Technical AI Safety"
  current: boolean; // append-only history: job changes flip this, never delete
  sourceUrl?: string;
  lastVerified?: string;
}

export type FundingEdge = GrantEdge | InvestmentEdge | AffiliationEdge;

export interface DomainMeta {
  id: string;
  label: string;
}

export interface FundingMeta {
  generated?: string; // producer ("hand-seeded starter" | "build_funding.py")
  generatedAt: string; // ISO date — the snapshot clock that drives open-now
  domains: DomainMeta[];
  fx?: Record<string, number>; // pinned annual-average rates used for conversion
  [k: string]: unknown;
}

export interface FundingData {
  meta: FundingMeta;
  nodes: FundingNode[];
  edges: FundingEdge[];
}

export type FundingStage = "cold" | "warm" | "in-convo" | "applied" | "funded";

export interface FundingOverlayEntry {
  id: string; // joins to FundingNode.id
  stage?: FundingStage;
  warm_path?: string;
  notes?: string;
}

/* Funder kind → label + color. Same restrained site palette as VERTICALS in
 * network-types.ts; order fixes the 2×2 territory grid in funding-graph.ts. */
export const FUNDER_KINDS: { id: FunderKind; label: string; color: string }[] = [
  { id: "philanthropy", label: "philanthropy", color: "#4c6b8a" },
  { id: "government", label: "government", color: "#5a7d5a" },
  { id: "vc", label: "venture", color: "#9b6a6a" },
  { id: "corporate", label: "corporate programs", color: "#a6611a" },
];

export const GRANTEE_COLOR = "#8a8475"; // neutral gray-tan — grantees are context, funders are the map
export const PERSON_COLOR = "#b08968"; // small outlined dots

/* Domain tags → labels (what the money funds). Baked copy also lives in
 * funding.json meta.domains so the pipeline and the page can't drift. */
export const DOMAINS: DomainMeta[] = [
  { id: "technical-alignment", label: "technical alignment" },
  { id: "interpretability", label: "interpretability" },
  { id: "evals", label: "evals" },
  { id: "agent-security", label: "agent security" },
  { id: "policy-governance", label: "policy / governance" },
  { id: "open-source", label: "open source" },
  { id: "field-building", label: "field building" },
];

/* Fundraising pipeline stage → label + color (PRIVATE layer only).
 * Cold→warm ramp ending in the reserved accent red once the money lands. */
export const FUNDING_STAGES: { id: FundingStage; label: string; color: string }[] = [
  { id: "cold", label: "cold", color: "#b3ab9c" },
  { id: "warm", label: "warm", color: "#b08968" },
  { id: "in-convo", label: "in conversation", color: "#a6611a" },
  { id: "applied", label: "applied", color: "#5a7d5a" },
  { id: "funded", label: "funded", color: "#a00" },
];

/* Single source of truth for HTML escaping — same policy module as /networks. */
export { escapeHtml } from "./network-types";

export const funderColor = (k: FunderKind): string =>
  FUNDER_KINDS.find((x) => x.id === k)?.color ?? GRANTEE_COLOR;
export const funderLabel = (k: FunderKind): string =>
  FUNDER_KINDS.find((x) => x.id === k)?.label ?? k;
export const fundingStageColor = (s?: FundingStage): string =>
  FUNDING_STAGES.find((x) => x.id === s)?.color ?? FUNDING_STAGES[0].color;
export const fundingStageLabel = (s?: FundingStage): string =>
  FUNDING_STAGES.find((x) => x.id === s)?.label ?? (s ?? "");
export const domainLabel = (id: string): string =>
  DOMAINS.find((d) => d.id === id)?.label ?? id;

export const nodeColor = (n: FundingNode): string =>
  n.kind === "funder" ? funderColor(n.funderKind) : n.kind === "grantee" ? GRANTEE_COLOR : PERSON_COLOR;
