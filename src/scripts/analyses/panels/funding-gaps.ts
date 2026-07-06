// Panel: the missing checks — RDPG link prediction over the money graph.
// Top predicted-missing grants, dashed on the funding map; warm doors for
// AoC-shaped work; and the holdout-validation curve that keeps us honest.

import type { PanelModule, RankedRow, Sweep } from "../../../data/analyses-types";

interface FundingGapsData {
  predicted: RankedRow[];
  warm: RankedRow[];
  aucSweep: Sweep;
  proposed: { a: string; b: string }[];
  stats: {
    nGrants: number;
    nInvestments: number;
    nFunders: number;
    nGrantees: number;
    nCandidates: number;
    nActiveFunders: number;
    d: number;
    auc: number;
    aucHard: number;
    aucInv: number;
  };
}

const panel: PanelModule = {
  slug: "funding-gaps",
  render(el, env, ctx) {
    const data = env.data as unknown as FundingGapsData;
    if (!data.predicted?.length) {
      ctx.empty(el, "no predicted gaps computed");
      return;
    }
    const { stats } = data;
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block(
        "min(100%, 660px)",
        `the ${data.predicted.length} most overdue checks — absent pairs ranked by link score (top of ${stats.nCandidates.toLocaleString()})`,
      ),
      {
        rows: data.predicted,
        columns: [
          { key: "funder", label: "funder", format: "text" },
          { key: "label", label: "predicted grantee", format: "text" },
          {
            key: "score",
            label: "score",
            format: "num",
            digits: 3,
            hint: "SVD link score, relative: 1.000 = the strongest predicted gap",
          },
          {
            key: "funders",
            label: "backers now",
            format: "num",
            digits: 0,
            hint: "funders that already back this grantee in the graph",
          },
          { key: "why", label: "why plausible", format: "text" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    const involved = new Set<string>();
    for (const e of data.proposed) {
      involved.add(e.a);
      involved.add(e.b);
    }
    ctx.minimap(
      wrap.block("300px", "the predicted checks, dashed on the funding map"),
      "funding",
      {
        extraEdges: data.proposed,
        colorFn: (id) => {
          if (!involved.has(id)) return null;
          const group = ctx.node("funding", id)?.group;
          return group ? ctx.colors.group("funding", group) : ctx.colors.accent;
        },
      },
    );

    ctx.table(
      wrap.block(
        "min(100%, 620px)",
        "warm doors for AoC-shaped work — predicted checks into agent-security / evals / multi-agent grantees",
      ),
      {
        rows: data.warm,
        columns: [
          { key: "funder", label: "funder", format: "text" },
          { key: "label", label: "predicted grantee", format: "text" },
          { key: "score", label: "score", format: "num", digits: 3 },
          { key: "apply", label: "apply", format: "text", hint: "the funder's application mode" },
          { key: "why", label: "why plausible", format: "text" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.line(
      wrap.block(
        "min(100%, 460px)",
        `the validation curve — hide ⅕ of the ${stats.nGrants} grants, can the model find them? (AUC, 0.5 = coin flip)`,
      ),
      { sweep: data.aucSweep },
    );
  },
};

export default panel;
