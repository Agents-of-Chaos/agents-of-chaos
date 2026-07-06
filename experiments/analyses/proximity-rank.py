# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "networkx", "scipy"]
# ///
"""proximity-rank — personalized PageRank from agents-of-chaos on the weighted
company graph: who a restarting random walk actually reaches, with hop-count
and effective-resistance diagnostics and a bottleneck flag where reach hangs
on a single relationship. Run: cd experiments/analyses && uv run proximity-rank.py
"""

import networkx as nx
import numpy as np
from _shared import emit, load_companies, stamp

AOC = "agents-of-chaos"
TYPE_W = {"business": 1.0, "shared-investor": 0.7, "competitor": 0.3}
ALPHAS = (0.5, 0.85, 0.95)
MAIN_ALPHA = 0.85
TOP_N = 25
BOTTLENECK_GAP = 25  # resistance rank this many places worse than hop rank


def build_graph(companies: dict) -> nx.Graph:
    G = nx.Graph()
    for c in companies["companies"]:
        G.add_node(c["id"])
    for e in companies["edges"]:
        assert e["type"] in TYPE_W, f"unknown edge type {e['type']!r}"
        a, b = e["source"], e["target"]
        if G.has_edge(a, b):  # a few pairs carry two typed edges; weights add
            G[a][b]["w"] += TYPE_W[e["type"]]
        else:
            G.add_edge(a, b, w=TYPE_W[e["type"]])
    return G


