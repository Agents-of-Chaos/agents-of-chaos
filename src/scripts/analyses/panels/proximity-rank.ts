// Panel: personalized PageRank reach from AoC — one wide table (three alpha
// leashes, hops, resistance, bottleneck flags) + minimap shaded by percentile.

import type { PanelModule, RankedRow } from "../../../data/analyses-types";

interface PercentileRow {
  id: string;
  label: string;
  pct: number | null; // null = outside AoC's component (unreachable)
}

interface ProximityRankData {
  reach: RankedRow[];
  percentile: PercentileRow[];
  unreachable: number;
}

const panel: PanelModule = {
  slug: "proximity-rank",
  render(el, env, ctx) {
    const data = env.data as unknown as ProximityRankData;
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block("min(100%, 720px)", "top 25 by walk share, α=.85 (AoC + its 5 direct ties excluded)"),
      {
        rows: data.reach,
        columns: [
          { key: "label", label: "company", format: "text" },
          { key: "vertical", label: "vertical", format: "text" },
          {
            key: "ppr85",
            label: "walk % α=.85",
            format: "num",
            digits: 2,
            hint: "share of a restarting random walk's time — the main ranking",
          },
          {
            key: "ppr50",
            label: "α=.50",
            format: "num",
            digits: 2,
            hint: "short leash: genuine proximity to AoC",
          },
          {
            key: "ppr95",
            label: "α=.95",
            format: "num",
            digits: 2,
            hint: "long leash: hub gravity shows here",
          },
          {
            key: "hops",
            label: "hops",
            format: "num",
            digits: 0,
            hint: "unweighted BFS distance from agents-of-chaos",
          },
          {
            key: "resistance",
            label: "resistance",
            format: "num",
            digits: 2,
            hint: "effective resistance on the reachable core — low means many parallel paths",
          },
          {
            key: "flag",
            label: "",
            format: "flag",
            hint: "resistance rank ≥25 places worse than hop rank: one relationship gates access",
          },
        ],
      },
    );

    const pctById = new Map(data.percentile.map((r) => [r.id, r.pct]));
    ctx.minimap(
      wrap.block(
        "300px",
        `reach percentile — darker red = more walk time; grey = no mapped path (${data.unreachable})`,
      ),
      "companies",
      {
        colorFn: (id) => (pctById.get(id) == null ? null : ctx.colors.accent),
        opacityFn: (id) => {
          const p = pctById.get(id);
          return p == null ? 0.3 : 0.08 + 0.87 * p;
        },
        radiusFn: (id) => {
          const p = pctById.get(id);
          return p == null ? 1.5 : 1.6 + 2.2 * p;
        },
      },
    );
  },
};

export default panel;
