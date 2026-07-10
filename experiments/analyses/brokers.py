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
    # Since the 2026-07 edge audit, AIUC's certification ties (ElevenLabs,
    # Intercom, UiPath) chain AoC into the main commercial web.
    assert len(aoc_biz_comp) > 2 and AOC in G_biz, "AoC left the business web — rewrite the caveat"
    assert G_biz.degree(AOC) < MIN_DEGREE, "AoC's business seat changed — rewrite caveat + headline"
    aoc_deg = G_mixed.degree(AOC)
    aoc_rank = ranked_mixed.index(AOC) + 1
    aoc_cons = cons_mixed[AOC]

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
        "sub": "who can broker introductions across the market's gaps",
        "headline": (
            f"The labs aside, the market's best-placed broker is "
            f"<strong>{top_nonlab['label']} (constraint {top_nonlab['constraint']:.2f}, "
            f"{top_nonlab['degree']} ties across {top_nonlab['spans']} verticals)</strong> — "
            f"and counting only real business ties, the seat passes to {top_nonlab_biz['label']} "
            f"({top_nonlab_biz['constraint']:.2f})."
        ),
        "prose": {
            "intro": (
                "<p>Who in this market can actually broker an introduction? Not the best-connected "
                "company — the one whose contacts don't already know each other. That company sits "
                "across the open gaps between clusters, and those gaps are where deal flow, hiring, "
                "and early market intelligence move first.</p>"
            ),
            "how": (
                "<p>The score, called constraint, measures how much a company's contacts overlap: high "
                "when all its ties fold back into one tight clique, low when its contacts are strangers "
                "to each other and it alone connects them. Low constraint is what makes a broker. "
                "Effective size is the companion number — a tie count discounted for redundancy, so 12 "
                "contacts who all know each other count as far fewer than 12 independent ones. We rank "
                f"the {G_mixed.number_of_nodes()} companies in the map's main connected cluster from "
                f"least constrained to most, keeping the {len(ranked_mixed)} with at least "
                f"{MIN_DEGREE} ties ({n_floor_mixed} smaller nodes are excluded — with one or two ties, "
                "the score says nothing). Then we re-run on business edges only — customer, partner, "
                "and platform relationships — because a bridge made of shared-investor edges may never "
                "convert to a warm intro. The second table is the honest broker list.</p>"
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
            f"AoC's own {aoc_deg} edges are {aoc_comp_n} competitor ties plus one unverified business "
            f"tie ({partner}), so its seat in the full-map table (constraint {aoc_cons:.2f}, rank "
            f"{aoc_rank} of {len(ranked_mixed)}) mostly reflects rivalry. In the business-only map, "
            f"AoC now reaches the main commercial web — its one path runs through {partner} — but a "
            f"single business tie sits below the {MIN_DEGREE}-tie floor, so AoC still earns no broker "
            f"score. Note also that {n_vc_mixed if n_vc_mixed else 'none'} of the top "
            f"{len(rows_mixed)} full-map brokers are VCs: the mapped VCs sit at the market's edge, not "
            "in its gaps."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {"brokers": rows_mixed, "brokersBusiness": rows_biz},
    }
    emit(payload)


if __name__ == "__main__":
    main()
