# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "graspologic==3.4.4"]
# ///
"""competitor-nominations — vertex nomination from the 14 competitor-flagged
seeds: who else does the network treat like a red-team vendor? Per-seed distance
ranks fused by Borda count + reciprocal-rank fusion (no naive centroid).
Run: cd experiments/analyses && uv run competitor-nominations.py
"""

import numpy as np
from _shared import emit, fix_signs, load_companies, stamp

AOC = "agents-of-chaos"
SEED = 0
RRF_K = 60  # standard reciprocal-rank-fusion constant (Cormack et al. 2009)
N_NULL = 1000  # random seed-sized subsets for the tightness null
TOP_CONSENSUS = 20
N_PROSPECTS = 20
N_RIVALS = 10
BUYER_VERTICALS = {"bank-fintech", "healthcare", "enterprise-other", "infra-platform"}
RIVAL_VERTICALS = {"agent-native-startup", "security-eval-vendor", "frontier-lab"}


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


def fuse(
    X: np.ndarray, ids: list[str], seed_ids: list[str], cand: list[str]
) -> tuple[dict[str, int], dict[str, int]]:
    """Each seed independently ranks every candidate by embedding distance; the
    per-seed rank lists are fused by Borda count and by reciprocal-rank fusion.
    Returns (borda_rank, rrf_rank) — 1-based, ties broken by id (deterministic).
    """
    pos = {cid: k for k, cid in enumerate(ids)}
    M = len(cand)
    Xc = X[[pos[c] for c in cand]]
    borda = dict.fromkeys(cand, 0.0)
    rrf = dict.fromkeys(cand, 0.0)
    for s in seed_ids:
        d = np.linalg.norm(Xc - X[pos[s]], axis=1)
        order = np.argsort(d, kind="stable")
        for rank0, ci in enumerate(order):
            borda[cand[ci]] += M - 1 - rank0
            rrf[cand[ci]] += 1.0 / (RRF_K + rank0 + 1)
    borda_rank = {
        c: k + 1 for k, c in enumerate(sorted(cand, key=lambda c: (-borda[c], c)))
    }
    rrf_rank = {
        c: k + 1 for k, c in enumerate(sorted(cand, key=lambda c: (-rrf[c], c)))
    }
    return borda_rank, rrf_rank


