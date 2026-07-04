# /funding nightly growth loop (plan 3 of 3)

**Goal:** the dataset re-verifies and grows without hand-tending: stale apply-statuses get re-checked, fetchers re-pull monthly, and one backlog funder gets researched per night — always landing as a PR, never a push to main.

**Placement decision:** GitHub Actions, not an Anthropic cloud routine. Two reasons, both from Alex's own placement rule: the repo is the deliverable (PRs against it), and coefficientgiving.org 403s datacenter egress while GH runners fetch it fine (same finding as the houses refresh). This is the "only if a Claude scheduled job doesn't make sense" branch — it doesn't, here.

**Implementation:** `.github/workflows/funding-nightly.yml` — cron 09:00 UTC + workflow_dispatch, `anthropics/claude-code-action@v1` (inputs verified against the current action.yml: `prompt` + `claude_args`; git identity configured manually; contents+pull-requests write). Uses the existing `ANTHROPIC_API_KEY` repo secret (set 2026-07-01 for nightly-explainers).

**One task per night, priority order** (encoded in the workflow prompt):
1. **Re-verify** — funders with `apply.lastVerified` > 14 days or a deadline within ±7 days; 3 stalest; live-page truth wins. Edit surface: `enrich/enriched.json` for swarm-sourced funders, `seeds/starter_funding.json` for the original 17.
2. **Monthly re-pull** — on the 1st: `uv run fetch_*.py` (cached, blocked-source tolerant) → rebuild.
3. **Grow** — first entry of `seeds/backlog.json`, researched to the same standard as the enrichment swarm (every $ needs a primary source; people only from staff pages), added to seeds + enriched.json.

**Gates before any PR:** `build_funding.py` → pytest → `npm test` → `npm run build`. Hard rules mirror the build's validators: never invent a $ figure, never touch `private/`, never delete verified records (demote), ids frozen, no direct pushes to main.

**Verification:** trigger once via `workflow_dispatch` after merge; confirm it opens a well-formed PR (or exits green with no changes); check the Actions log shows the gates running.

**Future options (not built):** parse 990-PF PDFs for grant-level philanthropy data; recency-weight grantee sizing; per-fund CG scraping when Cloudflare permits; overlay-stage sync with the /networks CRM.
