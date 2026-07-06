# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///
"""funder-shortlist — deterministic grant-fit scoring over the funding map's funders (no
graph model): mission x check-fit x door-openness x recency, every weight
visible. Run: cd experiments/analyses && uv run funder-shortlist.py
"""

import math
import statistics

import numpy as np
from _shared import emit, load_funding, stamp

TAGS_FULL = {"agent-security", "evals"}  # weight 1.0 — AoC's own lane
TAGS_HALF = {"technical-alignment"}  # weight 0.5 — adjacent
ASK_LO, ASK_HI = 100_000, 1_000_000  # AoC's first-money ask range
LAM = 0.5  # recency decay; sensitivity vs 1.0
TOP_N = 12
APPLY_SCORE = {"rolling": 1.0, "invite-only": 0.4, "closed": 0.0}
ROUNDS_NO_DEADLINE = 0.7  # recurring windows exist but you must wait


def tag_weight(tags: list[str]) -> float:
    """Relevance of one grantee: best matching tag wins."""
    if set(tags) & TAGS_FULL:
        return 1.0
    if set(tags) & TAGS_HALF:
        return 0.5
    return 0.0


def tag_share(tags: list[str]) -> float:
    """Fallback mission for funders with no tracked grants: mean weight of
    their DECLARED tags — reads as 'share of declared focus that is AoC-shaped'."""
    assert tags, "funder without domainTags"
    return sum(
        1.0 if t in TAGS_FULL else 0.5 if t in TAGS_HALF else 0.0 for t in tags
    ) / len(tags)


def check_fit(cmin: float, cmax: float) -> float:
    """Log-overlap of the funder's check range with the ask range, normalized
    by the (log) length of the ask range. Full coverage = 1."""
    lo, hi = max(cmin, ASK_LO), min(cmax, ASK_HI)
    if hi <= lo:
        return 0.0
    return math.log10(hi / lo) / math.log10(ASK_HI / ASK_LO)


def fmt_usd(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:g}B"
    if x >= 1e6:
        return f"${x / 1e6:g}M"
    if x >= 1e3:
        return f"${x / 1e3:g}k"
    return f"${x:g}"


