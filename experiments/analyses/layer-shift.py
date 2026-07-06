# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy", "scikit-learn", "graspologic==3.4.4"]
# ///
"""layer-shift — MASE across the three edge-type layers (business /
shared-investor / competitor): one shared basis, three score matrices, and the
companies whose structural role changes most when the lens changes.
Run: cd experiments/analyses && uv run layer-shift.py
"""

import numpy as np
from _shared import emit, fix_signs, load_companies, stamp

AOC = "agents-of-chaos"
SEED = 0
D = 2  # fixed — do NOT trust elbow selection at these densities
LAYER_TYPES = ["business", "shared-investor", "competitor"]
LAYER_LABELS = {
    "business": "business",
    "shared-investor": "shared investor",
    "competitor": "competitor",
}
TOP_SHIFT = 15
MIN_OMNI = 20  # below this the omnibus shift table is too thin to ship


def layer_adjacencies(companies: dict) -> tuple[dict[str, np.ndarray], list[str]]:
    ids = [c["id"] for c in companies["companies"]]
    idx = {i: k for k, i in enumerate(ids)}
    layers = {t: np.zeros((len(ids), len(ids))) for t in LAYER_TYPES}
    for e in companies["edges"]:
        assert e["type"] in layers, f"unknown edge type {e['type']!r}"
        a, b = idx[e["source"]], idx[e["target"]]
        A = layers[e["type"]]
        A[a, b] = A[b, a] = 1.0
    for t, A in layers.items():
        assert np.array_equal(A, A.T) and A.sum() > 0, f"bad layer {t}"
    return layers, ids


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    layers, ids = layer_adjacencies(companies)
    n = len(ids)
    A_list = [layers[t] for t in LAYER_TYPES]
    mean_deg = {t: float(layers[t].sum() / n) for t in LAYER_TYPES}
    assert all(1.0 < mean_deg[t] < 2.5 for t in LAYER_TYPES), mean_deg

    # ── MASE: one orthonormal basis V shared by all three layers ──────────
    from graspologic.embed import MultipleASE

    mase = MultipleASE(n_components=D, svd_seed=SEED)
    V = mase.fit_transform(A_list)
    assert isinstance(V, np.ndarray) and V.shape == (n, D), "undirected MASE"
    V = fix_signs(V)
    assert np.allclose(V.T @ V, np.eye(D), atol=1e-8), "V should be orthonormal"

    # R_k = Vᵀ A_k V — how layer k wires the two shared dimensions together
    score_layers = []
    cross = {}  # off-diagonal coupling per layer, for the prose
    for t in LAYER_TYPES:
        R = V.T @ layers[t] @ V
        assert np.allclose(R, R.T, atol=1e-8), "scores symmetric for undirected"
        cross[t] = abs(float(R[0, 1]))
        score_layers.append(
            {
                "label": LAYER_LABELS[t],
                "cells": [
                    [round(float(R[i, j]), 2) for j in range(D)] for i in range(D)
                ],
            }
        )
    biz_cross = cross["business"]
    other_cross = max(cross["shared-investor"], cross["competitor"])
    scores = {
        "rows": [f"dim {i + 1}" for i in range(D)],
        "cols": [f"dim {i + 1}" for i in range(D)],
        "layers": score_layers,
    }

    # ── does the shared basis recover the hand-drawn verticals? ──────────
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score

    verticals = [by_id[c]["vertical"] for c in ids]
    n_vert = len(set(verticals))
    assert n_vert == 8, f"expected 8 verticals, got {n_vert}"
    km = KMeans(n_clusters=n_vert, n_init=10, random_state=SEED).fit(V)
    ari = float(adjusted_rand_score(verticals, km.labels_))

    # ── omnibus: per-node drift across the three lenses ───────────────────
    # Restricted to nodes present (degree ≥1) in ALL three layers, otherwise a
    # node's "position" in a layer it has no edges in is pure noise at the origin.
    active = np.ones(n, dtype=bool)
    for t in LAYER_TYPES:
        active &= layers[t].sum(axis=1) > 0
    omni_ids = [ids[i] for i in range(n) if active[i]]
    n_omni = len(omni_ids)
    print(f"[layer-shift] nodes with degree>=1 in all three layers: {n_omni}")
    assert AOC not in omni_ids, "AoC has no shared-investor edges — keep caveat honest"

    shifts: list[dict] = []
    if n_omni >= MIN_OMNI:
        from graspologic.embed import OmnibusEmbed

        sel = np.flatnonzero(active)
        subs = [layers[t][np.ix_(sel, sel)] for t in LAYER_TYPES]
        omni = OmnibusEmbed(n_components=D, svd_seed=SEED)
        Z = omni.fit_transform(subs)
        assert isinstance(Z, np.ndarray) and Z.shape == (3, n_omni, D), Z.shape
        Z = fix_signs(Z.reshape(3 * n_omni, D)).reshape(3, n_omni, D)

        pair_names = [
            ("business", "shared investor"),
            ("business", "competitor"),
            ("shared investor", "competitor"),
        ]
        pair_idx = [(0, 1), (0, 2), (1, 2)]
        dists = np.zeros((n_omni, 3))
        for p, (a, b) in enumerate(pair_idx):
            dists[:, p] = np.linalg.norm(Z[a] - Z[b], axis=1)
        total = dists.sum(axis=1)
        order = np.argsort(-total, kind="stable")[:TOP_SHIFT]
        for k in order:
            cid = omni_ids[k]
            widest = pair_names[int(np.argmax(dists[k]))]
            shifts.append(
                {
                    "id": cid,
                    "label": by_id[cid]["name"],
                    "vertical": by_id[cid]["vertical"].replace("-", " "),
                    "shift": round(float(total[k]), 3),
                    "widest_gap": f"{widest[0]} ↔ {widest[1]}",
                }
            )
        assert shifts[0]["shift"] >= shifts[-1]["shift"] > 0

    top3 = ", ".join(s["label"] for s in shifts[:3])
    drift_note = (
        f"A big shift ({top3} lead) means the network sees a different company "
        "depending on the lens: partner-space says one thing, rivalry-space another."
        if shifts
        else f"Only {n_omni} companies are active in all three layers — too few for a "
        "stable shift table, so we skip it."
    )
    payload = {
        "slug": "layer-shift",
        "graph": "companies",
        "title": "Three lenses, one market",
        "sub": "same companies, three edge types — who moves when the lens changes",
        "headline": (
            f"Business ties wire the market's two shared dimensions together (cross-term "
            f"<strong>{biz_cross:.1f}</strong>, vs ≤{other_cross:.1f} for investor and rivalry "
            f"ties), the shared basis matches our hand-drawn verticals at ARI only {ari:.2f} — "
            f"and no role shifts more with the lens than {shifts[0]['label'] if shifts else '—'}'s."
        ),
        "prose": {
            "intro": (
                "<p>The company map draws three kinds of edges — business ties, shared investors, and "
                "competitor ties — and flattens them into one picture. But is “who you partner with,” "
                "“who funds you,” and “who you fight” really the same geometry? And which companies "
                "look completely different depending on which lens you pick up?</p>"
            ),
            "how": (
                "<p>Multiple adjacency spectral embedding (MASE) is like training one shared embedding "
                "space across three related datasets: every company gets a single position, and each edge "
                "layer gets its own small “mixing matrix” saying how that layer wires the shared "
                "dimensions together — same vocabulary, three different grammars. The heatmaps below are "
                "those 2×2 mixing matrices side by side; if the lenses agreed, the three would look alike. "
                "They don't: investor and rivalry ties stay on the diagonal (each dimension talks to "
                f"itself) while business ties load off-diagonal ({biz_cross:.1f}) and even negative on "
                "dim 2 — partnerships cut across the very structure that co-investment and competition "
                f"respect. Clustering the shared positions into 8 groups matches our hand-labeled "
                f"verticals at ARI {ari:.2f} (0 = random, 1 = perfect), so the wiring only faintly "
                "echoes the org chart. For the drift table we switch to an omnibus embedding — all three "
                f"layers stitched into one joint space so each of the {n_omni} companies active in every "
                "layer gets three comparable positions — and rank companies by how far their three "
                f"positions sit apart. {drift_note}</p>"
            ),
            "method": (
                f"<p>MASE (Arroyo et al., JMLR 2021) on the three binarized undirected layers over all "
                f"{n} companies, d={D} fixed and svd_seed=0; at per-layer mean degrees of "
                f"{mean_deg['business']:.1f}–{mean_deg['competitor']:.1f} the Zhu–Ghodsi elbow is "
                "unstable, so we do not trust automatic dimension selection here. Score matrices "
                "Rₖ = VᵀAₖV on the sign-fixed shared basis. ARI: KMeans(8, n_init=10, "
                "random_state=0) on V vs vertical labels. Shift table: OmnibusEmbed (Levin et al., "
                f"arXiv 2017), d={D}, svd_seed=0, restricted to the {n_omni} nodes with degree ≥1 in "
                "all three layers; per-node shift = sum of pairwise distances between its three omnibus "
                "positions. Layers are disconnected with 31–89 isolates each — spectral embeddings "
                "tolerate that (graspologic warns), but isolate positions are meaningless, hence the "
                "degree filter.</p>"
            ),
        },
        "caveat": (
            "The shared-investor layer leans on unverified investor lists (plain-text names, 17 of 178 "
            "edges inferred), so drift involving it is softer evidence. Agents of Chaos itself has no "
            "shared-investor edges (its 5 ties: 4 rivals + 1 inferred partner) and is excluded from the "
            "shift table by the degree filter."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "scores": scores,
            "shifts": shifts,
            "ari": round(ari, 3),
            "omniCount": n_omni,
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
