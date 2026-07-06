// Panel: Rombach coreness by layer — the prospect quadrant (investor-core,
// business-crust), mean coreness by vertical, and where the 14 rivals rank.

import type { PanelModule, Point, RankedRow } from "../../../data/analyses-types";

interface CorePeripheryData {
  quadrant: Point[];
  byVertical: { label: string; value: number }[];
  rivals: RankedRow[];
  nullTest: {
    pValue: number;
    significant: boolean;
    sigShare: number;
    nRandNets: number;
    spearmanCorenessDegree: number;
  };
}

const panel: PanelModule = {
  slug: "core-periphery",
  render(el, env, ctx) {
    const data = env.data as unknown as CorePeripheryData;
    const wrap = ctx.blocks(el);

    ctx.dots(
      wrap.block(
        "min(100%, 620px)",
        `coreness by layer — the ${data.quadrant.length} companies with both business and shared-investor ties`,
      ),
      {
        points: data.quadrant,
        quadrants: {
          labels: [
            "investor-core, business-crust — prospects",
            "core of both layers",
            "crust of both",
            "business-core, investor-crust",
          ],
        },
        labelTop: 7,
        xLabel: "business-layer coreness",
        yLabel: "shared-investor-layer coreness",
      },
    );

    ctx.bars(wrap.block("min(100%, 360px)", "mean full-graph coreness by vertical"), {
      rows: data.byVertical,
      format: "num",
      annotateTop: 3,
    });

    ctx.table(
      wrap.block(
        "min(100%, 560px)",
        `the 14 rivals (and us) by full-graph coreness — global structure not significant vs the degree-preserving null (p = ${ctx.fmt.num(data.nullTest.pValue, 2)}, ${data.nullTest.nRandNets} rewires)`,
      ),
      {
        rows: data.rivals,
        rankStart: 0, // rows carry their own graph-wide rank column
        columns: [
          { key: "label", label: "company", format: "text" },
          { key: "coreness", label: "coreness", format: "num", digits: 3, hint: "full graph; core block ≥ 0.75, crust ≤ 0.25" },
          { key: "rank", label: "rank", format: "num", digits: 0, hint: "of 186 non-isolated companies, 1 = most core" },
          { key: "business", label: "business", format: "num", digits: 3, hint: "business-edge layer coreness; — = no business edges" },
          { key: "investor", label: "investor", format: "num", digits: 3, hint: "shared-investor layer coreness; — = no shared-investor edges" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );
  },
};

export default panel;
