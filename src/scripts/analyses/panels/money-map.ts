// Panel: the money map — the funding world flattened to 2D from who-pays-whom
// alone (bipartite ASE), the kind misfits, and the domain × kind white space.

import type { Matrix, PanelModule, Point, RankedRow } from "../../../data/analyses-types";

interface MoneyMapData {
  map: Point[];
  misfits: RankedRow[];
  whiteSpace: Matrix;
  declarers: RankedRow[];
}

const panel: PanelModule = {
  slug: "money-map",
  render(el, env, ctx) {
    const data = env.data as unknown as MoneyMapData;
    const wrap = ctx.blocks(el);

    const nFunders = data.misfits.length;
    ctx.dots(
      wrap.block(
        "min(100%, 640px)",
        `the grant economy from wiring alone — ${data.map.length} nodes, funders colored by kind, grantees gray, area = $ through the node`,
      ),
      {
        points: data.map,
        graphKey: "funding",
        labelTop: 9,
        xLabel: "portfolio axis 1 — Coefficient Giving pole ← → SFF/Tallinn pole",
        yLabel: "portfolio axis 2 — ↑ NSF / Cooperative-AI campus pole",
      },
    );

    ctx.matrix(
      wrap.block(
        "min(100%, 420px)",
        "tracked $ by domain × funder kind — blank cells are the white space",
      ),
      {
        ...data.whiteSpace,
        format: "usd",
        scale: "seq",
      },
    );

    ctx.table(
      wrap.block(
        "min(100%, 480px)",
        `the headline's target list: all ${data.declarers.length} grantmakers declaring agent security as a focus — none has a tracked check into it (see "The short list" panel for scored fit)`,
      ),
      {
        rows: data.declarers,
        columns: [
          { key: "label", label: "grantmaker", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          { key: "apply", label: "apply", format: "text", hint: "application mode published by the funder" },
          { key: "checks", label: "checks", format: "num", digits: 0, hint: "tracked money edges in the graph (to any domain)" },
          { key: "routed", label: "routed", format: "usd", hint: "tracked $ out, undisclosed amounts at the median floor" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.table(
      wrap.block(
        "min(100%, 640px)",
        `all ${nFunders} placed funders vs their own kind — off-center = distance from the kind's centroid on the map`,
      ),
      {
        rows: data.misfits,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          { key: "checks", label: "checks", format: "num", digits: 0, hint: "tracked money edges in the graph" },
          { key: "routed", label: "routed", format: "usd", hint: "tracked $ out, undisclosed amounts at the median floor" },
          { key: "offCenter", label: "off-center", format: "num", digits: 2, hint: "distance to the leave-one-out centroid of its own kind" },
          { key: "behavesLike", label: "behaves like", format: "text", hint: "nearest funder on the map" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.minimap(wrap.block("300px", "the full funding graph — people dimmed"), "funding", {
      colorFn: (id) => {
        const n = ctx.node("funding", id);
        if (!n || n.group === "person") return null;
        return ctx.colors.group("funding", n.group);
      },
    });
  },
};

export default panel;
