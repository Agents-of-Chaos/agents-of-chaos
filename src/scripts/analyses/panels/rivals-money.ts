// Panel: rival money — the cross-graph join. Who already funds our 14 flagged
// rivals (conflict AND proven appetite), the clean-target list, and the rivals
// whose money we cannot see. Tables + join chains, no model.

import type { Chain, PanelModule, RankedRow } from "../../../data/analyses-types";

interface RivalsMoneyData {
  rivalBackers: RankedRow[];
  joins: Chain[];
  cleanTargets: RankedRow[];
  unmapped: RankedRow[];
}

const panel: PanelModule = {
  slug: "rivals-money",
  render(el, env, ctx) {
    const data = env.data as unknown as RivalsMoneyData;
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block(
        "min(100%, 920px)",
        "checkbooks with rival exposure — conflict and appetite are the same fact",
      ),
      {
        rows: data.rivalBackers,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "backed", label: "rivals backed", format: "text", hint: "→ marks a position that already exited to an acquirer" },
          { key: "conflict", label: "positions", format: "text" },
          {
            key: "usd",
            label: "tracked $",
            format: "usd",
            hint: "verified dollar edges into rivals; led-round edges carry the round total, not the fund's own check",
          },
          { key: "door", label: "door", format: "text", hint: "apply state on the funding map" },
          { key: "read", label: "the read", format: "text" },
        ],
      },
    );

    ctx.chain(
      wrap.block(
        "min(100%, 620px)",
        "the join, drawn as edges — solid = verified money edge on the funding graph; dashed = investor listed on the company card only",
      ),
      { chains: data.joins },
    );

    ctx.table(
      wrap.block(
        "min(100%, 720px)",
        "appetite without conflict — tracked money into agent-security / evals, zero rival positions",
      ),
      {
        rows: data.cleanTargets,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          {
            key: "usd",
            label: "$ into the lane",
            format: "usd",
            hint: "disclosed grant + investment dollars into grantees tagged agent-security or evals",
          },
          { key: "backed", label: "backs", format: "text" },
          { key: "door", label: "door", format: "text" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.table(
      wrap.block(
        "min(100%, 720px)",
        "rivals whose money we cannot see — intel gaps to verify",
      ),
      {
        rows: data.unmapped,
        rankStart: 0,
        columns: [
          { key: "label", label: "rival", format: "text" },
          { key: "who", label: "listed investors (company graph)", format: "text" },
          { key: "note", label: "status", format: "text" },
        ],
      },
    );
  },
};

export default panel;
