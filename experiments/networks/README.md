# /networks — company-landscape data pipeline

Builds the dataset behind `agents-of-chaos.ai/networks`: a map of companies
building or deploying AI agents — AoC's potential customers, partners,
competitors, and the surrounding ecosystem.

- **Node** = a company. **Color** = vertical. **Size** = deployment intensity
  (0–5: how central agents are to what they do = how much they need red-teaming).
- **Edges** = three researchable ties: `business` (built-on / partner / customer),
  `shared-investor`, `competitor`. Verified ties draw solid; AI-inferred draw dashed.

## Two layers

| layer | file | committed? | shipped? |
|-------|------|-----------|----------|
| public landscape | `src/data/companies.json` | yes | yes |
| private CRM (warm paths + pipeline stage) | `private/overlay.json` | **no (gitignored)** | **dev only** |

The private overlay is read in `src/components/NetworkGraph.astro` only under
`import.meta.env.DEV`, so a production build (the only thing deployed) cannot
contain it. `pytest` enforces the leakage guard.

## Rebuild

```
# 1. research swarm (discover → enrich → verify) → raw records
#    (run via the Workflow tool; save its result to:)
experiments/networks/raw/companies_raw.json

# 2. assemble + derive edges + validate → public dataset
python3 experiments/networks/build_network.py

# 3. validate the output
pytest experiments/networks/tests

# 4. see it
npm run dev    # localhost:4321/networks  (loads the private overlay too)
```

## Files

- `build_network.py` — dedupe, derive the 3 edge types, validate, write
  `src/data/companies.json`. Shared-investor edges are capped (`SHARED_INV_CAP`)
  so a mega-fund doesn't turn the map into a hairball.
- `tests/test_network_data.py` — schema + leakage-guard validation of the output.
- `raw/companies_raw.json` — the swarm output (input to the build).

The schema + display metadata (verticals, colors, stages) live in
`src/data/network-types.ts`; the runtime validation mirror is in
`src/data/companies.ts`.
