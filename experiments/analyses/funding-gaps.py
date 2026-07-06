# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""funding-gaps — RDPG/SVD link prediction over the money graph: which
funder→grantee checks should exist but don't, validated by k-fold edge holdout.
Run: cd experiments/analyses && uv run funding-gaps.py
"""

import html
import statistics

import numpy as np
from _shared import emit, fix_signs, load_funding, stamp
from scipy.stats import rankdata, spearmanr

GRANT_KINDS = {"philanthropy", "government", "corporate"}
AOC_TAGS = {"agent-security", "evals", "multi-agent"}  # AoC-shaped grantees
DS = [1, 2, 3, 4, 6, 8, 12]  # embedding-dimension grid for the holdout sweep
K = 5  # folds
TOP_N = 15
WARM_N = 10
SEED = 0


def build_matrix(
    edges: list[dict],
    f_index: dict[str, int],
    g_index: dict[str, int],
    impute: dict[str, float],
) -> np.ndarray:
    """Funder × grantee matrix of log10(amountUSD + 1); undisclosed amounts get
    the disclosed `impute` value for their edge type."""
    A = np.zeros((len(f_index), len(g_index)))
    for e in edges:
        amt = e["amountUSD"] if e.get("amountUSD") is not None else impute[e["type"]]
        assert amt > 0, f"non-positive amount on {e['source']}→{e['target']}"
        A[f_index[e["source"]], g_index[e["target"]]] = np.log10(amt + 1)
    return A


def link_scores(M: np.ndarray, d: int) -> np.ndarray:
    """Rank-d SVD reconstruction — the RDPG link score X @ Y.T with signs fixed
    coordinately (flip both factors, so scores are flip-invariant)."""
    with np.errstate(all="ignore"):  # macOS BLAS emits spurious warnings
        U, S, Vt = np.linalg.svd(M, full_matrices=False)
        Ud = U[:, :d]
        Uf = fix_signs(Ud)
        flips = np.sign(np.sum(Uf * Ud, axis=0))
        flips[flips == 0] = 1.0
        X = Uf * np.sqrt(S[:d])
        Y = (Vt[:d].T * flips) * np.sqrt(S[:d])
        P = X @ Y.T
    assert np.isfinite(P).all(), f"non-finite link scores at d={d}"
    return P


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Mann-Whitney AUC with tie handling: P(random positive > random negative)."""
    r = rankdata(np.concatenate([pos, neg]))
    n1, n0 = len(pos), len(neg)
    assert n1 > 0 and n0 > 0
    return float((r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def holdout_sweep(
    A: np.ndarray, neg_pools: dict[str, np.ndarray], rng: np.random.Generator
) -> dict[str, dict[int, list[float]]]:
    """5-fold edge holdout: hide a fold, re-embed, score hidden edges vs an
    equal number of seeded random absent pairs from each negative pool."""
    obs = [tuple(x) for x in np.argwhere(A > 0)]
    perm = rng.permutation(len(obs))
    folds = [perm[k::K] for k in range(K)]
    fold_negs = {
        name: [pool[rng.choice(len(pool), size=len(f), replace=False)] for f in folds]
        for name, pool in neg_pools.items()
    }
    out: dict[str, dict[int, list[float]]] = {n: {d: [] for d in DS} for n in neg_pools}
    for d in DS:
        for k, fold in enumerate(folds):
            M = A.copy()
            hidden = [obs[t] for t in fold]
            for i, j in hidden:
                M[i, j] = 0.0
            P = link_scores(M, d)
            pos = np.array([P[i, j] for i, j in hidden])
            for name in neg_pools:
                neg = np.array([P[i, j] for i, j in fold_negs[name][k]])
                out[name][d].append(auc(pos, neg))
    return out


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    domain_label = {d["id"]: d["label"] for d in funding["meta"]["domains"]}
    funders = [n for n in funding["nodes"] if n["kind"] == "funder"]
    grantees = [n for n in funding["nodes"] if n["kind"] == "grantee"]
    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    grants = [e for e in money if e["type"] == "grant"]
    invs = [e for e in money if e["type"] == "investment"]
    assert len(grants) >= 50 and len(invs) >= 10, "suspiciously few money edges"
    assert len({(e["source"], e["target"]) for e in money}) == len(
        money
    ), "duplicate funder→grantee pairs — matrix would silently overwrite"

    # ── structural facts we rely on (fail loud if the graph changes shape) ──
    assert all(nodes[e["source"]]["funderKind"] in GRANT_KINDS for e in grants)
    assert all(nodes[e["source"]]["funderKind"] == "vc" for e in invs)
    layer_overlap = {e["target"] for e in grants} & {e["target"] for e in invs}
    assert layer_overlap <= {"apollo-research"}, f"layers now share {layer_overlap}"
    regrants = [e for e in grants if e.get("regrantOf")]
    assert all(
        e["source"] == "survival-and-flourishing-fund"
        and e["regrantOf"] == "jaan-tallinn"
        for e in regrants
    ), "regrant structure changed — recheck double-counting"

    # undisclosed amounts → median disclosed amount of the same edge type
    med = {
        t: statistics.median(
            e["amountUSD"] for e in money if e["type"] == t and e["amountUSD"]
        )
        for t in ("grant", "investment")
    }
    floor = {
        t: min(e["amountUSD"] for e in money if e["type"] == t and e["amountUSD"])
        for t in ("grant", "investment")
    }
    n_null_g = sum(1 for e in grants if e.get("amountUSD") is None)
    n_null_i = sum(1 for e in invs if e.get("amountUSD") is None)

    # ── grant layer: philanthropy/government/corporate funders × any grantee ──
    gf_ids = [f["id"] for f in funders if f["funderKind"] in GRANT_KINDS]
    gg_ids = [g["id"] for g in grantees]
    f_index = {f: i for i, f in enumerate(gf_ids)}
    g_index = {g: i for i, g in enumerate(gg_ids)}
    A = build_matrix(grants, f_index, g_index, med)
    obs_mask = A > 0
    assert int(obs_mask.sum()) == len(grants)
    active = obs_mask.any(axis=1)
    n_active = int(active.sum())
    cand_idx = np.argwhere(~obs_mask)  # every absent funder→grantee pair
    hard_idx = np.argwhere(~obs_mask & active[:, None])  # active funders only

    rng = np.random.default_rng(SEED)
    sweep_g = holdout_sweep(A, {"easy": cand_idx, "hard": hard_idx}, rng)
    mean_easy = {d: float(np.mean(sweep_g["easy"][d])) for d in DS}
    mean_hard = {d: float(np.mean(sweep_g["hard"][d])) for d in DS}
    best_d = min(DS, key=lambda d: (-mean_easy[d], d))
    auc_easy, auc_hard = mean_easy[best_d], mean_hard[best_d]
    fold_lo = min(sweep_g["easy"][best_d])
    fold_hi = max(sweep_g["easy"][best_d])
    assert (
        auc_easy >= 0.65
    ), f"holdout AUC degraded to {auc_easy:.3f} — headline phrasing no longer honest"
    assert best_d == 1, (
        f"validation now picks d={best_d} — prose.how/caveat describe a 1-D "
        "activity×breadth model and must be rewritten by a human"
    )

    # ── investment layer: vc × (startups + apollo, the observed exception) ──
    vf_ids = [f["id"] for f in funders if f["funderKind"] == "vc"]
    vg_ids = [
        g["id"]
        for g in grantees
        if g["granteeKind"] == "startup" or g["id"] == "apollo-research"
    ]
    Ai = build_matrix(
        invs,
        {f: i for i, f in enumerate(vf_ids)},
        {g: i for i, g in enumerate(vg_ids)},
        med,
    )
    sweep_i = holdout_sweep(Ai, {"easy": np.argwhere(~(Ai > 0))}, rng)
    mean_inv = {d: float(np.mean(sweep_i["easy"][d])) for d in DS}
    auc_inv = max(mean_inv.values())
    assert (
        auc_inv < 0.65
    ), f"VC layer now validates (best AUC {auc_inv:.3f}) — ship its predictions"

    # ── final predictions: full-matrix embedding at the validated d ──────────
    P = link_scores(A, best_d)
    pairs = sorted(
        ((float(P[i, j]), gf_ids[i], gg_ids[j]) for i, j in cand_idx),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    top_score = pairs[0][0]
    assert top_score > 0, "no positive predicted gap — nothing to rank"

    # imputation sensitivity: median vs minimum-disclosed floor for null amounts
    P_floor = link_scores(build_matrix(grants, f_index, g_index, floor), best_d)
    rho = float(spearmanr(P[~obs_mask], P_floor[~obs_mask]).statistic)
    floor_pairs = sorted(
        ((float(P_floor[i, j]), gf_ids[i], gg_ids[j]) for i, j in cand_idx),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    top_overlap = len(
        {(f, g) for _, f, g in pairs[:TOP_N]}
        & {(f, g) for _, f, g in floor_pairs[:TOP_N]}
    )
    assert rho > 0.7, f"imputation choice reorders candidates too much: ρ={rho:.3f}"

    def why(f_node: dict, g_node: dict) -> tuple[str, str | None]:
        shared = sorted(
            set(f_node.get("domainTags") or []) & set(g_node.get("domainTags") or [])
        )
        if not g_node.get("domainTags"):
            return (
                "grantee has no declared focus — pattern only",
                "no declared focus on file",
            )
        if shared:
            return "shared focus: " + ", ".join(domain_label[t] for t in shared), None
        return "no declared overlap — co-funding pattern only", None

    def rows_for(sel: list[tuple[float, str, str]], with_apply: bool) -> list[dict]:
        out = []
        for s, fid, gid in sel:
            f_node, g_node = nodes[fid], nodes[gid]
            why_line, flag = why(f_node, g_node)
            row = {
                "id": gid,
                "funder": f_node["name"],
                "label": g_node["name"],
                "score": round(s / top_score, 3),
                "why": why_line,
            }
            if with_apply:
                row["apply"] = f_node["apply"]["mode"]
            else:
                row["funders"] = int(obs_mask[:, g_index[gid]].sum())
            row["flag"] = flag
            out.append(row)
        return out

    predicted = rows_for(pairs[:TOP_N], with_apply=False)
    warm_pairs = [
        (s, f, g)
        for s, f, g in pairs
        if set(nodes[g].get("domainTags") or []) & AOC_TAGS
    ][:WARM_N]
    assert len(warm_pairs) >= 3, "warm slice collapsed — recheck AoC tags"
    warm = rows_for(warm_pairs, with_apply=True)
    assert all(a["score"] >= b["score"] for a, b in zip(predicted, predicted[1:]))
    assert predicted[0]["score"] == 1.0

    proposed = [{"a": f, "b": g} for _, f, g in pairs[:TOP_N]]
    assert all(p["a"] in nodes and p["b"] in nodes for p in proposed)

    n_funders_by_top = len({f for _, f, _ in pairs[:TOP_N]})
    top1 = pairs[0]
    esc = html.escape
    top_f, top_g = esc(nodes[top1[1]]["name"]), esc(nodes[top1[2]]["name"])

    payload = {
        "slug": "funding-gaps",
        "graph": "funding",
        "title": "The missing checks",
        "sub": "link prediction over the money graph — which grants should exist but don't",
        "headline": (
            f"Hide a fifth of the graph's {len(grants)} tracked grants and a "
            f"{best_d}-dimensional embedding finds them again with <strong>AUC "
            f"{auc_easy:.2f}</strong> — turned on the {len(cand_idx):,} absent pairs, "
            f"it calls {top_f} → {top_g} the field's most overdue check."
        ),
        "prose": {
            "intro": (
                f"<p>The funding map records {len(grants)} grants that did happen. For anyone "
                "planning a raise — Agents of Chaos included — the sharper question is which "
                "checks haven't happened yet but fit the pattern of the ones that did. This "
                "panel scores every absent funder→grantee pair and ships only what survives "
                "validation.</p>"
            ),
            "how": (
                "<p>This is the recommender-system trick — people who bought X also bought Y — "
                "run on money instead of movies. Fill a funder × grantee grid with log-dollars, "
                "factor it with an SVD the way a recommender compresses user × movie ratings, "
                "and a large predicted value in an empty cell is a grant the pattern says is "
                "missing. The honest part is the test: hide a fifth of the real grants, refit, "
                f"and ask the model to pick them out from decoy pairs — AUC {auc_easy:.2f} means "
                "the real hidden grant outranks a decoy about three times out of four. "
                f"Validation also chose d={best_d}: {len(grants)} grants earn the model exactly "
                "one axis — how much a funder deploys × how widely a grantee is funded — and "
                "every richer model scored worse. The VC investment layer validates at "
                f"coin-flip (AUC {auc_inv:.2f} at best), so we refuse to predict it. A "
                "200-node graph gives coarse recommendations; read the list as prioritized "
                "homework, not prophecy.</p>"
            ),
            "method": (
                "<p>Random-dot-product-graph link prediction: truncated SVD of the "
                f"{len(gf_ids)}×{len(gg_ids)} funder × grantee matrix, entries log10($+1), "
                "scores X@Yᵀ (Athreya et al., JMLR 2018 for RDPG/ASE; Koren–Bell–Volinsky 2009 "
                f"for the matrix-completion reading). Undisclosed amounts ({n_null_g}/{len(grants)} "
                f"grants, {n_null_i}/{len(invs)} rounds) get the median disclosed amount of their "
                "edge type; re-scoring with the minimum disclosed instead reorders candidates "
                f"with Spearman ρ={rho:.2f} and keeps {top_overlap}/{TOP_N} of the top list. "
                "SFF's regranted checks (payer: Jaan Tallinn) count once, under the program "
                "that decided them. The grant and investment layers share no funders and only "
                "Apollo Research as a grantee, so each layer embeds separately — jointly, the "
                "philanthropy block zeroes out the VC block. d is chosen from {1…12} by 5-fold "
                "edge holdout (numpy default_rng(0)): hide a fold, re-embed, score hidden edges "
                f"against equal-count random absent pairs. d={best_d} maximizes mean AUC "
                f"({auc_easy:.3f}; folds {fold_lo:.2f}–{fold_hi:.2f}). Against harder decoys — "
                f"absent pairs of the {n_active} funders with tracked grants — AUC falls to "
                f"{auc_hard:.2f}: much of the easy signal is knowing who writes checks at all. "
                "SVD signs fixed via _shared.fix_signs with coordinated flips on both factors; "
                "scores shown relative to the strongest predicted gap.</p>"
            ),
        },
        "caveat": (
            "“Missing” means missing from this graph — a predicted check may exist in reality "
            f"but be untracked by our sources. {len(gf_ids) - n_active} of {len(gf_ids)} "
            "grant-side funders have no tracked grants, so the model can never nominate them. "
            f"The top list leans on one funder ({n_funders_by_top} distinct funders in {TOP_N} "
            f"rows): at d={best_d} the model knows activity and breadth, not thematic fit — the "
            "“why plausible” column is annotation from declared domain tags, not model output. "
            "Investment predictions failed validation (AUC ≈ 0.5) and are deliberately absent."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "predicted": predicted,
            "warm": warm,
            "aucSweep": {
                "x": DS,
                "xLabel": "embedding dimensions d",
                "series": [
                    {
                        "label": "vs any absent",
                        "y": [round(mean_easy[d], 3) for d in DS],
                    },
                    {
                        "label": "vs active only",
                        "y": [round(mean_hard[d], 3) for d in DS],
                    },
                    {"label": "VC rounds", "y": [round(mean_inv[d], 3) for d in DS]},
                ],
                "annotate": {"x": best_d, "text": f"validation picks d={best_d}"},
            },
            "proposed": proposed,
            "stats": {
                "nGrants": len(grants),
                "nInvestments": len(invs),
                "nFunders": len(gf_ids),
                "nGrantees": len(gg_ids),
                "nCandidates": int(len(cand_idx)),
                "nActiveFunders": n_active,
                "d": best_d,
                "auc": round(auc_easy, 3),
                "aucHard": round(auc_hard, 3),
                "aucInv": round(auc_inv, 3),
            },
        },
    }
    emit(payload)

    # eyeball table for the run log
    print(f"    d sweep (easy): {[f'{d}:{mean_easy[d]:.3f}' for d in DS]}")
    print(
        f"    chosen d={best_d}  easy={auc_easy:.3f}  hard={auc_hard:.3f}  inv={auc_inv:.3f}  ρ_impute={rho:.3f}"
    )
    for i, r in enumerate(predicted, 1):
        print(
            f"    {i:2d}. {r['funder'][:28]:28s} -> {r['label'][:32]:32s} {r['score']:.3f}  {r['why']}"
        )


if __name__ == "__main__":
    main()
