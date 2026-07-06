// Panel: the funder shortlist — priority table, field dollars per year,
// mission-vs-recency quadrant. Pure rubric, no graph model.

import type { PanelModule, Point, RankedRow } from "../../../data/analyses-types";

interface FunderShortlistData {
  shortlist: RankedRow[];
  byYear: { rows: { label: string; value: number }[] };
  quadrant: Point[];
}

const panel: PanelModule = {
  slug: "funder-shortlist",
  render(el, env, ctx) {
    const data = env.data as unknown as FunderShortlistData;
    const wrap = ctx.blocks(el);

    ctx.table(wrap.block("min(100%, 700px)", "apply here first — top 12 of 38 funders, flags shown not hidden"), {
      rows: data.shortlist,
      columns: [
        { key: "label", label: "funder", format: "text" },
        { key: "kind", label: "kind", format: "text" },
        { key: "mission", label: "mission", format: "pct", hint: "share of log-weighted grant $ into agent-security / evals grantees" },
        { key: "check", label: "check range", format: "text" },
        { key: "apply", label: "apply", format: "text" },
        { key: "lastActive", label: "last active", format: "num", digits: 0, hint: "latest dated grant in the graph" },
        { key: "flag", label: "", format: "flag" },
      ],
    });

    ctx.bars(wrap.block("min(100%, 340px)", "tracked field dollars per year (44 dated, dollar-stamped grants)"), {
      rows: data.byYear.rows,
      format: "usd",
    });

    ctx.dots(wrap.block("min(100%, 560px)", "every funder: mission fit vs recent money moved (jittered)"), {
      points: data.quadrant,
      graphKey: "funding",
      xLabel: "recency — decayed grant $, log-scaled",
      yLabel: "mission — share of $ that is AoC-shaped",
      labelTop: 7,
      quadrants: {
        labels: [
          "on-mission, no tracked $",
          "on-mission, deploying now",
          "off-mission, quiet",
          "deploying, off-mission",
        ],
      },
    });
  },
};

export default panel;
