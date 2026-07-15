# Panel contract — /networks/analyses

One panel = one method = one agent = exactly THREE files. You may not create, edit, or
delete anything else. No git commands. No `pip install`. No writes into `_derived/`.

```
experiments/analyses/<slug>.py           # compute (PEP-723 header, run with `uv run <slug>.py`)
src/data/analyses/<slug>.json            # output of running your .py (committed, minified)
src/scripts/analyses/panels/<slug>.ts    # panel module (ES module, archetype composition)
```

Paths are relative to the repo root. The page shell, sidebar, CSS, archetype renderers,
loader, and validators already exist — your panel module composes archetypes; your JSON
feeds both the server-rendered prose and your renderer.

## Audience & voice (IMPORTANT)

Readers are the people IN these graphs: founders, funders, and ML-literate operators in
the AI-agent ecosystem — plus Agents of Chaos itself using the page as a market instrument.
Each panel is partly an **explainer of graph statistics for ML people**. `prose.how`
teaches your method in 3–6 plain sentences anchored to concepts they know (embeddings,
similarity search, ablations, PageRank, seeds/nomination as "recommendation from examples").
One good analogy beats three equations. The full technical name + citation goes in
`prose.method` (the collapsible "for the curious" note), nowhere else. `prose.intro` states
the business question in 2–3 sentences. Tufte rules: the headline states the FINDING with
the key number in `<strong>`; direct labels over legends; no decoration.

Honesty is part of the voice: if a result rests on thin data (AoC's own node has only 5
edges, all to rivals; many funding attributes are missing), say so in `caveat` and show
flags in the table rather than hiding rows.

## Python compute contract

Template (copy the header; add per-method deps as needed):

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "networkx", "scipy", "graspologic==3.4.4"]
# ///
"""<slug> — one line. Run: cd experiments/analyses && uv run <slug>.py"""
import json
from _shared import load_companies, load_funding, emit   # loaders + envelope enforcement

companies = load_companies()   # dict: the public src/data/companies.json (NEVER the private overlay)
funding = load_funding()       # dict: the public src/data/funding.json
```

Finish with `emit(payload)` — it validates the envelope, forbids NaN, minifies, size-caps,
writes `src/data/analyses/<slug>.json`, and prints the OK line. Envelope:

```python
payload = {
  "slug": "<slug>",                  # == your filename stem
  "graph": "companies",              # "companies" | "funding" | "both" → sidebar section
  "title": "<short sidebar label>",
  "sub": "<one-line sidebar teaser>",
  "headline": "…finding sentence with <strong>key number</strong>…",
  "prose": {"intro": "<p>…</p>", "how": "<p>…</p>", "method": "<p>…</p>"},
  "caveat": "optional honest-data note (omit if none)",
  "inputs": {"companies": {"nodes": 188, "edges": 492}},   # stamps for graphs you used —
                                      # use _shared.stamp(companies) / stamp(funding)
  "data": { ... }                    # named blocks from the standard shapes below
}
```

Hard rules:
- ALL randomness seeded. graspologic embeds: pass `svd_seed=0`. numpy: `default_rng(0)`.
  scipy `svds`: pass a deterministic `v0` — `random_state=` CRASHES on this scipy/numpy
  combo (verified). Fix SVD sign ambiguity (flip each component so its max-|loading| entry
  is positive; `_shared.fix_signs`). Re-running must produce byte-identical output.
- Every node id you ship inside `data` must exist in the source graph — assert it
  (`_shared` exposes `company_ids` / `funding_ids`).
- Ship LABELS next to ids (`{"id": …, "label": …}`) — the frontend must render even after
  a node leaves the live graph.
- Ranked lists: pre-sorted, top-N only, N ≤ 25 rows per table.
- Numbers rounded to what the reader needs (coords 4 decimals, scores 3).
- Inputs are ONLY the two public JSONs via `_shared` loaders. Private overlay keys
  (`warm_path`, `stage`, `notes`) must never appear — pytest bans them.
- Liberal asserts on intermediate shapes; fail fast and loud.

## Standard data shapes (the only vocabulary inside `data`)

- **rows**: `[{"id"?: str, "label": str, <metric>: number|string|bool|null, …}, …]`
  pre-sorted. `null` renders as "—". Add `"flag": "<short note>"` for imputed/caveated rows,
  `"stale"?` never (computed at build time, not by you).
- **points**: `[{"id": str, "label": str, "x": float, "y": float, "group"?: str, "r"?: float}, …]`
  `group` = vertical id (companies) or funder-kind id (funding) → palette color.
- **matrix**: `{"rows": [str], "cols": [str], "cells": [[number|null]]}` — or small
  multiples: `{"rows", "cols", "layers": [{"label": str, "cells": [[…]]}]}`.
- **chains**: `[{"score"?: number, "nodes": [{"id","label","graph"?}], "edges": [{"label"?: str, "verified"?: bool}]}, …]`
  (`edges[i]` joins `nodes[i]→nodes[i+1]`; len(edges) == len(nodes)-1 — asserted).
- **sweep**: `{"x": [number], "xLabel"?: str, "series": [{"label": str, "y": [number|null]}], "annotate"?: {"x": number, "text": str}}`

Name your blocks descriptively: `data.nominees`, `data.map`, `data.blockMatrix`, …
Your panel TS knows its own block names; the shapes let you reuse the archetypes.

## Shared derived data

`experiments/analyses/_derived/` (gitignored) holds expensive shared artifacts written by
`prep_spectral.py` (ASE positions, SBM fits, Laplacian pseudoinverse). Read-only for panel
scripts; if you need something else, compute it privately in your own script.

## Panel module contract (TypeScript)

```ts
// src/scripts/analyses/panels/<slug>.ts
import type { PanelModule } from "../../../data/analyses-types";

