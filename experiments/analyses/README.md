# /networks/analyses — the compute pipeline

Twelve statistical analyses of the two public graphs (`src/data/companies.json`,
`src/data/funding.json`), in the graphstats lineage (spectral embedding, SBM,
vertex nomination — Priebe/Athreya/Vogelstein school; see *Hands-On Network
Machine Learning*). Modeled on alex-loftus.com/networks/analyses.

## Architecture

```
experiments/analyses/<slug>.py  ×12   PEP-723 uv scripts (graspologic/networkx/numpy)
        │  uv run <slug>.py
        ▼
src/data/analyses/<slug>.json  ×12    baked envelopes {slug, graph, title, sub, headline,
+ shared.json (prep_shared.py)         prose, caveat?, inputs, data} — committed
        │  build-time import
        ▼
src/data/analyses-manifest.ts          validates every envelope (bad bake FAILS the build),
                                       orders panels, computes staleness vs live graphs
        ▼
src/components/AnalysesShell.astro     server-renders ALL prose (crawlable, no-JS readable)
src/scripts/analyses/shell.ts          client draws visualizations only
src/scripts/analyses/archetypes/*      6 shared renderers: table dots bars matrix chain line
                                       (+ minimap in shared.ts) — no d3; layouts are baked
```

The binding rules live in `CONTRACT.md` (envelope, data shapes, voice, determinism).

## Rebake (after either graph changes)

```bash
./experiments/analyses/bake.sh     # prep_shared + all 12 scripts + strict pytest gate
```

Every script is deterministic (seeded, SVD sign-fixed, no wall-clock time):
re-running produces byte-identical JSON. The funding graph changes nightly
(GitHub Action) — the site self-heals display-side (baked labels + build-time
staleness dimming), but rebake to keep the numbers current.

## Tests

```bash
python3 -m pytest experiments/analyses/tests -q       # always-on: schema/leakage/finiteness
ANALYSES_STRICT=1 python3 -m pytest experiments/analyses/tests -q   # bake gate: ids + stamps current
npm test                                              # includes tests/analyses-core.test.mjs
./scripts/screenshot-analyses.sh                      # headless panel screenshots (after npm run build)
```

The always-on tier stays green under graph churn so the funding-nightly PR gate
is never blocked by analyses staleness; the strict tier is the rebake gate.

## Privacy

Inputs are ONLY the two public JSONs (`_shared.py` loaders). The private CRM
overlays never feed this pipeline; pytest + `emit()` + the build validator all
ban the private keys (`warm_path`, `stage`, `notes`).
