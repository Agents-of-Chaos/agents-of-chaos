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
- Clicking a node with an explainer shows the accent "✦ our explainer" card
  (`public/papers/explainers.json`, keyed by S2 paperId). Nightly workflow generates
  missing explainers; handcrafted ones are never overwritten.

## /networks

Company-landscape map; the private CRM overlay (`private/overlay.json`) is gitignored and
loads **only in `astro dev`** — never ship it.
