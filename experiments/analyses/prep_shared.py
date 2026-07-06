# /// script
# requires-python = ">=3.11"
# dependencies = ["networkx", "numpy"]
# ///
"""prep_shared — bake src/data/analyses/shared.json: a slim projection of both
graphs (labels, groups, degree, seeded 2D layout, edge pairs) so the analyses
page never bundles the full 400KB source JSONs. Run: cd experiments/analyses &&
uv run prep_shared.py
"""

import json

import networkx as nx
import numpy as np
from _shared import OUT_DIR, load_companies, load_funding, stamp

RNG_SEED = 0


def layout(G: nx.Graph, groups: dict[str, str]) -> dict[str, tuple[float, float]]:
    """Seeded spring layout initialized at per-group centroids (echoes the big
    maps' territory geography), normalized to [0,1]^2."""
    rng = np.random.default_rng(RNG_SEED)
    uniq = sorted(set(groups.values()))
    k = len(uniq)
    cols = int(np.ceil(np.sqrt(k)))
    centroid = {
        g: ((i % cols) / max(cols - 1, 1), (i // cols) / max(cols - 1, 1))
        for i, g in enumerate(uniq)
    }
    pos0 = {
        v: (
            centroid[groups[v]][0] + rng.normal(0, 0.08),
            centroid[groups[v]][1] + rng.normal(0, 0.08),
        )
        for v in G.nodes
    }
    pos = nx.spring_layout(
        G, pos=pos0, seed=RNG_SEED, k=1.6 / np.sqrt(max(len(G), 1)), iterations=80
    )
    xs = np.array([p[0] for p in pos.values()])
    ys = np.array([p[1] for p in pos.values()])
    span_x = xs.max() - xs.min() or 1.0
    span_y = ys.max() - ys.min() or 1.0
    return {
        v: (
            round(float((p[0] - xs.min()) / span_x), 4),
            round(float((p[1] - ys.min()) / span_y), 4),
        )
        for v, p in pos.items()
    }


def project_companies() -> dict:
    d = load_companies()
    G = nx.Graph()
    G.add_nodes_from(c["id"] for c in d["companies"])
    G.add_edges_from((e["source"], e["target"]) for e in d["edges"])
    groups = {c["id"]: c["vertical"] for c in d["companies"]}
    pos = layout(G, groups)
    return {
        "stamp": stamp(d),
        "nodes": {
            c["id"]: {
                "label": c["name"],
                "group": c["vertical"],
                "degree": G.degree(c["id"]),
                "x": pos[c["id"]][0],
                "y": pos[c["id"]][1],
            }
            for c in d["companies"]
        },
        "edges": sorted([sorted((e["source"], e["target"])) for e in d["edges"]]),
    }


def project_funding() -> dict:
    d = load_funding()
    G = nx.Graph()
    G.add_nodes_from(n["id"] for n in d["nodes"])
    G.add_edges_from((e["source"], e["target"]) for e in d["edges"])

    def group(n: dict) -> str:
        return n["funderKind"] if n["kind"] == "funder" else n["kind"]

    groups = {n["id"]: group(n) for n in d["nodes"]}
    pos = layout(G, groups)
    return {
        "stamp": stamp(d),
        "dataDate": d["meta"].get("generatedAt"),
        "nodes": {
            n["id"]: {
                "label": n["name"],
                "group": groups[n["id"]],
                "degree": G.degree(n["id"]),
                "x": pos[n["id"]][0],
                "y": pos[n["id"]][1],
            }
            for n in d["nodes"]
        },
        "edges": sorted([sorted((e["source"], e["target"])) for e in d["edges"]]),
    }


def main() -> None:
    payload = {
        "graphs": {"companies": project_companies(), "funding": project_funding()}
    }
    blob = json.dumps(
        payload, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "shared.json").write_text(blob + "\n")
    c, f = payload["graphs"]["companies"], payload["graphs"]["funding"]
    print(
        f"[shared] OK {len(blob) / 1024:.0f}KB — companies {c['stamp']['nodes']}n/{c['stamp']['edges']}e, "
        f"funding {f['stamp']['nodes']}n/{f['stamp']['edges']}e"
    )


if __name__ == "__main__":
    main()
