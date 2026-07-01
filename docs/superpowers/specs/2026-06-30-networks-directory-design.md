# /networks directory view — design

**Status:** implemented (2026-06-30). Grounded in a data classification of all 188 companies.

## Goal

The `/networks` map is spatial; scanning it to answer two business questions is slow. Add a **text directory** companion (inspired by alex-loftus.com/networks/affiliations) that makes two things obvious at a glance:

1. **Who are our direct competitors?**
2. **Where are paths to potential customers?**

## Shape

- **View toggle** inside `/networks`: `map ⇄ directory` (keeps the force map + PNG download; adds a second view). No new page/nav entry.
- **Directory** = the 8 existing verticals as sections → "what they do" **sub-categories** → companies as compact text rows (name, intensity dot, markers). Multi-column, dense, Tufte-style.
- Row click → the existing dossier panel (reused; carries the dev-only warm path).
- Search + vertical filter chips still apply; the directory re-renders from the same visible set.

## The two goals, concretely

- **Competitors = a cross-cutting flag, not a bucket.** Classification showed genuine red-teaming rivals scattered across sub-categories (CalypsoAI under guardrails, Robust Intelligence, Protect AI, Patronus, Promptfoo, TrojAI). So `competitor: true` is a per-company flag (14 companies incl. Irregular). A **competitors lens** collapses the directory to just them, in accent red, wherever they sit.
- **Customers = public rule + private path.** A company is a *likely customer* when its sub-category is buyer-heavy (`isBuyer`) **and** deployment intensity ≥ 4. A **likely-customers lens** shows them grouped by vertical, each with its **buyer persona** (public: "who to talk to"). In `npm run dev` the private overlay adds the **warm-intro path** inline; a prod build ships neither the overlay nor any warm string.

## Data model

- `Company.subcategory: string` (required) — bucket key within the vertical.
- `Company.competitor?: boolean` — direct-competitor flag.
- Canonical taxonomy: `experiments/networks/subcategories.json` (`{vertical: [{key,label,isBuyer,what}]}`), single source of truth. `build_network.py` reads it, validates every company's subcategory against its vertical's keys, and bakes the table into `companies.json` `meta.subcategories`. The frontend reads `meta.subcategories` (no second source).

## Files

- **Data/pipeline:** `subcategories.json` (new), `build_network.py` (pass-through + validation + meta), `raw/companies_raw.json` (subcategory + competitor tags), `companies.json` (regenerated).
- **Types/validation:** `network-types.ts` (`subcategory`/`competitor` on `Company`, `SubcategoryMeta`/`SubcategoryTable`), `companies.ts` (build-time subcategory assert; exports `subcategories`).
- **View:** `networks-directory.ts` (new — pure renderer: grouped list + markers, no graph state), `networks-graph.ts` (view/lens state, `?view=`/`?lens=` deep links, reuse of select/search/filter), `NetworkGraph.astro` (toggle + lens chips + `#net-directory` + CSS).
- **Tests:** `test_network_data.py` (subcategory validity per vertical, competitor set == expected 14, meta.subcategories coverage, leakage guard intact).

## Verification

pytest (14 companies competitor set, subcategory validity, leakage guard) + `astro build` + headless screenshots of directory / competitors lens / customers lens / dev warm paths + a bundle grep proving zero private strings ship.

## Taxonomy (data-grounded)

`security-eval-vendor`: agent-red-team\*, runtime-guardrails, aisec-platform, agent-eval, frontier-safety-evals, assurance-monitoring (\* = AoC's bucket). Other verticals bucket by function (coding / support / voice / sales / vertical-domain / general-computer-use / platforms for agent-native; payment-rails / banks / neobanks / finance-ops / consumer for fintech; scribes / RCM / clinical / patient / care-ops for healthcare; etc.). Full table in `subcategories.json`.
