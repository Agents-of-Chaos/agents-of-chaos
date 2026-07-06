# /// script
# requires-python = ">=3.11"
# ///
"""rivals-money — cross-graph join: which tracked checkbooks already fund our 14
flagged rivals (conflict AND proven appetite), which fund agent-security/evals
with zero rival exposure (clean targets), and which rivals' money we cannot see
at all. Run: cd experiments/analyses && uv run rivals-money.py
"""

import re
from collections import defaultdict

from _shared import emit, load_companies, load_funding, stamp

TAGS_APPETITE = {"agent-security", "evals"}  # AoC's own lane
SAFETY_TAGS = {"agent-security", "evals", "interpretability", "technical-alignment"}
SAFETY_NATIVE_MIN = 3  # >=3 non-rival safety-tagged portfolio slots = safety-native


def canon(name: str) -> str:
    """Casefold + strip one trailing parenthetical: 'Andreessen Horowitz (a16z)'
    folds onto 'andreessen horowitz'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip().casefold()


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:g}B"
    if x >= 1e6:
        return f"${x / 1e6:g}M"
    if x >= 1e3:
        return f"${x / 1e3:g}k"
    return f"${x:g}"


def short_round(txt: str | None) -> str | None:
    """'Series B (co-led with Redpoint)' -> 'Series B'."""
    if not txt:
        return None
    return re.sub(r"\s*\([^)]*\)\s*$", "", txt).strip() or None


def main() -> None:
    companies = load_companies()
    funding = load_funding()
    fnodes = {n["id"]: n for n in funding["nodes"]}
    funders = {n["id"]: n for n in funding["nodes"] if n["kind"] == "funder"}
    cnodes = {c["id"]: c for c in companies["companies"]}

    rivals = sorted(
        (c for c in companies["companies"] if c.get("competitor")),
        key=lambda c: c["id"],
    )
    assert len(rivals) == 14, f"expected 14 flagged rivals, got {len(rivals)}"
    rival_ids = {c["id"] for c in rivals}

    # ── join key 1: identity — rivals that are funding-graph grantees ────────
    riv_fund: dict[str, str] = {}  # funding node id -> companies id
    for n in funding["nodes"]:
        if n["kind"] == "grantee" and (n.get("networksId") or n["id"]) in rival_ids:
            riv_fund[n["id"]] = n.get("networksId") or n["id"]
    assert riv_fund, "no rival appears in the funding graph at all?"

    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    assert all(fnodes[e["source"]]["kind"] == "funder" for e in money)
    rival_edges = [e for e in money if e["target"] in riv_fund]
    assert rival_edges, "no money edges into rivals?"

    # ── join key 2: name — rival investor strings vs the tracked funder set ──
    funder_by_canon = {canon(f["name"]): fid for fid, f in funders.items()}
    assert len(funder_by_canon) == len(funders), "funder name canon collision"

    acquirer_of: dict[str, str] = {}  # companies id -> acquirer name
    listed: dict[str, list[str]] = {}  # companies id -> non-acquirer investor names
    string_ties: set[tuple[str, str]] = set()  # (funder id, companies rival id)
    all_names: set[str] = set()
    for c in rivals:
        listed[c["id"]] = []
        for raw in c.get("investors") or []:
            if "(acquirer)" in raw:
                acquirer_of[c["id"]] = re.sub(r"\s*\(acquirer\)\s*", "", raw).strip()
                continue
            listed[c["id"]].append(raw)
            all_names.add(canon(raw))
            fid = funder_by_canon.get(canon(raw))
            if fid:
                string_ties.add((fid, c["id"]))
    n_exited_rivals = len(acquirer_of)
    assert n_exited_rivals == 5, f"expected 5 exited rivals, got {n_exited_rivals}"
    # near-miss guard: no unmatched investor name should prefix-contain a funder name
    for nm in all_names - set(funder_by_canon):
        for fc in funder_by_canon:
            assert not (
                nm.startswith(fc + " ") or fc.startswith(nm + " ")
            ), f"possible missed name match: {nm!r} vs funder {fc!r}"

    # ── merge the two join keys into (funder, rival) pairs ───────────────────
    pairs: dict[tuple[str, str], dict | None] = {}  # -> funding edge or None
    for e in rival_edges:
        pairs[(e["source"], riv_fund[e["target"]])] = e
    for key in string_ties:
        pairs.setdefault(key, None)  # funding edge wins when both exist

    by_backer: dict[str, list[tuple[str, dict | None]]] = defaultdict(list)
    for (fid, rid), edge in sorted(pairs.items()):
        by_backer[fid].append((rid, edge))
    backer_ids = set(by_backer)
    assert backer_ids <= set(funders), "rival backer not a tracked funder"
    assert len(backer_ids) >= 5, f"suspiciously few rival backers: {len(backer_ids)}"

    # non-rival safety-tagged portfolio per funder (juniper-style thesis signal)
    safety_portfolio: dict[str, list[str]] = defaultdict(list)
    for e in money:
        g = fnodes[e["target"]]
        if e["target"] not in riv_fund and set(g.get("domainTags", [])) & SAFETY_TAGS:
            if g["name"] not in safety_portfolio[e["source"]]:
                safety_portfolio[e["source"]].append(g["name"])

    # ── table (a): rival backers ─────────────────────────────────────────────
    backers = []
    chains = []
    verified_rival_usd = 0.0
    for fid, hits in by_backer.items():
        f = funders[fid]
        usd = sum(e["amountUSD"] for _, e in hits if e and e.get("amountUSD"))
        verified_rival_usd += usd
        live, exited = [], []
        for rid, _ in hits:
            (exited if rid in acquirer_of else live).append(rid)
        conflict = (
            f"{len(live)} live + {len(exited)} exited"
            if live and exited
            else (f"{len(live)} live" if live else "exited only")
        )
        backed = ", ".join(
            cnodes[rid]["name"]
            + (
                f" → {acquirer_of[rid]}"
                if rid in acquirer_of and acquirer_of[rid] not in cnodes[rid]["name"]
                else ""
            )
            for rid, _ in hits
        )
        # the honest read: conflict and appetite are the same fact
        if not live:
            read = (
                f"rival stake dissolved into {', '.join(sorted({acquirer_of[r] for r in exited}))} — "
                "appetite proven, live conflict gone with the exit"
            )
        elif len(hits) >= 2:
            read = "multiple rival bets — likely conflicted for our equity, category conviction proven twice"
        else:
            read = "one live rival position — ask about conflicts; the appetite is real"
        if len(safety_portfolio[fid]) >= SAFETY_NATIVE_MIN:
            read += "; safety-native — also backs " + ", ".join(
                safety_portfolio[fid][:3]
            )
        backers.append(
            {
                "id": fid,
                "label": f["name"],
                "kind": f["funderKind"],
                "backed": backed,
                "conflict": conflict,
                "usd": usd or None,
                "door": f["apply"]["mode"],
                "read": read,
            }
        )
        # chains: one funder → rival edge per pair, verified = has a dollar edge
        for rid, edge in hits:
            if edge:
                bits = [
                    fmt_usd(edge["amountUSD"])
                    if edge.get("amountUSD")
                    else "$ undisclosed"
                ]
                if short_round(edge.get("round")):
                    bits.append(short_round(edge["round"]))
                if edge.get("year"):
                    bits.append(str(edge["year"]))
            else:
                bits = ["listed investor"]
            if rid in acquirer_of:
                bits.append(f"exited to {acquirer_of[rid]}")
            chains.append(
                {
                    "nodes": [
                        {"id": fid, "label": f["name"], "graph": "funding"},
                        {"id": rid, "label": cnodes[rid]["name"], "graph": "companies"},
                    ],
                    "edges": [{"label": " · ".join(bits), "verified": bool(edge)}],
                }
            )
    backers.sort(
        key=lambda r: (-len(r["backed"].split(", ")), -(r["usd"] or 0), r["id"])
    )
    chains.sort(
        key=lambda ch: (
            [r["id"] for r in backers].index(ch["nodes"][0]["id"]),
            ch["nodes"][1]["id"],
        )
    )
    for ch in chains:
        assert len(ch["edges"]) == len(ch["nodes"]) - 1 == 1
    n_exited_only = sum(1 for r in backers if r["conflict"] == "exited only")

    # ── table (b): appetite without conflict ─────────────────────────────────
    appetite: dict[str, list[dict]] = defaultdict(list)
    for e in money:
        if set(fnodes[e["target"]].get("domainTags", [])) & TAGS_APPETITE:
            appetite[e["source"]].append(e)
    clean = []
    for fid in sorted(set(appetite) - backer_ids):
        f = funders[fid]
        edges = appetite[fid]
        disclosed = [e for e in edges if e.get("amountUSD")]
        usd = sum(e["amountUSD"] for e in disclosed)
        by_size = sorted(edges, key=lambda e: (-(e.get("amountUSD") or 0), e["target"]))
        names = []
        for e in by_size:
            nm = fnodes[e["target"]]["name"]
            if nm not in names:
                names.append(nm)
        backed = ", ".join(names[:3]) + (
            f" +{len(names) - 3} more" if len(names) > 3 else ""
        )
        flags = []
        if all(e.get("regrantOf") for e in edges):
            payers = {fnodes[e["regrantOf"]]["name"] for e in edges}
            flags.append(
                f"money is {', '.join(sorted(payers))}'s, granted via this vehicle"
            )
        if not disclosed:
            flags.append("amounts undisclosed")
        if "multi-agent" in (f["apply"].get("notes") or "").lower():
            flags.append("multi-agent program on its apply page")
        clean.append(
            {
                "id": fid,
                "label": f["name"],
                "kind": f["funderKind"],
                "usd": usd or None,
                "backed": backed,
                "door": f["apply"]["mode"],
                "flag": "; ".join(flags) if flags else None,
            }
        )
    clean.sort(key=lambda r: (-(r["usd"] or 0), r["id"]))
    assert clean and not ({r["id"] for r in clean} & backer_ids)
    assert len(clean) <= 25 and len(backers) <= 25

    # ── table (c): rivals whose money we cannot see ──────────────────────────
    mapped_rivals = {rid for _, rid in pairs}
    unmapped = []
    for c in rivals:
        rid = c["id"]
        if rid in mapped_rivals:
            continue
        invs = listed[rid]
        if rid in acquirer_of:
            note = f"exited to {acquirer_of[rid]} — early backers cashed out; the owner is the checkbook now"
        elif not invs:
            note = "no investors listed on either graph — bootstrapped, or a true intel gap"
        else:
            note = f"none of its {len(invs)} listed investors is a tracked checkbook — verify before assuming small"
        unmapped.append(
            {
                "id": rid,
                "label": c["name"],
                "investorsListed": len(invs),
                "who": ", ".join(invs) if invs else None,
                "note": note,
            }
        )
    unmapped.sort(key=lambda r: (-r["investorsListed"], r["id"]))
    assert len(unmapped) + len(mapped_rivals) == 14

    # ── envelope ─────────────────────────────────────────────────────────────
    n_funders = len(funders)
    n_backers = len(backers)
    # caveat numbers, each scoped to exactly the set it describes
    nonnode_rival_ids = [
        c["id"] for c in rivals if c["id"] not in set(riv_fund.values())
    ]
    nonnode_names = {canon(nm) for rid in nonnode_rival_ids for nm in listed[rid]}
    name_matched = {fid for fid, _ in string_ties}
    edge_only = sorted(backer_ids - name_matched)
    assert name_matched <= backer_ids
    assert len(name_matched) + len(edge_only) == n_backers
    assert len(nonnode_rival_ids) == 14 - len(riv_fund)
    juniper_like = [r["label"] for r in backers if "safety-native" in r["read"]]
    exited_only_names = ", ".join(
        r["label"] for r in backers if r["conflict"] == "exited only"
    )
    payload = {
        "slug": "rivals-money",
        "graph": "both",
        "title": "Rival money",
        "sub": f"{n_backers} tracked checkbooks back our rivals; {len(clean)} fund the category clean",
        "headline": (
            f"{n_backers} of the {n_funders} tracked checkbooks already fund a flagged rival — "
            f"<strong>{fmt_usd(verified_rival_usd)}</strong> of it verified — but {n_exited_only} of the "
            f"{n_backers} hold only exited positions ({exited_only_names}), and {len(clean)} clean funders "
            "back agent-security or evals work without touching a rival."
        ),
        "prose": {
            "intro": (
                "<p>Agents of Chaos competes with 14 companies flagged as direct rivals on the companies "
                "graph. Before we pitch anyone, we want the money sorted into three piles: checkbooks "
                "already behind a rival (likely conflicted for our equity — but with proven appetite for "
                "exactly our category), checkbooks funding agent-security and evals work with no rival "
                "exposure (the clean targets), and rivals whose money we cannot see at all (intel gaps). "
                "Both facts about a rival-backer matter, conflict and appetite, so the table shows both "
                "and lets you weigh them.</p>"
            ),
            "how": (
                "<p>There is no model here — this is a database join dressed up as a graph walk, and the "
                "value is in the curation, not the math. We take the 14 rival-flagged companies and look "
                "them up in the funding graph two ways: by identity (four rivals are funding-graph nodes "
                "with money edges pointing at them) and by name (every investor listed on a rival's "
                "company card, matched against the 62 tracked funder nodes). Any funder with a hit lands "
                "in the conflict table; funders whose tracked money touches agent-security or evals "
                "grantees but never a rival land in the clean table. It is the same move as checking a "
                "benchmark for train–test contamination: mechanically trivial, but you want the overlap "
                "list before you trust the split. One wrinkle the tables keep visible: five rivals have "
                "already exited to acquirers, so those backers' conflicts died with the deal while their "
                "taste for the category did not.</p>"
            ),
            "method": (
                "<p>Deterministic two-key join, no fitted model. Key 1: identity — a funding-graph grantee "
                "whose networksId (or id) equals a competitor-flagged companies-graph id, plus all "
                f"grant/investment edges into it ({len(rival_edges)} edges, {len(riv_fund)} rivals). Key 2: "
                "canonical name equality (casefold, strip one trailing parenthetical) between the "
                "companies-graph investors[] strings and the funder node names; entries marked "
                "'(acquirer)' are treated as exits, not positions. No fuzzy matching — misses land in the "
                "intel-gap table rather than being guessed, and a prefix-containment assert guards "
                "near-miss names. Dollar conventions: led-round funding edges carry the round total "
                "(Sequoia's $80M into Irregular is the Series B it co-led with Redpoint, not its own "
                "check); undisclosed amounts stay null and are never imputed. Appetite = at least one "
                "money edge into a grantee whose domainTags include agent-security or evals; SFF's "
                "qualifying grants are all regrantOf Jaan Tallinn and are counted once, under the SFF "
                "vehicle, flagged. 'Safety-native' on a rival-backer means at least "
                f"{SAFETY_NATIVE_MIN} non-rival portfolio companies carrying safety tags "
                "(agent-security, evals, interpretability, technical-alignment).</p>"
            ),
        },
        "caveat": (
            f"Coverage is the caveat: {len(nonnode_rival_ids)} of 14 rivals are not funding-graph nodes, "
            f"so their backers are known only as the {len(nonnode_names)} name strings on their company "
            f"cards — no amounts, dates, or verification. Across all 14 cards, just {len(name_matched)} "
            f"of {len(all_names)} distinct investor names match a tracked funder; the remaining "
            f"{len(edge_only)} of the {n_backers} rival backers "
            f"({', '.join(funders[f]['name'] for f in edge_only)}) surface through funding-graph money "
            "edges instead. The clean list is therefore only as clean as the map: General Catalyst "
            "(Haize Labs) and Madrona (Gray Swan) back rivals too, they just are not tracked funder "
            "nodes here. Absence from every table means untracked, not unconflicted."
        ),
        "inputs": {"companies": stamp(companies), "funding": stamp(funding)},
        "data": {
            "rivalBackers": backers,
            "joins": chains,
            "cleanTargets": clean,
            "unmapped": unmapped,
        },
    }
    emit(payload)

    print(
        f"    verified rival $: {fmt_usd(verified_rival_usd)}   safety-native backers: {juniper_like}"
    )
    for r in backers:
        print(
            f"    {r['label'][:28]:28s} {r['conflict']:18s} {str(r['usd']):>10s}  {r['backed'][:60]}"
        )
    print("    clean targets:", ", ".join(r["label"] for r in clean))
    print("    unmapped rivals:", ", ".join(r["label"] for r in unmapped))


if __name__ == "__main__":
    main()
