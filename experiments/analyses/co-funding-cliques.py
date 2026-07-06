# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "networkx", "scipy", "graspologic==3.4.4"]
# ///
"""co-funding-cliques — which funders move in packs? Leiden communities on the
funder co-funding projection + a same-pack co-funding lift + the entry pack
for AoC. Run: cd experiments/analyses && uv run co-funding-cliques.py
"""

import math
from collections import defaultdict
from itertools import combinations

import networkx as nx
import numpy as np
from _shared import emit, load_funding, stamp

SEED = 1  # graspologic's native leiden PRNG rejects 0 (must be positive)
TRIALS = 20
AOC_TAGS = {"agent-security", "evals", "multi-agent"}  # AoC's lane
MIN_GRANTS_FOR_ENTRY = 2  # packs eligible as "entry pack" need >=2 grant edges

# Pack names are editorial and anchored on a distinctive member id: if the
# partition drifts on a future rebake, the anchor asserts below fail loudly
# and a human re-names, rather than shipping a mislabeled pack.
ANCHORS: dict[str, tuple[str, str]] = {
    "coefficient-giving": ("the EA-adjacent grant core", "EA core"),
    "cooperative-ai-foundation": ("the cooperative-AI bloc", "coop-AI"),
    "sequoia-capital": ("the Oasis Security syndicate", "Oasis synd."),
    "juniper-ventures": ("the safety seed pack", "seed pack"),
    "anthropic-programs": ("the Timaeus backers", "Timaeus"),
    "greylock": ("the 7AI syndicate", "7AI synd."),
}
# condensed from each funder's committed apply info (same snapshot)
ENTRY_WHY = {
    "cooperative-ai-foundation": (
        "joint 'Scaling AI Safety for a Multi-Agent World' round with "
        "Schmidt Sciences, Google DeepMind and ARIA — Tier 2 covers $300k–$1M"
    ),
    "nsf": "PESOSE solicitation names AI-agent protocol security; Track 1 up to $300k",
    "macroscopic-ventures": (
        "no application portal — the member a CAIF or NSF grant makes reachable"
    ),
}


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:g}B"
    if x >= 1e6:
        return f"${x / 1e6:g}M"
    if x >= 1e3:
        return f"${x / 1e3:g}k"
    return f"${x:g}"


