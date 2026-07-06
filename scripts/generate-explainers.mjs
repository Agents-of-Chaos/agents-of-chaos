// generate-explainers.mjs — nightly auto-explainer generation for /papers.
//
// For every paper in public/papers.json that doesn't yet have an explainer (per
// public/papers/explainers.json), ask Claude for a grounded one-page summary and template
// it into a self-contained, site-styled page under public/papers/explainers/<slug>.html —
// the same cream/Palatino/#a00 look as the hand-built METR explainer, minus the bespoke
// interactive figure. The manifest is what the /papers detail panel reads to surface the
// "read the explainer" affordance.
//
// Runs locally (`node scripts/generate-explainers.mjs`) or nightly in CI
// (.github/workflows/nightly-explainers.yml). Idempotent: skips papers already in the
// manifest. Needs ANTHROPIC_API_KEY; without it, it logs and exits 0 (CI stays green).
//
// Grounding: the model is told to use ONLY the provided title/abstract/tldr and never
// invent specifics, and every page is labelled "auto-generated from the abstract".

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PAPERS = join(ROOT, "public/papers.json");
const OUT_DIR = join(ROOT, "public/papers/explainers");
const MANIFEST = join(ROOT, "public/papers/explainers.json");
const MODEL = process.env.EXPLAINER_MODEL || "claude-opus-4-8";
const API = "https://api.anthropic.com/v1/messages";

const readJSON = (p, fallback) => (existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : fallback);
const esc = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const slugOf = (p) => (p.arxiv ? `arxiv-${p.arxiv}` : p.id).replace(/[^a-z0-9._-]/gi, "-");

const SYSTEM = `You write one-page explainers of academic papers for "Agents of Chaos", a research group that red-teams multi-agent AI systems and runs a weekly multi-agent-safety paper reading group.

Rules:
- Ground EVERYTHING only in the title, abstract, and TL;DR provided. Never invent numbers, results, datasets, or claims that aren't in that text. If the abstract doesn't say something, don't assert it.
- Plain, precise, Tufte-minimal prose. No hype, no marketing, no "it's not X, it's Y" constructions, no em-dashes, no rhetorical questions as filler.
- Where natural, note why the work matters for AI agents / multi-agent safety, but do not overclaim a connection that isn't there.
- Return ONLY a single JSON object, no prose around it, matching exactly:
{
  "headline": string,            // <= 12 words, a crisp title (may be a question); not just the paper title
  "lede": string,                // 1-2 sentences, plain-language what-and-why
  "keypoints": string[],         // 3-5 short bullets, the load-bearing takeaways
  "sections": [                  // 3-4 sections
    { "label": string,           // 2-4 word small-caps kicker, e.g. "the problem"
      "title": string,           // short section title
      "body": string[] }         // 1-2 short paragraphs
  ],
  "takeaway": string             // one-sentence bottom line
}`;

function userPrompt(p) {
  return `Paper title: ${p.title}
Authors: ${(p.authors || []).join(", ")}
Year: ${p.year ?? "n/a"} | Citations: ${p.citationCount ?? 0}
TL;DR: ${p.tldr || "(none provided)"}
Abstract: ${p.abstract || "(none provided)"}

Write the explainer JSON.`;
}

