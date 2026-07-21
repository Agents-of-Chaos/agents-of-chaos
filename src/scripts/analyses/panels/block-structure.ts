// Panel: eight verticals on paper — SBM block rates per edge layer, Leiden
// resolution sweep (K + ARI), and the mis-shelved companies at the plateau.

import type { Matrix, PanelModule, RankedRow, Sweep } from "../../../data/analyses-types";

interface BlockStructureData {
  blocks: Matrix;
  sweep: Sweep;
  misShelved: RankedRow[];
  plateau: {
    k: number;
    gamma: number;
    ari: number;
    misCount: number;
    nPartitioned: number;
    peakAri: number;
    peakAriK: number;
  };
}

const panel: PanelModule = {
  slug: "block-structure",
  render(el, env, ctx) {
    const data = env.data as unknown as BlockStructureData;
    const p = data.plateau;
    const wrap = ctx.blocks(el);

    ctx.matrix(
      wrap.block(
        "min(100%, 980px)",
        "block connection rates by edge layer (share of possible pairs wired; shading scaled per layer)",
      ),
      { ...data.blocks, format: "num", scale: "seq" },
    );

    ctx.line(
      wrap.block(
        "min(100%, 560px)",
        `Leiden sweep: low γ returns just the connected components; the stable cut above that is K=${p.k}, and agreement peaks at ${p.peakAri} (K=${p.peakAriK})`,
      ),
      { sweep: data.sweep },
    );

    ctx.table(
      wrap.block(
        "min(100%, 560px)",
        `mis-shelved at γ=${p.gamma}: ${p.misCount} of ${p.nPartitioned} companies sit in a community whose modal vertical isn't theirs — top ${data.misShelved.length} by degree`,
      ),
      {
        rows: data.misShelved,
        columns: [
          { key: "label", label: "company", format: "text" },
          { key: "shelved", label: "shelved as", format: "text" },
          { key: "wiredWith", label: "wired with", format: "text", hint: "modal vertical of its Leiden community" },
          { key: "commSize", label: "comm n", format: "num", digits: 0 },
          { key: "modalShare", label: "modal share", format: "pct", hint: "how dominant that modal vertical is" },
          { key: "degree", label: "degree", format: "num", digits: 0 },
          { key: "flag", label: "", format: "flag" },
        ],
      },
    );
  },
};

export default panel;
