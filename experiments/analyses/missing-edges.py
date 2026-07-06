# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "networkx", "scipy", "graspologic==3.4.4"]
# ///
"""missing-edges — supervised SBM on the verified company graph: non-edges the
block base rates say should exist (rival-vendor → buyer prospecting), plus a
verification-triage ranking of the currently-unverified edges.
Run: cd experiments/analyses && uv run missing-edges.py
"""

import networkx as nx
import numpy as np
from _shared import company_ids, emit, load_companies, stamp

BUYER_VERTICALS = ("bank-fintech", "healthcare", "enterprise-other", "infra-platform")
VERT_ORDER = (
    "frontier-lab",
    "agent-native-startup",
    "security-eval-vendor",
    "infra-platform",
    "enterprise-other",
    "bank-fintech",
    "healthcare",
    "investor-vc",
)
VERT_SHORT = {
    "frontier-lab": "frontier",
    "agent-native-startup": "agents",
    "security-eval-vendor": "security",
    "infra-platform": "infra",
    "enterprise-other": "enterprise",
    "bank-fintech": "banks",
    "healthcare": "health",
    "investor-vc": "VCs",
}
N_UNMAPPED_MAX = 25  # contract row cap; expect ~20 corroborated pairs
N_TRIAGE = 15
CLAIM_CHARS = 110


