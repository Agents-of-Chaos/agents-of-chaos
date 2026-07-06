// Panel: intro chains — Yen k-shortest routes from AoC to prospects, majors,
// and funders (via people where the funding graph names one), plus the
// intermediary leaderboard: who to cultivate first.

import type { Chain, NodeRef, PanelModule, RankedRow } from "../../../data/analyses-types";

interface ChainGroup {
  target: NodeRef;
  why?: string; // company targets: where the target came from
  rank?: number; // funder targets: funder-shortlist rank
  kind?: string; // funder targets: funder kind
  role?: string; // person targets: full role at the funder
  via?: string; // person targets: the funder they hang off
  flag?: string; // unreachable note
  chains: Chain[];
}

interface IntroChainsData {
  companyChains: ChainGroup[];
  fundingChains: ChainGroup[];
  personRoutes: ChainGroup[];
  sources: RankedRow[];
  leaderboard: RankedRow[];
  counts: { chains: number; companyChains: number; fundingChains: number; personChains: number };
}

const panel: PanelModule = {
  slug: "intro-chains",
  render(el, env, ctx) {
    const data = env.data as unknown as IntroChainsData;
    const wrap = ctx.blocks(el);

    for (const g of data.companyChains) {
      const block = wrap.block("min(100%, 720px)", `AoC → ${g.target.label} — ${g.why ?? ""}`);
      if (!g.chains.length) ctx.empty(block, g.flag ?? "unreachable.");
      else ctx.chain(block, { chains: g.chains });
    }

    ctx.table(
      wrap.block("min(100%, 420px)", "funding-graph sources: AoC-linked grantees, nearest first"),
      {
        rows: data.sources,
        columns: [
          { key: "label", label: "grantee", format: "text" },
          {
            key: "aocDistance",
            label: "distance to AoC",
            format: "num",
            digits: 0,
            hint: "weighted shortest-path cost in the company graph (business=1, shared-investor=2, competitor=10)",
          },
        ],
      },
    );

    for (const g of data.fundingChains) {
      const block = wrap.block(
        "min(100%, 720px)",
        `→ ${g.target.label} — funder shortlist #${g.rank}, ${g.kind ?? ""}`,
      );
      if (!g.chains.length) ctx.empty(block, g.flag ?? "unreachable.");
      else ctx.chain(block, { chains: g.chains });
    }

    for (const g of data.personRoutes) {
      const block = wrap.block(
        "min(100%, 720px)",
        `→ ${g.target.label} — ${g.role ?? ""}, ${g.via ?? ""} (a named human, not just an org)`,
      );
      ctx.chain(block, { chains: g.chains });
    }

    ctx.table(
      wrap.block(
        "min(100%, 560px)",
        `cultivate first — intermediary appearances across all ${data.counts.chains} chains ` +
          `(${data.counts.companyChains} company, ${data.counts.fundingChains + data.counts.personChains} funding)`,
      ),
      {
        rows: data.leaderboard,
        columns: [
          { key: "label", label: "who", format: "text" },
          { key: "graph", label: "graph", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          {
            key: "appearances",
            label: "on chains",
            format: "num",
            digits: 0,
            hint: "appearances strictly between a chain's source and its target",
          },
        ],
      },
    );
  },
};

export default panel;
