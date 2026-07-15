# Questions on the map — design

*2026-07-15 · approved by Alex after four rounds of brainstorming Q&A. Implementation plan:
`~/.claude/plans/alright-let-s-make-a-fizzy-quill.md` (reconciled from three parallel Plan-agent
designs: bake pipeline / client engine / risk-and-sequencing).*

## Problem

The twelve statistical analyses (/networks/analyses) answer real business questions — who to
meet, where the market gaps are, which single tie matters most — but they live a page away from
the maps they describe, written in stats vocabulary. A CEO visiting agents-of-chaos.ai gets a
pretty graph and no answers; a researcher gets answers with no way to re-ask them about a
different company. The maps show structure; they don't perform inference in front of you.

## Vision (one paragraph)

Above each map sits a strip of small multiples — postage-stamp renderings of the same graph, each
captioned only by a plain-English question. Click "who bridges the market?" and the big map
becomes the answer: brokers glow, everything else recedes, the one-sentence answer and two or
three callouts are written on the canvas itself. Click any company — or type your own company's
name — and every question re-answers from that seat: the whole strip becomes twelve simultaneous
statements about *you*. The evidence is one drawer away; the mathematics one page further. No
chrome, no jargon, no dashboard: a map you interrogate.

## Decisions (all approved, with the reasoning)

| Decision | Choice | Why |
|---|---|---|
| Primary user | Truly dual, layered | One surface, two reading depths (Tufte micro/macro): CEO reads the sentence, researcher expands the method. |
| Old analyses page | Slims to methods appendix | Findings live on the map (one home per fact); prose/method/citations stay SSR'd for SEO and rigor. |
| CEO takeaway | A name + a reason · a market picture · their own position | Action, understanding, self-interest. (Credibility arrives as a side effect, not a goal.) |
| Paradigm | Lenses ∪ ask-the-map, unified | Every lens IS its question — one system, no dual vocabulary. Not scrollytelling, not dossier-first. |
| Lens grammar | All four: recolor/resize/fade · words-on-canvas · new marks · deliberate reframe | Tufte: integrate words, numbers, pictures on one canvas. Reframe only on explicit activation (route-zoom precedent); the no-zoom-stealing contract holds for everything passive. |
| Re-aiming | Core feature | Seat = selected node (derived state, `seat = selected ?? AoC`). Cheap kernels recompute live; expensive answers pre-baked per node. |
| Switcher | Small-multiples strip | The thumbnail is evidence, not decoration: all answers' shapes visible at once. |
| Thumbnails on re-aim | All recompute | Twelve simultaneous statements about one protagonist — the research superpower and the CEO payoff. |
| Re-aim trigger | Auto on select + "find your company" search | The natural gesture is the trigger; Escape steps back. |
| Depth ladder | Canvas sentence → evidence drawer → methods appendix | Drawer reuses the existing archetype renderers; footer link "how was this computed? →". |
| Curation | 8 questions /networks, 5 /funding | Overlapping analyses merged (intro-chains + proximity → "who should we meet first?"); layer-shift + shared-investors appendix-only. |
| Default state | No question active | The map stays the hero; questions are an offer, not an ambush. `?q=` deep links. |
| Naming | None — just the questions | Maximum restraint: no header, no feature name, no UI vocabulary to learn. |
| Mobile | Functional, simplified | Chip scroller, recolor + sentence + bottom-sheet drawer; thumbnails and canvas annotations desktop-only. |
| Dossier | One context line + "ask from here" | Lens-aware fact ("#3 of 25 bridges"), nothing more — the dossier is already dense. |
| Morph lens | In — the showpiece | "What does the market really look like?" animates nodes to measured-similarity positions and back. The only lens that moves nodes; the transition itself announces the exception. |

## The 13 questions

**/networks:** Who should we meet first? · Which single handshake matters most? · Who bridges
the market? · Which ties should exist but don't? · Where is the market empty? · Who runs the
core — who's still outside? · Who else looks like a rival? · What does the market really look
like?

**/funding:** Which funders should we apply to now? · Who funds our rivals? · Who can introduce
us to a funder? · Which funders are within reach? · Who gatekeeps the money?

## Engineering reconciliation (the calls that shape the code)

1. **The feature is named "question" in all code** (`?q=`, `src/scripts/questions/`,
   `src/data/questions/`). "Lens" is already taken by the competitors/customers chips and
   `?lens=open`; it never appears in new code.
2. **No linear algebra in the browser.** The one expensive re-aim (effective-resistance best
   handshake) ships as pre-baked per-seat top-10 rankings for every core node; the quantized-L⁺
   Sherman–Morrison scheme was designed, measured feasible, and cut anyway — prebake gives
   identical answers with zero cross-language float risk.
3. **Default-seat numbers are never recomputed** — they render from the baked envelopes verbatim.
   Live kernels serve only non-default protagonists and must reproduce bake-emitted fixtures
   exactly (`node --test`).
4. **Facts bind live at render** on /funding: names, dollars, apply-status always come from the
   current funding.json; baked question data contributes only scores/ranks. On snapshot drift,
   rank claims drop and the † staleness treatment appears. The nightly Action never rebakes
   (BLAS differences would break byte-identical determinism).
5. **Sentence = HTML bar; marks and callouts = SVG inside the zoomed root** (pan/zoom/PNG-export
   for free; `__zoom` read from the svg element). Default sentences are also SSR'd — SEO keeps
   parity with today's crawlable prose.
6. **Escape ladders, one keydown handler per page**: funding `route → question → preview →
   selection`; networks `question → preview → selection`. (Consolidating networks' current
   double-listener is a prerequisite fix.)
7. **Full-graph compute, force-shown anchors** (path-finder precedent): filters never change an
   answer; they only hide context, and the seat + callout anchors stay visible.
8. **Kill-spikes before build**: thumbnail readability at 96×64, morph park/tween/byte-exact
   restore, canvas annotation legibility, JS/Python kernel parity. Each has a named fallback
   (glyph chips · crossfade · caption bar · all-prebaked); failures narrow the design instead of
   stalling it.

## Out of scope (recorded so we don't relitigate)

Scrollytelling/guided tour (rejected in Q&A) · what-if edge editing (future) · per-node baked
sentences (template scheme instead) · nightly rebaking (forbidden) · funding-side effective
resistance (near-tree graph; BFS answers it) · a second dashboard page (everything lives on the
maps or in the appendix).
