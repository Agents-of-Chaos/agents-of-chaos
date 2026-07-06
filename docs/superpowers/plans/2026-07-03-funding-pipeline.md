# /funding data pipeline (plan 2 of 3)

**Goal:** Replace the hand-seeded starter `src/data/funding.json` with ~40 funders whose dollars are verified against structured sources, plus the grantees/people/edges those sources yield. Nightly loop is plan 3.

**Mode note:** lives in `experiments/funding/` — leaner plan than plan 1 (contracts + invariants, not step-by-step code). Hard gates unchanged: `pytest experiments/funding/tests` + `funding-validate.ts` at `npm run build` + `npm test`.

**Pattern sources:** `experiments/networks/build_network.py` (stdlib build, fail-loud, meta block, terse report) · `~/loftusa.github.io/experiments/coauthorship/build_graph.py` (PEP 723 + `uv run`, `cached_get` disk cache, overrides replayed last).

## Layout

```
experiments/funding/
  README.md            # two-layer table, rebuild steps, source registry
  seeds/funders_v1.json # the 40 funders below (ids FROZEN; existing 17 starter ids reused verbatim)
  seeds/backlog.json    # growth queue (plan 3)
  fetch_eafunds.py  fetch_nsf.py  fetch_sff.py  fetch_propublica.py
  fetch_manifund.py fetch_gov_uk.py fetch_coefficient.py
  raw/                  # cached HTTP responses (committed) + normalized_<source>.json
  enrich/enriched.json  # swarm output: thesis/apply/people/checkSize per funder, per-claim sourceUrl
  overrides.json        # human corrections, applied LAST
  build_funding.py      # stdlib only: merge → resolve → FX → derive → validate → emit src/data/funding.json
  tests/test_funding_data.py  # pytest gate
```

## Fetcher contract (all seven)

