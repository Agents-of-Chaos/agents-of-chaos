/* Single source of truth for the /team page: the roster, the work, and the
 * ties between them. The evidence graph and the bio cards both render from
 * this file — the server reads it in .astro frontmatter, the client script
 * imports the same module, so the two can never drift.
 *
 * Every tie carries a `source`: a public URL (linked from the graph's detail
 * panel), "confirmed by the person", or "NDA — engagement record". Every URL
 * below was fetched and the claim read on the page (verification run,
 * 2026-06-12); rows without a public source were confirmed by Alex Loftus
 * (fact review, 2026-06-12).
 * The client lab is never named — "a frontier lab" only (site-wide rule). */

export type NodeType =
  | "work" // joint artifacts: the paper, the campaigns, shared research
  | "lab"
  | "university"
  | "community"
  | "company"
  | "program";

export interface GraphNode {
  id: string;
  label: string; // SHORT — the collide radius grows with label length
  full?: string; // long form, shown in tooltip/detail
  type: NodeType;
  href?: string; // the NDA hub has none
  note?: string; // e.g. "client under NDA"
}

export interface Tie {
  node: string; // GraphNode.id
  role?: string;
  years?: string;
  source: string;
}

export interface Member {
  id: string; // slug — graph node id, card data-person-id, #p= hash token
  name: string;
  role: "Lead" | "Member of Technical Staff";
  line: string; // one-line work statement on the card (≤ ~80 chars)
  links?: { label: string; href: string }[];
  ties: Tie[];
}

const AOC = "https://agentsofchaos.baulab.info/";
const AOC_REPORT = "https://agentsofchaos.baulab.info/report.html";
const NDA = "NDA — engagement record";

export const nodes: GraphNode[] = [
  {
    id: "aoc-paper",
    label: "Agents of Chaos",
    full: "Agents of Chaos (Shapira et al., 2026) — the first study of emergent harm in populated multi-agent environments. Covered by Science and Wired.",
    type: "work",
    href: AOC,
  },
  {
    id: "frontier-campaigns",
    label: "frontier-lab campaigns",
    full: "Internal red-team campaigns designed and led for a frontier lab (2026–). A measurable success that led to a follow-up.",
    type: "work",
  },
  {
    id: "nnsight",
    label: "NNsight / NDIF",
    full: "NNsight & the National Deep Inference Fabric (ICLR 2025) — open infrastructure for inspecting foundation-model internals.",
    type: "work",
    href: "https://nnsight.net/",
  },
  {
    id: "network-ml-book",
    label: "Hands-On Network ML",
    full: "Hands-On Network Machine Learning with Python (Cambridge University Press, 2025).",
    type: "work",
    href: "https://www.cambridge.org/core/books/handson-network-machine-learning-with-python/9735741A096973A9C963E930BBAF5368",
  },
  {
    id: "bilinear-mlps",
    label: "Bilinear MLPs",
    full: "Bilinear MLPs enable weight-based mechanistic interpretability (ICLR 2025 Spotlight).",
    type: "work",
    href: "https://arxiv.org/abs/2410.08417",
  },
  {
    id: "sdxl-sae",
    label: "SAEs for diffusion",
    full: "One-Step is Enough: Sparse Autoencoders for Text-to-Image Diffusion Models — with Agents of Chaos authors Chris Wendler and David Bau.",
    type: "work",
    href: "https://arxiv.org/abs/2410.22366",
  },
  {
    id: "bau-lab",
    label: "Bau Lab",
    full: "David Bau's interpretability lab, Northeastern University.",
    type: "lab",
    href: "https://baulab.info/",
  },
  {
    id: "northeastern",
    label: "Northeastern",
    full: "Northeastern University, Boston.",
    type: "university",
    href: "https://www.northeastern.edu/",
  },
  {
    id: "epfl",
    label: "EPFL",
    full: "École Polytechnique Fédérale de Lausanne.",
    type: "university",
    href: "https://www.epfl.ch/",
  },
  {
    id: "eleuther",
    label: "EleutherAI",
    full: "EleutherAI — the open-source AI research collective.",
    type: "community",
    href: "https://www.eleuther.ai/",
  },
  {
    id: "jpmorgan",
    label: "J.P. Morgan",
    full: "J.P. Morgan Research.",
    type: "company",
    href: "https://www.jpmorgan.com/technology/artificial-intelligence",
  },
];

