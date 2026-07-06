// Panel: supervised-SBM missing edges — unmapped vendor→buyer pairs,
// the 8×8 block base-rate table, and the verification-triage queue.

import type { Matrix, PanelModule, RankedRow } from "../../../data/analyses-types";

interface MissingEdgesData {
  unmapped: RankedRow[];
  triage: RankedRow[];
  blockP: Matrix;
}

const panel: PanelModule = {
  slug: "missing-edges",
  render(el, env, ctx) {
    const data = env.data as unknown as MissingEdgesData;
    const wrap = ctx.blocks(el);

    ctx.table(wrap.block("min(100%, 640px)", "unmapped customer relationships worth checking"), {
      rows: data.unmapped,
      columns: [
        { key: "label", label: "rival vendor", format: "text" },
        { key: "prospect", label: "prospective buyer", format: "text" },
        { key: "vertical", label: "vertical", format: "text" },
        { key: "phat", label: "P̂", format: "num", digits: 4, hint: "SBM block base rate, fit on verified edges only" },
        {
          key: "crossCheck",
          label: "cross-check",
          format: "text",
          hint: "independent pair-level evidence: Adamic–Adar on the co-investor layer (common-neighbor count agrees) and/or ≥2 shared named investors",
        },
        { key: "flag", label: "", format: "flag" },
      ],
    });

    ctx.matrix(wrap.block("min(100%, 420px)", "the base-rate table: P̂(edge) by vertical pair"), {
      ...data.blockP,
      format: "num",
      scale: "seq",
    });

    ctx.table(wrap.block("min(100%, 720px)", "verification triage: unverified edges the model most expects"), {
      rows: data.triage,
      columns: [
        { key: "label", label: "claimed edge", format: "text" },
        { key: "blocks", label: "block pair", format: "text" },
        { key: "type", label: "type", format: "text" },
        { key: "phat", label: "P̂", format: "num", digits: 4, hint: "same fitted base rate, scored on edges held out of the fit" },
        { key: "claim", label: "claim to verify", format: "text" },
      ],
    });
  },
};

export default panel;
