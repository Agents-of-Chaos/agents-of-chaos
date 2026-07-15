// Questions-on-the-map engine: one state machine per graph page. Owns the
// question lifecycle (enter/exit/re-aim), the ?q= URL param, the engine paint
// channel, and the strip/answer/drawer surfaces. The camera is touched ONLY
// on deliberate acts — question entry (reframe/morph) and exit (exact restore
// of the entry transform); everything else leaves the user's zoom alone.
//
// Seat is DERIVED state: seat = host.getSelected() ?? defaultSeat. Never
// stored separately — deselection resets it by derivation.

import { escapeHtml } from "../../data/network-types";
import { clearAnnotations, renderAnnotations } from "./annotate";
import { aseTargets } from "./defs/networks";
import { clearDrawer, mountDrawer } from "./drawer";
import * as kernels from "./kernels.js";
import { enterMorph, exitMorph } from "./morph";
import { initStrip } from "./strip";
import type {
  QComputeCtx,
  QEdge,
  QNode,
  QuestionDef,
  QuestionEls,
  QuestionEngine,
  QuestionHost,
  QuestionPayload,
  QuestionResult,
} from "./types";

// accent ramp for the lit set (rank 0 darkest); anchors darker still — one
// red family, matching the thumbnail palette so the thumb IS the map
const ANCHOR_FILL = "#a83420";
const LIT_DARK = "#c8442c";
const LIT_LIGHT = "#eec2b2";

function lerpHex(a: string, b: string, t: number): string {
  const pa = parseInt(a.slice(1), 16);
  const pb = parseInt(b.slice(1), 16);
  const ch = (sh: number) => {
    const va = (pa >> sh) & 0xff;
    const vb = (pb >> sh) & 0xff;
    return Math.round(va + (vb - va) * t);
  };
  return `#${((ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).padStart(6, "0")}`;
}

export interface QuestionOpts {
  defaultSeat: string;
  /** dynamic import of the baked questions JSON (caller owns the specifier) */
  payloadLoader: () => Promise<unknown>;
  appendixPath: string;
  /** legacy ?an= slug → ?q= slug, or null → redirect to the methods appendix */
  legacyRedirect: Record<string, string | null>;
  /** pristine records, un-mutated by d3 — the kernels' input */
  raw: {
    companies: { id: string }[];
    edges: { source: string; target: string; type: string; verified?: boolean }[];
  };
}