async function callClaude(paper) {
  const res = await fetch(API, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1800,
      system: SYSTEM,
      messages: [{ role: "user", content: userPrompt(paper) }],
    }),
  });
  if (!res.ok) throw new Error(`Anthropic ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const data = await res.json();
  const text = (data.content || []).map((b) => b.text || "").join("");
  const json = text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1);
  return JSON.parse(json);
}

function renderHTML(p, c) {
  const idLabel = p.arxiv ? `arXiv:${p.arxiv}` : "source";
  const authors = (p.authors || []).slice(0, 6).join(", ") + ((p.authors || []).length > 6 ? " et al." : "");
  const keypoints = (c.keypoints || []).map((k) => `<li>${esc(k)}</li>`).join("");
  const sections = (c.sections || []).map((s, i) => `
      <section>
        <span class="label"><span class="num">${String(i + 1).padStart(2, "0")}</span> ${esc(s.label)}</span>
        <h2>${esc(s.title)}</h2>
        ${(s.body || []).map((para) => `<p>${esc(para)}</p>`).join("\n        ")}
      </section>`).join("");
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>${esc(c.headline)} — explainer · Agents of Chaos</title>
<style>
:root{--bg:#fffff8;--fg:#111;--muted:#666;--muted-2:#888;--rule:#ccc;--rule-soft:#e6e2d6;--accent:#a00;--accent-soft:#fef0f0;--ink2:#2a4d69;--ok:#1f5c3a;--font:'Palatino','Palatino Linotype','Book Antiqua','Georgia',serif;--mono:'Menlo','Consolas',monospace;}
*{margin:0;padding:0;box-sizing:border-box;}
html{background:var(--bg);scroll-behavior:smooth;}
body{font-family:var(--font);background:var(--bg);color:var(--fg);line-height:1.55;-webkit-font-smoothing:antialiased;}
.wrap{max-width:820px;margin:0 auto;padding:0 1.6rem 5rem;}
.masthead{position:sticky;top:0;z-index:50;background:rgba(255,255,248,.92);backdrop-filter:blur(4px);display:flex;justify-content:space-between;align-items:baseline;gap:1rem;padding:.7rem 1.6rem .6rem;border-bottom:1px solid var(--rule-soft);font-variant:small-caps;letter-spacing:.13em;font-size:.74rem;max-width:820px;margin:0 auto;}
.masthead .left{color:var(--accent);}
.masthead .left a{color:var(--accent);text-decoration:none;}
.masthead .sep{color:var(--muted-2);margin:0 .5em;}
.masthead .right{color:var(--muted-2);}
.masthead .right b{color:var(--fg);}
.hero{padding:2.8rem 0 1.3rem;border-bottom:1px solid var(--rule);margin-bottom:.4rem;}
.kicker{font-variant:small-caps;letter-spacing:.2em;font-size:.72rem;color:var(--muted-2);margin-bottom:.9rem;}
.hero h1{font-size:clamp(2rem,4.6vw,3rem);font-weight:normal;font-variant:small-caps;letter-spacing:.02em;line-height:1.04;margin-bottom:.6rem;color:var(--accent);}
.hero .sub{font-size:1.14rem;font-style:italic;color:var(--muted);max-width:48ch;line-height:1.4;}
.hero .paper{margin-top:1rem;font-size:.92rem;color:var(--fg);}
.hero .meta{margin-top:.5rem;font-size:.76rem;font-variant:small-caps;letter-spacing:.1em;color:var(--muted-2);}
.hero .meta a{color:var(--ink2);}
.glance{display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;margin:1.4rem 0 0;padding:.7rem 0;border-top:1px solid var(--rule-soft);border-bottom:1px solid var(--rule-soft);font-size:.8rem;color:var(--muted);}
.glance b{color:var(--fg);}
.keypoints{margin:1.6rem 0;padding-left:0;list-style:none;}
.keypoints li{position:relative;padding-left:1.2rem;margin-bottom:.5rem;max-width:70ch;}
.keypoints li::before{content:"▸";color:var(--accent);position:absolute;left:0;}
section{margin:2.4rem 0;}
.label{font-variant:small-caps;letter-spacing:.2em;font-size:.74rem;color:var(--accent);display:block;margin-bottom:.5rem;}
.label .num{color:var(--muted-2);margin-right:.45em;}
h2{font-size:1.45rem;font-weight:normal;letter-spacing:-.005em;margin-bottom:.8rem;line-height:1.14;}
p{margin-bottom:.85rem;max-width:70ch;}
.takeaway{margin:2rem 0 0;padding:.9rem 1.1rem;border-left:3px solid var(--accent);background:var(--accent-soft);font-size:1.05rem;line-height:1.45;}
.takeaway .lab{font-variant:small-caps;letter-spacing:.14em;font-size:.66rem;color:var(--accent);display:block;margin-bottom:.2rem;}
a{color:var(--ink2);}
.foot{margin-top:3rem;padding-top:1.3rem;border-top:1px solid var(--rule);font-size:.78rem;color:var(--muted-2);line-height:1.6;}
.foot b{color:var(--muted);font-style:normal;}
.foot .rg{color:var(--accent);font-style:italic;}
.foot .auto{font-style:italic;}
</style>
</head>
<body>
<header class="masthead">
  <span class="left"><a href="/papers"><b>Agents of Chaos</b></a><span class="sep">/</span>reading-group explainer</span>
  <span class="right">paper<span class="sep">·</span><b>${esc(idLabel)}</b></span>
</header>
<div class="wrap">
  <div class="hero">
    <div class="kicker">What we're reading · an explainer</div>
    <h1>${esc(c.headline)}</h1>
    <p class="sub">${esc(c.lede)}</p>
    <p class="paper">${esc(p.title)}</p>
    <p class="meta">${esc(authors)} &nbsp;·&nbsp; ${p.year ?? ""} &nbsp;·&nbsp; <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(idLabel)} ↗</a></p>
    <div class="glance">
      <span>${p.year ?? "—"}</span>
      <span><b>${p.citationCount ?? 0}</b> citations</span>
      <span><b>${(p.refs || []).length}</b> references</span>
      ${p.arxiv ? `<span><a href="https://arxiv.org/abs/${esc(p.arxiv)}" target="_blank" rel="noopener">arXiv:${esc(p.arxiv)}</a></span>` : ""}
    </div>
  </div>
  <ul class="keypoints">${keypoints}</ul>
  ${sections}
  <div class="takeaway"><span class="lab">the bottom line</span>${esc(c.takeaway)}</div>
  <div class="foot">
    <span class="auto">Auto-generated from the paper's abstract by Claude (${esc(MODEL)}); grounded in the source text, but read the paper itself for specifics.</span><br>
    <b>Source.</b> <a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a><br>
    <span class="rg">Read with us.</span> One multi-agent-safety paper every Thursday, 10am PST — <a href="mailto:contact@agents-of-chaos.ai">contact@agents-of-chaos.ai</a>.
  </div>
</div>
</body>
</html>
`;
}

