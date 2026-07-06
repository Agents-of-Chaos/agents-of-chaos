// Panel: the doorkeepers — the people whose doors gate verified field money,
// scored on gated dollars x door brokerage. Table, dollar bars per door,
// minimap with the doorkeepers lit.

import type { PanelModule, RankedRow } from "../../../data/analyses-types";

interface Door {
  id: string;
  label: string;
  kind: string;
  gatedUSD: number;
  people: number;
}

interface MoneyBrokersData {
  gatekeepers: RankedRow[];
  doors: Door[];
  counts: { funders: number };
}

const panel: PanelModule = {
  slug: "money-brokers",
  render(el, env, ctx) {
    const data = env.data as unknown as MoneyBrokersData;
    const wrap = ctx.blocks(el);

    // Captions derived from the baked data, never hard-coded — a nightly rebake
    // that shifts the counts must not silently falsify them.
    const nDollar = data.gatekeepers.filter((r) => Number(r.gatedUSD) > 0).length;
    const nBridge = data.gatekeepers.length - nDollar;

    ctx.table(
      wrap.block("min(100%, 900px)", `the doorkeepers — ${nDollar} with verified $ behind their door, plus the ${nBridge} strongest bridges`),
      {
        rows: data.gatekeepers,
        columns: [
          { key: "label", label: "person", format: "text" },
          { key: "role", label: "role", format: "text" },
          { key: "funder", label: "door", format: "text" },
          { key: "gatedUSD", label: "gated $/yr", format: "usd", hint: "the funder's verified annual field giving — null published → $0, flagged" },
          { key: "brokeragePct", label: "brokerage", format: "pct", hint: `percentile of their funder's betweenness among all ${data.counts.funders} funders in the money graph` },
          { key: "unlock", label: "what the door unlocks", format: "text" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.bars(
      wrap.block("min(100%, 380px)", "verified field $/yr behind each door — the strongest bridges publish none"),
      {
        rows: data.doors.map((d) => ({
          id: d.id,
          label: `${d.label} · ${d.people}`,
          value: d.gatedUSD,
        })),
        format: "usd",
      },
    );

    const people = new Set(data.gatekeepers.map((r) => r.id as string));
    const doorKind = new Map(data.doors.map((d) => [d.id, d.kind]));
    ctx.minimap(wrap.block("300px", "the doorkeepers (red) and their doors on the funding map"), "funding", {
      colorFn: (id) =>
        people.has(id)
          ? ctx.colors.accent
          : doorKind.has(id)
            ? ctx.colors.group("funding", doorKind.get(id)!)
            : null,
      radiusFn: (id) => (people.has(id) ? 3.2 : doorKind.has(id) ? 3 : 2.2),
    });
  },
};

export default panel;