def mean_pairwise(X: np.ndarray) -> float:
    n = X.shape[0]
    assert n >= 2
    total = 0.0
    for i in range(n - 1):
        total += float(np.linalg.norm(X[i + 1 :] - X[i], axis=1).sum())
    return total / (n * (n - 1) / 2)


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    seed_ids = [c["id"] for c in companies["companies"] if c.get("competitor")]
    assert len(seed_ids) >= 3, "need several competitor-flagged seeds to fuse"
    assert AOC in by_id and AOC not in seed_ids

    A_ver, ids = build_adjacency(companies, verified_only=True)
    A_all, _ = build_adjacency(companies, verified_only=False)
    n_ver = int(A_ver.sum() / 2)
    n_all = int(A_all.sum() / 2)
    n_unver_records = sum(1 for e in companies["edges"] if not e["verified"])
    X = embed(A_ver)  # primary: verified edges only
    X_all = embed(A_all)  # sensitivity: all edges
    d = X.shape[1]
    print(f"[debug] unique pairs: verified={n_ver} all={n_all}; ASE d={d}")

    # Candidate pool: non-seeds with >=1 VERIFIED edge. Verified-isolates embed
    # at exactly the origin — their "distance to seeds" is an artifact, and the
    # same pool is used for both runs so survival is a like-for-like comparison.
    pos = {cid: k for k, cid in enumerate(ids)}
    deg_ver = A_ver.sum(axis=1)
    n_iso = int((deg_ver == 0).sum())
    cand = [c for c in ids if c not in set(seed_ids) and deg_ver[pos[c]] > 0]
    M = len(cand)
    assert all(deg_ver[pos[s]] > 0 for s in seed_ids), "a seed lost all edges?"
    print(f"[debug] pool: {M} candidates ({n_iso} verified-isolates excluded)")

    # ── step 0: are the seeds even a cluster in this embedding? ──────────────
    embedded = [c for c in ids if deg_ver[pos[c]] > 0]
    seed_mean = mean_pairwise(X[[pos[s] for s in seed_ids]])
    market_mean = mean_pairwise(X[[pos[c] for c in embedded]])
    tight_ratio = seed_mean / market_mean
    rng = np.random.default_rng(SEED)
    emb_idx = np.array([pos[c] for c in embedded])
    null = np.array(
        [
            mean_pairwise(X[rng.choice(emb_idx, size=len(seed_ids), replace=False)])
            for _ in range(N_NULL)
        ]
    )
    null_pctile = float((null < seed_mean).mean())
    print(
        f"[debug] tightness: seeds {seed_mean:.3f} vs market {market_mean:.3f} "
        f"(ratio {tight_ratio:.2f}, spread beats {null_pctile:.0%} of random subsets)"
    )

    # ── nomination: fuse per-seed distance ranks (verified + all-edges runs) ──
    borda_rank, rrf_rank = fuse(X, ids, seed_ids, cand)
    borda_all, _rrf_all = fuse(X_all, ids, seed_ids, cand)
    consensus = {
        c
        for c in cand
        if borda_rank[c] <= TOP_CONSENSUS and rrf_rank[c] <= TOP_CONSENSUS
    }
    n_agree = len(consensus)
    print(f"[debug] fusion agreement: {n_agree} of top-{TOP_CONSENSUS} shared")
    print(
        f"[debug] AoC sanity: borda #{borda_rank[AOC]}, rrf #{rrf_rank[AOC]} of {M}"
        f" (all-edges borda #{borda_all[AOC]})"
    )
    for c in sorted(cand, key=lambda c: borda_rank[c])[:10]:
        print(
            f"[debug]   #{borda_rank[c]:>3} {c:<28} {by_id[c]['vertical']:<22} "
            f"rrf#{rrf_rank[c]:<4} deg={int(deg_ver[pos[c]])}"
        )

    def rows_for(verticals: set[str], n: int, with_persona: bool) -> list[dict]:
        pool = sorted(
            (c for c in cand if by_id[c]["vertical"] in verticals and c != AOC),
            key=lambda c: borda_rank[c],
        )
        keep_all = set(sorted(pool, key=lambda c: borda_all[c])[:n])
        out = []
        for c in pool[:n]:
            row = {
                "id": c,
                "label": by_id[c]["name"],
                "vertical": by_id[c]["vertical"].replace("-", " "),
                "borda": borda_rank[c],
                "rrf": rrf_rank[c],
                "deg": int(deg_ver[pos[c]]),
                "intensity": by_id[c]["intensity"],
                "survives": c in keep_all,
                "flag": None if c in keep_all else "drops with unverified edges",
            }
            if with_persona:
                row["persona"] = by_id[c].get("buyer_persona")
            out.append(row)
        return out

    prospects = rows_for(BUYER_VERTICALS, N_PROSPECTS, with_persona=True)
    rivals = rows_for(RIVAL_VERTICALS, N_RIVALS, with_persona=False)
    assert len(prospects) == N_PROSPECTS and len(rivals) == N_RIVALS
    assert not {r["id"] for r in prospects + rivals} & (set(seed_ids) | {AOC})
    n_p_survive = sum(r["survives"] for r in prospects)
    n_r_survive = sum(r["survives"] for r in rivals)

    # ── percentile map for the minimap (100 = most-nominated) ────────────────
    percentile = [
        {
            "id": c,
            "label": by_id[c]["name"],
            "pct": round(100.0 * (M - borda_rank[c]) / (M - 1), 1),
            "consensus": c in consensus,
        }
        for c in sorted(cand, key=lambda c: borda_rank[c])
    ]
    seeds_block = [{"id": s, "label": by_id[s]["name"]} for s in seed_ids]

    top_rivals = ", ".join(r["label"] for r in rivals[:3])
    payload = {
        "slug": "competitor-nominations",
        "graph": "companies",
        "title": "Who else orbits the red-team cluster",
        "sub": f"the graph finds companies shaped like our {len(seed_ids)} flagged rivals",
        "headline": (
            f"The graph says <strong>{top_rivals}</strong> compete with us but were never "
            f"flagged, and ranks {prospects[0]['label']} as our top buyer prospect. "
            f"{n_p_survive} of {N_PROSPECTS} prospects and {n_r_survive} of {N_RIVALS} rivals "
            f"keep their spot when the {n_unver_records} unverified edges are added."
        ),
        "prose": {
            "intro": (
                f"<p>We flagged {len(seed_ids)} companies as competitors by hand. This panel asks the graph two "
                "questions. Which <em>buyers</em> sit closest to that red-team cluster? Those are prospects. And "
                "which unflagged companies does the graph treat as one of the pack? Those are rivals we may have "
                "missed.</p>"
            ),
            "how": (
                "<p>The idea: give the graph a few examples and ask for more like them. Each company gets a "
                "position computed from the verified edges alone, placed so that companies with similar "
                f"connections sit near each other. Each of the {len(seed_ids)} rivals then ranks every candidate "
                "by distance, and we merge the lists with two standard rank-combining rules. Where both rules "
                f"agree ({n_agree} of the top {TOP_CONSENSUS}), we call it consensus and color it on the map. "
                "One warning from the data itself: the rivals do not form one tight cluster — their average "
                f"spacing is {tight_ratio:.2f}× the market's, wider than {null_pctile:.0%} of random same-sized "
                "groups. That is why each rival votes separately instead of being averaged into a single query "
                "point, which would land in empty space. The “edges” column shows how much verified wiring backs "
                "each nomination; a rank built on 2 edges is a lead, not a verdict.</p>"
            ),
            "method": (
                "<p>Vertex nomination via adjacency spectral embedding (Fishkind, Lyzinski, Pao, Chen &amp; Priebe, "
                "<em>Vertex nomination schemes for membership prediction</em>, Ann. Appl. Stat. 2015). ASE of the "
                f"binarized undirected company graph, verified edges only ({n_ver} unique pairs from "
                f"{len(companies['edges']) - n_unver_records} verified records; "
                f"diagonal augmentation; Zhu–Ghodsi elbow picked d={d}; svd_seed=0). The graph is disconnected — "
                f"{n_iso} companies have no verified edge, embed at exactly the origin, and are excluded from the "
                "candidate pool as artifacts. Per-seed Euclidean distance ranks are fused by Borda count and by "
                "reciprocal-rank fusion (Cormack, Clarke &amp; Büttcher, SIGIR 2009; k=60), ties broken "
                f"lexicographically. Tightness null: {N_NULL} random seed-sized subsets of embedded companies. "
                f"Sensitivity: the pipeline re-run on all {n_all} unique pairs including unverified edges, same "
                "candidate pool; a row “survives” if it stays in its table.</p>"
            ),
        },
        "caveat": (
            "All the seeds are security-eval vendors, so the buyer list means “wired into the red-team world,” "
            f"not “ready to buy.” The method cannot see us either: AoC ranks #{borda_rank[AOC]} of {M} because it "
            f"has only {int(deg_ver[pos[AOC]])} verified edges. Check the edges column before acting on a thin "
            "nomination. And note who is missing: no bank ranks near the cluster yet — bank "
            "security deals are rarely public, so read that as unmapped, not uninterested."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "tightness": {
                "seed_mean": round(seed_mean, 3),
                "market_mean": round(market_mean, 3),
                "ratio": round(tight_ratio, 3),
                "null_pctile": round(null_pctile, 3),
            },
            "prospects": prospects,
            "rivals": rivals,
            "percentile": percentile,
            "seeds": seeds_block,
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
