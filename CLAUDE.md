# agents-of-chaos.ai — project notes for Claude

Astro 6 static site, deployed by Vercel: **push to `main` = production**, PRs = previews.
Background jobs work in `.claude/worktrees/<name>` and push `HEAD:main` (rebase on
`origin/main` first if rejected). Never commit without `npm test` + `npm run build`.

- `npm run build` — the real gate (Vercel runs this). `npx astro check` currently reports
  15 pre-existing errors (d3 selection generics + `node:fs` types in NetworkGraph.astro);
  they don't block the build — don't count them against your diff, but a cleanup is welcome.
- `npm test` — `node --test` over `tests/` (pure math in `src/scripts/papers-core.js`).
  Update these when the metric/ranking logic changes.
- `SEMANTIC_SCHOLAR_API_KEY` is NOT set in the Vercel env yet (Alex's action) — the
  `api/paper.js` proxy falls back to anonymous S2, which 429s under load. Client code must
  degrade gracefully when S2 is unreachable.

## /papers — behavior contract (user-requested; ask before changing any of these)

- Intro line above the graph: weekly reading group, Thursdays 10am PST, contact email.
- Discover slider = vertex nomination; every tick must reveal **within 100ms** — the first
  via the baked `frontier` in `public/papers.json` + background refresh, later ticks
  synchronously from the ranked pool.
- Click a node → detail panel + focus discovery on that paper (accent ring + glow).
  Shift-click builds a multi-focus set → nominate papers close to **all** of them
  (min-aggregation). Re-aiming re-ranks the held pool locally (instant), network only
  widens recall in the background.
- Escape, clicking empty space, or closing the panel clears the selection (ghosts tuck
  away, slider back to 0; pool kept so the next drag is instant).
- Nomination blends relevance with a **gentle** log-citation nudge (`CITE_WEIGHT = 0.25`);
  relevance stays primary — citations must never flip a clear relevance gap (tested).
- Hovering a node shows title/meta + TL;DR (or abstract lead); hovering an edge explains
  what relates the papers. Tooltip positioning must respect the current zoom transform
  (d3 stores it on the **svg** element `__zoom`, not on `g`).
- Papers a user removes (edit mode) must stay removed *and never be re-nominated*
  (`aoc.papers.removed.v1`); adds persist in `aoc.papers.adds.v1`; export → commit
  `public/papers.json` to publish.
- Clicking a nominated ghost is **inspect-only** (detail panel). A paper joins the set —
  and touches `aoc.papers.adds.v1` — ONLY via an explicit labeled control: the panel's
  "+ add to our reading set", the read-next list's "+ read", or the add-by-id input.
  On reload, the only solid nodes are baked papers plus deliberate adds.
- Clicking a node with an explainer shows the accent "✦ our explainer" card
  (`public/papers/explainers.json`, keyed by S2 paperId). Nightly workflow generates
  missing explainers; handcrafted ones are never overwritten.

## /networks

Company-landscape map; the private CRM overlay (`private/overlay.json`) is gitignored and
loads **only in `astro dev`** — never ship it.

- Never steal the user's zoom (user-requested; applies to the /funding map too): no
  programmatic re-fit except deliberate ones — double-click, view toggles, route zoom,
  window resize. In particular no `sim.on("end", fit)` — d3-force re-fires "end" after
  every drag reheat, which randomly zoomed the map back out (removed 2026-07-12).

The **question strip** (small multiples above the map; replaced the analyses rail
2026-07-15, design: `docs/superpowers/specs/2026-07-15-questions-on-the-map-design.md`)
turns the analyses into plain-English questions answered ON the map. Behavior contract
(user-approved; ask before changing):

- The feature is named **"question"** in all code (`?q=`, `src/scripts/questions/`,
  `src/data/questions/`) — the word "lens" belongs to the competitors/customers chips.
- Question entry/exit are the only new camera acts; **exit restores the exact prior
  zoom transform**. Recompute, thumb hover, and drawer toggles never move the camera.
  The market-shape morph is the ONE thing allowed to move nodes (snapshot restored
  verbatim on exit; `?qselftest=1` red-banners a camera-restore mismatch).
- One Escape ladder, one stratum per press: question → preview spotlight → selection.
- Seat is DERIVED (`selected ?? agents-of-chaos`); selecting any node re-aims the active
  question + all thumbnails. Default-seat numbers come ONLY from baked envelopes
  (via `src/data/questions/questions-companies.json`); live kernels serve non-default
  seats and must reproduce the baked fixtures bit-identically (`npm test` gate).
- Question computations run on the FULL graph; the seat + callout anchors are
  force-shown past filters (path-finder precedent).
- Thumbnails lead with a signature MARK (rings/paths/shape) — recolor alone is
  illegible at 96×64 (P0 spike). Callout boxes reserve space in the label declutter
  and hide their anchors' own labels (double-labeling otherwise).
- Rebake after graph changes: bake.sh runs `prep_questions.py` (infra-owned, panel
  agents never touch it). `?an=<slug>` legacy links redirect (mapped question or the
  methods appendix). Screenshots: `./scripts/screenshot-questions.sh` after a build.
- **Fog-of-war voice** (2026-07-21 audit; applies to ALL question/analysis prose):
  the graphs are public-info only and missingness is publicity-correlated, so
  absence claims are claims about the MAP — scope them ("mapped", "on the map",
  "on record"; funding money: "tracked"); superlatives are map-anchored ("the
  map's least-constrained seat"); hypothetical edges take conditional mood
  ("would cut"); exited stakes take past tense ("has backed … (exited)"). One
  scope word per clause, never hedge-stacked; observed-positive sourced facts
  stay plain. Every question bakes a `blindSpot` line (validator-required,
  rendered in the drawer fine print; embedded facts — e.g. the verified-only #1
  for bridges/best-handshake — are recomputed and assert-pinned at bake, rule 18
  in prep_questions.py). Route ribbons draw per-hop and dash any hop without a
  verified edge (funding affiliations count as sourced) + a marks-note line.

## /networks/analyses

Twelve statistical analyses of both graphs (graphstats school: ASE, SBM, vertex
nomination, PPR, effective resistance). Contract: `experiments/analyses/CONTRACT.md` —
one analysis = 3 files (`experiments/analyses/<slug>.py` → `src/data/analyses/<slug>.json`
→ `src/scripts/analyses/panels/<slug>.ts`). Everything is deterministic (seeded,
SVD-sign-fixed, no wall-clock) — re-running a script must be byte-identical. Inputs are
ONLY the two public JSONs, never the private overlays (pytest + emit() + build validator
all enforce). Rebake after either graph changes: `./experiments/analyses/bake.sh`
(strict pytest gate). The Astro shell SSRs all prose from the baked envelopes; the
manifest validates at build time and computes staleness vs live graphs, so nightly
funding churn dims stale rows (†) instead of breaking. No d3 on this page — archetype
renderers are plain SVG/HTML (`src/scripts/analyses/archetypes/`).

## /funding

Dollar-weighted funder landscape ("find your funder"). Size = sqrt(field-relevant $)
— every non-null $ in src/data/funding.json carries a source URL (validator-enforced);
never add a figure without one. Open-now derives from meta.generatedAt, not the wall
clock. The private overlay (private/funding-overlay.json: stage + warm paths) loads
only in `astro dev` — same rule as /networks. Pure math lives in
src/scripts/funding-core.js (node --test covered); dataset is regenerated by
experiments/funding — node ids are frozen, never re-slugged.

The /funding **question strip** (5 questions, added 2026-07-15) follows the /networks
contract above, plus funding-specific rules: entering a question exits path-finder route
mode and vice versa (mutual exclusion, no camera refit on the handoff); names, dollars,
and apply-status ALWAYS bind from live funding.json at render — baked question data
contributes only ids/scores/ranks (nightly churn dims the strip with † on stamp drift,
and tests/question-funding-degrade.test.mjs fails the nightly PR only if a question
would CRASH rather than degrade); default seat = gray-swan-ai (AoC's funding entry
point — AoC is not a funding node). The funding-nightly
GitHub Action (09:00 UTC) re-verifies stale apply-statuses / re-pulls monthly /
grows one backlog funder, always as a PR gated on build+pytest — never main.