async function main() {
  const onlyId = process.argv[2]; // optional: generate a single paper by id (for testing)
  const papers = readJSON(PAPERS, { nodes: [] }).nodes || [];
  const manifest = readJSON(MANIFEST, {});
  if (!process.env.ANTHROPIC_API_KEY) {
    console.log("ANTHROPIC_API_KEY not set — nothing to generate. (Set it as a repo secret to enable nightly runs.)");
    return;
  }
  mkdirSync(OUT_DIR, { recursive: true });

  const todo = papers.filter((p) => (onlyId ? p.id === onlyId : !manifest[p.id]) && (p.abstract || p.tldr));
  console.log(`${papers.length} papers · ${Object.keys(manifest).length} already have explainers · ${todo.length} to generate${onlyId ? ` (single: ${onlyId})` : ""}`);

  let made = 0;
  for (const p of todo) {
    const slug = slugOf(p);
    try {
      process.stdout.write(`  · ${p.title.slice(0, 54)} … `);
      const content = await callClaude(p);
      const html = renderHTML(p, content);
      writeFileSync(join(OUT_DIR, `${slug}.html`), html);
      manifest[p.id] = {
        url: `/papers/explainers/${slug}.html`,
        title: content.headline,
        kind: "auto",
        generatedAt: new Date().toISOString(),
      };
      made++;
      console.log("ok");
    } catch (e) {
      console.log(`FAILED: ${String(e.message || e).slice(0, 160)}`);
    }
  }
  // stable-sort the manifest by key so diffs are clean
  const sorted = Object.fromEntries(Object.entries(manifest).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(MANIFEST, JSON.stringify(sorted, null, 2) + "\n");
  console.log(`\n${made} explainer(s) generated · manifest now lists ${Object.keys(sorted).length}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