export function initQuestions(
  host: QuestionHost,
  els: QuestionEls,
  defs: QuestionDef[],
  opts: QuestionOpts,
): QuestionEngine {
  let payload: QuestionPayload | null = null;
  let ctx: QComputeCtx | null = null;
  let activeQ: string | null = null;
  let result: QuestionResult | null = null;
  let entryTransform: { k: number; x: number; y: number } | null = null;
  let morphed = false;
  let pending: string | null = null; // enter() before the payload lands — latest wins
  let thumbTimer = 0;

  els.answer.setAttribute("aria-live", "polite");

  const defOf = (slug: string) => defs.find((d) => d.id === slug);
  const seat = () => host.getSelected() ?? opts.defaultSeat;

  const strip = initStrip(host, els.strip, defs, {
    onToggle(slug) {
      if (activeQ === slug) exit();
      else enter(slug);
    },
    preview(ids) {
      host.setPreview(ids);
    },
  });

  function buildCtx(p: QuestionPayload): QComputeCtx {
    const byId = new Map<string, QNode>(host.nodes.map((n) => [n.id, n]));
    const adjT = new Map<string, QEdge[]>();
    const push = (a: string, e: QEdge) => {
      const l = adjT.get(a);
      if (l) l.push(e);
      else adjT.set(a, [e]);
    };
    for (const e of opts.raw.edges) {
      push(e.source, { to: e.target, type: e.type, verified: e.verified ?? false });
      push(e.target, { to: e.source, type: e.type, verified: e.verified ?? false });
    }
    return {
      payload: p,
      defaultSeat: opts.defaultSeat,
      ids: opts.raw.companies.map((c) => c.id).sort(),
      byId,
      adjT,
      raw: opts.raw,
      kernels,
    };
  }

  /* ---------- visuals (no camera acts in here) ---------- */

  function applyVisuals(def: QuestionDef, res: QuestionResult, s: string): void {
    const litRank = new Map(res.litIds.map((id, i) => [id, i]));
    const anchors = new Set(res.anchorIds);
    const denom = Math.max(1, res.litIds.length - 1);
    host.setQuestionPaint({
      fill(id) {
        if (anchors.has(id)) return ANCHOR_FILL;
        const r = litRank.get(id);
        return r === undefined ? null : lerpHex(LIT_DARK, LIT_LIGHT, r / denom);
      },
      r(id) {
        return anchors.has(id) ? host.radiusOf(id) * 1.25 : null;
      },
      // morph-class questions keep every node visible: the cloud's shape is the answer
      fade: def.noFade ? null : new Set([...res.litIds, ...res.anchorIds, s]),
    });
    host.forceShow(new Set([s, ...res.callouts.map((c) => c.id)]));
    renderAnnotations(host, res);

    const methods = `<a class="q-methods" href="${escapeHtml(opts.appendixPath)}?a=${encodeURIComponent(def.source[0])}">methods →</a>`;
    const seatLine =
      s !== opts.defaultSeat
        ? `<div class="q-seat">answering for <b>${escapeHtml(host.labelOf(s))}</b> · <button type="button" class="q-reset">reset</button></div>`
        : "";
    els.answer.innerHTML = `<span class="q-sentence">${escapeHtml(res.sentence)}</span> ${methods}${seatLine}`;
    els.answer.hidden = false;
    els.answer.querySelector(".q-reset")?.addEventListener("click", () => host.select(null));

    mountDrawer(els.drawer, def, res, {
      onHover: (id) => host.setPreview(id ? new Set([id]) : null),
      appendixPath: opts.appendixPath,
    });
    strip.setActive(def.id);
  }

  function teardownVisuals(): void {
    host.setQuestionPaint(null);
    host.forceShow(null);
    clearAnnotations(host);
    els.answer.hidden = true;
    els.answer.innerHTML = "";
    clearDrawer(els.drawer);
    strip.setActive(null);
  }

  /* ---------- URL (?q= rides along; never touch other params) ---------- */

  function urlSetQ(slug: string): void {
    const u = new URL(location.href);
    u.searchParams.set("q", slug);
    history.replaceState(null, "", u);
  }
  function urlClearQ(): void {
    const u = new URL(location.href);
    if (!u.searchParams.has("q")) return;
    u.searchParams.delete("q");
    history.replaceState(null, "", u);
  }

  /* ---------- enter / exit ---------- */

  function enter(slug: string): void {
    if (!ctx || !payload) {
      pending = slug;
      return;
    }
    const def = defOf(slug);
    if (!def || activeQ === slug) return;
    const wasMorphed = morphed;
    if (activeQ) teardownVisuals(); // switching questions keeps the camera
    else entryTransform = host.zoomTransform(); // first activation: save the exact zoom
    activeQ = slug;
    result = def.compute(seat(), ctx);
    applyVisuals(def, result, seat());

    // deliberate camera acts, only on entry
    if (def.morph) {
      if (wasMorphed) host.fitToIds(null, true);
      else {
        morphed = true;
        void enterMorph(host, aseTargets(payload)).then(() => {
          if (activeQ === slug) host.fitToIds(null, true);
        });
      }
    } else {
      const cam = () => {
        if (activeQ !== slug || !result) return;
        if (def.reframe === "focus") host.fitToIds(result.focusIds.length ? result.focusIds : null, true);
        else if (def.reframe === "all") host.fitToIds(null, true);
      };
      if (wasMorphed) {
        morphed = false;
        void exitMorph(host).then(cam);
      } else cam();
    }
    urlSetQ(slug);
  }

  function exit(): void {
    if (!activeQ) return;
    activeQ = null;
    result = null;
    teardownVisuals();
    const t = entryTransform;
    entryTransform = null;
    const restore = () => {
      if (t) host.setZoomTransform(t, true); // exact restore — never a re-fit
    };
    if (morphed) {
      morphed = false;
      void exitMorph(host).then(restore);
    } else restore();
    urlClearQ();
  }

  /* ---------- thumbnails: recompute on seat change, debounced + idle ---------- */

  function drawThumbs(): void {
    if (!ctx || !payload) return;
    const s = seat();
    const c = ctx;
    strip.drawAll((def) => def.compute(s, c), payload);
  }

  function scheduleThumbs(): void {
    if (!ctx) return;
    strip.setStale(true);
    clearTimeout(thumbTimer);
    thumbTimer = window.setTimeout(() => {
      const run = () => {
        drawThumbs();
        strip.setStale(false);
      };
      if ("requestIdleCallback" in window) requestIdleCallback(run, { timeout: 800 });
      else setTimeout(run, 0);
    }, 150);
  }

  /* ---------- engine surface ---------- */

  const engine: QuestionEngine = {
    onSelectionChange(_id) {
      if (!ctx) return;
      if (activeQ) {
        const def = defOf(activeQ);
        if (def) {
          result = def.compute(seat(), ctx);
          applyVisuals(def, result, seat()); // re-aim: NO camera act
        }
      }
      scheduleThumbs();
    },
    handleEscape() {
      if (!activeQ) return false;
      exit();
      return true;
    },
    active: () => activeQ,
    dossierContext(id) {
      if (!activeQ || !result) return null;
      const i = result.litIds.indexOf(id);
      if (i < 0) return null;
      return `#${i + 1} · ${defOf(activeQ)?.question ?? activeQ}`;
    },
  };

  /* ---------- payload load + deep links ---------- */

  void (async () => {
    try {
      const p = (await opts.payloadLoader()) as QuestionPayload;
      if (!p || p.kind !== "question-data") throw new Error("questions payload malformed");
      payload = p;
      ctx = buildCtx(p);
    } catch (err) {
      console.error("[questions] payload failed to load — questions disabled:", err);
      return;
    }
    drawThumbs();

    const params = new URLSearchParams(location.search);
    const preDeepLink = host.zoomTransform(); // for the qselftest restore check
    const an = params.get("an");
    if (an !== null && an in opts.legacyRedirect) {
      const mapped = opts.legacyRedirect[an];
      if (mapped === null) {
        // appendix-only analysis: hand the visitor to the methods page
        location.replace(`${opts.appendixPath}?a=${encodeURIComponent(an)}`);
        return;
      }
      const u = new URL(location.href);
      u.searchParams.delete("an");
      u.searchParams.set("q", mapped);
      history.replaceState(null, "", u);
      enter(mapped);
    }
    const q = params.get("q");
    if (q && defOf(q)) enter(q);
    if (pending !== null) {
      const want = pending;
      pending = null;
      if (activeQ !== want) enter(want); // a pre-payload click beats the URL
    }

    // dev/test hook: enter → exit must restore the camera bit-for-bit.
    // activeQ is read through active() — TS's IIFE flow analysis can't see
    // the mutation enter() made, and would otherwise "prove" it null here.
    if (params.get("qselftest") === "1" && engine.active()) {
      const pre = preDeepLink;
      setTimeout(() => {
        exit();
        setTimeout(() => {
          const t = host.zoomTransform();
          const ok =
            Math.abs(t.k - pre.k) < 1e-6 && Math.abs(t.x - pre.x) < 1e-6 && Math.abs(t.y - pre.y) < 1e-6;
          if (!ok) {
            const d = document.createElement("div");
            d.textContent = "QSELFTEST FAIL";
            d.style.cssText =
              "position:fixed;left:0;right:0;top:0;z-index:9999;background:#a00;color:#fff;" +
              "font:700 16px Georgia,serif;text-align:center;padding:8px;";
            document.body.appendChild(d);
          }
        }, 1400); // exit's morph-back (650ms) + animated restore (450ms) have settled
      }, 1500);
    }
  })();

  return engine;
}
