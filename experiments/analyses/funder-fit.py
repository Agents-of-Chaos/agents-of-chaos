# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""funder-fit — bipartite spectral embedding of the funder-by-grantee money matrix;
an out-of-sample "virtual AoC" (mean of seed-grantee positions) scores every
embeddable funder, and the ranking is compared against a cheap tag-share rubric.
Run: cd experiments/analyses && uv run funder-fit.py
"""

import statistics
from collections import defaultdict

import numpy as np
from _shared import emit, fix_signs, load_funding, stamp

LANE_TAGS = {"agent-security", "evals", "multi-agent"}  # AoC's lane == seed rule
TOP_N = 15
D_LO, D_HI = 2, 8


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:g}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M".replace(".0M", "M")
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:g}"


def fit(funding: dict) -> dict:
    """Everything through the virtual-AoC structural scores, factored out of
    main() so prep_questions.py can reuse the exact math via load_sibling
    (byte-equal by construction). Returns the intermediates main() reports on;
    the float-op sequence is untouched by the refactor."""
    nodes = {n["id"]: n for n in funding["nodes"]}
    all_funders = [n for n in funding["nodes"] if n["kind"] == "funder"]

    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    assert len(money) >= 50, f"suspiciously few money edges: {len(money)}"
    assert all(nodes[e["source"]]["kind"] == "funder" for e in money)
    assert all(nodes[e["target"]]["kind"] == "grantee" for e in money)

    # ── regrant double-count guard: a regrant already sits on the distributor;
    # the payer must not also carry a direct edge to the same grantee ─────────
    direct = {(e["source"], e["target"]) for e in money}
    for e in money:
        payer = e.get("regrantOf")
        if payer:
            assert (payer, e["target"]) not in direct, (
                f"double-counted regrant: {payer} pays {e['source']}→{e['target']} "
                "AND holds a direct edge to the same grantee"
            )

    # ── null amounts (common): impute funder median, else global median ──────
    disclosed = [e["amountUSD"] for e in money if e.get("amountUSD") is not None]
    assert disclosed, "no disclosed amounts at all?"
    global_med = statistics.median(disclosed)
    by_funder: dict[str, list[dict]] = defaultdict(list)
    for e in money:
        by_funder[e["source"]].append(e)
    med_by_funder = {}
    for f, es in by_funder.items():
        a = [e["amountUSD"] for e in es if e.get("amountUSD") is not None]
        med_by_funder[f] = statistics.median(a) if a else global_med
    n_null = sum(1 for e in money if e.get("amountUSD") is None)

    # ── the bipartite matrix: funders with >=1 money edge x funded grantees ──
    funders = sorted({e["source"] for e in money})
    grantees = sorted({e["target"] for e in money})
    n_emb, n_gr = len(funders), len(grantees)
    assert n_emb >= 10, f"too few embeddable funders: {n_emb}"
    fi = {f: i for i, f in enumerate(funders)}
    gi = {g: i for i, g in enumerate(grantees)}
    M = np.zeros((n_emb, n_gr))
    for e in money:
        M[fi[e["source"]], gi[e["target"]]] += (
            e.get("amountUSD") or med_by_funder[e["source"]]
        )
    W = np.where(M > 0, np.log10(M + 1), 0.0)
    assert (W.sum(axis=1) > 0).all() and (W.sum(axis=0) > 0).all()

    # ── SVD; d = largest scree gap restricted to [2, 8] ──────────────────────
    U, S, Vt = np.linalg.svd(W, full_matrices=False)
    assert S[0] > 0 and np.all(np.diff(S) <= 1e-9)
    gaps = S[:-1] - S[1:]
    band = range(D_LO, min(D_HI, len(S) - 1) + 1)
    d = min(band, key=lambda k: (-gaps[k - 1], k))
    assert D_LO <= d <= D_HI, f"d={d} outside [{D_LO},{D_HI}]"

    def embed(k: int) -> tuple[np.ndarray, np.ndarray]:
        scale = np.sqrt(S[:k])
        return fix_signs(U[:, :k]) * scale, fix_signs(Vt.T[:, :k]) * scale

    X_f, X_g = embed(d)  # funder / grantee latent positions

    # ── seeds: grantees in AoC's lane; virtual AoC = their mean position ─────
    seeds = [g for g in grantees if set(nodes[g].get("domainTags", [])) & LANE_TAGS]
    assert len(seeds) >= 5, f"too few seed grantees: {len(seeds)}"
    seed_set = set(seeds)
    aoc_pos = X_g[[gi[s] for s in seeds]].mean(axis=0)
    struct = X_f @ aoc_pos  # RDPG read: expected log-dollar mass on an AoC-shaped org
    return dict(
        nodes=nodes,
        all_funders=all_funders,
        money=money,
        global_med=global_med,
        by_funder=by_funder,
        med_by_funder=med_by_funder,
        n_null=n_null,
        funders=funders,
        grantees=grantees,
        fi=fi,
        gi=gi,
        W=W,
        S=S,
        embed=embed,
        d=d,
        X_f=X_f,
        X_g=X_g,
        seeds=seeds,
        seed_set=seed_set,
        struct=struct,
    )


def main() -> None:
    funding = load_funding()
    ffit = fit(funding)
    nodes, all_funders, money = ffit["nodes"], ffit["all_funders"], ffit["money"]
    global_med, by_funder = ffit["global_med"], ffit["by_funder"]
    n_null, funders, grantees = ffit["n_null"], ffit["funders"], ffit["grantees"]
    fi, gi, W, S = ffit["fi"], ffit["gi"], ffit["W"], ffit["S"]
    embed, d, X_f, X_g = ffit["embed"], ffit["d"], ffit["X_f"], ffit["X_g"]
    seeds, seed_set, struct = ffit["seeds"], ffit["seed_set"], ffit["struct"]
    n_emb, n_gr = len(funders), len(grantees)

    # ── validation: do each seed's ACTUAL funders rank high? ─────────────────
    funded_by: dict[str, set[str]] = defaultdict(set)
    for e in money:
        if e["target"] in seed_set:
            funded_by[e["target"]].add(e["source"])
    ranks_recon: list[int] = []
    ranks_loo: list[int] = []
    for s in seeds:
        assert funded_by[s], f"seed {s} has no funders?"
        for scores, sink in (
            (X_f @ X_g[gi[s]], ranks_recon),  # the model's ranking for this seed alone
            (  # leave-one-out: virtual position built WITHOUT this seed
                X_f @ X_g[[gi[o] for o in seeds if o != s]].mean(axis=0),
                ranks_loo,
            ),
        ):
            order = sorted(funders, key=lambda f: (-round(float(scores[fi[f]]), 6), f))
            rank_of = {f: r + 1 for r, f in enumerate(order)}
            sink.extend(rank_of[f] for f in funded_by[s])
    recon_med = float(np.median(ranks_recon))
    loo_med = float(np.median(ranks_loo))
    recon_hit5 = float(np.mean(np.array(ranks_recon) <= 5))
    loo_hit5 = float(np.mean(np.array(ranks_loo) <= 5))
    chance = (n_emb + 1) / 2
    assert recon_med < chance, f"reconstruction no better than chance ({recon_med})"

    # ── the cheap rubric: share of each funder's log-dollars in lane columns ─
    lane_w = W[:, [gi[s] for s in seeds]].sum(axis=1)
    rubric = lane_w / W.sum(axis=1)
    assert np.all((rubric >= 0) & (rubric <= 1))
    s_sorted = sorted(funders, key=lambda f: (-round(float(struct[fi[f]]), 6), f))
    r_sorted = sorted(funders, key=lambda f: (-round(float(rubric[fi[f]]), 6), -lane_w[fi[f]], f))
    s_rank = {f: r + 1 for r, f in enumerate(s_sorted)}
    r_rank = {f: r + 1 for r, f in enumerate(r_sorted)}
    from scipy.stats import spearmanr

    rho_sr = float(spearmanr(struct, rubric).statistic)
    overlap10 = len(set(s_sorted[:10]) & set(r_sorted[:10]))
    rubric_thin = sum(1 for f in r_sorted[:10] if len(by_funder[f]) <= 2)

    # ── sensitivity: does d move the story? ──────────────────────────────────
    X3, G3 = embed(min(d + 1, len(S)))
    struct3 = X3 @ G3[[gi[s] for s in seeds]].mean(axis=0)
    rho_d = float(spearmanr(struct, struct3).statistic)
    n_vc_top5_d4 = 0
    if len(S) >= 4:
        X4, G4 = embed(4)
        s4 = X4 @ G4[[gi[s] for s in seeds]].mean(axis=0)
        top5_d4 = sorted(funders, key=lambda f: (-s4[fi[f]], f))[:5]
        n_vc_top5_d4 = sum(1 for f in top5_d4 if nodes[f]["funderKind"] == "vc")

    # ── table rows: top 15 by structure, lane evidence + rubric comparison ───
    rows = []
    for f in s_sorted[:TOP_N]:
        es = by_funder[f]
        lane = [e for e in es if e["target"] in seed_set]
        lane_usd = sum(e["amountUSD"] for e in lane if e.get("amountUSD"))
        lane_und = sum(1 for e in lane if not e.get("amountUSD"))
        names = [
            nodes[e["target"]]["name"]
            for e in sorted(
                lane, key=lambda e: (-(e.get("amountUSD") or 0), e["target"])
            )[:2]
        ]
        if not lane:
            n = len(es)
            evidence = (
                "none in lane (its one tracked edge is elsewhere)"
                if n == 1
                else f"none in lane (all {n} edges elsewhere)"
            )
        else:
            usd = fmt_usd(lane_usd) if lane_usd else "$ undisclosed"
            evidence = f"{len(lane)}/{len(es)} edges · {usd} · {', '.join(names)}"
        flags = []
        if len(es) <= 2:
            flags.append(
                f"only {len(es)} tracked edge{'s' if len(es) > 1 else ''} — thin structure"
            )
        if lane_und:
            flags.append(
                f"{lane_und} lane amount{'s' if lane_und > 1 else ''} undisclosed"
            )
        rows.append(
            {
                "id": f,
                "label": nodes[f]["name"],
                "kind": nodes[f]["funderKind"],
                "score": round(float(struct[fi[f]]), 3),
                "rubricRank": r_rank[f],
                "rubricShare": round(float(rubric[fi[f]]), 3),
                "evidence": evidence,
                "flag": "; ".join(flags) if flags else None,
            }
        )
    assert rows[0]["score"] > 0

    # ── rank-vs-rank scatter: every embeddable funder ─────────────────────────
    rank_rank = [
        {
            "id": f,
            "label": nodes[f]["name"],
            "x": s_rank[f],
            "y": r_rank[f],
            "group": nodes[f]["funderKind"],
        }
        for f in s_sorted
    ]
    seeds_block = [{"id": s, "label": nodes[s]["name"]} for s in seeds]

    top1 = rows[0]
    top1_lane = next(r["evidence"].split(" edges")[0] for r in rows[:1])
    n_funders = len(all_funders)
    biggest_up = max(rows, key=lambda r: r["rubricRank"] - s_rank[r["id"]])
    payload = {
        "slug": "funder-fit",
        "graph": "funding",
        "title": "Structure's shortlist",
        "sub": f"a recommender over {len(money)} money edges nominates funders for an AoC-shaped org",
        "headline": (
            f"The wiring and the rubric agree on just <strong>{overlap10} of 10</strong> top funders: "
            f"read as a recommender, the giving graph makes {top1['label']} the #1 structural fit for an "
            f"AoC-shaped org, while the rubric's favorites — mostly VCs with one or two tracked deals — "
            "sit in another room of the graph."
        ),
        "prose": {
            "intro": (
                "<p>The shortlist panel scores funders on published attributes — focus areas, check "
                "sizes, open doors. This panel throws the attributes away and asks the wiring itself: "
                "which funders already put money on orgs shaped like Agents of Chaos? And where the two "
                "answers disagree, which one should we believe?</p>"
            ),
            "how": (
                "<p>This is the streaming-service trick applied to grantmaking: a recommender never reads "
                "a movie's synopsis, it factorizes the who-watched-what matrix and suggests films from "
                "viewers with similar taste. We factorize the who-funds-whom matrix (weighted by log "
                f"dollars) so every funder and grantee gets coordinates in a {d}-dimensional taste space — "
                "sitting close means funding the same kinds of orgs. Agents of Chaos is not in the funding "
                f"graph yet, so we place a virtual AoC at the average position of the {len(seeds)} grantees "
                "already working its lane (agent-security, evals, multi-agent), and score every funder by "
                "the dot product with that virtual position — the model's guess at how much money each "
                "funder would put on an org shaped like ours. The guess checks out: rank funders for each "
                f"seed grantee and its actual funders land at median rank {recon_med:g} of {n_emb} (chance "
                f"would be {chance:g}); hide the seed from the virtual position first and the median is "
                f"still {loo_med:g}.</p>"
            ),
            "method": (
                "<p>Truncated SVD of the funder-by-grantee matrix (log10(USD+1); grants + investments; "
                f"{n_emb} funders with ≥1 tracked money edge × {n_gr} funded grantees), positions U√S and "
                "V√S — the adjacency spectral embedding of a bipartite random dot product graph (Sussman "
                f"et al., 2012), signs fixed. d={d} by the largest scree gap within 2–8 (the global "
                f"elbow sits after the first singular value, one dimension short of usable); at d={d + 1} "
                f"the ranking broadly holds (Spearman ρ={rho_d:.2f}), while by d=4 the VC block gains spectral mass and "
                f"{n_vc_top5_d4} VCs enter the structural top 5 — the low-d story treats them as a "
                f"separate room. {n_null} of {len(money)} money edges lack amounts — imputed at the "
                f"funder's median disclosed grant, else the global median ({fmt_usd(global_med)}); led VC "
                "rounds carry round totals rather than the fund's own check, which log-weighting "
                "compresses. SFF regrants are attributed to the distributor once (asserted: the payer "
                "holds no duplicate direct edge). Rubric = the share of each funder's log-dollars landing "
                "on lane-tagged grantees, ties broken by lane log-dollars; Spearman between structure and "
                f"rubric is ρ={rho_sr:.2f}. Validation is reconstruction plus leave-one-out placement: "
                f"per-seed hit-rate of actual funders in the top 5 is {recon_hit5:.0%} (LOO {loo_hit5:.0%})."
                "</p>"
            ),
        },
        "caveat": (
            f"Structure can only speak about the {n_emb} of {n_funders} funders with at least one tracked "
            f"money edge — the other {n_funders - n_emb} have no row in the matrix and are unranked, not "
            f"low-ranked. Scores scale with expected log-dollars, so prolific funders ({top1['label']} "
            f"holds {len(by_funder[top1['id']])} of the {len(money)} tracked edges) sit high partly "
            f"because they fund a lot of everything. Rubric shares hit 100% for single-deal funders by "
            f"construction — {rubric_thin} of the rubric's top 10 rest on ≤2 tracked deals, flagged in "
            "the table."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "ranked": rows,
            "rankRank": rank_rank,
            "seeds": seeds_block,
        },
    }
    emit(payload)

    print(
        f"    d={d}  σ={np.round(S[:6], 1).tolist()}  seeds={len(seeds)}  "
        f"recon med={recon_med:g} hit5={recon_hit5:.2f}  loo med={loo_med:g} hit5={loo_hit5:.2f}  "
        f"ρ(struct,rubric)={rho_sr:.3f}  ρ(d,d+1)={rho_d:.3f}  top10 overlap={overlap10}"
    )
    for r in rows:
        print(
            f"    {s_rank[r['id']]:2d}. {r['label'][:36]:36s} {r['kind']:12s} "
            f"score={r['score']:6.3f} rubric#{r['rubricRank']:2d} share={r['rubricShare']:.2f} "
            f"| {r['evidence'][:60]}"
        )
    print(
        f"    biggest structure-over-rubric riser: {biggest_up['label']} "
        f"(struct #{s_rank[biggest_up['id']]} vs rubric #{biggest_up['rubricRank']}) — "
        f"lane evidence: {top1_lane}"
    )


if __name__ == "__main__":
    main()