export const team: Member[] = [
  {
    id: "alex-loftus",
    name: "Alex Loftus",
    role: "Lead",
    line: "Co-author of Agents of Chaos; leads red-team campaigns — Bau Lab, Northeastern",
    links: [
      { label: "site", href: "https://alex-loftus.com" },
      { label: "scholar", href: "https://scholar.google.com/citations?user=_Njcmm8AAAAJ" },
      { label: "github", href: "https://github.com/loftusa" },
    ],
    ties: [
      { node: "aoc-paper", role: "co-author", years: "2026", source: AOC },
      { node: "frontier-campaigns", source: NDA },
      { node: "bau-lab", role: "PhD student", years: "2024–", source: "https://baulab.info/" },
      { node: "northeastern", role: "PhD student", years: "2024–", source: "https://scholar.google.com/citations?user=_Njcmm8AAAAJ" },
      { node: "nnsight", role: "co-author", years: "2025", source: "https://proceedings.iclr.cc/paper_files/paper/2025/hash/e6c65eb9b56719c1aa45ff73874de317-Abstract-Conference.html" },
      { node: "network-ml-book", role: "co-author", years: "2025", source: "https://www.cambridge.org/core/books/handson-network-machine-learning-with-python/9735741A096973A9C963E930BBAF5368" },
    ],
  },
  {
    id: "jannik-brinkmann",
    name: "Jannik Brinkmann",
    role: "Lead",
    line: "Co-author of Agents of Chaos; leads red-team campaigns — University of Mannheim",
    links: [
      { label: "site", href: "https://jannik-brinkmann.github.io" },
      { label: "scholar", href: "https://scholar.google.com/citations?user=YtdTeaMAAAAJ" },
      { label: "github", href: "https://github.com/jannik-brinkmann" },
    ],
    ties: [
      { node: "aoc-paper", role: "co-author", years: "2026", source: AOC },
      { node: "frontier-campaigns", source: NDA },
      { node: "bau-lab", role: "visiting researcher", years: "2024", source: "https://jannik-brinkmann.github.io" },
      { node: "nnsight", role: "co-author", years: "2025", source: "https://proceedings.iclr.cc/paper_files/paper/2025/hash/e6c65eb9b56719c1aa45ff73874de317-Abstract-Conference.html" },
      { node: "jpmorgan", role: "research intern", years: "2025", source: "https://jannik-brinkmann.github.io" },
    ],
  },
  {
    id: "antonio-mari",
    name: "Antonio Mari",
    role: "Lead",
    line: "Stress-tested the frontier-lab campaigns — EPFL / ETH Zürich",
    links: [
      { label: "scholar", href: "https://scholar.google.com/citations?user=VL62tXMAAAAJ" },
      { label: "openreview", href: "https://openreview.net/profile?id=~Antonio_Mari1" },
    ],
    ties: [
      { node: "frontier-campaigns", source: NDA },
      { node: "sdxl-sae", role: "co-author", years: "2024–2025", source: "https://arxiv.org/abs/2410.22366" },
      { node: "epfl", role: "MS, Data Science", years: "2023–2026", source: "https://openreview.net/profile?id=~Antonio_Mari1" },
    ],
  },
  {
    id: "alice-rigg",
    name: "Alice Rigg",
    role: "Member of Technical Staff",
    line: "Stress-tested the frontier-lab campaigns — EleutherAI",
    links: [
      { label: "site", href: "https://woog97.github.io/" },
      { label: "scholar", href: "https://scholar.google.com/citations?user=9kp2s8UAAAAJ" },
      { label: "github", href: "https://github.com/woog97" },
    ],
    ties: [
      { node: "frontier-campaigns", source: NDA },
      { node: "eleuther", role: "ML researcher", years: "2025–", source: "https://openreview.net/profile?id=~Alice_Rigg1" },
      { node: "bilinear-mlps", role: "co-author", years: "2025", source: "https://arxiv.org/abs/2410.08417" },
    ],
  },
  {
    id: "negev-taglicht",
    name: "Negev Taglicht",
    role: "Member of Technical Staff",
    line: "Co-author of Agents of Chaos; ran its covert constitution-edit attack (Case 10)",
    links: [{ label: "dblp", href: "https://dblp.org/pid/431/0082.html" }],
    ties: [
      { node: "aoc-paper", role: "co-author · Case Study #10 attacker", years: "2026", source: AOC_REPORT },
      { node: "frontier-campaigns", source: NDA },
    ],
  },
  {
    id: "avery-yen",
    name: "Avery Yen",
    role: "Member of Technical Staff",
    /* Coauthor of the paper (Northeastern, footnote 1); ran the Kimi K2.5
     * case study (Quinn bot). Verified against report.html, 2026-06-13. */
    line: "Co-author of Agents of Chaos; ran the Kimi K2.5 case study — Northeastern",
    links: [],
    ties: [
      { node: "aoc-paper", role: "co-author", years: "2026", source: AOC },
      { node: "frontier-campaigns", source: NDA },
      { node: "northeastern", source: AOC_REPORT },
    ],
  },
  {
    /* Anton Alyakin (handle alyakin314) — distinct person from Antonio Mari
     * above; both are on the team. Frontier-campaigns tie confirmed by Alex.
     * Public footprint verified: JHU/NeuroData (Priebe/Vogelstein, 2019–21),
     * now WashU MD + NYU OLAB CNS AI fellow; "Medical LLMs are Vulnerable to
     * Data-poisoning Attacks", Nature Medicine 2025. */
    id: "anton-alyakin",
    name: "Anton Alyakin",
    role: "Member of Technical Staff",
    line: "Data-poisoning attacks on medical LLMs (Nature Medicine) — JHU/NeuroData alum",
    links: [
      { label: "site", href: "https://alyakin314.github.io/" },
      { label: "scholar", href: "https://scholar.google.com/citations?user=5rDtuRIAAAAJ" },
      { label: "github", href: "https://github.com/alyakin314" },
    ],
    ties: [{ node: "frontier-campaigns", source: NDA }],
  },
];

/* Fail at build time, not in front of a customer. */
const nodeIds = new Set(nodes.map((n) => n.id));
if (nodeIds.size !== nodes.length) throw new Error("team.ts: duplicate node ids");
const memberIds = new Set(team.map((m) => m.id));
if (memberIds.size !== team.length) throw new Error("team.ts: duplicate member ids");
for (const m of team) {
  if (nodeIds.has(m.id)) throw new Error(`team.ts: member id "${m.id}" collides with a node id`);
  for (const t of m.ties) {
    if (!nodeIds.has(t.node)) throw new Error(`team.ts: ${m.id} ties to unknown node "${t.node}"`);
    if (!t.source) throw new Error(`team.ts: ${m.id} → ${t.node} is missing a source`);
  }
}
