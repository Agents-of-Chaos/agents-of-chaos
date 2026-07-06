// Panel: upstream — the ultimate-source ledger (regrant chains collapsed),
// three exemplar money paths, the source/distributor/program table with the
// move for each door, and the grantees credible money converges on.

import type { Chain, PanelModule, RankedRow } from "../../../data/analyses-types";

interface UpstreamData {
  ledger: { rows: { id?: string; label: string; value: number }[] };
  chains: Chain[];
  funders: RankedRow[];
  authorities: RankedRow[];
}

const panel: PanelModule = {
  slug: "upstream",
  render(el, env, ctx) {
    const data = env.data as unknown as UpstreamData;
    const wrap = ctx.blocks(el);

    ctx.bars(wrap.block("min(100%, 420px)", "where the tracked grant dollars originate — regrant chains collapsed"), {
      rows: data.ledger.rows,
      format: "usd",
    });

    ctx.chain(wrap.block("min(100%, 520px)", "three ways a dollar reaches a grantee: tagged regrant, seeded endowment, straight from the source"), {
      chains: data.chains,
    });

    ctx.table(wrap.block("min(100%, 760px)", "the 20 biggest doors: pitch it, cultivate it, or watch its calls"), {
      rows: data.funders,
      columns: [
        { key: "label", label: "funder", format: "text" },
        { key: "cls", label: "class", format: "text", hint: "source = own wealth; distributor = pools/regrants others' money; program = institutional budget" },
        { key: "move", label: "the move", format: "text" },
        { key: "paid", label: "paid $", format: "usd", hint: "tracked grant dollars it paid as the funder of record" },
        { key: "originated", label: "originates $", format: "usd", hint: "tracked dollars that trace back to it after collapsing regrants" },
        { key: "hub", label: "hub", format: "num", digits: 3, hint: "weighted-HITS hub score: does its money land where other credible money lands?" },
        { key: "flag", label: "", format: "flag" },
      ],
    });

    ctx.table(wrap.block("min(100%, 460px)", "where credible money converges — HITS authority grantees"), {
      rows: data.authorities,
      columns: [
        { key: "label", label: "grantee", format: "text" },
        { key: "auth", label: "authority", format: "num", digits: 3, hint: "weighted-HITS authority: how much credible money converges here" },
        { key: "funders", label: "funders", format: "num", digits: 0, hint: "distinct tracked funders granting to this org" },
        { key: "inUsd", label: "tracked $ in", format: "usd" },
      ],
    });
  },
};

export default panel;
