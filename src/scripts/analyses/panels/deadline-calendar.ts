// Panel: the deadline calendar — every open funding door at the snapshot,
// ranked by SVD-embedding fit, with the dated deadlines as a survival curve.

import type { PanelModule, RankedRow, Sweep } from "../../../data/analyses-types";

interface Door {
  id: string;
  label: string;
  kind: string;
  status: "dated" | "rolling";
  days: number | null;
}

interface DeadlineCalendarData {
  actionList: RankedRow[];
  calendar: Sweep;
  doors: Door[];
  seeds: { id: string; label: string }[];
}

const panel: PanelModule = {
  slug: "deadline-calendar",
  render(el, env, ctx) {
    const data = env.data as unknown as DeadlineCalendarData;
    if (!data.actionList?.length) {
      ctx.empty(el, "no open doors at this snapshot.");
      return;
    }
    const wrap = ctx.blocks(el);

    const nDated = data.doors.filter((d) => d.status === "dated").length;
    ctx.table(
      wrap.block(
        "min(100%, 760px)",
        `the action list — ${data.actionList.length} of ${data.doors.length} open doors; unscorable rolling doors live on the minimap`,
      ),
      {
        rows: data.actionList,
        columns: [
          { key: "label", label: "funder", format: "text" },
          { key: "kind", label: "kind", format: "text" },
          { key: "closes", label: "closes", format: "text" },
          { key: "days", label: "days", format: "num", digits: 0, hint: "days from the snapshot to the deadline" },
          { key: "door", label: "apply to", format: "text", hint: "current program, read from the funder's application metadata" },
          { key: "checkMid", label: "check (mid)", format: "usd", hint: "midpoint of the published check range" },
          { key: "fit", label: "fit", format: "num", digits: 3, hint: "cosine between the funder's embedding and the mean of AoC-shaped grantees" },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );

    ctx.line(
      wrap.block(
        "min(100%, 460px)",
        `doors still open, read like a survival curve — each step is a dated deadline passing (${nDated} in total)`,
      ),
      { sweep: data.calendar },
    );

    const doorById = new Map(data.doors.map((d) => [d.id, d]));
    ctx.minimap(
      wrap.block("300px", "the funding map — dated doors in red, rolling doors in kind color"),
      "funding",
      {
        colorFn: (id) => {
          const d = doorById.get(id);
          if (!d) return null;
          return d.status === "dated" ? ctx.colors.accent : ctx.colors.group("funding", d.kind);
        },
        radiusFn: (id) => {
          const d = doorById.get(id);
          return d ? (d.status === "dated" ? 3.4 : 2.4) : 2;
        },
      },
    );
  },
};

export default panel;