def min_ranks(values: np.ndarray) -> np.ndarray:
    """Competition ("min") ranks, 1-based: rank = 1 + count strictly smaller."""
    s = np.sort(values)
    return np.searchsorted(s, values, side="left") + 1


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    G = build_graph(companies)
    assert AOC in G, "AoC node missing"
    neighbors = set(G.neighbors(AOC))
    assert len(neighbors) == 5, f"expected AoC's 5 direct ties, got {len(neighbors)}"
    assert all(G[AOC][n]["w"] in TYPE_W.values() for n in neighbors)
    # honesty about the seed: how does the walk leave AoC, and through whom most?
    w_out = sum(G[AOC][n]["w"] for n in neighbors)
    heavy = max(sorted(neighbors), key=lambda n: G[AOC][n]["w"])
    heavy_share = G[AOC][heavy]["w"] / w_out
    n_rival_ties = sum(1 for n in neighbors if G[AOC][n]["w"] == TYPE_W["competitor"])

    # ── personalized PageRank, three leash lengths ──────────────────────────
    ppr = {
        a: nx.pagerank(
            G,
            alpha=a,
            personalization={AOC: 1},
            nstart={AOC: 1},  # start at the seed: unreachable components stay exactly 0
            weight="w",
            max_iter=2000,
            tol=1e-10,
        )
        for a in ALPHAS
    }
    for a, p in ppr.items():
        assert abs(sum(p.values()) - 1.0) < 1e-9, f"PPR mass at alpha={a} not 1"
    main_ppr = ppr[MAIN_ALPHA]

    # ── hop distance (unweighted BFS) ────────────────────────────────────────
    hops = nx.single_source_shortest_path_length(G, AOC)

    # ── resistance distance on the largest connected component ──────────────
    lcc = max(nx.connected_components(G), key=len)
    assert AOC in lcc and len(lcc) > 100, "AoC must sit in the giant component"
    n_out = G.number_of_nodes() - len(lcc)
    zero_mass = {i for i, v in main_ppr.items() if v == 0.0}
    assert zero_mass == set(G) - lcc, "PPR zeros must be exactly the non-LCC nodes"

    lcc_ids = sorted(lcc)
    pos = {i: k for k, i in enumerate(lcc_ids)}
    L = nx.laplacian_matrix(G.subgraph(lcc_ids), nodelist=lcc_ids, weight="w")
    L = np.asarray(L.todense(), dtype=float)
    Lp = np.linalg.pinv(L)
    assert np.isfinite(Lp).all(), "pseudoinverse produced non-finite entries"
    assert np.allclose(L @ Lp @ L, L, atol=1e-6), "Penrose condition failed"
    k = pos[AOC]
    res = {i: float(Lp[pos[i], pos[i]] + Lp[k, k] - 2 * Lp[pos[i], k]) for i in lcc_ids}
    assert res[AOC] < 1e-9 and all(res[i] > 0 for i in lcc_ids if i != AOC)

    # ── bottleneck flag: close by hops, far by resistance ────────────────────
    others = [i for i in lcc_ids if i != AOC]
    hop_rank = dict(zip(others, min_ranks(np.array([hops[i] for i in others]))))
    res_rank = dict(zip(others, min_ranks(np.array([res[i] for i in others]))))
    bottleneck = {i: res_rank[i] - hop_rank[i] >= BOTTLENECK_GAP for i in others}

    # ── the table: top-25 by alpha=0.85, AoC + its 5 neighbors excluded ─────
    excluded = neighbors | {AOC}

    def top_ids(p: dict) -> list[str]:
        return sorted((i for i in p if i not in excluded), key=lambda i: (-p[i], i))[
            :TOP_N
        ]

    top = top_ids(main_ppr)
    assert all(i in lcc for i in top), "top-25 must be reachable"
    assert all(hops[i] >= 2 for i in top), "non-rivals start at hop 2"
    for i in top:  # resistance ≤ hops edges in series at the weakest weight
        assert res[i] <= hops[i] / TYPE_W["competitor"] + 1e-9

    rows = [
        {
            "id": i,
            "label": by_id[i]["name"],
            "vertical": by_id[i]["vertical"].replace("-", " "),
            "ppr85": round(main_ppr[i] * 100, 3),
            "ppr50": round(ppr[0.5][i] * 100, 3),
            "ppr95": round(ppr[0.95][i] * 100, 3),
            "hops": hops[i],
            "resistance": round(res[i], 2),
            "flag": "bottleneck" if bottleneck[i] else None,
        }
        for i in top
    ]
    assert all(a["ppr85"] >= b["ppr85"] for a, b in zip(rows, rows[1:]))
    n_btl = sum(1 for r in rows if r["flag"])
    top3 = ", ".join(r["label"] for r in rows[:3])

    # hub-gravity diagnostic for the prose: hop>=3 rows in each alpha's top-25
    n_far = {a: sum(1 for i in top_ids(ppr[a]) if hops[i] >= 3) for a in ALPHAS}
    deg = dict(G.degree())

    # ── minimap coloring: PPR percentile for every company ──────────────────
    ppr_sorted = np.sort([main_ppr[i] for i in lcc_ids])
    pct = {
        i: float(np.searchsorted(ppr_sorted, main_ppr[i], side="left"))
        / (len(lcc_ids) - 1)
        for i in lcc_ids
    }
    percentile = [
        {
            "id": i,
            "label": by_id[i]["name"],
            "pct": round(pct[i], 4) if i in lcc else None,
        }
        for i in sorted(G, key=lambda i: (-(pct.get(i, -1.0)), i))
    ]
    assert len(percentile) == G.number_of_nodes()
    assert sum(1 for r in percentile if r["pct"] is None) == n_out

    payload = {
        "slug": "proximity-rank",
        "graph": "companies",
        "title": "Everything within reach",
        "sub": "personalized PageRank from our seat: who a random walk actually finds",
        "headline": (
            f"A walk restarted at AoC piles up on {top3} — and "
            f"<strong>{n_btl} of the top {TOP_N}</strong> reachable companies "
            f"hang on a single gating relationship."
        ),
        "prose": {
            "intro": (
                "<p>The map has 188 companies, but which ones can Agents of Chaos actually get to "
                "from where it sits? Adjacency is not reach: a warm path through two strong ties beats "
                "a cold one through five. This panel scores every company by reachability from our seat "
                "in the graph — and flags where that reach hangs on a single relationship.</p>"
            ),
            "how": (
                "<p>Personalized PageRank is the recommender's oldest trick: drop a random walker on the "
                "AoC node, let it follow relationships (business ties at weight 1.0, shared-investor 0.7, "
                "mere rivalry 0.3), and with probability 1−α yank it home to restart. The share of time it "
                "spends at each company is that company's reach score — it blends every path at once, not "
                "just the shortest. α is the leash length, and the three columns are a diagnostic: at "
                f"α=0.5 the walker stays near home ({n_far[0.5]} of its top 25 lie beyond two hops), while "
                f"at α=0.95 it drifts into the graph's gravity wells — Anthropic ({deg['anthropic']} ties) "
                f"and OpenAI ({deg['openai']}) — and {n_far[0.95]} of the top 25 are hop-3+; a row that "
                "only shines at high α is hub gravity, not closeness. Hops counts raw handshakes; "
                "resistance distance treats the graph as an electrical circuit, where many parallel paths "
                "lower the resistance and one thin wire keeps it high. Close in hops but far in resistance "
                "(the flagged rows) means one relationship is doing all the work.</p>"
            ),
            "method": (
                "<p>Personalized PageRank (Page et al. 1999; topic-sensitive form of Haveliwala 2002) by "
                "power iteration (networkx, tol=1e-10) on the weighted undirected company graph, "
                "personalization mass 1 on agents-of-chaos; parallel typed edges between a pair sum their "
                f"weights. Main ranking α={MAIN_ALPHA}; the table excludes AoC itself and its 5 direct "
                f"neighbors ({n_rival_ties} rivals plus {by_id[heavy]['name']}, its only edges), so rows "
                "start at hop 2. Hop distance: unweighted BFS. "
                "Resistance distance (Klein &amp; Randić 1993), r(a,b)=L⁺aa+L⁺bb−2L⁺ab from the "
                f"Moore–Penrose pseudoinverse of the weighted Laplacian of the {len(lcc)}-node largest "
                f"component; the {n_out} companies outside it are unreachable (exactly zero PPR mass) and "
                f"carry no resistance value. Bottleneck flag: resistance rank ≥ {BOTTLENECK_GAP} places "
                "worse than hop rank (competition ranking over the component).</p>"
            ),
        },
        "caveat": (
            f"Every step out of AoC goes through one of its 5 ties: {n_rival_ties} rival edges (weight 0.3) "
            f"plus one inferred, unverified business tie to {by_id[heavy]['name']} that alone carries "
            f"{heavy_share:.0%} of each step out — a single hand-drawn edge with that much say over the ranking. "
            f"{n_out} companies sit in components no walk from AoC can reach: zero score, grey on the map."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "reach": rows,
            "percentile": percentile,
            "unreachable": n_out,
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
