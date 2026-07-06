# /// script
# requires-python = ">=3.11"
# dependencies = ["networkx"]
# ///
"""brokers — Burt structural holes on the company graph: who sits in the open
space between clusters (constraint + effective size), on the full mixed graph
and on business edges only. Run: cd experiments/analyses && uv run brokers.py
"""

import networkx as nx
from _shared import company_ids, emit, load_companies, load_funding, stamp

AOC = "agents-of-chaos"
INTRO_VERTICALS = {"investor-vc", "infra-platform", "enterprise-other"}
LAB = "frontier-lab"
MIN_DEGREE = 3
N_MIXED = 25
N_BUSINESS = 20


def build_graph(companies: dict, types: set[str] | None) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(c["id"] for c in companies["companies"])
    for e in companies["edges"]:
        if types is None or e["type"] in types:
            G.add_edge(e["source"], e["target"])
    return G


def lcc(G: nx.Graph) -> nx.Graph:
    return G.subgraph(max(nx.connected_components(G), key=len)).copy()


def broker_rows(
    G: nx.Graph, by_id: dict, top_n: int
) -> tuple[list[dict], list[str], dict]:
    """Constraint + effective size for degree>=MIN_DEGREE nodes, ascending constraint."""
    eligible = sorted(n for n in G if G.degree(n) >= MIN_DEGREE)
    assert eligible, "no nodes clear the degree floor?"
    cons = nx.constraint(G, nodes=eligible)
    eff = nx.effective_size(G, nodes=eligible)
    ranked = sorted(eligible, key=lambda n: (cons[n], -eff[n], n))
    rows = []
    for n in ranked[:top_n]:
        d = G.degree(n)
        assert 0.0 < cons[n] <= 1.5, f"constraint out of range for {n}: {cons[n]}"
        assert 0.0 < eff[n] <= d + 1e-9, f"effective size > degree for {n}"
        v = by_id[n]["vertical"]
        rows.append(
            {
                "id": n,
                "label": by_id[n]["name"],
                "vertical": v.replace("-", " "),
                "degree": d,
                "constraint": round(float(cons[n]), 3),
                "effSize": round(float(eff[n]), 1),
                "spans": len({by_id[m]["vertical"] for m in G[n]}),
                "flag": "broker by trade" if v in INTRO_VERTICALS else None,
            }
        )
    return rows, ranked, cons


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    ids = company_ids(companies)

    G_mixed = lcc(build_graph(companies, types=None))
    G_biz = lcc(build_graph(companies, types={"business"}))
    assert AOC in G_mixed, "AoC must sit in the giant component"
    assert set(G_mixed) <= ids and set(G_biz) <= ids

    rows_mixed, ranked_mixed, cons_mixed = broker_rows(G_mixed, by_id, N_MIXED)
    rows_biz, ranked_biz, _ = broker_rows(G_biz, by_id, N_BUSINESS)

    n_floor_mixed = G_mixed.number_of_nodes() - len(ranked_mixed)
    top_nonlab = next(r for r in rows_mixed if by_id[r["id"]]["vertical"] != LAB)
    top_nonlab_biz = next(r for r in rows_biz if by_id[r["id"]]["vertical"] != LAB)
    n_vc_mixed = sum(
        1 for r in rows_mixed if by_id[r["id"]]["vertical"] == "investor-vc"
    )

    # AoC's own seat — honest numbers for the caveat.
    aoc_edges = [e for e in companies["edges"] if AOC in (e["source"], e["target"])]
    aoc_comp_n = sum(1 for e in aoc_edges if e["type"] == "competitor")
    aoc_biz = [e for e in aoc_edges if e["type"] == "business"]
    assert len(aoc_edges) == aoc_comp_n + len(aoc_biz), "AoC edge mix changed"
    assert (
        len(aoc_biz) == 1 and not aoc_biz[0]["verified"]
    ), "AoC business-edge mix changed — rewrite the caveat"
    e = aoc_biz[0]
    partner = by_id[e["source"] if e["target"] == AOC else e["target"]]["name"]
    B_full = build_graph(companies, types={"business"})
    aoc_biz_comp = nx.node_connected_component(B_full, AOC)
    assert len(aoc_biz_comp) == 2, "AoC's business component grew — rewrite the caveat"
    aoc_deg = G_mixed.degree(AOC)
    aoc_rank = ranked_mixed.index(AOC) + 1
    aoc_cons = cons_mixed[AOC]
    assert AOC not in G_biz, "AoC joined the business LCC — rewrite caveat + headline"

    # Funding graph: forest check. Zero triangles => constraint == 1/degree
    # exactly, i.e. the statistic adds nothing beyond degree. Ship nothing.
    funding = load_funding()
    F = nx.Graph()
    F.add_nodes_from(n["id"] for n in funding["nodes"])
    F.add_edges_from((e["source"], e["target"]) for e in funding["edges"])
    fund_deg3 = sum(1 for n in F if F.degree(n) >= MIN_DEGREE)
    fund_tri = sum(nx.triangles(F).values()) // 3
    assert fund_tri == 0, "funding graph grew triangles — revisit data.brokersFunding"

    payload = {
        "slug": "brokers",
        "graph": "companies",
        "title": "The brokers",
        "sub": "who sits in the structural holes — and whose intros are real",
        "headline": (
            f"The labs aside, the market's widest structural hole belongs to "
            f"<strong>{top_nonlab['label']} (constraint {top_nonlab['constraint']:.2f}, "
            f"{top_nonlab['degree']} ties across {top_nonlab['spans']} verticals)</strong> — "
            f"on real business edges alone the seat passes to {top_nonlab_biz['label']} "
            f"({top_nonlab_biz['constraint']:.2f})."
        ),
        "prose": {
            "intro": (
                "<p>Who in this market can actually broker an introduction? Not the best-connected "
                "node — the least <em>constrained</em> one: the company whose contacts don't already "
                "know each other, so it sits across the open gaps between clusters. Those gaps are "
                "where deal flow, hiring, and early market intelligence move first.</p>"
            ),
            "how": (
                "<p>Burt's constraint is a concentration score on your ego network — think Herfindahl "
                "index for your attention: it's high when all your ties fold back into one tight clique, "
                "low when your contacts are mutual strangers you alone connect. Effective size is the "
                "companion statistic: your degree discounted for redundancy, exactly like effective "
                "sample size for correlated data — 12 contacts who all know each other count as far "
                f"fewer than 12 independent ones. We rank the {G_mixed.number_of_nodes()}-node giant "
                f"component ascending by constraint, keeping the {len(ranked_mixed)} nodes with degree "
                f"≥ {MIN_DEGREE} ({n_floor_mixed} lower-degree nodes are trivially constrained and "
                "excluded). Then we re-run on business edges only — customer, partner, and platform "
                "relationships — because a bridge made of shared-investor edges may never convert to a "
                "warm intro; the second table is the honest broker list.</p>"
            ),
            "method": (
                "<p>Burt (1992), <em>Structural Holes</em>: constraint "
                "c<sub>i</sub> = Σ<sub>j</sub>(p<sub>ij</sub> + Σ<sub>q</sub> p<sub>iq</sub>p<sub>qj</sub>)²; "
                "effective size via the Borgatti (1997) simplification for binary graphs; networkx "
                "implementations of both. Full mixed run: giant component of the company graph "
                f"({G_mixed.number_of_nodes()} nodes, {G_mixed.number_of_edges()} edges; smaller "
                "components excluded — constraint is a local statistic, so this only drops their few "
                f"eligible members). Business-only run: giant component of the business-edge subgraph "
                f"({G_biz.number_of_nodes()} nodes, {G_biz.number_of_edges()} edges, {len(ranked_biz)} "
                f"nodes over the degree floor). The funding graph was checked and not shipped: it has "
                f"zero triangles (a forest), so constraint reduces to exactly 1/degree for all "
                f"{fund_deg3} nodes over the floor — the statistic would restate degree and nothing "
                "else.</p>"
            ),
        },
        "caveat": (
            f"AoC's own {aoc_deg} edges are {aoc_comp_n} competitor ties plus one unverified, "
            f"inferred business tie ({partner}), so its mixed-graph seat (constraint {aoc_cons:.2f}, "
            f"rank {aoc_rank} of {len(ranked_mixed)}) is rivalry-flavored — and in the business-only "
            f"graph the AoC–{partner} pair is an isolated dyad off the giant component, so AoC is "
            f"absent from the warm-intro list entirely. Note also that "
            f"{n_vc_mixed if n_vc_mixed else 'none'} of the top {len(rows_mixed)} mixed-graph brokers "
            "are investor-vc nodes: the mapped VCs sit at this graph's periphery, not in its holes."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {"brokers": rows_mixed, "brokersBusiness": rows_biz},
    }
    emit(payload)


if __name__ == "__main__":
    main()
