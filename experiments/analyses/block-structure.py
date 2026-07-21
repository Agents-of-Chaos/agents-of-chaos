# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "networkx", "graspologic==3.4.4", "scikit-learn"]
# ///
"""block-structure — do the 8 verticals match the wiring? Supervised SBM block
rates per edge layer + Leiden resolution sweep + mis-shelved companies.
Run: cd experiments/analyses && uv run block-structure.py
"""

from collections import Counter

import networkx as nx
import numpy as np
from _shared import emit, load_companies, stamp

SEED = 1  # graspologic's native leiden PRNG rejects 0 (must be positive)
N_GAMMA = 40
N_MIS_ROWS = 15
EDGE_TYPES = ["business", "shared-investor", "competitor"]
# display order: sellers → buyers → money
ORDER = [
    "security-eval-vendor",
    "agent-native-startup",
    "frontier-lab",
    "infra-platform",
    "bank-fintech",
    "healthcare",
    "enterprise-other",
    "investor-vc",
]
SHORT = {
    "security-eval-vendor": "security",
    "agent-native-startup": "agents",
    "frontier-lab": "labs",
    "infra-platform": "infra",
    "bank-fintech": "banks",
    "healthcare": "health",
    "enterprise-other": "enterprise",
    "investor-vc": "VCs",
}


def block_layers(companies: dict, ids: list[str], y: np.ndarray) -> list[dict]:
    """Supervised SBM per edge type: 8x8 block connection probabilities.
    With y given this is pure density counting, so 7 components are no obstacle."""
    from graspologic.models import SBMEstimator

    idx = {i: k for k, i in enumerate(ids)}
    uy = list(np.unique(y))
    perm = [uy.index(v) for v in ORDER]
    layers = []
    for t in EDGE_TYPES:
        A = np.zeros((len(ids), len(ids)))
        n_edges = 0
        for e in companies["edges"]:
            if e["type"] == t:
                a, b = idx[e["source"]], idx[e["target"]]
                A[a, b] = A[b, a] = 1.0
                n_edges += 1
        est = SBMEstimator(directed=False, loops=False)
        est.fit(A, y=y)
        B = est.block_p_[np.ix_(perm, perm)]
        assert B.shape == (8, 8) and np.allclose(B, B.T), f"{t}: bad block matrix"
        assert 0.0 <= B.min() and B.max() <= 1.0, f"{t}: probs out of range"
        layers.append(
            {
                "label": f"{t.replace('-', ' ')} ({n_edges} edges)",
                "cells": [[round(float(v), 4) for v in row] for row in B],
            }
        )
    return layers


def leiden_sweep(
    G: nx.Graph, ids: list[str], vert: dict[str, str]
) -> tuple[np.ndarray, list[int], list[float], list[dict]]:
    from graspologic.partition import leiden
    from sklearn.metrics import adjusted_rand_score

    nodes = [n for n in ids if G.degree(n) > 0]  # 2 isolates carry no signal
    y_true = [vert[n] for n in nodes]
    gammas = np.logspace(-2, 1, N_GAMMA)
    Ks: list[int] = []
    ARIs: list[float] = []
    partitions: list[dict] = []
    for g in gammas:
        p = leiden(G, resolution=float(g), random_seed=SEED)
        assert set(p) == set(nodes), "leiden should partition all non-isolates"
        labels = [p[n] for n in nodes]
        Ks.append(len(set(labels)))
        ARIs.append(float(adjusted_rand_score(y_true, labels)))
        partitions.append(p)
    return gammas, Ks, ARIs, partitions


def find_plateau(
    Ks: list[int], ARIs: list[float], n_components: int
) -> tuple[int, int]:
    """Longest run of constant K above the trivial component count; within the
    run, the index with max ARI (ties -> lowest gamma). Returns (index, K)."""
    runs: list[tuple[int, int]] = []  # (start, end) inclusive
    s = 0
    for i in range(1, len(Ks) + 1):
        if i == len(Ks) or Ks[i] != Ks[s]:
            if Ks[s] > n_components:
                runs.append((s, i - 1))
            s = i
    assert runs, "no non-trivial plateau found"
    start, end = max(runs, key=lambda r: r[1] - r[0])
    best = max(range(start, end + 1), key=lambda i: (ARIs[i], -i))
    return best, Ks[best]


