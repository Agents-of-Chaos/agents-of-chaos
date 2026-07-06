// Panel: MASE across the three edge-type layers — shared basis, per-layer
// score matrices (side-by-side heatmaps), and the omnibus cross-lens shift table.

import type { Matrix, PanelModule, RankedRow } from "../../../data/analyses-types";

interface LayerShiftData {
  scores: Matrix;
  shifts: RankedRow[];
  ari: number;
  omniCount: number;
}

const panel: PanelModule = {
  slug: "layer-shift",
  render(el, env, ctx) {
    const data = env.data as unknown as LayerShiftData;
    const wrap = ctx.blocks(el);

    ctx.matrix(
      wrap.block(
        "min(100%, 560px)",
        "how each lens wires the two shared dimensions (R = VᵀAV; green +, red −, each heatmap scaled to its own max)",
      ),
      { ...data.scores, format: "num", scale: "div" },
    );

    if (data.shifts.length) {
      ctx.table(
        wrap.block(
          "min(100%, 560px)",
          `biggest cross-lens role shifts (omnibus embedding, the ${data.omniCount} companies active in all three layers)`,
        ),
        {
          rows: data.shifts,
          columns: [
            { key: "label", label: "company", format: "text" },
            { key: "vertical", label: "vertical", format: "text" },
            {
              key: "shift",
              label: "shift",
              format: "num",
              digits: 3,
              hint: "sum of pairwise distances between the company's three per-layer omnibus positions",
            },
            { key: "widest_gap", label: "widest gap", format: "text" },
          ],
        },
      );
    } else {
      ctx.empty(
        wrap.block("min(100%, 560px)"),
        `only ${data.omniCount} companies have edges in all three layers — too few for a stable shift table.`,
      );
    }
  },
};

export default panel;