def fit_sbm(companies: dict) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Supervised SBM on the VERIFIED-only adjacency; y = vertical labels."""
    from graspologic.models import SBMEstimator

    ids = [c["id"] for c in companies["companies"]]
    idx = {i: k for k, i in enumerate(ids)}
    A = np.zeros((len(ids), len(ids)))
    for e in companies["edges"]:
        if not e["verified"]:
            continue
        a, b = idx[e["source"]], idx[e["target"]]
        A[a, b] = A[b, a] = 1.0
    y = np.array([c["vertical"] for c in companies["companies"]])
    assert set(y) == set(VERT_ORDER), f"vertical set drifted: {sorted(set(y))}"

    # Closed-form MLE (per-block-pair edge densities): deterministic, no seed,
    # and connectivity-agnostic — the 7 components and isolates are fine as-is.
    sbm = SBMEstimator(directed=False, loops=False)
    sbm.fit(A, y=y)
    blocks = [str(b) for b in np.unique(y)]
    P, B = sbm.p_mat_, sbm.block_p_
    assert P.shape == A.shape and B.shape == (len(blocks), len(blocks))
    assert np.allclose(P, P.T) and np.isfinite(P).all()
    assert 0.0 <= P.min() and P.max() <= 1.0
    k0, k1 = idx[ids[0]], idx[ids[1]]
    b0, b1 = blocks.index(y[0]), blocks.index(y[1])
    assert P[k0, k1] == B[b0, b1], "p_mat_ inconsistent with block_p_"
    return P, B, blocks, ids


def cross_check_signals(
    companies: dict, cand: list[tuple[str, str]]
) -> tuple[dict, dict, dict]:
    """Pair-level evidence: Adamic–Adar + Soundarajan–Hopcroft common-neighbor
    scores on the verified shared-investor subgraph (2-hop pairs only), and raw
    investor-name overlap (strings — labels, not resolved entities)."""
    by_id = {c["id"]: c for c in companies["companies"]}
    S = nx.Graph()
    S.add_nodes_from(by_id)
    for e in companies["edges"]:
        if e["type"] == "shared-investor" and e["verified"]:
            S.add_edge(e["source"], e["target"])
    nx.set_node_attributes(
        S, {cid: c["vertical"] for cid, c in by_id.items()}, "community"
    )

    two_hop = [
        (a, b)
        for a, b in cand
        if not S.has_edge(a, b) and any(True for _ in nx.common_neighbors(S, a, b))
    ]
    aa = {(a, b): s for a, b, s in nx.adamic_adar_index(S, two_hop)}
    cn = {(a, b): s for a, b, s in nx.cn_soundarajan_hopcroft(S, two_hop)}
    assert set(aa) == set(two_hop) and set(cn) == set(two_hop)
    # cross-vertical pairs can never earn the same-community bonus, so the
    # S–H score reduces to a common-neighbor count here — assert that.
    assert all(
        cn[p] == len(list(nx.common_neighbors(S, *p))) for p in two_hop
    ), "S–H bonus fired on a cross-block pair?"

    inv = {cid: set(c.get("investors") or []) for cid, c in by_id.items()}
    shared = {(a, b): len(inv[a] & inv[b]) for a, b in cand}
    return aa, cn, shared


def main() -> None:
    companies = load_companies()
    known = company_ids(companies)
    by_id = {c["id"]: c for c in companies["companies"]}
    P, B, blocks, ids = fit_sbm(companies)
    idx = {i: k for k, i in enumerate(ids)}

    vendors = sorted(c["id"] for c in companies["companies"] if c.get("competitor"))
    buyers = sorted(
        c["id"] for c in companies["companies"] if c["vertical"] in BUYER_VERTICALS
    )
    assert vendors and buyers and not set(vendors) & set(buyers)
    assert "agents-of-chaos" not in vendors, "AoC itself is not competitor-flagged"

    existing = {frozenset((e["source"], e["target"])) for e in companies["edges"]}
    cand = [
        (v, b) for v in vendors for b in buyers if frozenset((v, b)) not in existing
    ]
    assert len(cand) > 100, "candidate non-edge pool suspiciously small"

    aa, cn, shared = cross_check_signals(companies, cand)

    # ── deliverable 1: unmapped vendor→buyer pairs, corroborated only ────────
    def phat(a: str, b: str) -> float:
        return float(P[idx[a], idx[b]])

    corroborated = [p for p in cand if shared[p] >= 2 or aa.get(p, 0.0) > 0.0]
    corroborated.sort(key=lambda p: (-phat(*p), -shared[p], -aa.get(p, 0.0), p))
    n_zero_block = sum(1 for p in corroborated if phat(*p) == 0.0)
    unmapped = []
    for v, b in corroborated[:N_UNMAPPED_MAX]:
        sigs = []
        if aa.get((v, b), 0.0) > 0.0:
            k = int(cn[v, b])
            sigs.append(f"AA {aa[v, b]:.2f} ({k} co-investor bridge{'s' * (k != 1)})")
        if shared[(v, b)] >= 2:
            sigs.append(f"{shared[v, b]} shared investors")
        unmapped.append(
            {
                "id": v,
                "label": by_id[v]["name"],
                "prospect": by_id[b]["name"],
                "vertical": VERT_SHORT[by_id[b]["vertical"]],
                "phat": round(phat(v, b), 4),
                "crossCheck": " + ".join(sigs),
                "flag": "P̂=0: no verified edges in this block"
                if phat(v, b) == 0.0
                else None,
            }
        )
    assert 5 <= len(unmapped) <= N_UNMAPPED_MAX, f"{len(unmapped)} corroborated pairs"
    assert all(r["crossCheck"] for r in unmapped)

    # ── deliverable 2: verification triage of the unverified edges ──────────
    unverified = [e for e in companies["edges"] if not e["verified"]]
    assert unverified, "no unverified edges left — retire this panel"
    ranked = sorted(
        unverified,
        key=lambda e: (-phat(e["source"], e["target"]), e["source"], e["target"]),
    )
    triage = []
    for e in ranked[:N_TRIAGE]:
        s, t = e["source"], e["target"]
        claim = e.get("label") or ""
        if len(claim) > CLAIM_CHARS:
            claim = claim[: CLAIM_CHARS - 1].rstrip() + "…"
        triage.append(
            {
                "label": f"{by_id[s]['name']} ↔ {by_id[t]['name']}",
                "blocks": f"{VERT_SHORT[by_id[s]['vertical']]} × {VERT_SHORT[by_id[t]['vertical']]}",
                "type": e["type"],
                "phat": round(phat(s, t), 4),
                "claim": claim,
            }
        )
    assert triage[0]["phat"] >= triage[-1]["phat"]

    # ── deliverable 3: the 8×8 base-rate table itself ────────────────────────
    perm = [blocks.index(v) for v in VERT_ORDER]
    cells = [[round(float(B[i, j]), 4) for j in perm] for i in perm]
    assert all(cells[i][j] == cells[j][i] for i in range(8) for j in range(8))
    block_p = {
        "rows": [VERT_SHORT[v] for v in VERT_ORDER],
        "cols": [VERT_SHORT[v] for v in VERT_ORDER],
        "cells": cells,
    }

    shipped = {r["id"] for r in unmapped}
    assert shipped <= known, f"unknown ids shipped: {shipped - known}"

    sec_bank = float(
        B[blocks.index("security-eval-vendor"), blocks.index("bank-fintech")]
    )
    n_inv2 = sum(1 for p in corroborated if shared[p] >= 2)
    top = unmapped[0]

    payload = {
        "slug": "missing-edges",
        "graph": "companies",
        "title": "Edges that should exist but don't",
        "sub": "block base rates flag unmapped buyer ties + a verification queue",
        "headline": (
            f"Block base rates plus co-investor evidence flag <strong>{len(unmapped)} "
            f"unmapped vendor→buyer pairs</strong> worth checking — starting with "
            f"{top['label']} × {top['prospect']} — and rank all {len(unverified)} "
            f"unverified edges into a verification queue."
        ),
        "prose": {
            "intro": (
                "<p>The map only shows edges someone wrote down. Which customer relationships "
                "are probably out there but unmapped — and of the edges we drew without "
                "confirming, which should we verify first? Both questions matter commercially: "
                "the rival security vendors' unmapped buyer ties are, by symmetry, Agents of "
                "Chaos's own prospect list.</p>"
            ),
            "how": (
                "<p>A stochastic block model is just a table of base rates: group the 188 "
                "companies by vertical and measure how densely each pair of verticals is "
                "actually wired, using verified edges only. Every company pair then inherits "
                "its block pair's density as a link probability P̂ — a bigram model for graphs: "
                "no pair-level nuance, but honest about what's typical. A non-edge with high P̂ "
                "is a hole where the market usually has a wire. Because P̂ is flat within a "
                "block pair, ties are broken by pair-level evidence: Adamic–Adar on the "
                "co-investor layer (common neighbors down-weighted by how promiscuous they are — "
                "tf-idf for mutual friends) and raw shared-investor names; the table keeps only "
                "pairs where at least one of those independent signals fires. The same fitted P̂, "
                "scored on the edges held out of the fit because they are unverified, gives a "
                "triage order for the audit queue (experiments/networks/edge_audit.json): verify "
                "high-P̂ claims first, since that is where the graph most expects an edge and "
                "where a wrong one distorts everything downstream.</p>"
            ),
            "method": (
                "<p>Supervised SBM: graspologic 3.4.4 SBMEstimator(directed=False, loops=False) "
                "fit on the verified-only binarized adjacency with y = the 8 vertical labels "
                "(Holland, Laskey &amp; Leinhardt, Social Networks 1983). The MLE is the closed-form "
                "per-block-pair edge density — deterministic, seedless, and connectivity-agnostic, "
                "so the graph's 7 components and isolates need no LCC restriction. Candidates: all "
                "non-edges (no edge of any type, verified or not) between a competitor-flagged "
                "vendor and the buyer verticals {banks, health, enterprise, infra}, ranked by "
                "p_mat_. Cross-checks on the verified shared-investor subgraph restricted to 2-hop "
                "pairs: adamic_adar_index (Adamic &amp; Adar, Social Networks 2003) and "
                "cn_soundarajan_hopcroft (WWW 2012) with community = vertical — for cross-block "
                "pairs the S–H community bonus can never fire, so it reduces to a common-neighbor "
                "count and always agrees with AA (asserted); both are reported as one signal. "
                "Investor overlap counts matching name strings, not resolved entities.</p>"
            ),
        },
        "caveat": (
            f"The vendor × bank cell of the base-rate table is exactly {sec_bank:.3f}: the map has "
            "no verified security-vendor–bank edge, so the SBM cannot recommend what it has never "
            "seen — bank pairs rank last on P̂ and survive here only on co-investor evidence. "
            f"Only {n_inv2} pairs clear the ≥2-shared-investor bar, and investor names are "
            "unresolved strings, so aliases and fund-vs-firm naming quietly undercount overlap."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {"unmapped": unmapped, "triage": triage, "blockP": block_p},
    }
    emit(payload)


if __name__ == "__main__":
    main()
