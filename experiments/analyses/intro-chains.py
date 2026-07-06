# /// script
# requires-python = ">=3.11"
# dependencies = ["networkx"]
# ///
"""intro-chains — Yen k-shortest intro routes from AoC to prospects, majors,
and funders, plus the intermediaries worth cultivating first.
Run: cd experiments/analyses && uv run intro-chains.py
"""

import itertools
from collections import Counter

import networkx as nx
from _shared import company_ids, emit, funding_ids, load_companies, load_funding, stamp

AOC = "agents-of-chaos"
K = 3  # chains kept per target
FRICTION = {"business": 1, "shared-investor": 2, "competitor": 10}
N_SOURCES = 3  # funding-graph sources: AoC-linked grantees closest to AoC

# Curated at bake time by reading the sibling baked panels (see method note):
# top-3 prospects from competitor-nominations.json, the one top-5 shortlist
# funder that lives in the company graph (funder-shortlist.json), the majors.
COMPANY_TARGETS: list[tuple[str, str]] = [
    ("uipath", "top nominated prospect"),
    ("servicenow", "top nominated prospect"),
    ("palantir", "top nominated prospect"),
    ("sequoia-capital", "shortlist VC in the company graph"),
    ("anthropic", "major"),
    ("openai", "major"),
    ("microsoft", "major"),
    ("google-deepmind", "major"),
]
# Top-5 of funder-shortlist.json by score (clean cutoff above the 0.6 band).
FUNDER_TARGETS: list[tuple[str, int]] = [
    ("coefficient-giving", 1),
    ("schmidt-sciences", 2),
    ("sequoia-capital", 3),
    ("insight-partners", 4),
    ("nsf", 5),
]


def build_company_graph(companies: dict) -> nx.Graph:
    G = nx.Graph()
    for c in companies["companies"]:
        G.add_node(c["id"])
    for e in companies["edges"]:
        w = FRICTION[e["type"]]
        a, b = e["source"], e["target"]
        if G.has_edge(a, b) and G[a][b]["w"] <= w:
            continue  # 7 multi-edge pairs: keep the cheapest relationship
        G.add_edge(a, b, w=w, type=e["type"], verified=e["verified"])
    return G


def build_funding_graph(funding: dict) -> nx.Graph:
    F = nx.Graph()
    for n in funding["nodes"]:
        F.add_node(n["id"])
    for e in funding["edges"]:
        F.add_edge(
            e["source"],
            e["target"],
            type=e["type"],
            year=e.get("year"),
            role=e.get("role"),
            verified=e.get("verified"),
        )
    return F


def yen_paths(G: nx.Graph, s: str, t: str, weight: str | None) -> list[list[str]]:
    try:
        return list(
            itertools.islice(nx.shortest_simple_paths(G, s, t, weight=weight), K)
        )
    except nx.NetworkXNoPath:
        return []


def company_chain(G: nx.Graph, path: list[str], name: dict) -> dict:
    nodes = [{"id": n, "label": name[n], "graph": "companies"} for n in path]
    edges = [
        {"label": G[a][b]["type"].replace("-", " "), "verified": G[a][b]["verified"]}
        for a, b in zip(path, path[1:])
    ]
    assert len(edges) == len(nodes) - 1
    return {
        "score": sum(G[a][b]["w"] for a, b in zip(path, path[1:])),
        "nodes": nodes,
        "edges": edges,
    }


def funding_edge_label(ed: dict) -> dict:
    if ed["type"] == "affiliation":
        role = (ed["role"] or "affiliated").split(",")[0]
        return {"label": role, "verified": True}  # all affiliations carry a sourceUrl
    label = ed["type"] + (f" {ed['year']}" if ed["year"] else "")
    return {"label": label, "verified": bool(ed["verified"])}


def funding_chain(F: nx.Graph, path: list[str], name: dict) -> dict:
    nodes = [{"id": n, "label": name[n], "graph": "funding"} for n in path]
    edges = [funding_edge_label(F[a][b]) for a, b in zip(path, path[1:])]
    assert len(edges) == len(nodes) - 1
    return {"score": len(edges), "nodes": nodes, "edges": edges}


