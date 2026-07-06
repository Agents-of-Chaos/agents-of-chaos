# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "graspologic==3.4.4"]
# ///
"""market-map — ASE of the company graph: the market in latent space, AoC's own
dot on it, and AoC's nearest structural neighbors. Run: cd experiments/analyses
&& uv run market-map.py
"""

import numpy as np
from _shared import emit, fix_signs, load_companies, stamp

AOC = "agents-of-chaos"
SEED = 0
N_NEIGHBORS = 20


def build_adjacency(
    companies: dict, verified_only: bool
) -> tuple[np.ndarray, list[str]]:
    ids = [c["id"] for c in companies["companies"]]
    idx = {i: k for k, i in enumerate(ids)}
    A = np.zeros((len(ids), len(ids)))
    for e in companies["edges"]:
        if verified_only and not e["verified"]:
            continue
        a, b = idx[e["source"]], idx[e["target"]]
        A[a, b] = A[b, a] = 1.0
    return A, ids


def embed(A: np.ndarray) -> np.ndarray:
    from graspologic.embed import AdjacencySpectralEmbed

    ase = AdjacencySpectralEmbed(n_elbows=2, svd_seed=SEED)
    X = ase.fit_transform(A)
    assert (
        isinstance(X, np.ndarray) and X.ndim == 2
    ), "undirected ASE should return one matrix"
    return fix_signs(X)


def neighbor_ranks(X: np.ndarray, ids: list[str], exclude: set[str]) -> list[str]:
    k = ids.index(AOC)
    d = np.linalg.norm(X - X[k], axis=1)
    order = np.argsort(d, kind="stable")
    return [ids[i] for i in order if ids[i] != AOC and ids[i] not in exclude]


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    rivals = {
        e["source"] if e["target"] == AOC else e["target"]
        for e in companies["edges"]
        if AOC in (e["source"], e["target"])
    }
    assert AOC in by_id and rivals, "AoC node with edges expected"

    A_all, ids = build_adjacency(companies, verified_only=False)
    A_ver, _ = build_adjacency(companies, verified_only=True)
    X = embed(A_all)
    X_ver = embed(A_ver)
    d = X.shape[1]

    # (a) the map: first two latent dimensions, every company
    points = [
        {
            "id": cid,
            "label": by_id[cid]["name"],
            "x": round(float(X[i, 0]), 4),
            "y": round(float(X[i, 1]), 4),
            "group": by_id[cid]["vertical"],
        }
        for i, cid in enumerate(ids)
    ]

    # (b) does embedding magnitude track deployment intensity?
    mag = np.linalg.norm(X, axis=1)
    intensity = np.array([by_id[c]["intensity"] for c in ids], dtype=float)
    from scipy.stats import pearsonr

    r, p = pearsonr(mag, intensity)
    rng = np.random.default_rng(SEED)  # jitter the 0-5 grid so 188 dots don't overprint
    mag_points = [
        {
            "id": cid,
            "label": by_id[cid]["name"],
            "x": round(float(mag[i]), 4),
            "y": round(float(intensity[i] + rng.uniform(-0.18, 0.18)), 3),
            "group": by_id[cid]["vertical"],
        }
        for i, cid in enumerate(ids)
    ]

    # (c) AoC's nearest neighbors (excluding its 5 known rivals), with a
    # verified-only sensitivity pass: does the neighbor survive the re-run?
    near_all = neighbor_ranks(X, ids, exclude=rivals)[:N_NEIGHBORS]
    near_ver = set(neighbor_ranks(X_ver, ids, exclude=rivals)[:N_NEIGHBORS])
    k = ids.index(AOC)
    dist = {cid: float(np.linalg.norm(X[ids.index(cid)] - X[k])) for cid in near_all}
    neighbors = [
        {
            "id": cid,
            "label": by_id[cid]["name"],
            "vertical": by_id[cid]["vertical"].replace("-", " "),
            "distance": round(dist[cid], 3),
            "intensity": by_id[cid]["intensity"],
            "survives": cid in near_ver,
            "flag": None if cid in near_ver else "drops w/o unverified edges",
        }
        for cid in near_all
    ]
    n_survive = sum(1 for n in neighbors if n["survives"])
    top3 = ", ".join(n["label"] for n in neighbors[:3])

    payload = {
        "slug": "market-map",
        "graph": "companies",
        "title": "The map",
        "sub": "188 companies placed by their connections alone, our dot among them",
        "headline": (
            f"The companies wired most like AoC are <strong>{top3}</strong> — "
            f"{n_survive} of {N_NEIGHBORS} stay on the list when unverified edges are dropped."
        ),
        "prose": {
            "intro": (
                "<p>What does the market look like if you ignore the hand-drawn category labels and let "
                "the connections speak? We give every company a position computed purely from who it "
                "connects to, then read off where Agents of Chaos sits — and who sits closest.</p>"
            ),
            "how": (
                "<p>The technique works like a word embedding: companies with similar connection "
                "patterns land near each other, whether or not they share a category. (An automatic "
                f"rule picked {d} coordinates per company here.) Distance on this map means playing a "
                "similar role in the market — so AoC's nearest non-rival neighbors, listed below, are a "
                "prospecting shortlist: the network treats them as companies in our position. A "
                "company's distance from the center also roughly tracks how much agent activity it has "
                f"(correlation {r:.2f}).</p>"
            ),
            "method": (
                "<p>Adjacency spectral embedding of the binarized undirected company graph (all 492 edges; "
                "diagonal augmentation; Zhu–Ghodsi elbow via graspologic, svd_seed=0), per Sussman et al. "
                "(JASA 2012) and the RDPG survey of Athreya et al. (JMLR 2018). Sensitivity: re-embedding on the "
                "421 verified edges only; a neighbor “survives” if it stays in the top-20. Caveats: AoC's "
                "own edges are 5 competitor ties, so its position is defined by the rivalry layer; isolates embed "
                "near the origin; distances beyond the second elbow dimension are noise at this sparsity.</p>"
            ),
        },
        "caveat": (
            "AoC's only mapped edges are its 5 rival ties, so its position on this map reflects rivalry — "
            "add real investor and partner edges and the map sharpens."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "map": points,
            "magnitude": {
                "points": mag_points,
                "pearson_r": round(float(r), 3),
                "p": float(f"{p:.2e}"),
            },
            "neighbors": neighbors,
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
