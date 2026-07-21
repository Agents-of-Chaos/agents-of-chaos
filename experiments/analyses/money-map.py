# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""money-map — the funding world flattened to 2D from who-pays-whom alone:
bipartite ASE of the dollar-weighted money graph, kind misfits, and the
domain x funder-kind white-space matrix.
Run: cd experiments/analyses && uv run money-map.py
"""

import math
import statistics
from collections import Counter, defaultdict

import numpy as np
from _shared import emit, fix_signs, load_funding, stamp

KINDS = ["philanthropy", "government", "corporate", "vc"]
R_MIN, R_MAX = 2.0, 9.0  # dot radius clip (px)
R_SCALE = 0.9  # r = R_SCALE * sqrt($M), clipped


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    return f"${x / 1e3:.0f}k"


def components(edges: list[dict]) -> dict[str, str]:
    """Union-find roots for every node touched by `edges`."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e["source"])] = find(e["target"])
    return {n: find(n) for n in parent}


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    grants = [e for e in money if e["type"] == "grant"]
    n_funders_total = sum(1 for n in funding["nodes"] if n["kind"] == "funder")

    # the money graph is exactly bipartite — every money edge is funder→grantee
    assert all(
        nodes[e["source"]]["kind"] == "funder"
        and nodes[e["target"]]["kind"] == "grantee"
        for e in money
    ), "money graph not bipartite"
    # regrant payers (Jaan Tallinn) have no direct money edges → no double count
    payers = {e["regrantOf"] for e in money if e.get("regrantOf")}
    for p in payers:
        assert not any(e["source"] == p for e in money), f"double-count risk: {p}"

    med = statistics.median(
        e["amountUSD"] for e in money if e.get("amountUSD") is not None
    )
    n_null = sum(1 for e in money if e.get("amountUSD") is None)
    assert 1e5 < med < 1e8, f"implausible median grant {med}"

    # tracked dollars through each node (undisclosed amounts floored at median)
    routed: dict[str, float] = defaultdict(float)
    for e in money:
        amt = e.get("amountUSD") or med
        routed[e["source"]] += amt
        routed[e["target"]] += amt

    # ── giant component of the money graph ─────────────────────────────────
    roots = components(money)
    comp_sizes = Counter(roots.values())
    giant_root = max(comp_sizes, key=lambda k: (comp_sizes[k], k))
    gset = {n for n, r in roots.items() if r == giant_root}
    n_islands = len(comp_sizes) - 1
    island_nodes = [n for n in roots if n not in gset]
    island_dollars = sum(
        (e.get("amountUSD") or med) for e in money if e["source"] not in gset
    )
    n_unplaced_funders = n_funders_total - sum(
        1 for n in gset if nodes[n]["kind"] == "funder"
    )
    # the unplaced split: funders with no money edge at all vs island VCs
    money_touched = {e["source"] for e in money} | {e["target"] for e in money}
    n_zero_edge_funders = sum(
        1
        for n in funding["nodes"]
        if n["kind"] == "funder" and n["id"] not in money_touched
    )
    n_island_funders = sum(1 for n in island_nodes if nodes[n]["kind"] == "funder")
    assert n_zero_edge_funders + n_island_funders == n_unplaced_funders, (
        f"unplaced split broken: {n_zero_edge_funders}+{n_island_funders}"
        f"!={n_unplaced_funders}"
    )
    assert len(gset) >= 50, f"giant component suspiciously small: {len(gset)}"
    assert all(
        nodes[n]["kind"] == "funder" and nodes[n]["funderKind"] == "vc"
        for n in island_nodes
        if nodes[n]["kind"] == "funder"
    ), "islands expected to be VC-only on the funder side"

    funders = sorted(n for n in gset if nodes[n]["kind"] == "funder")
    grantees = sorted(n for n in gset if nodes[n]["kind"] == "grantee")
    assert len(funders) >= 10 and len(grantees) >= 40

    # ── bipartite ASE: SVD of the rectangular log-dollar matrix ────────────
    # (symmetrizing first degenerates: bipartite spectra pair up ±σ and the
    # top-2 vectors load on one side each — verified on this graph)
    fi = {n: i for i, n in enumerate(funders)}
    gi = {n: i for i, n in enumerate(grantees)}
    B = np.zeros((len(funders), len(grantees)))
    for e in money:
        if e["source"] in gset:
            B[fi[e["source"]], gi[e["target"]]] += math.log10(
                (e.get("amountUSD") or med) + 1
            )
    U, S, Vt = np.linalg.svd(B, full_matrices=False)
    assert S[0] > S[1] > S[2] > 0 and S[1] - S[2] > 1, f"unstable spectrum {S[:4]}"
    Z = fix_signs(np.vstack([U[:, :3] * np.sqrt(S[:3]), Vt[:3].T * np.sqrt(S[:3])]))
    order = funders + grantees
    dim1 = {n: float(Z[i, 0]) for i, n in enumerate(order)}
    pos = {n: (float(Z[i, 1]), float(Z[i, 2])) for i, n in enumerate(order)}

    # dimension 1 is mostly volume — that story moves into dot AREA instead
    log_routed = np.array([math.log10(routed[n] + 1) for n in order])
    r_vol = float(np.corrcoef(Z[: len(order), 0], log_routed)[0, 1])
    assert r_vol > 0.6, f"dim1 should track volume, r={r_vol}"

    # ── the map: dims 2–3, funders colored by kind, grantees gray ──────────
    def radius(dollars: float) -> float:
        return round(min(R_MAX, max(R_MIN, R_SCALE * math.sqrt(dollars / 1e6))), 1)

    points = []
    for n in order:
        nd = nodes[n]
        is_f = nd["kind"] == "funder"
        dollars = routed[n] if is_f else nd["fieldDollarsUSD"]
        # a few startups have verified $0 inbound (undisclosed VC rounds) —
        # they render at the minimum radius
        assert dollars is not None and dollars >= 0, f"no dollars for {n}"
        points.append(
            {
                "id": n,
                "label": nd["name"],
                "x": round(pos[n][0], 4),
                "y": round(pos[n][1], 4),
                "group": nd["funderKind"] if is_f else "grantee",
                "r": radius(dollars),
            }
        )
    # two identically-wired pairs exist: a funder pair splitting one grantee and
    # a grantee pair sharing one backer → coincident dots; nudge duplicates
    # apart with seeded jitter, disclosed
    rng = np.random.default_rng(0)
    seen: set[tuple[float, float]] = set()
    n_jittered = 0
    for p in points:
        while (p["x"], p["y"]) in seen:
            p["x"] = round(p["x"] + float(rng.uniform(-0.04, 0.04)), 4)
            p["y"] = round(p["y"] + float(rng.uniform(-0.04, 0.04)), 4)
            n_jittered += 1
        seen.add((p["x"], p["y"]))
    assert len(points) == len(gset) and n_jittered <= 4

    # ── misfits: distance to the leave-one-out centroid of your own kind ───
    misfits = []
    for f in funders:
        kind = nodes[f]["funderKind"]
        same = [g for g in funders if g != f and nodes[g]["funderKind"] == kind]
        assert same, f"kind {kind} has a single embedded funder"
        cx = sum(pos[g][0] for g in same) / len(same)
        cy = sum(pos[g][1] for g in same) / len(same)
        near = min(
            (g for g in funders if g != f),
            key=lambda g: (math.hypot(pos[f][0] - pos[g][0], pos[f][1] - pos[g][1]), g),
        )
        n_checks = sum(1 for e in money if e["source"] == f)
        n_regrant = sum(1 for e in money if e["source"] == f and e.get("regrantOf"))
        flags = []
        if n_checks == 1:
            flags.append("single tracked check — one-edge position")
        if n_regrant:
            payer = nodes[
                next(
                    e["regrantOf"]
                    for e in money
                    if e["source"] == f and e.get("regrantOf")
                )
            ]["name"]
            flags.append(f"{n_regrant}/{n_checks} checks regrant {payer} money")
        misfits.append(
            {
                "id": f,
                "label": nodes[f]["name"],
                "kind": kind,
                "checks": n_checks,
                "routed": round(routed[f]),
                "offCenter": round(math.hypot(pos[f][0] - cx, pos[f][1] - cy), 2),
                "behavesLike": f"{nodes[near]['name']} ({nodes[near]['funderKind']})",
                "flag": "; ".join(flags) if flags else None,
            }
        )
    misfits.sort(key=lambda r: (-r["offCenter"], r["id"]))
    n_one_check = sum(1 for m in misfits if m["checks"] == 1)

    # ── white-space matrix: domain × funder kind, every dollar lands once ──
    # dollars split evenly across the grantee's domain tags; untagged grantees
    # get their own row so no money silently disappears
    domains = [dom["id"] for dom in funding["meta"]["domains"]]
    dom_label = {dom["id"]: dom["label"] for dom in funding["meta"]["domains"]}
    cells: dict[tuple[str, str], float] = defaultdict(float)
    for e in money:
        kind = nodes[e["source"]]["funderKind"]
        tags = nodes[e["target"]].get("domainTags") or ["(untagged)"]
        amt = e.get("amountUSD") or med
        for t in tags:
            cells[(t, kind)] += amt / len(tags)
    total = sum(cells.values())
    assert abs(total - sum((e.get("amountUSD") or med) for e in money)) < 1
    row_ids = sorted(domains, key=lambda t: -sum(cells.get((t, k), 0) for k in KINDS))
    row_ids.append("(untagged)")
    matrix_cells = [
        [round(cells[(t, k)]) if (t, k) in cells else None for k in KINDS]
        for t in row_ids
    ]
    n_empty = sum(1 for row in matrix_cells[:-1] for c in row if c is None)

    # ── the headline numbers: agent-security is grant-free ─────────────────
    as_grantees = {
        n["id"]
        for n in funding["nodes"]
        if n["kind"] == "grantee" and "agent-security" in n.get("domainTags", [])
    }
    assert as_grantees and all(
        nodes[g]["granteeKind"] == "startup" for g in as_grantees
    ), "agent-security grantees expected to be all startups"
    as_grants = [e for e in grants if e["target"] in as_grantees]
    assert not as_grants, "a grant into agent-security exists — rewrite the headline"
    as_vc_dollars = sum(
        (e.get("amountUSD") or med) for e in money if e["target"] in as_grantees
    )
    as_declarers = [
        n
        for n in funding["nodes"]
        if n["kind"] == "funder"
        and n["funderKind"] != "vc"
        and "agent-security" in n.get("domainTags", [])
    ]
    # the headline's target list, named: every declarer, most active first
    declarer_rows = []
    for n in sorted(as_declarers, key=lambda n: (-routed[n["id"]], n["id"])):
        n_checks = sum(1 for e in money if e["source"] == n["id"])
        declarer_rows.append(
            {
                "id": n["id"],
                "label": n["name"],
                "kind": n["funderKind"],
                "apply": n["apply"]["mode"],
                "checks": n_checks,
                "routed": round(routed[n["id"]]) if n_checks else None,
                "flag": None
                if n_checks
                else "declared focus only — no tracked checks anywhere in the graph",
            }
        )
    assert 0 < len(declarer_rows) <= 25, f"{len(declarer_rows)} declarers"
    assert not any(
        e["source"] == r["id"] and e["target"] in as_grantees
        for e in money
        for r in declarer_rows
    ), "a declarer funds agent-security after all — rewrite the headline"
    ma_grantees = [
        n
        for n in funding["nodes"]
        if n["kind"] == "grantee" and "multi-agent" in n.get("domainTags", [])
    ]
    ma_dollars = sum(
        (e.get("amountUSD") or med)
        for e in money
        if e["target"] in {g["id"] for g in ma_grantees}
    )
    ma_declarers = sum(
        1
        for n in funding["nodes"]
        if n["kind"] == "funder" and "multi-agent" in n.get("domainTags", [])
    )
    n_untagged = sum(
        1
        for n in funding["nodes"]
        if n["kind"] == "grantee" and not n.get("domainTags")
    )
    untagged_dollars = sum(
        (e.get("amountUSD") or med)
        for e in money
        if not nodes[e["target"]].get("domainTags")
    )
    top_misfit = misfits[1]  # [0] is SFF, a pole; NSF is the cross-kind misfit
    assert (
        top_misfit["id"] == "nsf"
    ), f"expected NSF as top cross-kind misfit, got {top_misfit['id']}"
    # prose + axis labels state these orientations — fail loud if churn flips them
    assert top_misfit["behavesLike"].startswith(
        "Cooperative AI Foundation"
    ), top_misfit["behavesLike"]
    assert pos["coefficient-giving"][0] < 0 < pos["survival-and-flourishing-fund"][0]
    assert pos["nsf"][1] > 0, "NSF pole flipped — fix the y-axis label"

    payload = {
        "slug": "money-map",
        "graph": "funding",
        "title": "The money map",
        "sub": f"{len(gset)} funded nodes placed by who-pays-whom alone — poles, misfits, white space",
        "headline": (
            "The map's biggest white space is AoC's own lane: <strong>zero of the "
            f"{len(grants)} tracked grants touch an agent-security grantee</strong> — all "
            f"{fmt_usd(as_vc_dollars)} of tracked agent-security money is venture capital into "
            f"startups, even though {len(as_declarers)} grantmakers declare agent security as a focus."
        ),
        "prose": {
            "intro": (
                "<p>The funding map's curated view sorts funders into four kinds and eight domains. "
                "This panel throws the labels away and asks what shape the money actually has: every "
                "funder and grantee is placed purely by who pays whom, weighted by dollars. The shape "
                "answers two business questions at once — which funders behave alike (whatever their "
                "label says), and where no tracked check lands at all.</p>"
            ),
            "how": (
                "<p>Think of the t-SNE plots people make of embedding spaces — except this one is "
                "deterministic and linear, so distances are honest and rerunning it cannot rearrange "
                "the picture. Each funder's row of log-dollars across grantees is its portfolio "
                "vector; a matrix factorization compresses those vectors so that two funders land "
                "close when they fund the same orgs at similar scale, and each grantee lands amid its "
                f"funders. The first coordinate mostly measures volume (r={r_vol:.2f} with log dollars "
                "routed), so size lives in the dot area and the map shows the next two coordinates — "
                "the ones that encode taste. Three poles emerge: Coefficient Giving's institutional "
                "portfolio on the left, the SFF/Tallinn cluster on the right, and the NSF/Cooperative-AI "
                "campus pole on top. The funders far from their own kind's center are the findings — "
                "NSF, a federal science agency on paper, is wired like a philanthropy: its nearest neighbor "
                "on the map is the Cooperative AI Foundation.</p>"
            ),
            "method": (
                "<p>Adjacency spectral embedding of the weighted bipartite funder×grantee matrix "
                "(entries log10($+1); undisclosed amounts floored at the tracked median "
                f"{fmt_usd(med)}, {n_null} of {len(money)} edges): rank-3 truncated SVD, funders at "
                "U√S, grantees at V√S (Sussman et al., JASA 2012), joint sign-fixing for reproducibility. "
                "Symmetrizing first degenerates — bipartite spectra pair up ±σ and the top singular "
                "vectors load on one side each (verified) — so the rectangular route is required. The "
                "map plots dimensions 2–3; dimension 1 is volume and moves into dot area "
                "(r ∝ √$ through the node, clipped 2–9px; funders use tracked outbound dollars, grantees "
                "their verified fieldDollarsUSD). Giant component only (76 of 94 nodes with money "
                "edges); affiliation edges excluded — people would clutter a money map. SFF's regranted "
                "checks stay attributed to SFF; the payer (Jaan Tallinn) has no direct edges, so no "
                "dollar is counted twice. Off-center = distance to the leave-one-out centroid of the "
                "funder's own kind in map coordinates. The white-space matrix splits each check evenly "
                "across the grantee's domain tags so every dollar lands exactly once (CMU FOCAL's $3.5M "
                "halves between multi-agent and technical alignment); it covers all 130 money edges, "
                "islands included. Two identically-wired pairs — two funders splitting the same single "
                "grantee, and two grantees sharing the same single backer — are "
                "nudged apart by ±0.04 seeded jitter. The third axis rides a modest eigengap "
                f"(σ₃={S[2]:.1f} vs σ₄={S[3]:.1f}), so read vertical positions as suggestive, not exact.</p>"
            ),
        },
        "caveat": (
            f"Coverage limits what the wiring can say: {n_unplaced_funders} of {n_funders_total} funders "
            f"are missing from the map — {n_zero_edge_funders} have no tracked money edge at all, and "
            f"the other {n_island_funders} are VCs whose checks sit in {n_islands} investment islands "
            f"({len(island_nodes)} nodes, {fmt_usd(island_dollars)}) that share no grantee with the grant "
            f"economy; island money appears in the matrix but not on the map. {n_one_check} of {len(funders)} "
            f"placed funders have exactly one tracked check, so their positions are one-edge readings "
            f"(flagged). {n_untagged} of 69 grantees carry no domain tags; their {fmt_usd(untagged_dollars)} "
            f"sits in the matrix's untagged row rather than vanishing. VC cells credit full round sizes "
            f"to the round's lead, and {n_null} undisclosed amounts enter at the {fmt_usd(med)} median floor."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "map": points,
            "misfits": misfits,
            "whiteSpace": {
                "rows": [dom_label.get(t, t) for t in row_ids],
                "cols": KINDS,
                "cells": matrix_cells,
            },
            "declarers": declarer_rows,
        },
    }
    emit(payload)

    print(
        f"    giant={len(gset)} ({len(funders)}F/{len(grantees)}G)  islands={n_islands} "
        f"({len(island_nodes)} nodes, {fmt_usd(island_dollars)})  r(dim1,log$)={r_vol:.3f}  "
        f"unplaced={n_unplaced_funders} ({n_zero_edge_funders} zero-edge + {n_island_funders} island VCs)"
    )
    print(
        f"    agent-security: {fmt_usd(as_vc_dollars)} all-VC, {len(as_declarers)} non-VC declarers, 0 grants"
        f"  |  multi-agent: {len(ma_grantees)} grantee, {fmt_usd(ma_dollars)}, {ma_declarers} declarers"
        f"  |  empty domain cells: {n_empty}/32  |  jittered: {n_jittered}"
    )
    for m in misfits[:6]:
        print(
            f"    {m['label'][:32]:32s} {m['kind']:12s} off-center={m['offCenter']:.2f} "
            f"behaves like {m['behavesLike']}"
        )


if __name__ == "__main__":
    main()
