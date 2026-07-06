// Panel: vertex nomination from the 14 competitor-flagged seeds — buyer-side
// prospects, unflagged rival-shaped companies, and the consensus set on the map.

import type { PanelModule, RankedRow } from "../../../data/analyses-types";

interface NominationsData {
  tightness: { seed_mean: number; market_mean: number; ratio: number; null_pctile: number };
  prospects: RankedRow[];
  rivals: RankedRow[];
  percentile: RankedRow[]; // {id, label, pct, consensus}
  seeds: { id: string; label: string }[];
}

const panel: PanelModule = {
  slug: "competitor-nominations",
  render(el, env, ctx) {
    const data = env.data as unknown as NominationsData;
    const wrap = ctx.blocks(el);
    const seedIds = new Set(data.seeds.map((s) => s.id));
    const consensus = new Set(
      data.percentile.filter((r) => r.consensus).map((r) => r.id as string),
    );

    const rankCols = [
      { key: "borda", label: "fused #", format: "num", digits: 0, hint: "Borda-count fusion of all 14 per-seed distance rankings" },
      { key: "rrf", label: "rrf #", format: "num", digits: 0, hint: "reciprocal-rank fusion of the same rankings" },
      { key: "deg", label: "edges", format: "num", digits: 0, hint: "verified edges supporting this nomination" },
      { key: "intensity", label: "intensity", format: "num", digits: 0 },
    ] as const;

    ctx.table(
      wrap.block("min(100%, 700px)", "buyer-side prospects nearest the red-team cluster"),
      {
        rows: data.prospects,
        rankStart: 0, // the fused rank is the rank — no extra counter
        columns: [
          { key: "label", label: "company", format: "text" },
          { key: "vertical", label: "vertical", format: "text" },
          ...rankCols,
          { key: "persona", label: "buyer persona", format: "text" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.table(
      wrap.block("min(100%, 480px)", "rival-shaped but never competitor-flagged"),
      {
        rows: data.rivals,
        rankStart: 0,
        columns: [
          { key: "label", label: "company", format: "text" },
          { key: "vertical", label: "vertical", format: "text" },
          ...rankCols,
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.minimap(
      wrap.block("300px", "consensus top-20 nominees (red) · the 14 seeds (black)"),
      "companies",
      {
        colorFn: (id) =>
          seedIds.has(id) ? ctx.colors.ink : consensus.has(id) ? ctx.colors.accent : null,
        radiusFn: (id) => (seedIds.has(id) ? 3.2 : consensus.has(id) ? 2.8 : 2.2),
        opacityFn: (id) => (seedIds.has(id) || consensus.has(id) ? 0.95 : 0.3),
      },
    );
  },
};

export default panel;
