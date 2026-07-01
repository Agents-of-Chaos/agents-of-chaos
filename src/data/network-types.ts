/* Types + display metadata for the /networks company-landscape map.
 *
 * The map is two-layer:
 *   - PUBLIC  (companies.json) — every field on `Company` + `CompanyEdge`.
 *               Committed, shipped to everyone.
 *   - PRIVATE (private/overlay.json, gitignored) — `PrivateOverlayEntry`.
 *               Warm-intro paths + pipeline stage + notes. Loaded ONLY in
 *               `astro dev` (see NetworkGraph.astro), never in a prod build.
 *
 * Color encodes VERTICAL, size encodes deployment INTENSITY (how much a company
 * runs agents in production = how much it needs red-teaming). Red (#a00) is
 * reserved site-wide for highlight/the customer end of the funnel. */

export type Vertical =
  | "frontier-lab"
  | "agent-native-startup"
  | "bank-fintech"
  | "healthcare"
  | "security-eval-vendor"
  | "investor-vc"
  | "infra-platform"
  | "enterprise-other";

export interface Company {
  id: string; // slug — node id, edge endpoint, ?focus= token
  name: string;
  vertical: Vertical; // → color
  subcategory: string; // "what they do" bucket key within the vertical → directory grouping
  blurb: string; // one line: what they do with agents
  intensity: number; // 0..5 deployment intensity → node size
  competitor?: boolean; // true = a direct competitor of Agents of Chaos (cross-cutting flag)
  priorityRank: number; // "learn about first" rank (1 = highest; 0 = AoC itself). Drives the priority bar.
  url?: string;
  investors?: string[]; // → shared-investor edges (derived in the build)
  buyer_persona?: string; // public-safe (title only, e.g. "Head of Trust & Safety")
  trigger?: string; // public-safe purchase trigger
  confidence: "high" | "medium" | "low"; // research confidence → node opacity
  x?: number; // baked initial layout (force relaxes from here); optional
  y?: number;
}

/* One "what they do" bucket inside a vertical. The ordered list per vertical is
 * baked into companies.json `meta.subcategories` (canonical source:
 * experiments/networks/subcategories.json) and drives the directory view. */
export interface SubcategoryMeta {
  key: string;
  label: string; // short, for a dense text directory
  isBuyer: boolean; // companies here are likely BUYERS of agent red-teaming
  what?: string; // one-line description
}
export type SubcategoryTable = Record<Vertical, SubcategoryMeta[]>;

export type EdgeType = "business" | "shared-investor" | "competitor";

export interface CompanyEdge {
  source: string; // Company.id
  target: string; // Company.id
  type: EdgeType;
  label?: string; // e.g. "built on", "invests in", "shared: a16z"
  directed?: boolean; // business "built-on"/"invests-in" point source→target
  verified: boolean; // true = solid; false = AI-inferred, drawn dashed
}

export interface NetworkData {
  companies: Company[];
  edges: CompanyEdge[];
  meta?: Record<string, unknown>;
}

export type Stage = "cold" | "warm" | "in-convo" | "design-partner" | "customer";

export interface PrivateOverlayEntry {
  id: string; // joins to Company.id
  warm_path?: string; // "you → D. Bau → contact → CEO"
  stage?: Stage;
  notes?: string;
  priority?: number;
}

export interface VerticalMeta {
  id: Vertical;
  label: string;
  color: string;
}

/* Vertical → label + color. The palette is the restrained set the rest of the
 * site uses (muted blue/rust/sage/plum/…); order also fixes the layout grid of
 * category "territories" in networks-graph.ts. Keep in sync with the legend. */
export const VERTICALS: VerticalMeta[] = [
  { id: "frontier-lab", label: "frontier labs", color: "#4c6b8a" },
  { id: "agent-native-startup", label: "agent-native startups", color: "#a6611a" },
  { id: "bank-fintech", label: "banks / fintech", color: "#5a7d5a" },
  { id: "healthcare", label: "healthcare", color: "#8a6d9b" },
  { id: "security-eval-vendor", label: "security / eval vendors", color: "#b08968" },
  { id: "investor-vc", label: "investors / VCs", color: "#9b6a6a" },
  { id: "infra-platform", label: "infra / platform", color: "#4f7a72" },
  { id: "enterprise-other", label: "other enterprise", color: "#8a8475" },
];

/* Pipeline stage → label + color (PRIVATE layer only). Color runs cold→warm,
 * ending in the reserved accent red for a closed customer. */
export const STAGES: { id: Stage; label: string; color: string }[] = [
  { id: "cold", label: "cold", color: "#b3ab9c" },
  { id: "warm", label: "warm", color: "#b08968" },
  { id: "in-convo", label: "in conversation", color: "#a6611a" },
  { id: "design-partner", label: "design partner", color: "#5a7d5a" },
  { id: "customer", label: "customer", color: "#a00" },
];

/* Escape a string for safe HTML interpolation. Single source of truth for both
 * viz scripts (networks-graph + networks-directory) — escaping is a security
 * policy that must not silently diverge between modules. */
const HTML_ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
export const escapeHtml = (s: string): string => String(s).replace(/[&<>"]/g, (c) => HTML_ESC[c]!);

export const verticalColor = (v: Vertical): string =>
  VERTICALS.find((x) => x.id === v)?.color ?? "#8a8475";
export const verticalLabel = (v: Vertical): string =>
  VERTICALS.find((x) => x.id === v)?.label ?? v;
export const stageColor = (s?: Stage): string =>
  STAGES.find((x) => x.id === s)?.color ?? STAGES[0].color;
export const stageLabel = (s?: Stage): string =>
  STAGES.find((x) => x.id === s)?.label ?? (s ?? "");
