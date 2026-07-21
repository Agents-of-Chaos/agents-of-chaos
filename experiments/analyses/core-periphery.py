# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "networkx", "scipy", "cpnet", "numba>=0.59"]
# ///
"""core-periphery — Rombach continuous coreness on the full / business-only /
shared-investor-only company layers, config-model significance, and the
investor-core-but-business-crust prospect quadrant.
Run: cd experiments/analyses && uv run core-periphery.py

Shipped estimator: cpnet's Rombach (label switching, alpha=0.5, beta=0.8,
num_runs=10) — NOT the Borgatti-Everett fallback. cpnet's inner loop is
numba-jitted and draws from numba's own per-thread RNG, which np.random.seed
does NOT touch; seeding it via a jitted np.random.seed call (see _seed_all)
makes detection exactly reproducible (verified by the in-script double-run).
"""

import random
from collections import defaultdict

import networkx as nx
import numpy as np
from _shared import company_ids, emit, load_companies, stamp

AOC = "agents-of-chaos"
SEED = 0
N_RAND = 500  # config-model nulls for qstest
ALPHA, BETA = 0.5, 0.8  # cpnet defaults; coreness forms two blocks: <=0.25, >=0.75
GAP = (0.26, 0.74)  # no coreness values may fall strictly inside this band


def _seed_all() -> None:
    """Seed numpy, python random, AND numba's separate per-thread RNG."""
    from numba import njit

    np.random.seed(SEED)
    random.seed(SEED)

    @njit(cache=False)
    def _seed_numba(s):
        np.random.seed(s)

    _seed_numba(SEED)


def layer_graph(companies: dict, types: set[str]) -> nx.Graph:
    """Undirected simple graph over nodes with >=1 edge of the given types."""
    G = nx.Graph()
    for e in companies["edges"]:
        if e["type"] in types:
            G.add_edge(e["source"], e["target"])
    assert G.number_of_nodes() > 0, f"empty layer {types}"
    return G


def rombach_coreness(G: nx.Graph) -> dict[str, float]:
    import cpnet

    _seed_all()
    alg = cpnet.Rombach(num_runs=10, alpha=ALPHA, beta=BETA, algorithm="ls")
    alg.detect(G)
    c = {k: float(v) for k, v in alg.get_coreness().items()}
    vals = np.array(list(c.values()))
    assert set(c) == set(G.nodes), "coreness must cover every node in the layer"
    assert vals.min() >= 0.0 and vals.max() <= 1.0, "coreness out of [0,1]"
    assert not np.any((vals > GAP[0]) & (vals < GAP[1])), (
        "Rombach kernel should leave the (0.25, 0.75) band empty — "
        "quadrant midpoint split relies on it"
    )
    return c