PEP 723 header (`uv run`, deps: httpx only; stdlib html.parser where HTML). Each:
1. `cached_get(url, key)` → disk cache in `raw/` (re-runs are offline; 429/403 → backoff, then reuse last cache with a STALE warning, never crash).
2. Emits `raw/normalized_<source>.json`: `{ "source": "<name>", "fetched": ISO, "records": [...] }` where each record is one of:
   - grant: `{funder_hint, grantee_name, amount_usd|null, amount_original?{value,currency}, year, program?, source_url, payer_hint?}` (payer_hint from SFF's "Source" column → regrantOf)
   - funder_total: `{funder_hint, year, amount_usd, method, source_url}`
   - person: `{name, title, funder_hint, profile_url, source_url}`
3. Prints a terse report: records by type, $ coverage, cache hits.

Sources (access verified 2026-07-02): EA Funds CSV API `funds.effectivealtruism.org/api/grants` (filter LTFF) · NSF Awards API (queries: program "Safe Learning-Enabled Systems", keyword sets "AI safety", "adversarial machine learning" — field-relevant slice ONLY; capture poName as person records) · SFF recommendations HTML table (Round|Source|Organization|Amount|Receiving Charity|Purpose) · ProPublica Nonprofit Explorer v2 (search by org name → EIN → org totals; save the name→EIN resolution in raw/ for audit; PDFs NOT parsed — org totals only, medium confidence) · Manifund public pages/Next data (grants + regrantors) · gov.uk/AISI/ARIA pages (round totals, deadlines, backers as funder_total records) · Coefficient Giving fund pages + archived DB github.com/rufuspollock/open-philanthropy-grants (real UA; 403 tolerated → archive fallback).

## v1 funder seeds (~40; kind · id · $-verifier)

Existing 17 keep their ids. New (23): philanthropy — `jaan-tallinn` (SFF payer sums), `ai-risk-mitigation-fund`, `longview-philanthropy`, `founders-pledge-gcr` (990/site), `cooperative-ai-foundation` (**kind change: also a funder** — joint calls; stays a grantee node too? NO — see edge case below), `halcyon-futures`, `safe-ai-fund` (null-$ likely), `craig-newmark-philanthropies`; government — `darpa` (USAspending: AI Cyber Challenge), `iarpa` (TrojAI), `nist-caisi`, `ukri-epsrc` (GtR API), `eu-horizon` (CORDIS); vc — `ballistic-ventures` ($360M cyber Fund II), `syn-ventures`, `yl-ventures` (networksId yl-ventures), `cyberstarts` (networksId cyberstarts), `a16z` (networksId andreessen-horowitz-a16z; Promptfoo seed/A participation), `redpoint-ventures` (Irregular co-lead); corporate — `google-deepmind` (networksId google-deepmind; joint $10M call), `microsoft-afmr` (networksId microsoft-ai if exists — VERIFY, else none), `aws-programs` (Alignment Project backer). Each seed: `{id, name, aliases, funderKind, networksId?, sourceHints{}}`. networksId values MUST be grep-verified against companies.json before committing seeds.
Cooperative-AI-Foundation edge case: it is BOTH grantee (receives Macroscopic $15M) and funder (joint call). Model stays single-node `kind: "grantee"` in v1 with the joint call credited to its backers — revisit if CAIF grants appear in sources.

## build_funding.py

Stdlib only. Steps: load seeds (assert frozen ids ⊇ current funding.json funder ids) → load normalized_*.json → entity-resolve (exact id → aliases → norm() loose; unresolved grantees ≥ $250k become grantee nodes, below dropped with report line) → FX (pinned `{year: 2025, GBP: 1.27, EUR: 1.08}`, keep amount_original) → merge enrich/enriched.json (structured $ ALWAYS beats swarm $; swarm $ only with sourceUrl at ≤ medium confidence) → derive `fieldDollarsUSD` (funder = annualFieldGivingUSD ?? 0; grantee = Σ verified inbound, multiYear amortized, regrant-deduped via regrantOf) + priorityRank (unique; funders by field-$ × apply-openness, VCs interleaved) → apply overrides.json → validate (mirror EVERY funding-validate.ts rule + regrant sums recomputed both ways + PRIVATE_KEYS leakage guard) → emit with meta (source registry, fx, counts) → terse report (counts, unverified edges, null-$ funders, stalest lastVerified).

## tests/test_funding_data.py (pytest gate)

Mirrors `experiments/networks/tests/test_network_data.py`: every validate rule as a test over the EMITTED file; `test_no_private_keys_in_public`; `test_every_dollar_has_source`; `test_regrant_no_double_count` (recompute independently); `test_frozen_ids` (all previous funding.json ids still present); `test_overlay_ids_subset` (private/funding-overlay.json ids ⊆ nodes, skipped if file absent); `test_networksid_membership`.

## Enrichment swarm

Approved plan step: research swarm via the Workflow tool (discover→enrich→verify, as /networks was built). Per-funder: thesis (their words), apply {mode,url,deadline,notes}, publicly-listed people (staff-page URL required), checkSize — every claim carries sourceUrl; NEVER a dollar figure without one; verify pass refutes/demotes. Output `enrich/enriched.json`.

## Execution order

1. Seeds + README (verify networksIds) — commit.
2. Fetchers in parallel waves (disjoint files, no-commit contract; controller commits): wave A {eafunds, nsf}, {sff, propublica}, {manifund, gov_uk, coefficient}. Run LIVE from this Mac (residential egress; CG may still 403 → archive fallback is in-contract).
3. build_funding.py + pytest suite — sequential, gates green on the fetched data (pre-enrichment: apply/thesis fields carried over from starter for the 17, defaults for new).
4. Enrichment swarm (Workflow) → enriched.json → rebuild → pytest.
5. `npm test` + `npm run build` + browser eyeball (map legibility at ~40 funders; every dossier spot-check 10 random grants against sourceUrls) → commit → push (same PR #29).

## Verification

pytest green · both validators green · 10-grant source spot-check · regrant recomputation match · map legible (labels declutter, territories hold at 40 funders) · directory groups sane · lens rings real deadlines (ARIA/AISI live data) · no private leakage (grep) · PR diff review before push.
