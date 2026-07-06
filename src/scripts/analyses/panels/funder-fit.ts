// Panel: structure's shortlist — a bipartite spectral embedding (collaborative
// filtering over money edges) ranks funders for an AoC-shaped org; the table
// and rank-vs-rank scatter surface where structure disagrees with the rubric.

import type { PanelModule, Point, RankedRow } from "../../../data/analyses-types";

interface FunderFitData {
  ranked: RankedRow[];
  rankRank: Point[];
  seeds: { id: string; label: string }[];
}

const panel: PanelModule = {
  slug: "funder-fit",
  render(el, env, ctx) {
    const data = env.data as unknown as FunderFitData;
    if (!data.ranked?.length) {
      ctx.empty(el, "no embeddable funders in the current graph.");
      return;
    }
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block(
        "min(100%, 720px)",
        `who the wiring nominates — top ${data.ranked.length} of ${data.rankRank.length} embeddable funders`,
      ),
      {
        rows: data.ranked,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          {
            key: "score",
            label: "structure fit",
            format: "num",
            digits: 3,
            hint: "dot product with the virtual AoC position — expected log-dollar mass on an AoC-shaped org",
          },
          {
            key: "rubricRank",
            label: "rubric rank",
            format: "num",
            digits: 0,
            hint: "rank by lane share alone — disagreement with the structure rank is the finding",
          },
          {
            key: "rubricShare",
            label: "lane share",
            format: "pct",
            hint: "share of the funder's log-dollars on agent-security / evals / multi-agent grantees",
          },
          {
            key: "evidence",
            label: "lane evidence",
            format: "text",
            hint: "tracked money edges into AoC-lane grantees: count, disclosed dollars, largest recipients",
          },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.dots(
      wrap.block("min(100%, 560px)", "every embeddable funder, ranked twice — off the diagonal = disagreement"),
      {
        points: data.rankRank,
        graphKey: "funding",
        xLabel: "rank by structure (1 = knock first)",
        yLabel: "rank by rubric (1 = knock first)",
        labelTop: 8,
        quadrants: {
          labels: [
            "structure says knock, rubric shrugs",
            "neither is excited",
            "both say knock",
            "rubric says knock — on 1–2 deals",
          ],
        },
      },
    );

    const seedIds = new Set(data.seeds.map((s) => s.id));
    const kindOf = new Map(data.ranked.map((r) => [r.id as string, String(r.kind)]));
    ctx.minimap(
      wrap.block("300px", "the funding map — lane seeds in red, structure's top 15 in their kind color"),
      "funding",
      {
        colorFn: (id) =>
          seedIds.has(id) ? ctx.colors.accent : kindOf.has(id) ? ctx.colors.group("funding", kindOf.get(id)!) : null,
      },
    );
  },
};

export default panel;
