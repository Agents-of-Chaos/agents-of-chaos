// Panel: effective-resistance optimal single-edge addition — the one handshake
// that most shrinks AoC's distance to the whole market, drawn dashed on the map.

import type { PanelModule, RankedRow } from "../../../data/analyses-types";

interface BestNewEdgeData {
  candidates: RankedRow[];
  proposed: { a: string; b: string; label: string }[];
  current: { sumResistance: number; kirchhoff: number; nCore: number; nCandidates: number };
}

const AOC = "agents-of-chaos";

const panel: PanelModule = {
  slug: "best-new-edge",
  render(el, env, ctx) {
    const data = env.data as unknown as BestNewEdgeData;
    if (!data.candidates?.length) {
      ctx.empty(el, "no candidate edges computed");
      return;
    }
    const wrap = ctx.blocks(el);

    ctx.table(
      wrap.block(
        "min(100%, 640px)",
        `every possible new AoC edge, ranked (top-10 of ${data.current.nCandidates})`,
      ),
      {
        rows: data.candidates,
        columns: [
          { key: "label", label: "company", format: "text" },
          { key: "vertical", label: "vertical", format: "text" },
          { key: "persona", label: "who to call", format: "text" },
          {
            key: "dAocPct",
            label: "Δ AoC (%)",
            format: "num",
            digits: 2,
            hint: "% cut in Σ effective resistance from AoC to everyone in the core",
          },
          {
            key: "dGlobalPct",
            label: "Δ global (%)",
            format: "num",
            digits: 2,
            hint: "% cut in the Kirchhoff index (all-pairs resistance) — the network-wide view",
          },
        ],
      },
    );

    const proposedIds = new Set(data.proposed.map((e) => e.b));
    ctx.minimap(
      wrap.block("300px", "the proposed handshakes, dashed (top-3)"),
      "companies",
      {
        extraEdges: data.proposed,
        colorFn: (id) => {
          if (id === AOC) return ctx.colors.accent;
          if (proposedIds.has(id)) {
            const n = ctx.node("companies", id);
            return n ? ctx.colors.group("companies", n.group) : ctx.colors.ink;
          }
          return null;
        },
        radiusFn: (id) => (id === AOC ? 4 : proposedIds.has(id) ? 3.2 : 2.2),
      },
    );
  },
};

export default panel;
