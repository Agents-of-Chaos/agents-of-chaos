# /funding — funder-landscape data pipeline

Builds the dataset behind `agents-of-chaos.ai/funding`: a map of funders supporting AI safety and governance research — foundations, governments, and venture capital backing the research, infrastructure, and institutions that matter.

- **Node** = a funder or grantee. **Color** = funder kind (philanthropy, government, VC, corporate).
  **Size** = sqrt(field-relevant annual dollars verified against structured sources).
- **Edges** = three types: `grant` (funder → grantee), `investment` (VC → startup), `affiliation` (person → org).
  Verified edges draw solid; unverified (swarm output without sourceUrl) draw dashed.

## Two layers

| layer | file | committed? | shipped? |
|-------|------|-----------|----------|
| public funder map | `src/data/funding.json` | yes | yes |
| private CRM (stage + warm paths) | `private/funding-overlay.json` | **no (gitignored)** | **dev only** |

The private overlay is read in `src/components/FundingGraph.astro` (or similar) only under `import.meta.env.DEV`, so a production build cannot contain it. `pytest` enforces the leakage guard.

## Pipeline

```
seeds/funders_v1.json
      ↓
 [fetchers — parallel waves]
 fetch_eafunds.py / fetch_nsf.py / fetch_sff.py / fetch_propublica.py
 fetch_manifund.py / fetch_gov_uk.py / fetch_coefficient.py
      ↓
 raw/normalized_*.json (cached HTTP + deduplicated records)
      ↓
 build_funding.py
   └─ load seeds
   └─ entity-resolve (grantees ≥$250k → nodes)
   └─ FX (GBP 1.27, EUR 1.08; keep amount_original)
   └─ merge enrich/enriched.json (swarm output)
   └─ derive fieldDollarsUSD + priorityRank
   └─ apply overrides.json
   └─ validate + emit
      ↓
 src/data/funding.json + meta (source registry, fx, counts)
```

## Rebuild

```bash
# 1. Fetch (parallel waves; this Mac for residential egress; no commits)
uv run fetch_eafunds.py && uv run fetch_nsf.py
uv run fetch_sff.py && uv run fetch_propublica.py
uv run fetch_manifund.py && uv run fetch_gov_uk.py && uv run fetch_coefficient.py

# 2. Build
uv run build_funding.py

# 3. Validate
pytest experiments/funding/tests/

# 4. See it locally (loads private overlay too)
npm run dev   # localhost:4321/funding
```

## Source registry

Each source yields standardized records. Fetchers must handle transient failures gracefully
(cache reuse with STALE warning; 403/429 tolerated). Every dollar figure carries a source URL
by construction.

| source | what | access | via | record types |
|--------|------|--------|-----|--------------|
| EA Funds | LTFF + other EA funds | public CSV API | `funds.effectivealtruism.org/api/grants` | grant, funder_total |
| NSF | Safe Learning-Enabled Systems + AI safety keyword | public API | `resources.research.gov/common/webapi/awardapisearch-v1.htm` | grant, person |
| SFF | Recommendations table (Round, Source, Organization, Amount) | public HTML | `survivalandflourishing.fund/recommendations` | grant, person (via "Source" → regrantOf) |
| ProPublica | Org totals by EIN lookup | public explorer | `projects.propublica.org/nonprofits/` | org_totals (medium confidence; PDFs not parsed) |
| Manifund | Public grants pages + Next.js data | public pages + data | `manifund.org` | grant, person, regrant |
| gov.uk (AISI/ARIA) | Round totals, deadlines, backer lists | public pages | `gov.uk/AISI`, `aria.org.uk` | funder_total, round metadata |
| Coefficient | Fund pages + archived open-philanthropy DB | public pages + archive | `coefficientgiving.org/funds`, `github.com/rufuspollock/...` | grant, org_totals |

## Files

- `seeds/funders_v1.json` — the 38-funder seed set (17 existing + 21 new); ids frozen.
  Structure: `{id, name, aliases, funderKind, networksId?, sourceHints}`.
- `seeds/backlog.json` — growth queue for future rounds (6 candidates).
- `fetch_*.py` — PEP 723 headers (`uv run`); httpx + stdlib (html.parser where HTML).
  Each emits `raw/normalized_<source>.json` and prints a terse report.
- `raw/` — cached HTTP responses (committed) + `normalized_*.json` outputs.
- `enrich/enriched.json` — swarm output: per-funder thesis, apply metadata, people, checkSize; every claim carries sourceUrl.
- `overrides.json` — human corrections applied last (optional; e.g., legal name fixes).
- `build_funding.py` — stdlib only. Loads seeds, normalizes, entity-resolves, applies FX, merges swarm, derives $USD + rank, validates, emits.
- `tests/test_funding_data.py` — pytest gate: schema validation, FX correctness, regrant deduplication, frozen-id preservation, private-key leakage guard, networksId membership.

## Iron rules

1. **NEVER a dollar figure without a source URL.** Structured sources only; swarm $ only with sourceUrl at ≤ medium confidence.
2. **IDs are frozen once emitted.** Never re-slug an id; use aliases if name changes.
3. **Regrants are deduplicated.** `regrantOf` edge prevents double-counting when both the re-grantor and grantee appear as nodes.
4. **Private overlay stays private.** `import.meta.env.DEV` guard enforced by pytest; no leakage to production builds.