def best_funding_paths(F: nx.Graph, sources: list[str], target: str) -> list[list[str]]:
    """Pool Yen paths from every source, keep the K shortest overall.
    Deterministic tie-break: hop count, then source closeness rank, then Yen rank."""
    pool: list[tuple[int, int, int, list[str]]] = []
    for si, s in enumerate(sources):
        for yi, p in enumerate(yen_paths(F, s, target, weight=None)):
            pool.append((len(p) - 1, si, yi, p))
    pool.sort(key=lambda x: (x[0], x[1], x[2]))
    return [p for _, _, _, p in pool[:K]]


def main() -> None:
    companies = load_companies()
    funding = load_funding()
    cids, fids = company_ids(companies), funding_ids(funding)
    cname = {c["id"]: c["name"] for c in companies["companies"]}
    cvert = {c["id"]: c["vertical"] for c in companies["companies"]}
    fnode = {n["id"]: n for n in funding["nodes"]}
    fname = {n["id"]: n["name"] for n in funding["nodes"]}

    G = build_company_graph(companies)
    F = build_funding_graph(funding)

    # ── the mandatory honesty checks: AoC's periphery, machine-verified ──────
    aoc_edges = [e for e in companies["edges"] if AOC in (e["source"], e["target"])]
    assert len(aoc_edges) == 5, f"AoC degree changed: {len(aoc_edges)}"
    type_counts = Counter(e["type"] for e in aoc_edges)
    assert type_counts == {"competitor": 4, "business": 1}, type_counts
    biz = next(e for e in aoc_edges if e["type"] == "business")
    aiuc = biz["source"] if biz["target"] == AOC else biz["target"]
    assert aiuc == "aiuc" and not biz["verified"], "AIUC tie changed — update caveat"
    assert G.degree("aiuc") == 1, "AIUC grew edges — caveat's dead-end claim is stale"
    G_no_rivalry = nx.Graph(
        (a, b, d) for a, b, d in G.edges(data=True) if d["type"] != "competitor"
    )
    G_no_rivalry.add_nodes_from(G.nodes)
    cutoff = nx.node_connected_component(G_no_rivalry, AOC)
    assert cutoff == {AOC, "aiuc"}, f"no-rivalry component changed: {sorted(cutoff)}"

    # ── company chains: AoC → 8 curated targets ──────────────────────────────
    assert all(t in cids for t, _ in COMPANY_TARGETS)
    aoc_component = nx.node_connected_component(G, AOC)
    company_groups, first_hops = [], Counter()
    intermediaries: Counter = Counter()
    n_company_chains = 0
    for target, why in COMPANY_TARGETS:
        if target not in aoc_component:
            company_groups.append(
                {
                    "target": {
                        "id": target,
                        "label": cname[target],
                        "graph": "companies",
                    },
                    "why": why,
                    "flag": "outside AoC's connected component — no route exists",
                    "chains": [],
                }
            )
            continue
        chains = []
        for path in yen_paths(G, AOC, target, weight="w"):
            assert path[0] == AOC and path[-1] == target
            assert (
                G[path[0]][path[1]]["type"] == "competitor"
            ), f"first hop to {target} is not a rival — rewrite the caveat"
            first_hops[path[1]] += 1
            for n in path[1:-1]:
                intermediaries[("companies", n)] += 1
            chains.append(company_chain(G, path, cname))
        assert len(chains) == K
        n_company_chains += len(chains)
        company_groups.append(
            {
                "target": {"id": target, "label": cname[target], "graph": "companies"},
                "why": why,
                "chains": chains,
            }
        )
    n_unreachable_company = sum(1 for g in company_groups if not g["chains"])
    for major in ("anthropic", "openai", "google-deepmind"):
        assert nx.shortest_path_length(G, AOC, major) == 2, f"{major} not 2 hops"

    # ── funding sources: the AoC-linked grantees closest to AoC ─────────────
    linked = [
        (n["id"], n["networksId"])
        for n in funding["nodes"]
        if n["kind"] == "grantee" and n.get("networksId")
    ]
    assert linked, "no grantees carry a networksId"
    ranked = sorted(
        (
            (nx.shortest_path_length(G, AOC, nid, weight="w"), fid)
            for fid, nid in linked
            if nid in cids and nid in aoc_component
        ),
    )
    sources = [fid for _, fid in ranked[:N_SOURCES]]
    source_rows = [
        {
            "id": fid,
            "label": fname[fid],
            "graph": "funding",
            "aocDistance": dist,
        }
        for dist, fid in ranked[:N_SOURCES]
    ]
    assert len(sources) == N_SOURCES, sources

    # ── funding chains: sources → top-5 shortlist funders ────────────────────
    assert all(t in fids for t, _ in FUNDER_TARGETS)
    funding_groups = []
    n_funding_chains = 0
    for target, rank in FUNDER_TARGETS:
        paths = best_funding_paths(F, sources, target)
        chains = []
        for path in paths:
            for n in path[1:-1]:
                intermediaries[("funding", n)] += 1
            chains.append(funding_chain(F, path, fname))
        n_funding_chains += len(chains)
        group = {
            "target": {"id": target, "label": fname[target], "graph": "funding"},
            "rank": rank,
            "kind": fnode[target].get("funderKind", fnode[target]["kind"]),
            "chains": chains,
        }
        if not chains:
            group["flag"] = "no grant/investment path from any AoC-linked grantee"
        funding_groups.append(group)
    n_unreachable_funder = sum(1 for g in funding_groups if not g["chains"])

    # ── person routes: every person is a leaf (degree 1, verified below), so
    #    chains cannot pass THROUGH people — they can only END at one. Ship
    #    routes to each reachable funder that carries a named person. ─────────
    person_deg = Counter()
    for e in funding["edges"]:
        for end in (e["source"], e["target"]):
            if fnode[end]["kind"] == "person":
                person_deg[end] += 1
    assert person_deg and set(person_deg.values()) == {1}, "people are no longer leaves"

    person_of: dict[str, tuple[str, str]] = {}  # funder -> (person, full role)
    for e in funding["edges"]:  # file order = deterministic first-listed person
        if e["type"] == "affiliation" and e["target"] not in person_of:
            person_of[e["target"]] = (e["source"], e.get("role") or "affiliated")
    shortlisted = {t for t, _ in FUNDER_TARGETS}
    person_groups = []
    n_person_chains = 0
    for funder in sorted(person_of):
        if funder in shortlisted:
            continue
        paths = best_funding_paths(F, sources, funder)
        if not paths:
            continue
        person, role = person_of[funder]
        chains = []
        for path in paths:
            full = path + [person]
            for n in full[1:-1]:
                intermediaries[("funding", n)] += 1
            chains.append(funding_chain(F, full, fname))
        n_person_chains += len(chains)
        person_groups.append(
            {
                "target": {"id": person, "label": fname[person], "graph": "funding"},
                "role": role,
                "via": fname[funder],
                "chains": chains,
            }
        )
    assert person_groups, "no reachable funder carries a named person"

    # ── leaderboard: intermediary appearances across ALL shipped chains ─────
    n_chains = n_company_chains + n_funding_chains + n_person_chains
    kind_of = lambda g, n: (  # noqa: E731
        cvert[n].replace("-", " ")
        if g == "companies"
        else fnode[n].get("funderKind") or fnode[n]["kind"]
    )
    leaderboard = [
        {
            "id": n,
            "label": cname[n] if g == "companies" else fname[n],
            "graph": g,
            "kind": kind_of(g, n),
            "appearances": c,
        }
        for (g, n), c in sorted(
            intermediaries.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])
        )[:10]
    ]
    assert len(leaderboard) == 10 and leaderboard[0]["appearances"] >= 2

    top_hop, top_hop_n = first_hops.most_common(1)[0]
    assert top_hop in {e["source"] for e in aoc_edges} | {
        e["target"] for e in aoc_edges
    }

    payload = {
        "slug": "intro-chains",
        "graph": "both",
        "title": "Three hops to anyone",
        "sub": "the three cheapest intro routes to each prospect, major lab, and funder",
        "headline": (
            f"Anthropic, OpenAI, and Google DeepMind sit <strong>two hops</strong> from AoC — "
            f"but every one of the {n_company_chains} company routes opens through a rival, and "
            f"{cname[top_hop]} alone fronts {top_hop_n} of them."
        ),
        "prose": {
            "intro": (
                "<p>The map shows who is adjacent to whom; this panel turns that into asks. For eight company "
                "targets — the top prospects, the major labs, and one VC — plus the top five funders, we compute "
                "the three cheapest intro routes each, then count who keeps showing up in the middle. The "
                "recurring middlemen are the relationships worth investing in.</p>"
            ),
            "how": (
                "<p>The route-finder works like a maps app asked for alternates: the best path, then the "
                "next-best that differs somewhere, never revisiting a stop. Each hop has a price. A business tie "
                "costs 1, a shared investor 2, a rival 10 — so a route through one competitor wins only if it "
                "saves ten partner hops. Three routes per target means two backups when a relationship goes cold. "
                f"On the funding side, routes start from the {N_SOURCES} grantees nearest AoC "
                f"({', '.join(r['label'] for r in source_rows)}), and every hop counts the same. One structural "
                "fact: every person in the funding graph has exactly one edge, so no route passes <em>through</em> "
                "a person — a chain can only end at one. That is why the person routes end with a name and a "
                "role.</p>"
            ),
            "method": (
                "<p>Yen (1971) k-shortest loopless paths, k=3, via networkx <code>shortest_simple_paths</code> "
                "(Dijkstra subroutine on the weighted company graph; unweighted BFS hops on the funding graph). "
                "Edge weights business=1, shared-investor=2, competitor=10 are design choices, not measurements — "
                "reweighting reorders routes but cannot create reachability. For the 7 company pairs with two edge "
                "types we keep the cheaper. Targets were curated at bake time from the competitor-nominations and "
                f"funder-shortlist panels plus the four majors; all {len(COMPANY_TARGETS)} company targets sit "
                f"inside AoC's {len(aoc_component)}-node component ({n_unreachable_company} unreachable), while "
                f"{n_unreachable_funder} of {len(FUNDER_TARGETS)} shortlist funders "
                f"({', '.join(g['target']['label'] for g in funding_groups if not g['chains']) or 'none'}) have "
                f"no funding-graph path from any AoC-linked grantee. Funding caveats: "
                f"{sum(1 for e in funding['edges'] if e.get('year') is None)}/{len(funding['edges'])} edges "
                "lack a year, and affiliation edges carry roles but no dollars.</p>"
            ),
        },
        "caveat": (
            "Every company route starts through a rival, and it has to: 4 of AoC's 5 edges are competitor ties, "
            "and the fifth — an unverified business tie to AIUC — is a dead end, since AIUC's only edge points "
            "back to AoC. Remove the rival edges and AoC is cut off from the market entirely. These routes exist "
            "because rivals see us, not because partners do yet."
        ),
        "inputs": {"companies": stamp(companies), "funding": stamp(funding)},
        "data": {
            "companyChains": company_groups,
            "fundingChains": funding_groups,
            "personRoutes": person_groups,
            "sources": source_rows,
            "leaderboard": leaderboard,
            "counts": {
                "chains": n_chains,
                "companyChains": n_company_chains,
                "fundingChains": n_funding_chains,
                "personChains": n_person_chains,
                "unreachableCompanyTargets": n_unreachable_company,
                "unreachableFunderTargets": n_unreachable_funder,
            },
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
