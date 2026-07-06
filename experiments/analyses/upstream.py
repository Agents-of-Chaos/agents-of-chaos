# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""upstream — trace every tracked grant dollar to its ultimate source (regrant
tags + documented seedings), classify all funders source/distributor/program,
and run weighted HITS for crowd-validation. Run: cd experiments/analyses &&
uv run upstream.py
"""

import math
from collections import defaultdict

import numpy as np
from _shared import emit, load_funding, stamp

TOP_FUNDERS = 20
TOP_AUTHORITIES = 10
HITS_ITERS = 100

# Funder-to-funder seeding documented in the data (node blurbs, both sides):
# CAIF was seeded with $15M by Macroscopic Ventures — its grants are
# Macroscopic's wealth one hop downstream. Not a graph edge; disclosed.
SEEDINGS = {"cooperative-ai-foundation": "macroscopic-ventures"}
SEED_LABEL = {
    "cooperative-ai-foundation": "$15M seed — documented in prose, not as an edge"
}

# Philanthropies hand-classified from blurbs + regrant structure. Judgment
# calls carry a flag that ships in the table. government/corporate → program,
# VC → distributor (LP capital) — rule-based below.
PHIL_CLASS: dict[str, str] = {
    # sources — the wealth and the agenda live in the same house
    "coefficient-giving": "source",
    "jaan-tallinn": "source",
    "vitalik-buterin": "source",
    "schmidt-sciences": "source",
    "craig-newmark-philanthropies": "source",
    "laude-institute": "source",
    "sloan-foundation": "source",
    "macroscopic-ventures": "source",
    # program — institutional nonprofit budget, closer to corporate than donor
    "mozilla": "program",
    # distributors — pool or regrant money that originates elsewhere
    "survival-and-flourishing-fund": "distributor",
    "ltff": "distributor",
    "aistof": "distributor",
    "manifund": "distributor",
    "ai-risk-mitigation-fund": "distributor",
    "founders-pledge-gcr": "distributor",
    "longview-philanthropy": "distributor",
    "cooperative-ai-foundation": "distributor",
    "catalyze-impact": "distributor",
    "safe-ai-fund": "distributor",
    "foresight-institute": "distributor",
    "nlnet": "distributor",
    "future-of-life-institute": "distributor",
    "halcyon-futures": "distributor",
}

JUDGMENT_FLAGS: dict[str, str] = {
    "coefficient-giving": "Moskovitz/Tuna wealth with in-house program staff — source and distributor under one roof",
    "jaan-tallinn": "no direct edges by design — his dollars appear as SFF regrant tags",
    "vitalik-buterin": "individual donor; his tracked giving flows through FLI",
    "macroscopic-ventures": "originates column includes CAIF's grants via the documented $15M seed",
    "cooperative-ai-foundation": "grants from a Macroscopic-seeded endowment — origin credited upstream",
    "ltff": "pooled EA Funds donor money — upstream untraceable",
    "future-of-life-institute": "endowed largely by Vitalik Buterin's 2021 gift",
    "nlnet": "largely regrants EU NGI programme money",
    "longview-philanthropy": "advises and directs major donors' money",
    "mozilla": "nonprofit institutional budget — classed program",
    "frontier-model-forum-aisf": "pools the frontier labs' money — classed distributor, not program",
}

MOVE = {"source": "cultivate", "distributor": "pitch", "program": "watch the calls"}


def classify(f: dict) -> str:
    kind = f["funderKind"]
    if kind == "vc":
        return "distributor"  # LP capital deployed as equity
    if kind == "government":
        return "program"
    if kind == "corporate":
        return "distributor" if f["id"] == "frontier-model-forum-aisf" else "program"
    assert kind == "philanthropy", f"unknown funderKind {kind!r}"
    assert (
        f["id"] in PHIL_CLASS
    ), f"unclassified philanthropy {f['id']!r} — extend PHIL_CLASS"
    return PHIL_CLASS[f["id"]]


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        s = f"{x / 1e9:.1f}".removesuffix(".0") + "B"
    elif x >= 1e6:
        s = f"{x / 1e6:.1f}".removesuffix(".0") + "M"
    elif x >= 1e3:
        s = f"{x / 1e3:.0f}k"
    else:
        s = f"{x:.0f}"
    return "$" + s


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    funders = [n for n in funding["nodes"] if n["kind"] == "funder"]
    n_funders = len(funders)
    assert n_funders >= 30, f"suspiciously few funders: {n_funders}"
    phil_ids = {f["id"] for f in funders if f["funderKind"] == "philanthropy"}
    assert phil_ids == set(PHIL_CLASS), (
        f"PHIL_CLASS out of sync with the graph: "
        f"missing={phil_ids - set(PHIL_CLASS)}, stale={set(PHIL_CLASS) - phil_ids}"
    )

    grants = [e for e in funding["edges"] if e["type"] == "grant"]
    investments = [e for e in funding["edges"] if e["type"] == "investment"]
    assert all(nodes[e["source"]]["kind"] == "funder" for e in grants)
    assert all(nodes[e["target"]]["kind"] == "grantee" for e in grants)
    assert len(grants) >= 50, f"suspiciously few grants: {len(grants)}"
    for src in SEEDINGS.values():
        assert nodes[src]["kind"] == "funder"

    cls = {f["id"]: classify(f) for f in funders}
    n_src = sum(1 for c in cls.values() if c == "source")
    n_dist = sum(1 for c in cls.values() if c == "distributor")
    n_prog = sum(1 for c in cls.values() if c == "program")
    assert n_src + n_dist + n_prog == n_funders

    # ── (a) ultimate-source ledger over dollar-stamped grants ───────────────
    stamped = [e for e in grants if e.get("amountUSD") is not None]
    n_null = len(grants) - len(stamped)
    total = sum(e["amountUSD"] for e in stamped)
    assert 1e8 < total < 5e9, f"implausible tracked total {total}"

    named: dict[str, float] = defaultdict(float)  # origin funder id → $
    pools: dict[str, float] = defaultdict(float)  # distributor id → untraceable $
    for e in stamped:
        up = e.get("regrantOf")
        src = e["source"]
        if up is not None:
            assert nodes[up]["kind"] == "funder", f"regrantOf {up!r} not a funder"
            named[up] += e["amountUSD"]
        elif src in SEEDINGS:
            named[SEEDINGS[src]] += e["amountUSD"]
        elif cls[src] == "distributor":
            pools[src] += e["amountUSD"]  # pooled payers, not traceable further
        else:
            named[src] += e[
                "amountUSD"
            ]  # sources + programs originate their own budget
    assert abs(sum(named.values()) + sum(pools.values()) - total) < 1

    ranked_named = sorted(named.items(), key=lambda kv: (-kv[1], kv[0]))
    cg_share = named["coefficient-giving"] / total
    jt_share = named["jaan-tallinn"] / total
    top2_share = cg_share + jt_share
    assert 0.5 < top2_share < 0.99, f"concentration claim broke: {top2_share}"
    named_share = sum(named.values()) / total

    ledger_rows = [
        {"id": fid, "label": nodes[fid]["name"], "value": round(v)}
        for fid, v in ranked_named
    ] + [
        {
            "id": fid,
            "label": f"{nodes[fid]['name']} pool — payers untagged",
            "value": round(v),
        }
        for fid, v in sorted(pools.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    ledger_rows.sort(key=lambda r: -r["value"])
    assert abs(sum(r["value"] for r in ledger_rows) - total) < 2

    # ── (b) weighted HITS on the funder→grantee grant graph ─────────────────
    floor = min(
        e["amountUSD"] for e in stamped
    )  # undisclosed = smallest verified grant
    assert floor > 0
    pair: dict[tuple[str, str], float] = defaultdict(float)
    for e in grants:
        pair[(e["source"], e["target"])] += e.get("amountUSD") or floor
    fids = sorted({s for s, _ in pair})
    gids = sorted({g for _, g in pair})
    fi = {f: i for i, f in enumerate(fids)}
    gi = {g: i for i, g in enumerate(gids)}
    W = np.zeros((len(fids), len(gids)))
    for (s, g), amt in pair.items():
        W[fi[s], gi[g]] = math.log10(amt + 1)
    assert (W >= 0).all() and W.sum() > 0

    hub = np.ones(len(fids))
    auth = np.ones(len(gids))
    for _ in range(HITS_ITERS):
        auth_prev = auth
        auth = W.T @ hub
        auth /= np.linalg.norm(auth)
        hub = W @ auth
        hub /= np.linalg.norm(hub)
    assert float(np.linalg.norm(auth - auth_prev)) < 1e-10, "HITS did not converge"
    # nonneg W + ones init keeps both vectors nonnegative — this IS the sign fix
    assert (hub >= 0).all() and (auth >= 0).all()
    hub_of = {f: float(h) for f, h in zip(fids, hub)}

    funders_in: dict[str, set] = defaultdict(set)
    dollars_in: dict[str, float] = defaultdict(float)
    for e in grants:
        funders_in[e["target"]].add(e["source"])
        dollars_in[e["target"]] += e.get("amountUSD") or 0
    auth_order = sorted(range(len(gids)), key=lambda i: (-auth[i], gids[i]))
    authorities = [
        {
            "id": gids[i],
            "label": nodes[gids[i]]["name"],
            "auth": round(float(auth[i]), 3),
            "funders": len(funders_in[gids[i]]),
            "inUsd": round(dollars_in[gids[i]]) or None,
        }
        for i in auth_order[:TOP_AUTHORITIES]
    ]

    # ── (c) the funder table: class, move, paid vs originated, hub ──────────
    paid_of: dict[str, float] = defaultdict(float)
    n_edges_of: dict[str, int] = defaultdict(int)
    n_null_of: dict[str, int] = defaultdict(int)
    for e in grants:
        n_edges_of[e["source"]] += 1
        if e.get("amountUSD") is None:
            n_null_of[e["source"]] += 1
        else:
            paid_of[e["source"]] += e["amountUSD"]
    assert sum(n_null_of.values()) == n_null

    sff_paid = paid_of["survival-and-flourishing-fund"]
    jt_named = named["jaan-tallinn"]
    JUDGMENT_FLAGS["survival-and-flourishing-fund"] = (
        f"payer of record for pooled donors — {fmt_usd(jt_named)} of its "
        f"{fmt_usd(sff_paid)} is tagged as Jaan Tallinn's money"
    )

    rows = []
    for f in funders:
        fid = f["id"]
        n_e, n_nul = n_edges_of[fid], n_null_of[fid]
        paid = paid_of[fid] if (n_e and n_e > n_nul) else None
        originated = named.get(fid) or None
        annual = f.get("annualFieldGivingUSD") or 0
        flags = []
        if fid in JUDGMENT_FLAGS:
            flags.append(JUDGMENT_FLAGS[fid])
        elif f["funderKind"] == "vc":
            flags.append("LP capital, equity not grants — pitch with a cap table")
        if n_e == 0 and not originated:
            flags.append(
                f"no grants tracked here; ~{fmt_usd(annual)}/yr declared field giving"
                if annual
                else "no grants tracked in this graph"
            )
        elif n_nul == n_e and n_e > 0:
            s = "s" if n_e > 1 else ""
            flags.append(f"{n_e} grant{s} tracked, amount{s} undisclosed")
        elif n_nul:
            flags.append(f"{n_nul} of {n_e} tracked amounts undisclosed")
        rows.append(
            {
                "id": fid,
                "label": f["name"],
                "cls": cls[fid] + (" (VC)" if f["funderKind"] == "vc" else ""),
                "move": MOVE[cls[fid]]
                + (" (equity)" if f["funderKind"] == "vc" else ""),
                "paid": round(paid) if paid else None,
                "originated": round(originated) if originated else None,
                "hub": round(hub_of[fid], 3) if fid in hub_of else None,
                "flag": "; ".join(flags) if flags else None,
                "_size": max(paid or 0, originated or 0, annual),
            }
        )
    rows.sort(key=lambda r: (-r["_size"], r["id"]))
    table = [{k: v for k, v in r.items() if k != "_size"} for r in rows[:TOP_FUNDERS]]

    # ── chains: three ways a dollar reaches a grantee ────────────────────────
    def biggest(pred) -> dict:
        cands = [e for e in stamped if pred(e)]
        assert cands, "chain exemplar missing from the data"
        return max(cands, key=lambda e: (e["amountUSD"], e["target"]))

    sff_top = biggest(lambda e: e.get("regrantOf") == "jaan-tallinn")
    n_tagged = sum(1 for e in grants if e.get("regrantOf") == "jaan-tallinn")
    n_tagged_stamped = sum(1 for e in stamped if e.get("regrantOf") == "jaan-tallinn")
    assert 0 < n_tagged_stamped <= n_tagged
    assert jt_named == sum(
        e["amountUSD"] for e in stamped if e.get("regrantOf") == "jaan-tallinn"
    ), "jt_named must equal the sum over dollar-stamped tagged regrants"
    caif_focal = biggest(
        lambda e: e["source"] == "cooperative-ai-foundation"
        and e["target"] == "cmu-focal"
    )
    cg_top = biggest(lambda e: e["source"] == "coefficient-giving")

    def hop(e: dict) -> dict:
        return {
            "label": f"{fmt_usd(e['amountUSD'])} grant, {e['year']}",
            "verified": bool(e.get("verified")),
        }

    def ref(fid: str) -> dict:
        return {"id": fid, "label": nodes[fid]["name"]}

    chains = [
        {
            "nodes": [
                ref("jaan-tallinn"),
                ref("survival-and-flourishing-fund"),
                ref(sff_top["target"]),
            ],
            "edges": [
                {
                    "label": (
                        f"{fmt_usd(jt_named)} across {n_tagged} tagged regrants, "
                        f"{n_tagged_stamped} with amounts"
                    ),
                    "verified": True,
                },
                hop(sff_top),
            ],
        },
        {
            "nodes": [
                ref("macroscopic-ventures"),
                ref("cooperative-ai-foundation"),
                ref("cmu-focal"),
            ],
            "edges": [
                {"label": SEED_LABEL["cooperative-ai-foundation"], "verified": False},
                hop(caif_focal),
            ],
        },
        {
            "nodes": [ref("coefficient-giving"), ref(cg_top["target"])],
            "edges": [
                {
                    "label": f"{fmt_usd(cg_top['amountUSD'])} direct, {cg_top['year']} — no chain",
                    "verified": True,
                }
            ],
        },
    ]
    for c in chains:
        assert len(c["edges"]) == len(c["nodes"]) - 1

    # ── envelope ─────────────────────────────────────────────────────────────
    n_tracked_payers = len({e["source"] for e in stamped})
    inv_total = sum(
        e["amountUSD"] for e in investments if e.get("amountUSD") is not None
    )
    payload = {
        "slug": "upstream",
        "graph": "funding",
        "title": "Upstream sources",
        "sub": f"who originates the money vs who hands it out — {n_funders} funders classified",
        "headline": (
            f"Collapse the regrant chains and <strong>{round(100 * top2_share)}% of the "
            f"{fmt_usd(total)}</strong> in tracked grants originates with just two sources — "
            f"Coefficient Giving ({round(100 * cg_share)}%) and Jaan Tallinn "
            f"({round(100 * jt_share)}%); most other doors hand out money that started somewhere else."
        ),
        "prose": {
            "intro": (
                "<p>A pitch meeting goes differently depending on whether the desk across from you "
                "is where the money originates, a professional pass-through, or a line in an "
                "institution's budget. Distributors have open applications and fast cycles — you "
                "pitch them; sources set the agendas the distributors execute — you cultivate them; "
                f"programs answer to calls and budget years. This panel classifies all {n_funders} "
                "funders on the map and traces every tracked grant dollar as far upstream as the "
                "data allows.</p>"
            ),
            "how": (
                "<p>Think of gradient flow in a deep network: the loss is computed in one place, and "
                "every layer in between just passes the signal along, reshaped. Funding has the same "
                "structure — SFF is the desk that hands you the check, but most of its tracked grants "
                "are tagged as Jaan Tallinn's money, so the signal you need to please originates one "
                "layer up. We follow each grant's regrant tags (and the one funder-seeding the data "
                "documents, Macroscopic's $15M into CAIF) upstream until the trail ends, then re-total "
                "the ledger by ultimate source. Separately, a weighted HITS pass — the algorithm behind "
                "early web search — scores funders by whether their money lands where other credible "
                "money also lands, and grantees by how much credible money converges on them. The "
                "classification reads off the move: pitch distributors, cultivate sources, watch the "
                "programs' calls.</p>"
            ),
            "method": (
                f"<p>Attribution: each dollar-stamped grant ({len(stamped)} of {len(grants)}; "
                f"{fmt_usd(total)}) is credited to its <code>regrantOf</code> funder when tagged "
                f"({n_tagged_stamped} dollar-stamped SFF edges → Jaan Tallinn; "
                f"{n_tagged} tagged in all), else across the blurb-documented "
                "Macroscopic→CAIF seeding, else to the payer of record; dollars paid by distributors "
                "with no tag stay in explicit “pool — payers untagged” buckets rather than being "
                "credited as origins, and program budgets (government, corporate) count as their own "
                "origin. Weighted HITS (Kleinberg 1999), hand-rolled power iteration on the "
                f"{len(fids)}×{len(gids)} funder→grantee matrix with W = log10(pair dollars + 1), "
                f"undisclosed amounts floored at the smallest verified grant ({fmt_usd(floor)}); "
                f"all-ones init, {HITS_ITERS} iterations, L2-normalized each step — deterministic, "
                "converging to the leading singular vectors of W. Classification: government/corporate "
                "→ program; VC → distributor of LP capital; FMF's AI Safety Fund → distributor (it "
                "pools the frontier labs' money); the "
                f"{len(PHIL_CLASS)} philanthropies are hand-classified from blurbs and regrant "
                "structure, with every judgment call flagged in the table. Investments "
                f"({len(investments)} edges, {fmt_usd(inv_total)} of led-round totals) are excluded "
                "throughout — round totals are not the investor's own dollars.</p>"
            ),
        },
        "caveat": (
            f"Tracked is not the field: only {n_tracked_payers} of {n_funders} funders have "
            "dollar-stamped grants in this graph, and the biggest, Coefficient Giving, also runs the "
            f"most public grants database — so the {round(100 * top2_share)}% measures concentration "
            f"of what we can verify, with a visibility bias toward funders who publish. {n_null} of "
            f"{len(grants)} grants carry no amount (floored in HITS, absent from the ledger); SFF's "
            f"untagged {fmt_usd(pools.get('survival-and-flourishing-fund', 0))} is pooled money we "
            "cannot split across its payers; the Macroscopic→CAIF seed is documented in node blurbs, "
            "not as a graph edge."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "ledger": {"rows": ledger_rows},
            "chains": chains,
            "funders": table,
            "authorities": authorities,
        },
    }
    emit(payload)

    # eyeball log
    print(f"    classes: {n_src} sources / {n_dist} distributors / {n_prog} programs")
    print(
        f"    named origins cover {100 * named_share:.1f}% of {fmt_usd(total)}; floor={fmt_usd(floor)}"
    )
    for r in ledger_rows:
        print(
            f"    {r['label'][:46]:46s} {r['value']:>13,d}  {100 * r['value'] / total:5.2f}%"
        )
    print(
        "    top hubs:",
        ", ".join(
            f"{f}={hub_of[f]:.3f}"
            for f in sorted(hub_of, key=hub_of.get, reverse=True)[:4]
        ),
    )
    print("    top authorities:", ", ".join(a["label"] for a in authorities[:5]))


if __name__ == "__main__":
    main()
