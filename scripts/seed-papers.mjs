// scripts/seed-papers.mjs — generate public/papers.json from a handful of seed papers.
// One throttled batch call to Semantic Scholar → node objects (via the shared toNode).
// Run:  node scripts/seed-papers.mjs            (anonymous; the batch endpoint tolerates it)
//       SEMANTIC_SCHOLAR_API_KEY=… node scripts/seed-papers.mjs   (faster / more reliable)
//
// This is the curator's "refresh the canonical graph" path; the in-page "export" button
// produces the same shape from a live-grown graph. Edit SEEDS and re-run to reseed.
import { writeFile, mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { toNode, BATCH_FIELDS, REC_FIELDS } from "../src/scripts/papers-core.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(__dirname, "..", "public", "papers.json");
const KEY = process.env.SEMANTIC_SCHOLAR_API_KEY || "";

// The current reading set: agent prompt-injection + frontier-risk evaluation.
const SEEDS = [
  "ARXIV:2603.12277", // Prompt Injection as Role Confusion (Ye, Cui, Hadfield-Menell; ICML 2026)
  "ARXIV:2603.15714", // How Vulnerable Are AI Agents to Indirect Prompt Injections? (Dziemian, Zou, Kolter, et al.)
];
// The METR Frontier Risk Report isn't on S2/arXiv, so it has no fetchable SPECTER2
// vector. scripts/embed_specter2.py embeds it offline into the same space (verified
// ~0.96 cosine vs S2's vectors); we splice that node in below. Re-run that script if
// you change the report text.

async function batch(ids) {
  for (let i = 0; i < 6; i++) {
    const r = await fetch(
      `https://api.semanticscholar.org/graph/v1/paper/batch?fields=${BATCH_FIELDS}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(KEY ? { "x-api-key": KEY } : {}) },
        body: JSON.stringify({ ids }),
      },
    );
    if (r.status === 429) {
      const wait = 1000 * 2 ** i;
      console.error(`  429, backing off ${wait}ms…`);
      await new Promise((s) => setTimeout(s, wait));
      continue;
    }
    const d = await r.json();
    if (Array.isArray(d)) return d;
    throw new Error("unexpected response: " + JSON.stringify(d).slice(0, 200));
  }
  throw new Error("rate limited after retries — try again or set SEMANTIC_SCHOLAR_API_KEY");
}

// Recommendations for the seed set — baked into papers.json as a lightweight "frontier" so the
// /papers discovery slider reveals its first paper instantly on page load (the live page then
// refreshes + embeds these in the background). No embeddings here → keeps the file small.
async function recommend(ids, limit = 80) {
  for (let i = 0; i < 6; i++) {
    const r = await fetch(
      `https://api.semanticscholar.org/recommendations/v1/papers/?fields=${REC_FIELDS}&limit=${limit}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(KEY ? { "x-api-key": KEY } : {}) },
        body: JSON.stringify({ positivePaperIds: ids, negativePaperIds: [] }),
      },
    );
    if (r.status === 429) {
      const wait = 1000 * 2 ** i;
      console.error(`  rec 429, backing off ${wait}ms…`);
      await new Promise((s) => setTimeout(s, wait));
      continue;
    }
    const d = await r.json();
    return Array.isArray(d.recommendedPapers) ? d.recommendedPapers : [];
  }
  return [];
}

const raw = await batch(SEEDS);
const nodes = raw.map(toNode).filter(Boolean);

// Splice in the locally-embedded METR report as a first-class node. Build it through
// toNode (so it normalizes the vector + handles tldr/abstract the same way), then
// override the S2-placeholder URL with the report page.
const metr = JSON.parse(await readFile(resolve(__dirname, "metr-embedding.json"), "utf8"));
const metrNode = toNode({
  paperId: metr.id,
  title: metr.title,
  year: metr.year,
  authors: metr.authors.map((name) => ({ name })),
  externalIds: {},
  citationCount: 0,
  references: [],
  embedding: { vector: metr.vector },
  abstract: metr.abstract,
  tldr: { text: metr.tldr },
});
metrNode.url = metr.url;
nodes.push(metrNode);
const withVec = nodes.filter((n) => n.vec).length;

// Bake the discovery frontier: recommendations for the seed set, minus papers already in the
// graph, as small vector-less candidate objects (id/title/authors/year/citations/url/arxiv +
// ghost/vnScore/nearestId ready to drop straight into the graph). S2's own order → vnScore ramp.
const s2Ids = nodes.filter((n) => /^[0-9a-f]{40}$/i.test(n.id)).map((n) => n.id);
const readIds = new Set(nodes.map((n) => n.id));
const anchor = s2Ids[0] || (nodes[0] && nodes[0].id) || null;
let frontier = [];
try {
  const rec = (await recommend(s2Ids)).filter((p) => p && p.paperId && !readIds.has(p.paperId));
  frontier = rec.map((p, i) => {
    const n = toNode(p);
    return n && {
      id: n.id, title: n.title, authors: n.authors, year: n.year, citationCount: n.citationCount,
      url: n.url, arxiv: n.arxiv, ghost: true, vnScore: 1 - i / rec.length, nearestId: anchor,
    };
  }).filter(Boolean);
} catch (e) {
  console.error("  frontier bake failed (page falls back to live preload):", e.message);
}

await mkdir(dirname(OUT), { recursive: true });
await writeFile(
  OUT,
  JSON.stringify({ nodes, frontier, seededFrom: [...SEEDS, metr.id], builtAt: new Date().toISOString() }),
);

console.log(`wrote ${nodes.length} nodes (${withVec} with embeddings) + ${frontier.length} baked frontier candidates → ${OUT}`);
for (const n of nodes) {
  console.log(`  ${n.year}  ${String(n.refs.length).padStart(3)} refs  vec=${n.vec ? "y" : "n"}  ${n.title.slice(0, 58)}`);
}
