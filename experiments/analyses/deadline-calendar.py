# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""deadline-calendar — every open funding door at the snapshot, ranked by
SVD-embedding fit to AoC-shaped grantees, with the dated deadlines laid out
as a calendar. Run: cd experiments/analyses && uv run deadline-calendar.py
"""

import re
from datetime import date
from urllib.parse import urlparse

import numpy as np
from _shared import emit, fix_signs, load_funding, stamp
from scipy.stats import spearmanr

SEED_TAGS = {"agent-security", "evals", "multi-agent"}  # AoC's lane
ENERGY = 0.90  # keep the smallest rank holding >=90% of squared Frobenius energy
ZERO_NORM = 1e-9  # below this, a funder has no position in the truncated space
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
MONTHS_FULL = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def human(iso: str, snap_year: int) -> str:
    """'2026-08-08' -> 'Aug 8' (year appended only if it differs from the snapshot's)."""
    d = date.fromisoformat(iso)
    s = f"{MONTHS[d.month - 1]} {d.day}"
    return s if d.year == snap_year else f"{s} {d.year}"


def door_text(f: dict) -> str:
    """Short 'what to apply to' from apply notes, else the site host."""
    raw = (f["apply"].get("notes") or "").strip()
    if raw:
        m = re.search(
            r"\bOpen(?: now)?:\s*(.+)", raw
        )  # skip past closed-round preambles
        segs = [s.strip() for s in (m.group(1) if m else raw).split(";")]
        seg = segs[0]
        if seg.lower().startswith("no open application") and len(segs) > 1:
            seg = segs[1]  # the actionable clause follows the disclaimer
        seg = seg.rstrip(".")
        if seg.count("(") > seg.count(")"):  # clause split stranded a parenthetical
            seg = seg[: seg.rindex("(")].rstrip(" ,—-")
        if len(seg) > 76:
            seg = seg[:75].rsplit(" ", 1)[0].rstrip(" ,—-") + "…"
            if seg.count("(") > seg.count(")"):
                seg = seg[: seg.rindex("(")].rstrip(" ,—-") + "…"
        return seg
    url = f["apply"].get("url")
    if url:
        return urlparse(url).netloc.removeprefix("www.")
    return "see funder"


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    funders = [n for n in funding["nodes"] if n["kind"] == "funder"]
    grantees = [n for n in funding["nodes"] if n["kind"] == "grantee"]
    assert len(funders) >= 30 and len(grantees) >= 30, "graph shrank suspiciously"

    snap = funding["meta"]["generatedAt"]  # the data's 'today' — never wall clock
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", snap), snap
    snap_d = date.fromisoformat(snap)

    # ── which doors are open at the snapshot ─────────────────────────────────
    # rolling = open horizon; rounds need a live deadline; a rolling program
    # that publishes a hard close (ONR's Long Range BAA) is treated as dated.
    open_funders: list[dict] = []
    for f in funders:
        a = f["apply"]
        assert a["mode"] in ("rolling", "rounds", "invite-only", "closed"), a["mode"]
        dl = a.get("deadline")
        if dl is not None and date.fromisoformat(dl) < snap_d:
            continue  # deadline already passed at the snapshot
        if a["mode"] == "rolling" or (a["mode"] == "rounds" and dl):
            f["_days"] = (date.fromisoformat(dl) - snap_d).days if dl else None
            open_funders.append(f)
    n_open = len(open_funders)
    dated = sorted(
        (f for f in open_funders if f["_days"] is not None),
        key=lambda f: (f["_days"], f["id"]),
    )
    assert n_open >= 10, f"suspiciously few open doors: {n_open}"
    assert dated, "no dated deadlines at all?"
    assert all(0 <= f["_days"] <= 365 for f in dated), "deadline out of range"
    max_days = max(f["_days"] for f in dated)

    # ── the money matrix: funders x grantees, log10 dollars ─────────────────
    fid_ix = {n["id"]: i for i, n in enumerate(funders)}
    gid_ix = {n["id"]: i for i, n in enumerate(grantees)}
    money = [e for e in funding["edges"] if e["type"] in ("grant", "investment")]
    assert all(
        nodes[e["source"]]["kind"] == "funder"
        and nodes[e["target"]]["kind"] == "grantee"
        for e in money
    ), "money edge not funder->grantee"
    # regrants: SFF edges are paid by Jaan Tallinn but the s-process taste is
    # SFF's, so they stay on the SFF row. No payer has duplicate direct edges
    # for the same grants — assert, so nothing is counted twice.
    payers = {e["regrantOf"] for e in money if e.get("regrantOf")}
    for p in payers:
        direct = {e["target"] for e in money if e["source"] == p}
        regranted = {e["target"] for e in money if e.get("regrantOf") == p}
        assert not direct & regranted, f"double-counted regrant via {p}"

    floor = min(e["amountUSD"] for e in money if e.get("amountUSD") is not None)
    assert 0 < floor < 1e6, f"implausible floor {floor}"
    n_null_amt = sum(1 for e in money if e.get("amountUSD") is None)

    dollars = np.zeros((len(funders), len(grantees)))
    for e in money:
        dollars[fid_ix[e["source"]], gid_ix[e["target"]]] += e.get("amountUSD") or floor
    A = np.log10(dollars + 1.0)
    assert int((A.sum(1) > 0).sum()) >= 20, "too few funders with money edges"

    # ── SVD embedding + AoC profile ──────────────────────────────────────────
    U, S, Vt = np.linalg.svd(A, full_matrices=False)
    energy = np.cumsum(S**2) / (S**2).sum()
    d = int(np.searchsorted(energy, ENERGY) + 1)
    assert 2 <= d <= 20, f"odd embedding rank d={d}"

    seeds = sorted(
        (g for g in grantees if set(g.get("domainTags") or []) & SEED_TAGS),
        key=lambda g: g["id"],
    )
    assert len(seeds) >= 5, f"only {len(seeds)} seed grantees"

    def fit_at(rank: int) -> dict[str, float]:
        Ud, Vd = U[:, :rank].copy(), Vt[:rank].T.copy()
        U2 = fix_signs(Ud)  # deterministic sign convention from the left factor…
        signs = np.sign((U2 * Ud).sum(axis=0))
        assert set(np.unique(signs)) <= {-1.0, 1.0}
        XL = U2 * np.sqrt(S[:rank])
        XR = (Vd * signs) * np.sqrt(
            S[:rank]
        )  # …applied jointly so XL@XR.T is preserved
        prof = XR[[gid_ix[s["id"]] for s in seeds]].mean(axis=0)
        pn = float(np.linalg.norm(prof))
        assert pn > 1e-6, "seed profile collapsed to zero"
        out: dict[str, float] = {}
        for f in funders:
            x = XL[fid_ix[f["id"]]]
            nx = float(np.linalg.norm(x))
            assert not (ZERO_NORM < nx < 1e-3), f"ambiguous tiny norm for {f['id']}"
            if nx > ZERO_NORM:
                c = float(x @ prof / (nx * pn))
                assert -1.0001 <= c <= 1.0001, c
                out[f["id"]] = c
        return out

    fit = fit_at(d)
    rhos = {}
    for alt in (d - 2, d + 2):
        f_alt = fit_at(alt)
        common = sorted(set(fit) & set(f_alt))
        rhos[alt] = float(
            spearmanr([fit[k] for k in common], [f_alt[k] for k in common]).statistic
        )
        assert rhos[alt] > 0.8, f"fit unstable vs d={alt}: rho={rhos[alt]}"

    # ── the action list: scored by fit, then unscored dated, then isolated ──
    def row(f: dict) -> dict:
        cs = f.get("checkSizeUSD")
        flags = []
        n_edges = int((dollars[fid_ix[f["id"]]] > 0).sum())
        n_und = sum(
            1 for e in money if e["source"] == f["id"] and e.get("amountUSD") is None
        )
        if f["id"] not in fit:
            flags.append(
                "no tracked money edges — unscored"
                if n_edges == 0
                else "portfolio isolated in the embedding — unscored"
            )
        elif n_edges == 1:
            only = [e for e in money if e["source"] == f["id"]]
            tgt = nodes[only[0]["target"]]["name"]
            if len(only) == 1:
                kind_word = "grant" if only[0]["type"] == "grant" else "investment"
                flags.append(
                    f"fit rests on one {'undisclosed ' if n_und else ''}{kind_word} ({tgt})"
                )
            else:
                flags.append(f"fit rests on a single counterparty ({tgt})")
        elif n_und:
            flags.append(f"{n_und} amount{'s' if n_und > 1 else ''} undisclosed")
        return {
            "id": f["id"],
            "label": f["name"],
            "kind": f["funderKind"],
            "closes": human(f["apply"]["deadline"], snap_d.year)
            if f["_days"] is not None
            else "rolling",
            "days": f["_days"],
            "door": door_text(f),
            "checkMid": round((cs["min"] + cs["max"]) / 2) if cs else None,
            "fit": round(fit[f["id"]], 3) if f["id"] in fit else None,
            "flag": "; ".join(flags) if flags else None,
        }

    scored = sorted(
        (f for f in open_funders if f["id"] in fit),
        key=lambda f: (-fit[f["id"]], f["id"]),
    )
    unscored_dated = [f for f in dated if f["id"] not in fit]
    isolated = sorted(
        (
            f
            for f in open_funders
            if f["id"] not in fit
            and f["_days"] is None
            and dollars[fid_ix[f["id"]]].sum() > 0
        ),
        key=lambda f: f["id"],
    )
    table = [row(f) for f in scored + unscored_dated + isolated]
    n_omitted = n_open - len(table)
    assert len(table) <= 25, f"table too long: {len(table)}"
    assert {f["id"] for f in dated} <= {r["id"] for r in table}, "a dated door fell off"
    assert n_omitted >= 0

    # ── calendar staircase: doors still open vs days from the snapshot ──────
    day_counts: dict[int, int] = {}
    for f in dated:
        day_counts[f["_days"]] = day_counts.get(f["_days"], 0) + 1
    horizon = max(90, max_days + 3)
    xs, ys = [0], [n_open]
    remaining = n_open
    for dd in sorted(day_counts):
        xs += [dd, dd]
        ys += [remaining, remaining - day_counts[dd]]
        remaining -= day_counts[dd]
    xs.append(horizon)
    ys.append(remaining)
    assert remaining == n_open - len(dated)

    # annotate the busiest day (ties -> earliest); note when it is one shared form
    busy = min(day_counts, key=lambda k: (-day_counts[k], k))
    busy_funders = [f for f in dated if f["_days"] == busy]
    busy_date = human(busy_funders[0]["apply"]["deadline"], snap_d.year)
    one_form = len({f["apply"]["url"] for f in busy_funders}) == 1
    if len(busy_funders) > 1:
        annotate_txt = f"{busy_date} — {len(busy_funders)} doors" + (
            ", one application" if one_form else ""
        )
    else:
        annotate_txt = f"{busy_date} — {busy_funders[0]['name']}"

    # ── headline: best-fit dated door + how many doors are live ─────────────
    dated_fit = [f for f in dated if f["id"] in fit]
    assert dated_fit, "no dated door has a fit score"
    best = max(dated_fit, key=lambda f: fit[f["id"]])
    multi = (
        f", and {len(busy_funders)} of the {len(dated)} dates are a single "
        f"{busy_date} multi-agent application"
        if len(busy_funders) > 1 and one_form
        else ""
    )
    headline = (
        f"{len(dated)} of the <strong>{n_open} open doors</strong> on the funding map "
        f"close on a date, every one inside the next {max_days} days — the best-fit "
        f"dated door is {best['name']} (fit {fit[best['id']]:.2f}, closes "
        f"{human(best['apply']['deadline'], snap_d.year)}){multi}."
    )

    snap_h = f"{MONTHS_FULL[snap_d.month - 1]} {snap_d.day}, {snap_d.year}"
    n_no_edge = sum(1 for f in open_funders if dollars[fid_ix[f["id"]]].sum() == 0)
    best_flag_bits = [r for r in table if r["id"] == best["id"]]
    payload = {
        "slug": "deadline-calendar",
        "graph": "funding",
        "title": "The deadline calendar",
        "sub": f"{n_open} open doors ranked by portfolio fit; {len(dated)} dated deadlines inside {max_days} days",
        "headline": headline,
        "prose": {
            "intro": (
                f"<p>Agents of Chaos needs first money, and funders' doors do not stay open. "
                f"At the {snap_h} snapshot, {n_open} of the map's {len(funders)} funders will "
                f"take an application — {n_open - len(dated)} on rolling intake, {len(dated)} "
                f"with hard dates, every one of those dates inside the next {max_days} days. "
                f"Which doors do we walk through, and in what order?</p>"
            ),
            "how": (
                "<p>Most of this panel is a plain join, not a statistical model: for every "
                "funder whose door is open at the snapshot, the deadline, program, and check "
                "size are read straight off the graph's application metadata. The one computed "
                "column is fit. We factor the funder-by-grantee money matrix the way a "
                "recommender factors users-by-items: an SVD gives every funder and every "
                f"grantee a position in the same {d}-dimensional taste space, where two "
                "funders sit close when their dollars flow to the same kinds of grantees. We "
                f"average the positions of the {len(seeds)} grantees already doing AoC-shaped "
                "work — agent security, evals, multi-agent — into one profile, and score each "
                "open funder by the cosine between its position and that profile. Cosine keeps "
                "the direction of a funder's taste and throws away its size, so a small fund "
                "concentrated on our lane outranks a giant that touches it incidentally.</p>"
            ),
            "method": (
                f"<p>Open door: apply.mode = rolling, or rounds with deadline ≥ "
                f"meta.generatedAt ({snap}); one rolling program (ONR's Long Range BAA) "
                f"publishes a hard close and is treated as dated. Fit: truncated SVD "
                f"(numpy.linalg.svd) of the {len(funders)}×{len(grantees)} funder-by-grantee "
                f"matrix, cell = log10(dollars+1) summed over grant and investment edges; the "
                f"{n_null_amt} of {len(money)} edges with undisclosed amounts enter at the "
                f"minimum disclosed grant (${floor:,.0f}). Rank d={d} is the smallest holding "
                f"≥{ENERGY:.0%} of squared Frobenius energy; Spearman ρ of fit against d={d - 2} "
                f"and d={d + 2} is {rhos[d - 2]:.2f} and {rhos[d + 2]:.2f}. Positions U√Σ "
                f"(funders) and V√Σ (grantees) share one deterministic sign convention "
                f"(fix_signs on U, the same flips applied to V); profile = unweighted mean of "
                f"the seed positions; fit = cosine. SFF's regrants (payer: Jaan Tallinn) stay "
                f"on the SFF row — the s-process taste is what you apply to — and no payer "
                f"duplicates them as direct edges, so no dollar is counted twice. Funders with "
                f"no money edges, or whose only edges are invisible to the top {d} components, "
                f"are shown unscored rather than imputed.</p>"
            ),
        },
        "caveat": (
            f"{n_no_edge} of the {n_open} open doors have no tracked money edges, so fit "
            f"cannot be computed; the {len(unscored_dated)} dated ones stay in the table "
            f"unscored, and the other {n_omitted} (mostly VCs and new programs) appear only "
            f"on the minimap. {len(isolated)} more funders hold a single investment no other "
            f"funder shares, which the truncated embedding cannot see — also unscored. "
            + (
                f"For the best-fit dated door ({best['name']}), the "
                f"{best_flag_bits[0]['flag']}. "
                if best_flag_bits
                and (best_flag_bits[0]["flag"] or "").startswith("fit rests")
                else ""
            )
            + "Led-round investment amounts are round totals, not the fund's own check."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "actionList": table,
            "calendar": {
                "x": xs,
                "xLabel": f"days after the snapshot ({snap})",
                "series": [{"label": "doors open", "y": ys}],
                "annotate": {"x": busy, "text": annotate_txt},
            },
            "doors": [
                {
                    "id": f["id"],
                    "label": f["name"],
                    "kind": f["funderKind"],
                    "status": "dated" if f["_days"] is not None else "rolling",
                    "days": f["_days"],
                }
                for f in sorted(open_funders, key=lambda f: f["id"])
            ],
            "seeds": [{"id": s["id"], "label": s["name"]} for s in seeds],
        },
    }
    emit(payload)

    # eyeball table for the run log
    print(f"    snapshot={snap}  d={d}  seeds={len(seeds)}  rho={rhos}")
    print(f"    dated: {[(r['id'], r['_days']) for r in dated]}")
    for i, r in enumerate(table, 1):
        print(
            f"    {i:2d}. {r['label'][:30]:30s} {r['closes']:>8s} "
            f"fit={r['fit'] if r['fit'] is not None else '   —'} "
            f"{('FLAG: ' + r['flag']) if r['flag'] else ''}"
        )


if __name__ == "__main__":
    main()