def null_test(G: nx.Graph) -> tuple[bool, float]:
    """Kojaku-Masuda (q,s)-test of the single Rombach core-periphery pair
    against N_RAND Chung-Lu expected-degree random graphs."""
    import cpnet

    _seed_all()
    alg = cpnet.Rombach(num_runs=10, alpha=ALPHA, beta=BETA, algorithm="ls")
    alg.detect(G)
    pair_id, coreness = alg.get_pair_id(), alg.get_coreness()
    assert len(set(pair_id.values())) == 1, "Rombach yields exactly one pair"
    _seed_all()  # qstest's null graphs + re-detections draw from all 3 RNGs
    _, _, significant, p_values = cpnet.qstest(
        pair_id, coreness, G, alg, num_of_rand_net=N_RAND
    )
    p = float(p_values[0])
    assert 0.0 <= p <= 1.0
    return bool(significant[0]), p


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    known_ids = company_ids(companies)

    G_full = layer_graph(companies, {"business", "shared-investor", "competitor"})
    G_biz = layer_graph(companies, {"business"})
    G_inv = layer_graph(companies, {"shared-investor"})
    assert set(G_full) <= known_ids
    n_full = G_full.number_of_nodes()

    c_full = rombach_coreness(G_full)
    assert c_full == rombach_coreness(G_full), (
        "Rombach not deterministic despite seeding — "
        "switch to the Borgatti-Everett fallback"
    )
    c_biz = rombach_coreness(G_biz)
    c_inv = rombach_coreness(G_inv)

    significant, p_null = null_test(G_full)
    sig_share = 1.0 if significant else 0.0  # single pair => all-or-nothing

    deg = dict(G_full.degree())
    from scipy.stats import spearmanr

    order = sorted(c_full)
    rho, _ = spearmanr([c_full[n] for n in order], [deg[n] for n in order])

    # ── quadrant scatter: x=business coreness, y=investor coreness ──────────
    # upper-left = investor-core + business-crust = the prospect quadrant.
    both = sorted(set(G_biz) & set(G_inv))
    assert len(both) >= 10, "dual-layer overlap collapsed — rethink the scatter"
    assert AOC not in G_inv, "AoC gained investor edges — revisit the caveat text"
    quadrant = [
        {
            "id": n,
            "label": by_id[n]["name"],
            "x": round(c_biz[n], 4),
            "y": round(c_inv[n], 4),
            "group": by_id[n]["vertical"],
        }
        for n in both
    ]
    xs = [p["x"] for p in quadrant]
    ys = [p["y"] for p in quadrant]
    mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    # the dots archetype draws its guides at the extent midpoints — they must
    # fall inside the kernel gap so the split is exactly core-block vs crust
    assert GAP[0] < mx < GAP[1] and GAP[0] < my < GAP[1], "midpoint left the gap"
    prospects = sorted(
        (p for p in quadrant if p["x"] < mx and p["y"] >= my),
        key=lambda p: -p["y"],
    )
    n_core_both = sum(1 for p in quadrant if p["x"] >= mx and p["y"] >= my)
    assert prospects, "no prospect quadrant — headline needs rewriting"

    # ── bars: mean full-graph coreness by vertical ───────────────────────────
    agg: dict[str, list[float]] = defaultdict(list)
    for n, c in c_full.items():
        agg[by_id[n]["vertical"]].append(c)
    by_vertical = sorted(
        (
            {
                "label": f"{v.replace('-', ' ')} ({len(cs)})",
                "value": round(float(np.mean(cs)), 3),
            }
            for v, cs in agg.items()
        ),
        key=lambda r: (-r["value"], r["label"]),
    )
    assert len(by_vertical) == 8, "expected 8 verticals"

    # ── table: the 14 competitor-flagged companies + AoC itself ─────────────
    rank = {
        n: i + 1 for i, n in enumerate(sorted(c_full, key=lambda n: (-c_full[n], n)))
    }
    rival_ids = sorted(c["id"] for c in companies["companies"] if c.get("competitor"))
    assert len(rival_ids) == 14, "competitor flag count drifted"
    assert all(r in c_full for r in rival_ids), "rival missing from the full graph"

    def rival_row(n: str, flag: str | None) -> dict:
        return {
            "id": n,
            "label": by_id[n]["name"],
            "coreness": round(c_full[n], 3),
            "rank": rank[n],
            "business": round(c_biz[n], 3) if n in c_biz else None,
            "investor": round(c_inv[n], 3) if n in c_inv else None,
            "flag": flag,
        }

    rivals = sorted(
        [rival_row(n, None) for n in rival_ids]
        + [rival_row(AOC, "that's us — 5 thin edges")],
        key=lambda r: r["rank"],
    )
    n_rival_core = sum(1 for r in rivals if r["id"] != AOC and r["coreness"] >= 0.75)

    prospect_names = ", ".join(p["label"] for p in prospects[:3])
    payload = {
        "slug": "core-periphery",
        "graph": "companies",
        "title": "Core and crust",
        "sub": "who holds the middle of the market — and is the core even real?",
        "headline": (
            f"<strong>{len(prospects)} of {len(both)}</strong> companies sit in the prospect "
            f"quadrant — central in the money network, but with few mapped business deals "
            f"({prospect_names}, …). One caution: the market's “core” looks no more special "
            f"than its edge counts alone would predict (p = {p_null:.2f}), so read “core” as "
            f"“well-connected,” nothing more."
        ),
        "prose": {
            "intro": (
                "<p>Every market has an establishment and a crust. We ask three things. Which companies "
                "hold the middle of the agent ecosystem? Is that core a real structure, or just who "
                "happens to have the most edges? And the actionable one: who is central in the money "
                "network but peripheral in the business network — well-financed, with no deals on "
                "this map yet? Open ground or deals done quietly: either way, those are the "
                "companies to pitch.</p>"
            ),
            "how": (
                "<p>Each company gets a score from 0 (crust) to 1 (core), fitted so that high scorers "
                "hold most of the map's edges in the classic establishment shape: core companies connect "
                "to everyone including each other, crust companies connect only to the core. We compute "
                f"it three times — on all {G_full.number_of_edges()} ties, on business ties only, and on "
                "shared-investor ties only. Then a reality check: rewire the map at random "
                f"{N_RAND} times, keeping each company's number of ties, and re-fit. The real map does "
                f"not beat the rewired ones (p = {p_null:.2f}), and the score tracks raw tie count "
                f"almost exactly (correlation {rho:.2f}) — so the overall core is largely popularity in "
                "disguise. The useful signal is in the split: crossing the money score against the "
                "business score separates the establishment (high on both) from the prospects "
                "(financed, no mapped deals yet).</p>"
            ),
            "method": (
                "<p>Rombach et al., “Core-Periphery Structure in Networks (Revisited)”, SIAM Review 59(3), "
                "2017 — continuous coreness via the cpnet implementation (label switching, α=0.5, β=0.8, "
                "best of 10 runs; the kernel maps ranks onto two blocks, crust ≤ 0.25 and core ≥ 0.75, so the "
                "quadrant guides at the axis midpoints split exactly core-block vs crust-block). Significance: "
                f"Kojaku &amp; Masuda's (q,s)-test (Scientific Reports 8:7351, 2018) with {N_RAND} Chung-Lu "
                "expected-degree null graphs; Rombach yields a single core-periphery pair, so significance is "
                "all-or-nothing across the 186 nodes — here: not significant. Determinism note: cpnet's inner "
                "loop is numba-jitted and uses numba's own RNG, which numpy seeding does not touch; we seed "
                "numpy, python, and numba (via a jitted np.random.seed) and verify by double-run. The method "
                "needs no connected graph: all 186 non-isolated companies across 5 components are scored, and "
                "small components land in the crust by construction.</p>"
            ),
        },
        "caveat": (
            f"{n_rival_core} of our 14 rivals land in the core mostly because the 27 security vendors "
            "all point competitor edges at each other. AoC itself is crust: rank "
            f"{rank[AOC]} of {n_full} on 5 thin edges (4 rival ties + 1 unverified business tie), and "
            "with no shared-investor edges at all it cannot appear on the quadrant chart. Two of the "
            f"{len(prospects)} “prospects” are competitor-flagged."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "quadrant": quadrant,
            "byVertical": by_vertical,
            "rivals": rivals,
            "nullTest": {
                "pValue": round(p_null, 3),
                "significant": significant,
                "sigShare": sig_share,
                "nRandNets": N_RAND,
                "spearmanCorenessDegree": round(float(rho), 3),
            },
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