def main() -> None:
    funding = load_funding()
    nodes = {n["id"]: n for n in funding["nodes"]}
    funders = [n for n in funding["nodes"] if n["kind"] == "funder"]
    assert len(funders) >= 10, f"suspiciously few funders: {len(funders)}"

    # funder→grantee money edges (grants + the 2 VC investments)
    money = [e for e in funding["edges"] if nodes[e["source"]]["kind"] == "funder"]
    assert all(nodes[e["target"]]["kind"] == "grantee" for e in money)
    assert len(money) >= 20, f"suspiciously few funder→grantee edges: {len(money)}"

    dated = [e for e in money if e.get("year") is not None]
    NOW = max(e["year"] for e in dated)  # data-derived "now" — never wall clock
    assert 2020 <= NOW <= 2100, f"implausible NOW={NOW}"
    global_med_amount = statistics.median(
        e["amountUSD"] for e in money if e.get("amountUSD") is not None
    )
    global_med_year = statistics.median(e["year"] for e in dated)
    # reference date for "is this deadline still open" — newest apply.lastVerified
    ref_date = max(f["apply"]["lastVerified"] for f in funders)
    assert len(ref_date) == 10 and ref_date[4] == "-", ref_date

    disclosed_checks = [f["checkSizeUSD"] for f in funders if f.get("checkSizeUSD")]
    imp_cmin = float(np.percentile([c["min"] for c in disclosed_checks], 25))
    imp_cmax = float(np.percentile([c["max"] for c in disclosed_checks], 25))
    assert imp_cmin < imp_cmax

    by_funder: dict[str, list[dict]] = {f["id"]: [] for f in funders}
    for e in money:
        by_funder[e["source"]].append(e)

    rows = []
    for f in funders:
        fid = f["id"]
        edges = by_funder[fid]
        flags: list[str] = []

        # ── imputation pools ────────────────────────────────────────────────
        amounts = [e["amountUSD"] for e in edges if e.get("amountUSD") is not None]
        years = [e["year"] for e in edges if e.get("year") is not None]
        med_amount = statistics.median(amounts) if amounts else global_med_amount
        med_year = statistics.median(years) if years else global_med_year
        n_imputed = sum(1 for e in edges if e.get("amountUSD") is None)
        if edges and n_imputed:
            flags.append(f"{n_imputed}/{len(edges)} grant amounts undisclosed")

        # ── (1) mission: share of log1p-weighted dollars into AoC-shaped grantees
        if edges:
            w = [math.log1p(e.get("amountUSD") or med_amount) for e in edges]
            rel = [tag_weight(nodes[e["target"]]["domainTags"]) for e in edges]
            mission = sum(r * x for r, x in zip(rel, w)) / sum(w)
        elif f.get("domainTags"):
            mission = tag_share(f["domainTags"])
            flags.append("no tracked grants — mission from declared tags")
        else:
            mission = 0.0
            flags.append("no tracked grants, no declared focus — mission 0")

        # ── (2) check fit vs the $100k–$1M ask ─────────────────────────────
        cs = f.get("checkSizeUSD")
        if cs:
            cmin, cmax = cs["min"], cs["max"]
        else:
            cmin, cmax = imp_cmin, imp_cmax
            flags.append("check size imputed (p25 of disclosed)")
        fit = check_fit(cmin, cmax)

        # ── (3) door openness ───────────────────────────────────────────────
        mode = f["apply"]["mode"]
        if mode == "rounds":
            deadline = f["apply"].get("deadline")
            ready = 1.0 if (deadline and deadline > ref_date) else ROUNDS_NO_DEADLINE
        else:
            ready = APPLY_SCORE[mode]

        # ── (4) recency: decayed dollars, imputed fields flagged ────────────
        rec = {}
        for lam in (LAM, 1.0):
            rec[lam] = sum(
                (e.get("amountUSD") or med_amount)
                * math.exp(-lam * (NOW - (e.get("year") or med_year)))
                for e in edges
            )
        if edges and any(e.get("year") is None for e in edges):
            flags.append("grant year imputed (median)")

        assert 0 <= mission <= 1 and 0 <= fit <= 1 and 0 <= ready <= 1
        rows.append(
            {
                "id": fid,
                "label": f["name"],
                "kind": f["funderKind"],
                "mission": mission,
                "fit": fit,
                "ready": ready,
                "rec": rec,
                "check": f"{fmt_usd(cmin)}–{fmt_usd(cmax)}",
                "apply": mode,
                "lastActive": max(years) if years else None,
                "flag": "; ".join(flags) if flags else None,
            }
        )

    # scale recency to [0,1] on log1p dollars, per λ; composite gated by openness
    comp = {}
    for lam in (LAM, 1.0):
        top = max(math.log1p(r["rec"][lam]) for r in rows)
        assert top > 0
        for r in rows:
            r[f"recs{lam}"] = math.log1p(r["rec"][lam]) / top
        comp[lam] = [
            r["ready"] * (0.5 * r["mission"] + 0.25 * r["fit"] + 0.25 * r[f"recs{lam}"])
            for r in rows
        ]
    from scipy.stats import spearmanr

    rho = float(spearmanr(comp[LAM], comp[1.0]).statistic)
    assert rho > 0.9, f"λ sweep should barely move ranks, got ρ={rho}"

    for r, c in zip(rows, comp[LAM]):
        r["score"] = c
    rows.sort(key=lambda r: (-r["score"], r["id"]))
    n_flagged = sum(1 for r in rows[:TOP_N] if r["flag"])
    top = rows[0]
    assert top["ready"] == 1.0 and top["score"] > 0.5

    shortlist = [
        {
            "id": r["id"],
            "label": r["label"],
            "kind": r["kind"].replace("-", " "),
            "mission": round(r["mission"], 3),
            "check": r["check"],
            "apply": r["apply"],
            "lastActive": r["lastActive"],
            "score": round(r["score"], 3),
            "flag": r["flag"],
        }
        for r in rows[:TOP_N]
    ]

    # field dollars per year — dated AND dollar-stamped edges only
    stamped = [e for e in dated if e.get("amountUSD") is not None]
    assert stamped
    per_year: dict[int, float] = {}
    for e in stamped:
        per_year[e["year"]] = per_year.get(e["year"], 0.0) + e["amountUSD"]
    by_year = [
        {"label": str(y), "value": round(v)} for y, v in sorted(per_year.items())
    ]
    assert (
        abs(sum(r["value"] for r in by_year) - sum(e["amountUSD"] for e in stamped)) < 1
    )

    # several funders share exactly (0, 1.0) etc — seeded jitter keeps the dots apart
    rng = np.random.default_rng(0)
    quadrant = [
        {
            "id": r["id"],
            "label": r["label"],
            "x": round(r[f"recs{LAM}"] + rng.uniform(-0.018, 0.018), 4),
            "y": round(r["mission"] + rng.uniform(-0.018, 0.018), 4),
            "group": r["kind"],
        }
        for r in rows
    ]
    assert len(quadrant) == len(funders)

    n_no_grants = sum(1 for r in rows if r["rec"][LAM] == 0)
    n_funders = len(funders)
    n_untracked = sum(1 for f in funders if not by_funder[f["id"]])
    n_no_check = sum(1 for f in funders if not f.get("checkSizeUSD"))
    n_missing_both = sum(
        1 for e in money if e.get("amountUSD") is None and e.get("year") is None
    )
    payload = {
        "slug": "funder-shortlist",
        "graph": "funding",
        "title": "The short list",
        "sub": f"{n_funders} funders scored on mission, check size, open doors, recency",
        "headline": (
            f"<strong>{top['label']}</strong> tops the shortlist — "
            f"{round(100 * top['mission'])}% of its log-weighted grant dollars already go to "
            f"AoC-shaped work, its checks span {top['check']}, and the door is open ({top['apply']})."
        ),
        "prose": {
            "intro": (
                "<p>Agents of Chaos will soon ask for first money — roughly $100k–$1M in grants. The "
                f"funding map holds {n_funders} funders. Which door do we knock on first? This panel is "
                "a plain scoring rubric, not a graph model: four factors, every weight visible.</p>"
            ),
            "how": (
                "<p>Each funder gets four scores between 0 and 1. <em>Mission</em>: the share of its "
                "grant dollars that go to agent-security or evals work (log-dollars, so one $30M "
                "mega-grant counts as attention, not a thousand small grants). <em>Check fit</em>: how "
                "much of our $100k–$1M ask its published check sizes cover. <em>Openness</em>: rolling "
                "or open-deadline programs score 1, invite-only 0.4, closed 0. <em>Recency</em>: recent "
                "grant dollars count far more than old ones (half-life about 1.4 years). The composite "
                "multiplies openness against a mission-heavy blend of the rest, so a perfect-fit funder "
                "you cannot apply to scores zero — by design.</p>"
            ),
            "method": (
                "<p>Deterministic scoring, no fitted model. Mission: Σ rel(g)·log1p($) / Σ log1p($) over "
                "each funder's grant edges, rel = 1.0 if the grantee's domainTags hit {agent-security, "
                "evals}, 0.5 for {technical-alignment}, else 0 — the half-weight marks alignment work as "
                "adjacent to, not identical with, AoC's red-teaming lane. Funders with no tracked grants "
                f"({n_untracked} of {n_funders}) fall back to the mean tag-weight of their own declared "
                "domainTags, flagged. Undisclosed amounts → the funder's median disclosed grant, else "
                f"the global median ({fmt_usd(global_med_amount)}); missing years → median year; missing "
                f"check sizes ({n_no_check} of {n_funders}) → the 25th percentile of disclosed minima and "
                f"maxima ({fmt_usd(imp_cmin)}–{fmt_usd(imp_cmax)}), all flagged. Check fit is the "
                "log-scale overlap with [$100k, $1M]. Openness: rolling = 1, rounds with a deadline "
                "past the newest apply.lastVerified in the data = 1, rounds without a stated window = 0.7, "
                f"invite-only = 0.4, closed = 0. Recency: Σ $·exp(−λ·({NOW}−year)) with λ=0.5 and {NOW} = "
                "max year in the data (never wall clock), rescaled by log1p to [0,1]; re-ranking at λ=1.0 "
                f"gives Spearman ρ={rho:.3f}, so the decay choice barely moves the list. "
                "Composite = openness × (0.5·mission + 0.25·check + 0.25·recency). The quadrant "
                "dots carry ±0.018 seeded jitter so funders with identical scores stay visible as "
                "separate dots.</p>"
            ),
        },
        "caveat": (
            f"Only {n_funders - n_untracked} of {n_funders} funders have grants tracked in this graph — "
            f"the other {n_untracked} are scored on declared focus areas with zero recency "
            f"({n_no_grants} funders sit at recency 0). {n_missing_both} of {len(money)} money edges "
            f"lack both amount and year; {n_no_check} of {n_funders} funders publish no check size. "
            f"Every imputation is flagged in the table ({n_flagged} of the top {TOP_N} rows carry flags)."
        ),
        "inputs": {"funding": stamp(funding)},
        "data": {
            "shortlist": shortlist,
            "byYear": {"rows": by_year},
            "quadrant": quadrant,
        },
    }
    emit(payload)

    # eyeball table for the run log
    print(f"    ρ(λ=0.5 vs 1.0)={rho:.3f}   NOW={NOW}   ref_date={ref_date}")
    for i, r in enumerate(rows[:TOP_N], 1):
        print(
            f"    {i:2d}. {r['label'][:34]:34s} {r['kind']:12s} "
            f"score={r['score']:.3f} mission={r['mission']:.2f} fit={r['fit']:.2f} "
            f"ready={r['ready']:.1f} rec={r[f'recs{LAM}']:.2f} "
            f"{('FLAG: ' + r['flag']) if r['flag'] else ''}"
        )


if __name__ == "__main__":
    main()