const panel: PanelModule = {
  slug: "<slug>",
  render(el, env, ctx) {
    // el: the panel's empty .an-viz div (cleared + re-invoked on resize; read el.clientWidth)
    // env: your <slug>.json envelope (env.data = your blocks)
    // ctx: AnalysesCtx — archetypes, colors, fmt, tooltip, hover bus, minimap, node lookup
    const wrap = ctx.blocks(el);                    // flex-wrap block container
    ctx.table(wrap.block("min(100%, 560px)"), { rows: env.data.nominees, columns: [...] });
    ctx.minimap(wrap.block("300px"), "companies", { colorFn: id => ... });
  },
};
export default panel;
```

Rules:
- Compose the archetypes (`ctx.table/dots/bars/matrix/chain/line/minimap`) — do NOT write
  bespoke d3 unless no archetype fits, and then import d3 SUBMODULES only (`d3-selection`,
  `d3-scale`, …), never `import * as d3 from "d3"`.
- No `<style>` tags, no font-family, no page-level CSS. Pinned classes for text:
  `an-axis`, `an-label`, `an-note`. Colors from `ctx.colors` only.
- Hover: archetypes already publish/subscribe the one-id hover bus — no wiring needed.
  If you draw bespoke marks, call `ctx.hover.set(id)` / subscribe via `ctx.hover.on(fn)`.
- Empty data: archetypes no-op; if your primary block is empty, call `ctx.empty(el, "…")`.

## Question data (infra-owned — panel agents: hands off)

`prep_questions.py` is NOT a panel and is exempt from the three-file rule: it is
an infra emitter that runs AFTER the panel loop in bake.sh, because its default
answers are copied from the just-baked envelopes (single source of truth). It
writes `src/data/questions/questions-<graph>.json` (data for the on-map
questions UI on /networks and /funding) and `src/data/questions/fixtures.json`
(JS kernel-parity oracles), validated by `_shared.emit_questions()`, by
`tests/test_question_data.py`, and at build time by `src/data/questions.ts`.

- Panel agents never create, edit, or depend on these files. Everything above
  this section is unchanged.
- Rebake trigger: any change to a source graph or a sibling envelope.
  `./experiments/analyses/bake.sh` already reruns prep_questions.py after the
  panel loop — it is the only sanctioned way to refresh question data.
- Inputs are ONLY the public graph JSONs, the baked envelopes in
  `src/data/analyses/`, and `src/data/analyses/shared.json`. Same privacy rules
  as `emit()`, plus `priority` joins the banned-key list.
- The client-side JS kernels must reproduce the Python kernels bit-for-bit.
  The twelve determinism rules (1-10 graph/constraint/ppr, 11 sbmRank,
  12 rivalOrbit) live in prep_questions.py's module docstring;
  fixtures.json is the parity oracle (node --test asserts exact id order and
  float equality against it).

## Definition of done (ALL must pass)

1. `cd experiments/analyses && uv run <slug>.py` exits 0, prints the OK line.
2. Re-run: byte-identical (`git diff --stat` shows your JSON unchanged on 2nd run).
3. `npx tsc --noEmit -p .` introduces no NEW errors (14 pre-existing TS2347 in papers-graph.ts).
4. `python3 -m pytest experiments/analyses/tests -q` passes.
5. Self-review against this contract; final message = headline + honest caveats
   (verify agents adversarially re-check; do not oversell).
