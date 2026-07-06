// Panel: the market in latent space (ASE), AoC starred, nearest neighbors.

import type { PanelModule, Point, RankedRow } from "../../../data/analyses-types";

interface MarketMapData {
  map: Point[];
  magnitude: { points: Point[]; pearson_r: number; p: number };
  neighbors: RankedRow[];
}

const panel: PanelModule = {
  slug: "market-map",
  render(el, env, ctx) {
    const data = env.data as unknown as MarketMapData;
    const wrap = ctx.blocks(el);

    ctx.dots(wrap.block("min(100%, 620px)", "the market in latent space (first two ASE dimensions)"), {
      points: data.map,
      star: ["agents-of-chaos"],
      labelTop: 8,
      xLabel: "latent dimension 1",
      yLabel: "latent dimension 2",
    });

    ctx.table(wrap.block("min(100%, 460px)", "AoC's nearest structural neighbors (rivals excluded)"), {
      rows: data.neighbors,
      columns: [
        { key: "label", label: "company", format: "text" },
        { key: "vertical", label: "vertical", format: "text" },
        { key: "distance", label: "distance", format: "num", digits: 3, hint: "euclidean, full latent space" },
        { key: "intensity", label: "intensity", format: "num", digits: 0 },
        { key: "flag", label: "", format: "flag" },
      ],
    });

    ctx.dots(
      wrap.block("min(100%, 520px)", `latent magnitude vs deployment intensity (r=${data.magnitude.pearson_r})`),
      {
        points: data.magnitude.points,
        xLabel: "‖latent position‖",
        yLabel: "deployment intensity (jittered)",
      },
    );
  },
};

export default panel;
