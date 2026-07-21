# /// script
# requires-python = ">=3.11"
# ///
"""shared-investors — bipartite analysis of investor lists: who already funds our
14 rivals, and which look-alike funds carry zero rival exposure ("uncontested
capital"). Run: cd experiments/analyses && uv run shared-investors.py
"""

import math
import re
from collections import Counter, defaultdict

from _shared import emit, load_companies, stamp

MIN_ANCHOR_PORTFOLIO = 3  # anchors: rival-backers with >= this many mapped companies
MIN_CAND_PORTFOLIO = 2  # one shared deal is not a portfolio pattern
MEGA_HUB = 25  # >25 mapped companies = similar to everyone (vacuous today, max is 24)
TWINS_PER_ANCHOR = 3
MAX_UNCONTESTED = 14  # closes the 0.408 cosine tie group exactly


def canon(name: str) -> str:
    """Casefold + strip one trailing parenthetical: 'Andreessen Horowitz (a16z)'
    and 'Cisco (acquirer)' fold onto their plain variants."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip().casefold()


def cosine(a: set[str], b: set[str]) -> float:
    overlap = len(a & b)
    return overlap / math.sqrt(len(a) * len(b)) if overlap else 0.0


def main() -> None:
    companies = load_companies()
    by_id = {c["id"]: c for c in companies["companies"]}
    rival_ids = {c["id"] for c in companies["companies"] if c.get("competitor")}
    assert len(rival_ids) == 14, f"expected 14 competitor flags, got {len(rival_ids)}"

    # bipartite incidence: canonical investor -> set of mapped company ids
    portfolio: dict[str, set[str]] = defaultdict(set)
    variants: dict[str, Counter] = defaultdict(Counter)
    for c in companies["companies"]:
        for raw in c.get("investors") or []:
            key = canon(raw)
            portfolio[key].add(c["id"])
            variants[key][raw] += 1
    n_listed = sum(1 for c in companies["companies"] if c.get("investors"))
    assert n_listed >= 100 and len(portfolio) >= 300, "investor coverage collapsed?"
    assert (
        max(len(p) for p in portfolio.values()) <= MEGA_HUB
    ), "an investor crossed the mega-hub cutoff — revisit MEGA_HUB and the twins list"

    def label(key: str) -> str:
        pairs = variants[key].most_common()
        return sorted(pairs, key=lambda t: (-t[1], len(t[0]), t[0]))[0][0]

    # rivals whose mapped money already exited to an acquirer (data-encoded)
    owner = {
        rid: m.group(1)
        for rid in rival_ids
        if (m := re.search(r"\((.+)\)$", by_id[rid]["name"]))
    }
    exited = {
        rid
        for rid in rival_ids
        if any("(acquirer)" in raw for raw in by_id[rid].get("investors") or [])
        or any(
            canon(raw) == canon(owner.get(rid, "\0"))
            for raw in by_id[rid].get("investors") or []
        )
    }

    # ── step 1: rival backers, ranked by distinct rivals then mapped portfolio ──
    backers = {k for k, p in portfolio.items() if p & rival_ids}
    ranked = sorted(
        backers,
        key=lambda k: (-len(portfolio[k] & rival_ids), -len(portfolio[k]), label(k)),
    )
    anchors = [k for k in ranked if len(portfolio[k]) >= MIN_ANCHOR_PORTFOLIO]
    assert 5 <= len(anchors) <= 25, f"anchor cutoff produced {len(anchors)} rows"

    def backer_flag(k: str) -> str | None:
        owned = [
            rid for rid in portfolio[k] & rival_ids if canon(owner.get(rid, "\0")) == k
        ]
        if owned:
            return (
                f"owns {by_id[owned[0]]['name'].split(' (')[0]}, not an outside cheque"
            )
        return None

    rival_backers = [
        {
            "label": label(k),
            "nRivals": len(portfolio[k] & rival_ids),
            "rivals": ", ".join(
                sorted(by_id[r]["name"] for r in portfolio[k] & rival_ids)
            ),
            "portfolio": len(portfolio[k]),
            "flag": backer_flag(k),
        }
        for k in anchors
    ]

    # ── step 2: portfolio twins with zero rival exposure ────────────────────────
    # exclude name-string kin of any backer or acquirer, checked on RAW variants
    # ('Lightspeed' vs 'Lightspeed Venture Partners', 'NVentures (Nvidia)', 'Cisco
    # Investments') — free-text labels split one firm across several strings.
    backer_strings = {v.casefold() for k in backers for v in variants[k]} | backers

    def name_kin(k: str) -> bool:
        mine = {v.casefold() for v in variants[k]} | {k}
        return any(a in b or b in a for a in mine for b in backer_strings)

    candidates = [
        k
        for k in portfolio
        if k not in backers
        and MIN_CAND_PORTFOLIO <= len(portfolio[k]) <= MEGA_HUB
        and not name_kin(k)
    ]
    assert candidates, "no twin candidates survived the filters"

    best: dict[str, tuple[float, str, int]] = {}  # cand -> (cos, anchor, shared)
    for a in anchors:
        sims = sorted(
            ((cosine(portfolio[a], portfolio[c]), c) for c in candidates),
            key=lambda t: (-t[0], t[1]),
        )
        for s, c in [t for t in sims if t[0] > 0][:TWINS_PER_ANCHOR]:
            shared = len(portfolio[a] & portfolio[c])
            if c not in best or (s, shared) > (best[c][0], best[c][2]):
                best[c] = (s, a, shared)

    agg = sorted(
        best.items(),
        key=lambda kv: (-kv[1][0], -kv[1][2], -len(portfolio[kv[0]]), label(kv[0])),
    )[:MAX_UNCONTESTED]
    uncontested = []
    for c, (s, a, shared) in agg:
        assert 0.0 < s <= 1.0 and shared >= 1 and not (portfolio[c] & rival_ids)
        names = sorted(by_id[i]["name"] for i in portfolio[c] & portfolio[a])
        overlap = ", ".join(names[:3]) + (
            f" +{len(names) - 3}" if len(names) > 3 else ""
        )
        uncontested.append(
            {
                "label": label(c),
                "cosine": round(s, 3),
                "twin": label(a),
                "overlap": overlap,
                "portfolio": len(portfolio[c]),
            }
        )

    # ── bars: distinct mapped backers per rival (incl. acquirers; 0 is honest) ──
    per_rival = sorted(
        (
            {
                "id": rid,
                "label": by_id[rid]["name"],
                "value": sum(1 for p in portfolio.values() if rid in p),
            }
            for rid in rival_ids
        ),
        key=lambda r: (-r["value"], r["label"]),
    )
    assert all(r["id"] in by_id for r in per_rival)

    n_multi = sum(1 for k in backers if len(portfolio[k] & rival_ids) >= 2)
    multi_names = " and ".join(
        sorted(label(k) for k in backers if len(portfolio[k] & rival_ids) >= 2)
    )
    top = uncontested[0]

    payload = {
        "slug": "shared-investors",
        "graph": "companies",
        "title": "Follow the money",
        "sub": f"{len(backers)} funds already back our rivals — and the funds that invest like them but don't",
        "headline": (
            f"Mapped rival money is wide but shallow: <strong>{len(backers)} listed investors</strong> back "
            f"our 14 rivals, yet only {n_multi} ({multi_names}) hold more than one — and the "
            f"closest look-alike fund with no mapped rival position is {top['label']} "
            f"(similarity {top['cosine']:.2f} to {top['twin']}, {len((portfolio[canon(top['label'])] & portfolio[canon(top['twin'])]))} shared bets)."
        ),
        "prose": {
            "intro": (
                "<p>Fourteen companies on this map are flagged as direct competitors. Their investor "
                "lists are public evidence of who has already paid for agent red-teaming, and the map "
                f"records acquirers for {len(exited)} of the 14 — so this category demonstrably exits. "
                "Two lists fall out: the funds with proven appetite, and the funds that invest just "
                "like them but hold no rival position. The second list is a pitch list with no "
                "conflict the map can see.</p>"
            ),
            "how": (
                "<p>Treat each investor as a checklist over the 188 mapped companies: a mark for every "
                "company it backs. Two investors are similar when their checklists overlap — the same "
                "math behind “customers who bought X also bought Y.” For each proven rival-backer we "
                "find its nearest neighbors among investors holding zero rival positions. High "
                "similarity means overlapping bets, so the twin plausibly shares the investment thesis "
                "without the conflicting position. Investors with a single mapped company are excluded "
                f"(one shared deal is not a pattern), and funds with more than {MEGA_HUB} mapped "
                "companies would be excluded for being similar to everyone — today that excludes no "
                f"one (the largest mapped portfolio is {max(len(p) for p in portfolio.values())}).</p>"
            ),
            "method": (
                "<p>Bipartite investor×company incidence over the public map "
                f"({n_listed}/188 companies list investors; {len(portfolio)} distinct investors after "
                "canonicalizing free-text names by case and trailing parenthetical, so “Andreessen "
                "Horowitz (a16z)” folds onto “Andreessen Horowitz”). Twins: cosine similarity of "
                "L2-normalized binary rows — item-based collaborative filtering per Sarwar et al. "
                f"(WWW 2001). Anchors are the {len(anchors)} rival-backers with ≥{MIN_ANCHOR_PORTFOLIO} mapped "
                f"companies; candidates need {MIN_CAND_PORTFOLIO}–{MEGA_HUB} mapped companies, zero rival "
                "overlap, and no name-string kinship with any rival-backer or acquirer (this removes "
                "“Lightspeed” vs “Lightspeed Venture Partners”, “NVentures (Nvidia)”, “Cisco "
                "Investments”). Investor names are labels, not graph nodes; ties break by shared-deal "
                "count, then portfolio size, then name.</p>"
            ),
        },
        "caveat": (
            f"Investor lists cover {n_listed} of 188 companies and are free-text strings: near-duplicates "
            "like Samsung vs Samsung Next count separately, Adversa AI lists no investors at all, and "
            "“portfolio” means portfolio-on-this-map, not the fund's real book — the twins only see "
            "the slice of each fund that happens to be mapped here."
        ),
        "inputs": {"companies": stamp(companies)},
        "data": {
            "rivalBackers": rival_backers,
            "uncontested": uncontested,
            "backersPerRival": per_rival,
        },
    }
    emit(payload)


if __name__ == "__main__":
    main()
