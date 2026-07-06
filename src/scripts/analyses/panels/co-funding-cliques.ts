// Panel: co-funding packs — Leiden communities on the funder co-funding
// projection, the observed-vs-expected pack ledger, the same-pack lift, and
// the entry pack (with open doors) for AoC.

import type { Matrix, PanelModule, RankedRow } from "../../../data/analyses-types";

interface CoFundingCliquesData {
  members: RankedRow[];
  ledger: Matrix;
  entry: RankedRow[];
  packTies: { a: string; b: string }[];
  stats: {
    lift: number;
    sameRate: number;
    crossRate: number;
    nPacks: number;
    nCoFunders: number;
    nMovers: number;
    nFunders: number;
    entryPack: string;
    entryShort: string;
  };
}

const panel: PanelModule = {
  slug: "co-funding-cliques",
  render(el, env, ctx) {
    const data = env.data as unknown as CoFundingCliquesData;
    if (!data.members?.length) {
      ctx.empty(el, "no co-funding pairs in the current graph.");
      return;
    }
    const s = data.stats;
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block(
        "min(100%, 640px)",
        `who runs with whom — all ${s.nCoFunders} funders with at least one co-funding partner, grouped by pack (entry pack first)`,
      ),
      {
        rows: data.members,
        rankStart: 0,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "pack", label: "pack", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          { key: "door", label: "door", format: "text", hint: "how you apply" },
          { key: "ties", label: "pack ties", format: "num", digits: 0, hint: "pack-mates it shares at least one grantee with" },
          { key: "orgs", label: "shared orgs", format: "num", digits: 0, hint: "distinct grantees shared with pack-mates" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.matrix(
      wrap.block(
        "min(100%, 460px)",
        "the pack ledger: log10 of observed ÷ degree-expected co-funding — green = the packs seek each other out; blank = never co-fund; tiny packs get big diagonals",
      ),
      { ...data.ledger, format: "num", scale: "div" },
    );

    ctx.table(
      wrap.block(
        "min(100%, 640px)",
        `the entry pack — ${s.entryPack.replace(/^the /, "")}: same-pack pairs co-fund at ${Math.round(100 * s.sameRate)}% vs ${Math.round(100 * s.crossRate)}% across packs, so land one and the rest warm up`,
      ),
      {
        rows: data.entry,
        rankStart: 0,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "door", label: "door", format: "text" },
          { key: "check", label: "check range", format: "text" },
          { key: "why", label: "why this door", format: "text" },
        ],
      },
    );

    const entryIds = new Set(data.entry.map((r) => r.id as string));
    const kindOf = new Map(data.members.map((r) => [r.id as string, r.kind as string]));
    ctx.minimap(
      wrap.block("320px", "the entry pack on the funding map (red; dashed = shared-grantee ties); other pack members colored by kind"),
      "funding",
      {
        colorFn: (id) =>
          entryIds.has(id)
            ? ctx.colors.accent
            : kindOf.has(id)
              ? ctx.colors.group("funding", kindOf.get(id)!)
              : null,
        radiusFn: (id) => (entryIds.has(id) ? 3.4 : kindOf.has(id) ? 2.8 : 2.2),
        extraEdges: data.packTies,
      },
    );
  },
};

export default panel;
