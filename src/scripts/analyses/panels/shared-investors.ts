// Panel: who already funds the 14 rivals, backers per rival, and the
// zero-rival "portfolio twins" (uncontested capital).

import type { PanelModule, RankedRow } from "../../../data/analyses-types";

interface SharedInvestorsData {
  rivalBackers: RankedRow[];
  uncontested: RankedRow[];
  backersPerRival: { id: string; label: string; value: number }[];
}

const panel: PanelModule = {
  slug: "shared-investors",
  render(el, env, ctx) {
    const data = env.data as unknown as SharedInvestorsData;
    const wrap = ctx.blocks(el);

    ctx.table(wrap.block("min(100%, 620px)", "funders with demonstrated appetite (backers of the 14 rivals)"), {
      rows: data.rivalBackers,
      columns: [
        { key: "label", label: "investor", format: "text" },
        { key: "nRivals", label: "rivals", format: "num", digits: 0, hint: "distinct rival portfolio companies" },
        { key: "rivals", label: "which", format: "text" },
        { key: "portfolio", label: "in-map portfolio", format: "num", digits: 0, hint: "mapped companies listing this investor — not the fund's full book" },
        { key: "flag", label: "", format: "flag" },
      ],
    });

    ctx.bars(wrap.block("min(100%, 340px)", "mapped backers per rival (incl. acquirers)"), {
      rows: data.backersPerRival,
      format: "num",
      annotateTop: 3,
    });

    ctx.table(wrap.block("min(100%, 620px)", "uncontested capital: portfolio twins with zero rival exposure"), {
      rows: data.uncontested,
      columns: [
        { key: "label", label: "investor", format: "text" },
        { key: "cosine", label: "cosine", format: "num", digits: 3, hint: "portfolio-vector similarity to its twin" },
        { key: "twin", label: "twin of", format: "text", hint: "the rival-backer it most resembles" },
        { key: "overlap", label: "co-investments", format: "text", hint: "shared mapped portfolio companies with the twin" },
        { key: "portfolio", label: "in-map portfolio", format: "num", digits: 0 },
      ],
    });
  },
};

export default panel;
