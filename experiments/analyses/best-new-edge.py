# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""best-new-edge — effective-resistance optimal single-edge addition, exact.

Which ONE new tie (agents-of-chaos, u) most shrinks AoC's summed effective
resistance to everyone in the connected core? Exact Sherman-Morrison rank-1
update of the Laplacian pseudoinverse, exhaustive over all non-neighbors,
brute-force verified for the top-3. Run: cd experiments/analyses && uv run best-new-edge.py
"""

import numpy as np
from _shared import company_ids, emit, load_companies, stamp

AOC = "agents-of-chaos"
EXPECTED_RIVALS = {"aiuc", "gray-swan-ai", "haize-labs", "helivan", "irregular"}
TOP_N = 10
N_PROPOSED = 3  # dashed ties drawn on the minimap
N_VERIFY = 3  # brute-force pinv recomputation for the top-N candidates


def largest_component(ids: list[str], adj: dict[str, set[str]]) -> list[str]:
    seen: set[str] = set()
    best: set[str] = set()
    for s in ids:
        if s in seen:
            continue
        comp, stack = {s}, [s]
        while stack:
            for y in adj[stack.pop()]:
                if y not in comp:
                    comp.add(y)
                    stack.append(y)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    return sorted(best)


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    ids = [c["id"] for c in companies["companies"]]
    adj: dict[str, set[str]] = {i: set() for i in ids}
    for e in companies["edges"]:
        assert e["source"] != e["target"], "self-loop in companies.json"
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])

    lcc = largest_component(ids, adj)
    n = len(lcc)
    assert n == 171 and AOC in lcc, f"LCC changed: {n} nodes, AoC in: {AOC in lcc}"
    assert adj[AOC] == EXPECTED_RIVALS, f"AoC edge inventory changed: {adj[AOC]}"
    n_excluded = len(ids) - n

    li = {cid: k for k, cid in enumerate(lcc)}
    a = li[AOC]
    A = np.zeros((n, n))
    for cid in lcc:
        for nb in adj[cid]:
            if nb in li:
                A[li[cid], li[nb]] = 1.0
    assert np.array_equal(A, A.T) and A.diagonal().sum() == 0

    # Laplacian pseudoinverse, computed ONCE (dense pinv is fine at n=171).
    L = np.diag(A.sum(1)) - A
    Lp = np.linalg.pinv(L, hermitian=True)
    assert np.allclose(Lp.sum(1), 0, atol=1e-9), "L+ rows must sum to 0 (null space 1)"
    dg = np.diag(Lp)

    # r(a,j) = L+_aa + L+_jj - 2 L+_aj ; current objectives.
    r_a = Lp[a, a] + dg - 2.0 * Lp[a, :]
    assert abs(r_a[a]) < 1e-12 and np.all(r_a[np.arange(n) != a] > 0)
    S_a = float(r_a.sum())  # sum of resistances AoC -> everyone
    Kf = float(n * np.trace(Lp))  # Kirchhoff index (sum over unordered pairs)
    assert np.isclose(S_a, n * Lp[a, a] + np.trace(Lp)), "row-sum-zero identity broke"

    # Sherman-Morrison for every candidate u at once. Adding edge (a,u) updates
    # L by +b b^T with b = e_a - e_u (b ⊥ 1, so the pinv update is exact):
    #   L+_new = L+ - v v^T / (1 + r(a,u)),  v = L+ b = L+[:,a] - L+[:,u]
    # Then (using 1^T v = 0 and L+ row sums 0):
    #   Δ S_a  = (n·v_a² + ‖v‖²) / (1 + r(a,u))
    #   Δ Kf   =  n·‖v‖²         / (1 + r(a,u))
    V = Lp[:, [a]] - Lp  # column u holds v for candidate u
    va = V[a, :]
    vtv = (V**2).sum(axis=0)
    denom = 1.0 + r_a
    d_aoc = (n * va**2 + vtv) / denom
    d_glob = n * vtv / denom

    candidates = [u for u in lcc if u != AOC and u not in adj[AOC]]
    assert len(candidates) == n - 1 - len(EXPECTED_RIVALS) == 165
    assert all(
        d_aoc[li[u]] > 0 and d_glob[li[u]] > 0 for u in candidates
    ), "adding an edge must strictly reduce both objectives (Rayleigh monotonicity)"

    ranked = sorted(candidates, key=lambda u: (-d_aoc[li[u]], u))
    ranked_glob = sorted(candidates, key=lambda u: (-d_glob[li[u]], u))

    # Brute-force verification: rebuild L with the extra edge, recompute pinv.
    for u in ranked[:N_VERIFY]:
        k = li[u]
        b = np.zeros(n)
        b[a], b[k] = 1.0, -1.0
        Lp2 = np.linalg.pinv(L + np.outer(b, b), hermitian=True)
        r2 = Lp2[a, a] + np.diag(Lp2) - 2.0 * Lp2[a, :]
        assert np.isclose(S_a - d_aoc[k], float(r2.sum()), atol=1e-8), u
        assert np.isclose(Kf - d_glob[k], float(n * np.trace(Lp2)), atol=1e-8), u

    known = company_ids(companies)
    rows = []
    for u in ranked[:TOP_N]:
        k = li[u]
        assert u in known
        rows.append(
            {
                "id": u,
                "label": by_id[u]["name"],
                "vertical": by_id[u]["vertical"].replace("-", " "),
                "persona": by_id[u]["buyer_persona"].split(" (")[0],
                "dAocPct": round(float(100 * d_aoc[k] / S_a), 2),
                "dGlobalPct": round(float(100 * d_glob[k] / Kf), 2),
            }
        )
    proposed = [
        {"a": AOC, "b": u, "label": by_id[u]["name"]} for u in ranked[:N_PROPOSED]
    ]

    top1, top2 = rows[0], rows[1]
    pct = lambda u: float(100 * d_aoc[li[u]] / S_a)  # noqa: E731
    gap12 = pct(ranked[0]) - pct(ranked[1])
    spread10 = pct(ranked[0]) - pct(ranked[TOP_N - 1])
    gb = ranked_glob[0]
    gb_pct = round(float(100 * d_glob[li[gb]] / Kf), 2)
    gb_aoc_rank = ranked.index(gb) + 1
    # The prose bakes these two facts — refuse to emit a stale story if they break.
    assert gb_aoc_rank == len(candidates), (
        f"global optimum {gb} is no longer the WORST AoC edge (rank {gb_aoc_rank}) — "
        "rewrite the disagreement sentence in prose.how"
    )
    assert A[li[gb]].sum() == 1, f"{gb} is no longer a one-edge pendant — fix prose.how"

    payload = {
        "slug": "best-new-edge",
        "graph": "companies",
        "title": "The one handshake",
        "sub": "which single new relationship most shrinks our distance to the whole market",
        "headline": (
            f"The best single new tie is <strong>{top1['label']}</strong> — that one edge cuts "
            f"AoC's distance to the whole market by <strong>{top1['dAocPct']:.1f}%</strong>. "
            f"It is nearly a tie: {top2['label']} sits {gap12:.3f} points behind, and the whole "
            f"top-10 spans {spread10:.2f} — so pick the hub you can actually reach."
        ),
        "prose": {
            "intro": (
                "<p>Agents of Chaos touches this map through five edges, all competitor ties. Suppose we "
                "could add exactly one new relationship — a design partner, an investor, a platform "
                "integration. Which one would pull us closest to the whole market at once, not just to "
                "one company?</p>"
            ),
            "how": (
                "<p>Treat the graph as an electrical circuit: every edge is a resistor, and the effective "
                "resistance between two companies measures how hard it is to travel between them through "
                "all routes at once. Many short parallel paths mean low resistance. We score AoC's position "
                "as the sum of its resistances to all 170 other companies in the connected core. Then, for "
                f"each of the {len(candidates)} companies we have no tie to, we ask: add that one edge — "
                "what is the exact new score? (An algebraic shortcut answers this exactly for every "
                "candidate at once.) The winners are all hubs, and nearly interchangeable ones: AoC is "
                f"peripheral enough that even the <em>worst</em> candidate cuts {pct(ranked[-1]):.1f}%, but "
                "hubs nearly double that. The comparison column scores the same edge by how much it shrinks "
                "resistance between <em>all</em> pairs of companies. That objective prefers rescuing "
                f"stranded nodes — its winner ({by_id[gb]['name']}, a one-edge pendant, −{gb_pct:.1f}% "
                f"global) is the single worst edge for AoC, #{gb_aoc_rank} of {len(candidates)}.</p>"
            ),
            "method": (
                "<p>Resistance distance per Klein &amp; Randić (1993); global objective is the Kirchhoff "
                "index Kf = n·tr(L⁺). L⁺ computed once via dense numpy.linalg.pinv (hermitian) on the "
                f"{n}-node largest connected component of the all-edges company graph (unweighted, "
                "unverified edges included). Adding edge (a,u) updates L by +(e_a−e_u)(e_a−e_u)ᵀ; the "
                "pseudoinverse follows by Sherman–Morrison, exact because e_a−e_u is orthogonal to the "
                "Laplacian null space (cf. Ranjan, Zhang &amp; Boley 2014). Exhaustive over all "
                f"{len(candidates)} non-neighbors; the top-{N_VERIFY} deltas verified against brute-force "
                f"pinv recomputation to 1e-8. The {n_excluded} companies outside the core are unreachable "
                "(infinite resistance) and excluded.</p>"
            ),
        },
        "caveat": (
            "All of this depends on the current edge inventory: AoC's 5 edges are all competitor ties, so "
            "“distance to market” is measured through the rivalry layer. Unverified edges count as wire, "
            f"and the {n_excluded} companies outside the connected core are not scored."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "candidates": rows,
            "proposed": proposed,
            "current": {
                "sumResistance": round(S_a, 3),
                "kirchhoff": round(Kf, 3),
                "nCore": n,
                "nCandidates": len(candidates),
            },
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
