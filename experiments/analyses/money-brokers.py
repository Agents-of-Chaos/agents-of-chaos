# /// script
# requires-python = ">=3.11"
# dependencies = ["networkx"]
# ///
"""money-brokers — which PEOPLE sit at the gates of the most money reachable by
agent-safety work: gated dollars (the verified annual budget behind their door)
x brokerage (their funder's betweenness in the money graph).
Run: cd experiments/analyses && uv run money-brokers.py
"""

import networkx as nx
from _shared import emit, load_funding, stamp

N_BRIDGE_ROWS = 4  # zero-dollar people added for their door's bridging alone


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:.0f}"


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    today = funding["meta"]["generatedAt"]  # snapshot date — never wall clock
    assert len(today) == 10 and today[4] == "-", f"bad generatedAt {today!r}"
    domain_label = {d["id"]: d["label"] for d in funding["meta"]["domains"]}

    funders = [n for n in funding["nodes"] if n["kind"] == "funder"]
    people = [n for n in funding["nodes"] if n["kind"] == "person"]
    assert len(funders) >= 10 and len(people) >= 10

    # funders mirror fieldDollarsUSD == annualFieldGivingUSD (null → 0); use the
    # annual field for its explicit per-year semantics, asserted consistent.
    for f in funders:
        assert (f.get("fieldDollarsUSD") or 0) == (
            f.get("annualFieldGivingUSD") or 0
        ), f["id"]

    # ── money graph: funder–grantee grant + investment edges, presence only ──
    # (unweighted: undisclosed amounts count as presence; SFF's regranted edges
    # stay as topology — we never SUM dollars through them, and gated dollars
    # are per-door, so no regrant pool is counted twice.)
    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    assert all(nodes[e["source"]]["kind"] == "funder" for e in money)
    assert all(nodes[e["target"]]["kind"] == "grantee" for e in money)
    M = nx.Graph()
    for e in money:
        M.add_edge(e["source"], e["target"])
    bc_money = nx.betweenness_centrality(M, normalized=True)  # exact, deterministic

    # ── the spec'd tripartite check: person betweenness is ZERO by construction
    aff = [
        e for e in funding["edges"] if e["type"] == "affiliation" and e.get("current")
    ]
    assert all(nodes[e["source"]]["kind"] == "person" for e in aff)
    assert all(nodes[e["target"]]["kind"] == "funder" for e in aff)
    per_person = {}
    for e in aff:
        assert (
            e["source"] not in per_person
        ), f"person {e['source']} has >1 affiliation — pendant argument breaks, revisit"
        per_person[e["source"]] = e
    assert len(per_person) == len(
        people
    ), "every person should carry exactly one current affiliation"
    T = nx.Graph()
    for n in funding["nodes"]:
        T.add_node(n["id"])
    for e in funding["edges"]:
        T.add_edge(e["source"], e["target"])
    bc_tri = nx.betweenness_centrality(T, normalized=True)
    assert all(
        bc_tri[p["id"]] == 0.0 for p in people
    ), "a person has nonzero betweenness — pendant claim false, revisit method"

    # brokerage percentile of a funder = share of the other funders strictly below
    fb = {f["id"]: bc_money.get(f["id"], 0.0) for f in funders}
    vals = sorted(fb.values())
    n_f = len(vals)

    def pct_below(x: float) -> float:
        return sum(1 for v in vals if v < x) / (n_f - 1)

    def unlock(f: dict) -> str:
        doms = [domain_label[t] for t in f.get("domainTags") or []]
        dom_s = (
            ", ".join(doms[:3]) + (f" +{len(doms) - 3}" if len(doms) > 3 else "")
            if doms
            else "no declared focus tracked"
        )
        mode = f["apply"]["mode"]
        deadline = f["apply"].get("deadline")
        if mode == "rolling":
            return f"rolling door — {dom_s}"
        if mode == "rounds" and deadline and deadline > today:
            return f"open call closes {deadline} — {dom_s}"
        if mode == "rounds":
            return f"periodic rounds — {dom_s}"
        if mode == "closed":
            return f"no open call right now — {dom_s}"
        return f"{mode} — {dom_s}"

    # ── score every person via the door they hold ────────────────────────────
    rows = []
    for e in aff:
        p, f = nodes[e["source"]], nodes[e["target"]]
        annual = f.get("annualFieldGivingUSD")
        bc = fb[f["id"]]
        deg = M.degree(f["id"]) if f["id"] in M else 0
        flags = []
        if annual is None:
            flags.append("no published annual figure — $0 shown")
        if deg == 0:
            flags.append("no tracked money edges in this graph — brokerage 0")
        elif bc == 0.0:
            flags.append(f"{deg} tracked edge{'s' if deg != 1 else ''}, no bridging")
        rows.append(
            {
                "id": p["id"],
                "label": p["name"],
                "role": e["role"],
                "funder": f["name"],
                "fid": f["id"],
                "gatedUSD": round(annual or 0),
                "brokeragePct": round(pct_below(bc), 3),
                "bc": bc,
                "unlock": unlock(f),
                "flag": "; ".join(flags) if flags else None,
            }
        )
    rows.sort(key=lambda r: (-r["gatedUSD"], -r["bc"], r["id"]))

    dollar_rows = [r for r in rows if r["gatedUSD"] > 0]
    assert (
        3 <= len(dollar_rows) <= 20
    ), f"{len(dollar_rows)} dollar-gated people — layout assumed ~12"
    bridge_rows = [r for r in rows if r["gatedUSD"] == 0 and r["bc"] > 0][
        :N_BRIDGE_ROWS
    ]
    table = dollar_rows + bridge_rows
    assert len(table) <= 25

    # ── the doors behind the table, deduped ──────────────────────────────────
    door_ids: list[str] = []
    for r in table:
        if r["fid"] not in door_ids:
            door_ids.append(r["fid"])
    doors = [
        {
            "id": fid,
            "label": nodes[fid]["name"],
            "kind": nodes[fid]["funderKind"],
            "gatedUSD": round(nodes[fid].get("annualFieldGivingUSD") or 0),
            "people": sum(1 for r in table if r["fid"] == fid),
        }
        for fid in door_ids
    ]

    # ── headline numbers (asserted, not assumed) ─────────────────────────────
    gated_total = sum(d["gatedUSD"] for d in doors)  # distinct doors — no double count
    n_dollar_doors = sum(1 for d in doors if d["gatedUSD"] > 0)
    held = {e["target"] for e in aff}
    dollars_and_bridge = sorted(
        f["id"]
        for f in funders
        if (f.get("annualFieldGivingUSD") or 0) > 0 and fb[f["id"]] > 0
    )
    held_both = [i for i in dollars_and_bridge if i in held]
    unheld_both = [i for i in dollars_and_bridge if i not in held]
    assert held_both == [
        "nsf"
    ], f"headline claims NSF holds the unique people-held $+bridge door, got {held_both}"
    assert unheld_both == [
        "coefficient-giving",
        "ltff",
        "schmidt-sciences",
        "survival-and-flourishing-fund",
    ], f"caveat names the unheld $+bridge doors, got {unheld_both}"
    smaller_unheld = " and ".join(
        nodes[i]["name"]
        for i in unheld_both
        if i not in ("coefficient-giving", "survival-and-flourishing-fund")
    )
    nsf_people = [r for r in table if r["fid"] == "nsf"]
    assert len(nsf_people) == 4 and all(
        "Program Officer" in r["role"] for r in nsf_people
    )
    nsf_pct = nsf_people[0]["brokeragePct"]

    n_null_door_people = sum(
        1 for r in rows if r["flag"] and "no published annual figure" in r["flag"]
    )
    n_covered = len(held)
    n_zero_bc = sum(1 for v in vals if v == 0.0)
    biggest_absent = max(
        (f for f in funders if f["id"] not in held),
        key=lambda f: fb[f["id"]],
    )
    assert biggest_absent["id"] == "coefficient-giving", biggest_absent["id"]

    for r in table:
        del r["fid"], r["bc"]  # internal keys — table ships person id + scores only

    payload = {
        "slug": "money-brokers",
        "graph": "funding",
        "title": "The doorkeepers",
        "sub": f"{len(dollar_rows)} named people hold doors to {fmt_usd(gated_total)}/yr of verified field money",
        "headline": (
            f"{len(dollar_rows)} named people hold the doors to <strong>{fmt_usd(gated_total)} a year</strong> of "
            f"verified field giving across {n_dollar_doors} funders — and NSF's four program officers hold the only "
            "door in this table that is also a bridge between separate money territories."
        ),
        "prose": {
            "intro": (
                "<p>Grant applications go to institutions, but doors are opened by people — the funding map carries "
                f"{len(people)} of them, each verified from a staff page to a current role at a funder. Which of them "
                "sit at the gates of the most money reachable by agent-safety work, and which hold doors that bridge "
                "funding territories that otherwise never touch on the map? Being on this who-to-get-to-know list is a "
                "compliment: the graph is saying your door matters.</p>"
            ),
            "how": (
                "<p>Each person gets two scores, and neither is a black box. <em>Gated dollars</em> is simply the "
                "verified annual field budget of the funder whose staff page lists them — the size of the budget "
                "behind their door. <em>Brokerage</em> asks how often shortest paths through the money graph (funders "
                "wired to the grantees they fund) route through that person's funder. That is betweenness centrality, "
                "and it behaves like attention bottlenecks in a transformer: a few tokens end up on the route most "
                "heads pass through, and masking one cuts distant parts of the context off from each other — here, a "
                "high-brokerage door joins funding territories that otherwise never meet. The striking thing is how "
                "little the two scores overlap in this table — big budgets mostly sit behind doors that bridge "
                "nothing we can see, and the strongest people-held bridges publish no budget at all. Only one door "
                "here scores on both.</p>"
            ),
            "method": (
                "<p>Gated dollars = the funder's annualFieldGivingUSD (basis year varies by funder; null → $0, "
                f"flagged — {n_null_door_people} of {len(people)} people sit behind doors with no published figure). "
                "Brokerage: betweenness centrality (Freeman 1977), exact unweighted undirected shortest paths on the "
                f"funder–grantee money graph ({M.number_of_edges()} grant + investment edges, presence only — "
                "undisclosed amounts count as presence; SFF's regranted edges kept as topology, dollars never summed "
                "through them). We first computed betweenness for the person nodes themselves on the full tripartite "
                f"person–funder–grantee graph, as one should: every one of the {len(people)} people carries exactly "
                "one current affiliation edge, so each is a pendant and their betweenness is identically zero — a "
                "degree-one node lies on no shortest path (verified in-script, asserted on every rebake). The "
                "brokerage a person exercises is therefore the brokerage of the door they hold: the table reports "
                f"their funder's betweenness as a percentile — the share of the other {n_f - 1} funders strictly "
                f"below ({n_zero_bc} of {n_f} funders sit at zero, so any bridging at all clears the 80s). Colleagues "
                "at the same funder tie on both scores by construction; their roles differentiate them. Affiliations "
                f"are current-only; deadline checks use the snapshot date {today}, never wall clock. No randomness "
                "anywhere.</p>"
            ),
        },
        "caveat": (
            f"The people layer covers {n_covered} of {n_f} funders and misses the two biggest hubs: "
            f"{biggest_absent['name']} ({fmt_usd(biggest_absent['annualFieldGivingUSD'])}/yr and the graph's "
            "strongest bridge) and the Survival and Flourishing Fund have no staff mapped yet, so nobody holds those "
            f"doors in this table — and two smaller dollars-plus-bridge doors, {smaller_unheld}, are likewise "
            f"unstaffed in the map. Gated dollars can only see the funders that publish an annual figure — "
            f"{n_null_door_people} of {len(people)} people show $0 for that reason, not because their door is small "
            "(Juniper Ventures and the Cooperative AI Foundation, the two strongest people-held bridges, are both in "
            "that bucket). And betweenness measures tracked edges, not influence."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {"gatekeepers": table, "doors": doors, "counts": {"funders": n_f}},
    }
    emit(payload)

    print(
        f"    today={today}  doors={len(doors)}  gated_total={fmt_usd(gated_total)}  nsf_pct={nsf_pct}"
    )
    for i, r in enumerate(table, 1):
        print(
            f"    {i:2d}. {r['label'][:24]:24s} {fmt_usd(r['gatedUSD']):>8s} "
            f"brk={r['brokeragePct']:.3f} {r['funder'][:26]:26s} "
            f"{('FLAG: ' + r['flag']) if r['flag'] else ''}"
        )


if __name__ == "__main__":
    main()