def leiden_blocks(G: nx.Graph) -> dict[str, int]:
    from graspologic.partition import leiden

    part = leiden(G, random_seed=SEED, trials=TRIALS)
    part_again = leiden(G, random_seed=SEED, trials=TRIALS)
    assert part == part_again, "leiden partition not identical across re-runs"
    assert set(part) == set(G.nodes), "leiden must partition every co-funder"
    return part


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    today = funding["meta"]["generatedAt"]  # snapshot date — never wall clock
    assert len(today) == 10 and today[4] == "-", f"bad generatedAt {today!r}"

    funders = [n for n in funding["nodes"] if n["kind"] == "funder"]
    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    assert all(nodes[e["source"]]["kind"] == "funder" for e in money)
    assert all(nodes[e["target"]]["kind"] == "grantee" for e in money)
    n_grants = sum(1 for e in money if e["type"] == "grant")
    n_undisclosed = sum(
        1 for e in money if e["type"] == "grant" and e.get("amountUSD") is None
    )
    # regrants: SFF money is Jaan Tallinn's — we count the grantee ONCE (under
    # SFF, who runs the pick); assert the payer has no direct edges that would
    # double-count a grantee as two "independent" co-funders.
    regrant_payers = {e["regrantOf"] for e in money if e.get("regrantOf")}
    for payer in regrant_payers:
        assert not any(e["source"] == payer for e in money), (
            f"regrant payer {payer} also grants directly — co-funding pairs "
            "with its regrantor would double-count one decision"
        )

    # ── bipartite projection: weight = number of shared grantees ────────────
    backs: dict[str, set[str]] = defaultdict(set)
    for e in money:
        backs[e["source"]].add(e["target"])
    movers = sorted(backs)  # funders with >=1 money edge
    G = nx.Graph()
    for f1, f2 in combinations(movers, 2):
        shared = backs[f1] & backs[f2]
        if shared:
            G.add_edge(f1, f2, weight=float(len(shared)))
    assert G.number_of_nodes() >= 10, f"co-funding graph too thin: {G}"
    n_isolates = len(movers) - G.number_of_nodes()

    part = leiden_blocks(G)
    packs: dict[int, list[str]] = defaultdict(list)
    for fid, c in part.items():
        packs[c].append(fid)
    assert 3 <= len(packs) <= 10, f"unexpected pack count {len(packs)}"

    # Jaccard robustness: same pipeline, weight = |shared| / |union|
    GJ = nx.Graph()
    for f1, f2 in combinations(movers, 2):
        shared = backs[f1] & backs[f2]
        if shared:
            GJ.add_edge(f1, f2, weight=len(shared) / len(backs[f1] | backs[f2]))
    partJ = leiden_blocks(GJ)
    byJ: dict[int, list[str]] = defaultdict(list)
    for fid, c in partJ.items():
        byJ[c].append(fid)
    packsJ = {frozenset(m) for m in byJ.values()}
    n_stable = sum(1 for m in packs.values() if frozenset(m) in packsJ)

    # ── name packs via anchors (loud failure on drift) ──────────────────────
    named: list[dict] = []
    for c, members in packs.items():
        hits = [a for a in ANCHORS if a in members]
        assert len(hits) == 1, f"pack {sorted(members)} has anchors {hits} — re-name"
        name, short = ANCHORS[hits[0]]
        named.append({"members": sorted(members), "name": name, "short": short})
    assert len({p["short"] for p in named}) == len(named)

    # ── entry pack: grant packs ranked by AoC-lane share of grant edges ─────
    for p in named:
        ge = [e for e in money if e["source"] in p["members"] and e["type"] == "grant"]
        aoc = sum(
            1 for e in ge if set(nodes[e["target"]].get("domainTags") or []) & AOC_TAGS
        )
        p["nGrants"] = len(ge)
        p["aocShare"] = aoc / len(ge) if ge else 0.0
        p["nMultiAgent"] = sum(
            1
            for m in p["members"]
            if "multi-agent" in (nodes[m].get("domainTags") or [])
        )
    eligible = [p for p in named if p["nGrants"] >= MIN_GRANTS_FOR_ENTRY]
    assert eligible, "no grant-heavy pack — entry-pack framing is broken"
    entry = max(eligible, key=lambda p: (p["aocShare"], p["nGrants"], p["name"]))
    assert entry["aocShare"] > 0
    runner = max(
        (p for p in eligible if p is not entry),
        key=lambda p: (p["aocShare"], p["nGrants"], p["name"]),
    )
    # the caveat's stability claim, asserted: under Jaccard weights the entry
    # pack folds into the big philanthropy core (with the EA-core anchor)
    merged = set(entry["members"]) | {"coefficient-giving"}
    assert any(
        merged <= pj for pj in packsJ
    ), "caveat claim broken: entry pack no longer merges into the EA core under Jaccard"

    # ── pack display order: entry first, then size desc, then short asc ─────
    named.sort(key=lambda p: (p is not entry, -len(p["members"]), p["short"]))
    pack_of = {m: p for p in named for m in p["members"]}

    # ── THE actionable stat: same-pack vs cross-pack co-funding lift ────────
    same_co = same_n = cross_co = cross_n = 0
    for f1, f2 in combinations(sorted(part), 2):
        co = bool(backs[f1] & backs[f2])
        if part[f1] == part[f2]:
            same_n += 1
            same_co += co
        else:
            cross_n += 1
            cross_co += co
    assert same_n and cross_n and cross_co > 0
    same_rate = same_co / same_n
    cross_rate = cross_co / cross_n
    lift = same_rate / cross_rate
    assert lift > 1.5, f"packs should concentrate co-funding, lift={lift:.2f}"

    # ── DCSBM-style ledger: observed vs degree-expected co-funding weight ───
    deg = dict(G.degree(weight="weight"))
    two_m = sum(deg.values())
    k = len(named)
    idx = {p["short"]: i for i, p in enumerate(named)}
    O = np.zeros((k, k))
    for u, v, w in G.edges(data="weight"):
        i, j = idx[pack_of[u]["short"]], idx[pack_of[v]["short"]]
        O[i, j] += w
        if i != j:
            O[j, i] += w
    cells: list[list[float | None]] = []
    for i, pr in enumerate(named):
        row: list[float | None] = []
        Dr = sum(deg[m] for m in pr["members"])
        for j, ps in enumerate(named):
            Ds = sum(deg[m] for m in ps["members"])
            if i == j:
                expct = (Dr * Dr - sum(deg[m] ** 2 for m in pr["members"])) / (
                    2 * two_m
                )
            else:
                expct = Dr * Ds / (2 * two_m)
            if O[i, j] == 0:
                row.append(None)  # never co-fund → blank, not −inf
            else:
                assert expct > 0
                row.append(round(math.log10(O[i, j] / expct), 2))
        cells.append(row)
    assert (
        abs(O.sum() + np.trace(O) - 2 * sum(w for *_, w in G.edges(data="weight")))
        < 1e-9
    )

    # ── members table (one row per co-funding funder, pack-grouped) ─────────
    members_rows = []
    single_glue: dict[str, str] = {}
    for p in named:
        pack_shared: set[str] = set()
        for f1, f2 in combinations(p["members"], 2):
            pack_shared |= backs[f1] & backs[f2]
        if len(pack_shared) == 1:
            single_glue[p["short"]] = nodes[next(iter(pack_shared))]["name"]
        for m in sorted(p["members"], key=lambda m: (-deg[m], m)):
            packmates = [x for x in p["members"] if x != m]
            ties = sum(1 for x in packmates if backs[m] & backs[x])
            orgs = set().union(*(backs[m] & backs[x] for x in packmates))
            members_rows.append(
                {
                    "id": m,
                    "label": nodes[m]["name"],
                    "pack": p["short"],
                    "kind": nodes[m]["funderKind"],
                    "door": nodes[m]["apply"]["mode"],
                    "ties": ties,
                    "orgs": len(orgs),
                    "flag": (
                        f"pack rests on one shared bet: {single_glue[p['short']]}"
                        if p["short"] in single_glue
                        else None
                    ),
                }
            )
    assert len(members_rows) == G.number_of_nodes() <= 25

    # ── entry-pack door table (openness judged against the snapshot date) ───
    def door(f: dict) -> tuple[str, bool]:
        mode, deadline = f["apply"]["mode"], f["apply"].get("deadline")
        if mode == "rolling":
            return "rolling", True
        if mode == "rounds" and deadline and deadline > today:
            return f"rounds — closes {deadline}", True
        return mode, False

    entry_rows = []
    for m in entry["members"]:
        f = nodes[m]
        label, is_open = door(f)
        cs = f.get("checkSizeUSD")
        entry_rows.append(
            {
                "id": m,
                "label": f["name"],
                "door": label,
                "check": f"{fmt_usd(cs['min'])}–{fmt_usd(cs['max'])}" if cs else None,
                "why": ENTRY_WHY.get(m, ""),
                "_open": is_open,
                "_deadline": f["apply"].get("deadline") or "9999",
            }
        )
    entry_rows.sort(key=lambda r: (not r["_open"], r["_deadline"], r["id"]))
    n_open = sum(r.pop("_open") for r in entry_rows)
    for r in entry_rows:
        r.pop("_deadline")
    assert n_open >= 1, "entry pack has no open door — reframe the panel"
    open_names = [r["label"] for r in entry_rows[:n_open]]

    pack_ties = [
        {"a": f1, "b": f2}
        for f1, f2 in combinations(sorted(entry["members"]), 2)
        if backs[f1] & backs[f2]
    ]
    assert pack_ties

    n_funders = len(funders)
    ledger_between = round(10 ** cells[idx[runner["short"]]][idx[entry["short"]]], 1)
    payload = {
        "slug": "co-funding-cliques",
        "graph": "funding",
        "title": "Co-funding packs",
        "sub": (
            f"{len(named)} packs among {G.number_of_nodes()} co-funding funders — "
            f"same-pack pairs are {lift:.1f}× likelier to co-fund you"
        ),
        "headline": (
            f"Funders on this map hunt in packs: two funders from the same pack are "
            f"<strong>{lift:.1f}×</strong> more likely to co-fund the same grantee than two "
            f"funders from different packs — and the pack nearest AoC's multi-agent lane "
            f"({entry['name'].removeprefix('the ')}: "
            f"{', '.join(nodes[m]['name'] for m in sorted(entry['members'], key=lambda m: (-deg[m], m)))}) "
            f"has {n_open} doors open."
        ),
        "prose": {
            "intro": (
                f"<p>Raising a first grant is not {n_funders} independent doors. Funders share "
                "deal flow, referees, and joint calls, so landing one of them moves its "
                "pack-mates' priors about you. This panel finds the packs in the funding map "
                "and measures how much being inside one matters — then names the pack, and the "
                "specific open doors, where Agents of Chaos should start.</p>"
            ),
            "how": (
                "<p>Think of each funder as a label and each grantee as a training example: "
                "labels that keep firing on the same examples are correlated, and that "
                "co-occurrence signal is the same raw material word embeddings are built from. "
                "We wire two funders together by how many grantees they both back, then run a "
                "community detector on that co-occurrence graph — the packs fall out the way "
                "clusters fall out of an embedding. To check the packs are real and not just an "
                "artifact of a few prolific funders, we compare each pack pair's observed "
                "co-funding against what a degree-matched random rewiring would produce; on a "
                "log scale, green cells mean the packs seek each other out beyond what their "
                f"sheer activity predicts. The payoff number reads like a recommender's lift: "
                f"{round(100 * same_rate)}% of same-pack funder pairs back at least one common "
                f"grantee versus {round(100 * cross_rate)}% of cross-pack pairs — "
                f"{lift:.1f}× the co-funding odds.</p>"
            ),
            "method": (
                "<p>Bipartite funder→grantee multigraph (grants + investments) projected onto "
                "funders; edge weight = count of shared grantees, so the "
                f"{n_undisclosed} of {n_grants} grants with undisclosed amounts carry the same "
                "evidentiary weight as disclosed ones and no dollar is ever double-counted. "
                "SFF's grants are regrants of Jaan Tallinn's money; they are counted once, as "
                "SFF decisions (the s-process makes the pick), and the payer has no direct "
                "grant edges — asserted in code. Communities: graspologic's Leiden "
                f"(Traag, Waltman &amp; van Eck 2019), random_seed={SEED}, trials={TRIALS}, "
                "partition asserted identical across two runs. Robustness: re-clustering with "
                f"Jaccard weights (shared over union) reproduces {n_stable} of {len(named)} "
                "packs exactly and merges the two philanthropy blocs into one. The ledger is "
                "DCSBM-style: observed block-pair weight over the configuration-model "
                "expectation D<sub>r</sub>D<sub>s</sub>/2m (Chung–Lu), shown as log10; tiny "
                "packs get huge diagonals because their degree-expected weight is near zero. "
                "The lift compares P(≥1 shared grantee) for same-pack vs cross-pack pairs "
                f"among the {G.number_of_nodes()} partitioned funders; it is descriptive, not "
                "predictive — the packs were learned from the same co-funding matrix, so it "
                "quantifies how concentrated co-funding is, not an out-of-sample forecast. "
                f"Entry pack: among packs with ≥{MIN_GRANTS_FOR_ENTRY} grant edges, the one "
                "whose grants most often land on grantees tagged agent-security, evals, or "
                f"multi-agent ({round(100 * entry['aocShare'])}% for {entry['name']} vs "
                f"{round(100 * runner['aocShare'])}% for {runner['name']}; "
                f"{entry['nMultiAgent']} of {len(entry['members'])} members declare "
                "multi-agent as a focus). Door-open claims are judged against the snapshot "
                f"date {today}, never wall clock.</p>"
            ),
        },
        "caveat": (
            f"Thin where it matters: only {len(movers)} of {n_funders} funders have tracked "
            f"money edges, {n_isolates} of those co-fund with nobody, and {len(single_glue)} "
            f"of the {len(named)} packs rest on a single shared bet (one syndicated round, "
            "not a repeated pattern — flagged in the table). The entry-pack boundary is the least "
            "stable cut: under Jaccard weighting the cooperative-AI bloc merges into the EA "
            f"grant core (the two blocs already seek each other out at {ledger_between}× "
            "expected), so read it as the multi-agent-flavored wing of one big "
            "philanthropy pack — its open doors are real either way."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "members": members_rows,
            "ledger": {
                "rows": [p["short"] for p in named],
                "cols": [p["short"] for p in named],
                "cells": cells,
            },
            "entry": entry_rows,
            "packTies": pack_ties,
            "stats": {
                "lift": round(lift, 1),
                "sameRate": round(same_rate, 3),
                "crossRate": round(cross_rate, 3),
                "nPacks": len(named),
                "nCoFunders": G.number_of_nodes(),
                "nMovers": len(movers),
                "nFunders": n_funders,
                "entryPack": entry["name"],
                "entryShort": entry["short"],
            },
        },
    }
    emit(payload)

    # eyeball block for the run log
    print(f"    lift={lift:.2f} (same {same_co}/{same_n}, cross {cross_co}/{cross_n})")
    for p in named:
        star = " <-- entry" if p is entry else ""
        print(
            f"    {p['short']:12s} n={len(p['members'])} grants={p['nGrants']:3d} "
            f"aocShare={p['aocShare']:.2f} multiAgentTags={p['nMultiAgent']}{star}"
        )
    for r in entry_rows:
        print(f"      {r['label']:28s} {r['door']:26s} {r['check'] or '—'}")


if __name__ == "__main__":
    main()