def main() -> None:
    companies = load_companies()
    ids = [c["id"] for c in companies["companies"]]
    vert = {c["id"]: c["vertical"] for c in companies["companies"]}
    name = {c["id"]: c["name"] for c in companies["companies"]}
    assert set(vert.values()) == set(ORDER), "vertical taxonomy changed — update ORDER"
    y = np.array([vert[i] for i in ids])

    # ── part 1: supervised block rates per layer ────────────────────────────
    layers = block_layers(companies, ids, y)
    biz = np.array(layers[0]["cells"])
    i_sec, i_lab = ORDER.index("security-eval-vendor"), ORDER.index("frontier-lab")
    i_bank, i_health = ORDER.index("bank-fintech"), ORDER.index("healthcare")
    assert biz[i_sec, i_lab] > 0.04, "security x labs should be the hot business cell"
    assert biz[i_sec, i_bank] == 0.0 and biz[i_sec, i_health] == 0.0

    # exact edge counts behind the headline
    sec_partners: Counter[str] = Counter()
    for e in companies["edges"]:
        if e["type"] != "business":
            continue
        va, vb = vert[e["source"]], vert[e["target"]]
        if "security-eval-vendor" in (va, vb):
            sec_partners[va if va != "security-eval-vendor" or va == vb else vb] += 1
    sec_total = sum(sec_partners.values())
    sec_labs = sec_partners["frontier-lab"]
    assert sec_labs == 27 and sec_total == 54, "headline counts drifted — re-verify"

    # ── part 2: unsupervised leiden sweep ───────────────────────────────────
    G = nx.Graph()
    G.add_nodes_from(ids)
    for e in companies["edges"]:
        G.add_edge(e["source"], e["target"])
    n_comp = sum(1 for c in nx.connected_components(G) if len(c) > 1)
    assert n_comp == 4, "component structure changed — trivial-plateau rule assumes 4"

    gammas, Ks, ARIs, partitions = leiden_sweep(G, ids, vert)
    pi, plateau_k = find_plateau(Ks, ARIs, n_comp)
    plateau_gamma = float(gammas[pi])
    peak_ari = max(ARIs)
    peak_k = Ks[ARIs.index(peak_ari)]
    peak_gamma = float(gammas[ARIs.index(peak_ari)])
    assert plateau_k < 8, "plateau no longer skips 8 — rewrite the finding"

    # facts the method prose states — pinned here so churn can't silently lie
    assert (
        nx.number_connected_components(G) == n_comp
    ), "isolated companies reappeared — prose.method assumes every company holds an edge"
    assert (
        Ks[0] == n_comp
    ), "lowest-γ Leiden no longer returns the components — fix the trivial-shelf sentence"
    first_nontrivial = next(i for i, k in enumerate(Ks) if k > n_comp)
    assert all(k == n_comp for k in Ks[:first_nontrivial])
    triv_hi = float(gammas[first_nontrivial])
    run_s, run_e = pi, pi
    while run_s > 0 and Ks[run_s - 1] == plateau_k:
        run_s -= 1
    while run_e < len(Ks) - 1 and Ks[run_e + 1] == plateau_k:
        run_e += 1
    assert Ks[run_s] == Ks[run_e] == plateau_k and run_s <= pi <= run_e

    sweep = {
        "x": [round(float(np.log10(g)), 3) for g in gammas],
        "xLabel": "log10 resolution γ",
        "series": [
            {"label": "communities K", "y": Ks},
            {
                "label": "ARI vs 8 verticals ×100",
                "y": [round(a * 100, 1) for a in ARIs],
            },
        ],
        "annotate": {
            "x": round(float(np.log10(plateau_gamma)), 3),
            "text": f"plateau K={plateau_k}",
        },
    }

    # ── part 3: mis-shelved at the plateau γ ────────────────────────────────
    part = partitions[pi]
    comms: dict[int, list[str]] = {}
    for n, c in part.items():
        comms.setdefault(c, []).append(n)
    modal: dict[int, tuple[str, float]] = {}
    for c, members in comms.items():
        (top_v, top_n), *_ = sorted(
            Counter(vert[m] for m in members).items(), key=lambda kv: (-kv[1], kv[0])
        )
        modal[c] = (top_v, top_n / len(members))
    mis = [n for n in ids if n in part and modal[part[n]][0] != vert[n]]
    mis.sort(key=lambda n: (-G.degree(n), n))
    mis_rows = [
        {
            "id": n,
            "label": name[n],
            "shelved": SHORT[vert[n]],
            "wiredWith": SHORT[modal[part[n]][0]],
            "commSize": len(comms[part[n]]),
            "modalShare": round(modal[part[n]][1], 2),
            "degree": G.degree(n),
            "flag": "plurality only" if modal[part[n]][1] < 0.5 else None,
        }
        for n in mis[:N_MIS_ROWS]
    ]
    assert len(mis_rows) == N_MIS_ROWS and all(r["label"] for r in mis_rows)

    payload = {
        "slug": "block-structure",
        "graph": "companies",
        "title": "Eight verticals on paper",
        "sub": "do the eight hand-drawn verticals match how the market actually wires?",
        "headline": (
            f"Security vendors' documented commerce runs through frontier labs — <strong>{sec_labs} of "
            f"their {sec_total} mapped business edges</strong> — while security×banks and "
            f"security×healthcare show zero mapped deals. And when an algorithm redraws the groups "
            f"from the wiring alone, its best match to the shelves is weak — agreement peaks at "
            f"{peak_ari:.2f} of 1, and its stable cut has {plateau_k} groups, not 8."
        ),
        "prose": {
            "intro": (
                f"<p>The map colors {len(ids)} companies by eight hand-assigned verticals. Two questions. Do "
                "those shelves describe how the market actually connects? And — the sales question — "
                "which buyer verticals actually <em>transact</em> with security vendors? We first score "
                "the shelves against the real edges, then let an algorithm redraw the groups from "
                "scratch and count the disagreements.</p>"
            ),
            "how": (
                "<p>Part one keeps the labels: for each pair of verticals, count what share of the "
                "possible company pairs actually hold an edge. That gives an 8×8 grid of connection "
                "rates per edge type. The business grid is a hub-and-spoke around the frontier labs: "
                "labs' mapped deals with security vendors, banks, and enterprises run at about 7× the "
                "typical rate, while security→banks and security→healthcare are empty on the map. "
                "Part two deletes the "
                "labels: a clustering algorithm regroups the companies from the wiring alone, run 40 "
                "times from coarse to fine. If the taxonomy matched the wiring, some run would recover "
                "eight groups agreeing with the shelves. Agreement is scored from 0 (chance) to 1 (a "
                "perfect match). Part three lists the best-connected companies whose data-drawn group "
                "is dominated by a different vertical than their own.</p>"
            ),
            "method": (
                f"<p>Supervised: graspologic 3.4.4 SBMEstimator with y fixed to the vertical labels "
                f"(Holland, Laskey &amp; Leinhardt 1983) — a supervised fit is per-block density "
                f"estimation, so the graph's {n_comp} components need no LCC restriction. Unsupervised: "
                f"graspologic.partition.leiden (Traag, Waltman &amp; van Eck 2019), random_seed=1 "
                f"(the native PRNG rejects 0), γ ∈ logspace(−2, 1, 40), all {len(companies['edges'])} "
                f"edges unweighted, ARI per Hubert &amp; Arabie 1985. Below γ≈{triv_hi:.2f} Leiden "
                f"returns exactly the {n_comp} connected components, so those cuts are trivial; the "
                f"reported plateau is the longest constant-K run above the component count (K={plateau_k}, "
                f"γ≈{float(gammas[run_s]):.2f}–{float(gammas[run_e]):.2f}, agreement {ARIs[pi]:.2f}). "
                f"K passes through {peak_k} only at γ≈{peak_gamma:.2f}, where agreement peaks at "
                f"{peak_ari:.2f} — even at its best, the members mostly don't match. At the plateau, "
                f"{len(mis)} of {len(partitions[pi])} partitioned companies sit in a community whose "
                f"modal vertical is not their own; the table shows the top {N_MIS_ROWS} by degree.</p>"
            ),
        },
        "caveat": (
            f"The clustering method has a known blind spot: groups holding fewer than about 22 "
            f"internal edges cannot surface on their own, and verticals the size of frontier-lab "
            f"(14 companies) or investor-vc (16) fall below that — so low agreement is partly the "
            f"method's floor, not proof the taxonomy is wrong. And the empty security×banks and "
            f"security×healthcare cells may be unmapped deals rather than absent ones — "
            f"{sum(1 for e in companies['edges'] if not e['verified'])} of "
            f"{len(companies['edges'])} edges are themselves unverified."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "blocks": {
                "rows": [SHORT[v] for v in ORDER],
                "cols": [SHORT[v] for v in ORDER],
                "layers": layers,
            },
            "sweep": sweep,
            "misShelved": mis_rows,
            "plateau": {
                "k": plateau_k,
                "gamma": round(plateau_gamma, 3),
                "ari": round(ARIs[pi], 3),
                "misCount": len(mis),
                "nPartitioned": len(partitions[pi]),
                "peakAri": round(peak_ari, 3),
                "peakAriK": peak_k,
            },
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
