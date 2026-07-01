# /networks priority bar + top-20 edge audit — design

**Status:** implemented (2026-07-01).

## Goal

As CEO of Agents of Chaos, know **which nodes to learn about first**. Add a "bar at the top" that shows only the highest-priority companies and reveals more as you widen it. Then **empirically audit the edges** of the top-20 so the map's most-important nodes are accurate.

## The metric — `priorityRank`

"We-should-care-about-it-ness", ranked 1..N-1 (1 = highest); Agents of Chaos itself is 0 (the anchor, always shown). Chosen from three options the user saw ranked on real data — **customers-first**, **competitors-first**, **interleave** — the user picked **interleave**, **public**.

Interleave = zipper two sorted streams 1:1:
- **customers/hubs**: `cust_score = 0.75·(intensity/5 if likely-customer else 0) + 0.25·centrality`
- **competitors**: `comp_score = 0.6 + 0.4·centrality`

so the ranking spans both market and competition (top-20 ≈ 10 customers + 10 rivals). Baked in `build_network.py` (a unique-permutation is asserted), stored as `Company.priorityRank`. **Named `priorityRank`, not `priority`** — `priority` is a private overlay (CRM) key guarded by the leakage test; the collision fails the build.

## The bar

A range slider ("start here") at the top of the controls. `matches()` shows a company iff `priorityRank === 0 || priorityRank <= N` (ANDed with search / vertical / lens filters). Default N = all (drag left to focus). Applies to **both** map and directory. `#k` rank shows in the dossier + directory rows only while engaged. `?priority=N` deep link. Public — built from already-public customer/competitor signals, neutral framing.

Edge case (fixed): if the pinned node is filtered out, `applyFilter` calls `select(null)` — otherwise the dossier lingers for an off-map company and the highlight dims to a ghost.

## The edge audit

A 20-agent workflow (sonnet, websites + web search) audited every edge of the top-20: verdict per existing edge (confirmed / refuted / uncertain, with a source) + missing edges to other mapped companies (sourced, confidence-rated). Result: **0 refuted**, 7 inferred→solid, **+94 new sourced edges**. Applied at build via `experiments/networks/edge_audit.json` (`confirm` → set verified, `add` → new verified edge), *before* priority so the new ties feed centrality. Provenance (with source URLs) in `experiments/networks/audits/top20_edge_audit.json`.

## Files

`build_network.py` (priority + audit application), `edge_audit.json` + `audits/` (new), `network-types.ts`/`companies.ts` (`priorityRank`), `networks-graph.ts` (slider, matches gate, dossier rank, deep link, unpin fix), `networks-directory.ts` (`rankOf`), `NetworkGraph.astro` (bar markup + CSS), `test_network_data.py` (unique-permutation test).

## Verification

pytest (priorityRank permutation, competitor set, subcategory validity, leakage guard) + `astro build` + headless screenshots (map/directory focused to top-20, the ghost-scenario fix) + a 2-reviewer adversarial pass (found the pinned-node ghost bug + a11y gaps, all fixed).
