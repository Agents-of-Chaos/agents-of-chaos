# /funding — funding landscape map — design

**Status:** approved (2026-07-02, Alex, via plan review). Third sibling to /papers and /networks.

## Goal

A dollar-weighted map of the funding landscape for AI safety and agent security. Public framing: **"find your funder"** — a navigator for researchers and orgs seeking money (open-now status front and center). Private framing (dev-only): AoC's own fundraising intelligence — pipeline stages and warm paths, exactly like /networks' CRM overlay.

## Shape

- **Territory force map** (like /networks): funders pulled into four territories by kind — philanthropy / government / VC / corporate. Grantees settle between their funders via grant edges; program officers hug their funder.
- **Dollars drive the visuals**: node radius = sqrt(field-relevant $) — a funder is sized by what it gives *into this field* per year (NSF counts only AI-safety-relevant awards), a grantee by verified in-field $ received. Edge width = sqrt(grant $). Unknown $ = small dotted-outline node; undisclosed grant = hairline. Dashed = unverified.
- **Views**: map ⇄ directory (kind → program, funders sorted by $/yr, grantees grouped by domain). Snapshot in time — grant history lives in dossiers, no timeline.
- **Controls**: search, funder-kind chips, domain chips, $-floor slider (exponential ramp; hides unknown-$ funders when > 0), **open-now lens** (green ring on funders currently accepting applications — derived from `apply` mode + deadline vs the snapshot date, never the wall clock).
- **Public path finder**: two type-ahead slots, BFS over the full graph (ignores filters), route highlighted in accent red with fit-to-route zoom and an A → x → y → B breadcrumb. Disconnected pair → "No public funding path connects these two."
- **Dossier** (click): money profile (annual $, check range, top grants w/ $, year, source link), how-to-apply (mode badge, deadline, link), publicly-listed people, thesis, domain tags, cross-link `→ /networks?focus=` when the entity is on the company map; dev-only stage/warm-path block.
- **Deep links**: `#f=<id>`, `?view=directory`, `?lens=open`, `?min=USD`.

## Data model

Nodes: `funder` (kind, domains, `annualFieldGivingUSD|null` — non-null **requires** `annualFieldGivingBasis {year, method, sourceUrl}` —, `checkSizeUSD`, `apply {mode, url, deadline, notes, lastVerified}`, `inKind` for credits-not-cash), `grantee` (research-org/university/startup/fieldbuilding), `person` (**publicly-listed roles only**, title + profile link). All nodes: frozen slug ids (never re-derived), `aliases[]` for entity resolution (Open Philanthropy → coefficient-giving), `confidence` → opacity, `sources[]` ≥ 1, `networksId?` validated against companies.json, `priorityRank`, `fieldDollarsUSD` (baked sizing value, regrant-deduped).

Edges: `grant` (funder→grantee; `amountUSD ≠ null ⇒ sourceUrl` — the invariant; `multiYear` amortized; `regrantOf` = payer funder id, the double-count dedup key for SFF/Tallinn, OP→LTFF, FMF←labs), `investment` (vc/corporate→startup), `affiliation` (person→funder, append-only with `current` flag).

`meta`: taxonomy, source registry, pinned annual FX rates, `generatedAt` (drives open-now).

## Pipeline — `experiments/funding/`

Mirrors `build_network.py` (stdlib, fail-loud, meta block) + coauthorship style (`uv run` PEP 723 fetchers, disk-cached `raw/`, `overrides.json` replayed last). Fetchers: Coefficient Giving (fund pages + archived DB; Cloudflare 403s from cloud → real-UA/GH-runner), SFF recommendations table (payer column!), EA Funds CSV API, NSF Awards API (program officers!), ProPublica 990s, Manifund, UK AISI/ARIA pages. Research swarm fills thesis/apply/people/VC evidence — may never invent a $ figure. Build validates: every $ has a live source URL, regrant sums recomputed both ways, `apply.deadline` in the past while mode="rounds" **fails the build**, PRIVATE_KEYS leakage guard, networksId membership. Gates: `pytest experiments/funding/tests` + `funding.ts` build-time re-validation + `npm test` on `funding-core`.

v1 = ~40 funders (16 philanthropy, 8 government, 10 agent-security VCs, 6 corporate programs) with verified dollars; grows nightly.

## Nightly growth

Claude scheduled cloud routine (preferred; GH Actions fallback for Cloudflare-blocked sources): one task/night — re-verify stale apply-status, monthly re-pull, or grow one backlog funder with ≥1 primary source. Build + pytest must pass; opens a PR listing every changed figure with its source. Never touches `private/`, never estimates dollars, never edits ids or companies.json.

## Files

- **Page**: `src/pages/funding.astro`, `src/components/FundingGraph.astro` (overlay island cloned verbatim from NetworkGraph.astro:14-28), `src/scripts/funding-graph.ts`, `funding-directory.ts`, `funding-core.js` (pure: BFS, $ scales, open-now, computeVisible, formatUsd — `tests/funding-core.test.mjs`), `src/data/funding-types.ts`, `funding.ts`, `funding.json`.
- **Edits**: `Base.astro` only (isNetworks → isFullPage; nav link).
- **Pipeline**: `experiments/funding/` per above; `private/funding-overlay.json` (gitignored, dev-only).

## Verification

`npm test` + `npm run build` + pytest green; `grep -r "warm_path\|funding-overlay" dist/` empty; 10 random grants spot-checked against sources; dev shows stage rings / prod shows none; ARIA's July-2026 deadline as the live open-now test case.
