// Panel: Burt structural holes — who brokers the market, on all edges vs
// business edges only, with the brokers accented on the company minimap.

import type { Column, PanelModule, RankedRow } from "../../../data/analyses-types";

interface BrokersData {
  brokers: RankedRow[];
  brokersBusiness: RankedRow[];
}

const COLUMNS: Column[] = [
  { key: "label", label: "company", format: "text" },
  { key: "vertical", label: "vertical", format: "text" },
  { key: "degree", label: "ties", format: "num", digits: 0 },
  {
    key: "constraint",
    label: "constraint",
    format: "num",
    digits: 3,
    hint: "Burt constraint — lower = wider structural hole",
  },
  { key: "effSize", label: "eff. size", format: "num", digits: 1, hint: "nonredundant contacts" },
  { key: "spans", label: "spans", format: "num", digits: 0, hint: "distinct verticals among direct ties" },
  { key: "flag", label: "", format: "flag" },
];

const panel: PanelModule = {
  slug: "brokers",
  render(el, env, ctx) {
    const data = env.data as unknown as BrokersData;
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block("min(100%, 560px)", "widest structural holes — full graph (competitor + investor + business edges)"),
      { rows: data.brokers, columns: COLUMNS },
    );

    ctx.table(wrap.block("min(100%, 560px)", "business edges only — the warm-intro broker list"), {
      rows: data.brokersBusiness,
      columns: COLUMNS,
    });

    const bizIds = new Set(data.brokersBusiness.map((r) => String(r.id)));
    const brokerIds = new Set([...data.brokers, ...data.brokersBusiness].map((r) => String(r.id)));
    ctx.minimap(
      wrap.block("300px", "the brokers on the company map (larger dot = on the business-only list)"),
      "companies",
      {
        colorFn: (id) => {
          if (!brokerIds.has(id)) return null;
          const n = ctx.node("companies", id);
          return n ? ctx.colors.group("companies", n.group) : ctx.colors.accent;
        },
        radiusFn: (id) => (bizIds.has(id) ? 3.4 : brokerIds.has(id) ? 2.6 : 1.8),
      },
    );
  },
};

export default panel;
