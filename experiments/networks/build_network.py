#!/usr/bin/env python3
"""Assemble the /networks public dataset from the research-swarm output.

Reads   experiments/networks/raw/companies_raw.json  (the Workflow result:
        {"companies": [...enriched+verified records...], ...})
Writes  src/data/companies.json                       (public: companies + edges)

Edges are DERIVED here, not authored:
  - business     : from each company's relationships of type built-on/partner/
                   customer (built-on/customer are directed source->target).
  - competitor   : from relationships of type competitor.
  - shared-investor : a pair sharing an investor, but ONLY for investors that
                   back a SMALL set (<= SHARED_INV_CAP) in our data — a mega-fund
                   like a16z would otherwise turn the map into a hairball; its
                   portfolio still shows in each company's dossier.

Stdlib only (no deps). Fails LOUD on bad data — better here than in the browser.
Run:  python3 experiments/networks/build_network.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from functools import lru_cache
from itertools import combinations, zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "experiments" / "networks" / "raw" / "companies_raw.json"
OUT = ROOT / "src" / "data" / "companies.json"
# canonical "what they do" taxonomy: {vertical: [{key,label,isBuyer,what}]}. Baked
# into companies.json meta so the directory view groups without a second source.
SUBCATS = ROOT / "experiments" / "networks" / "subcategories.json"
# empirical edge audit of the top-priority nodes (websites + web search): confirm
# existing ties (→ solid) and add newly-found ones. Optional; skipped if absent.
EDGE_AUDIT = ROOT / "experiments" / "networks" / "edge_audit.json"

VERTICALS = {
    "frontier-lab",
    "agent-native-startup",
    "bank-fintech",
    "healthcare",
    "security-eval-vendor",
    "investor-vc",
    "infra-platform",
    "enterprise-other",
}
PRIVATE_KEYS = {
    "warm_path",
    "stage",
    "notes",
    "priority",
}  # must NEVER reach the public file
SHARED_INV_CAP = (
    4  # investors backing more than this don't get pairwise edges (hairball guard)
)


# relationship type -> (edge type, directed). label defaults to the rtype itself.
RTYPE_MAP = {
    "competitor": ("competitor", False),
    "built-on": ("business", True),
    "customer": ("business", True),
    "partner": ("business", False),
}


@lru_cache(maxsize=None)
def slug(s: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


@lru_cache(maxsize=None)
def norm(s: str) -> str:
    """loose key for matching relationship targets to companies"""
    s = s.lower()
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|the|ai|labs?|technologies)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def main() -> int:
    if not RAW.exists():
        sys.exit(f"missing {RAW} — save the swarm result there first")
    payload = json.loads(RAW.read_text())
    records = payload["companies"] if isinstance(payload, dict) else payload
    assert isinstance(records, list) and records, "no company records found"

    subcats = json.loads(SUBCATS.read_text())["subcategories"]
    assert set(subcats) == VERTICALS, "subcategories.json must cover every vertical"
    # fail loud on malformed taxonomy metadata (better here than a silently
    # mis-scoped "likely customers" lens in the browser)
    for v, items in subcats.items():
        assert items, f"{v}: no sub-categories"
        keys = [s["key"] for s in items]
        assert len(keys) == len(set(keys)), f"{v}: duplicate sub-category keys"
        for s in items:
            assert {"key", "label", "isBuyer"} <= set(
                s
            ), f"{v}/{s.get('key')}: missing key/label/isBuyer"
            assert isinstance(
                s["isBuyer"], bool
            ), f"{v}/{s['key']}: isBuyer must be a bool"
    subcat_keys = {v: {s["key"] for s in items} for v, items in subcats.items()}

    # ---- companies: dedupe by id, validate ----
    companies: list[dict] = []
    by_id: dict[str, dict] = {}
    norm_to_id: dict[str, str] = {}
    dupes = 0
    for r in records:
        cid = slug(r["name"])
        if not cid:
            continue
        if cid in by_id:
            dupes += 1
            # merge investors so a shared-investor signal isn't lost on the dupe
            inv = set(by_id[cid].get("investors", [])) | set(r.get("investors") or [])
            by_id[cid]["investors"] = sorted(inv)
            continue
        vert = r["vertical"]
        assert vert in VERTICALS, f"{r['name']}: bad vertical {vert!r}"
        intensity = int(r.get("intensity", 0))
        assert 0 <= intensity <= 5, f"{r['name']}: intensity {intensity} out of range"
        sub = r.get("subcategory")
        assert sub, f"{r['name']}: missing subcategory"
        assert (
            sub in subcat_keys[vert]
        ), f"{r['name']}: subcategory {sub!r} not in {vert} taxonomy"
        c = {
            "id": cid,
            "name": r["name"],
            "vertical": vert,
            "subcategory": sub,
            "blurb": (r.get("blurb") or "").strip(),
            "intensity": intensity,
            "confidence": r.get("confidence", "medium"),
        }
        # cross-cutting: a direct competitor of Agents of Chaos (red-teaming vendors
        # sit in several sub-categories, so this is a flag, not a bucket).
        if r.get("competitor"):
            c["competitor"] = True
        for opt in ("url", "buyer_persona", "trigger"):
            if r.get(opt):
                c[opt] = r[opt].strip()
        if r.get("investors"):
            c["investors"] = sorted(
                {i.strip() for i in r["investors"] if i and i.strip()}
            )
        companies.append(c)
        by_id[cid] = c
        norm_to_id.setdefault(norm(r["name"]), cid)

    def resolve(name: str) -> str | None:
        cid = slug(name)
        if cid in by_id:
            return cid
        return norm_to_id.get(norm(name))

    # ---- edges ----
    edges: list[dict] = []
    seen_edges: set[tuple] = set()

    def add_edge(
        s: str, t: str, etype: str, label: str, directed: bool, verified: bool
    ) -> None:
        if s == t:
            return
        key = (frozenset((s, t)), etype)  # one line per pair per type
        if key in seen_edges:
            return
        seen_edges.add(key)
        e = {"source": s, "target": t, "type": etype, "verified": bool(verified)}
        if label:
            e["label"] = label
        if directed:
            e["directed"] = True
        edges.append(e)

    # business + competitor, from relationships
    for r in records:
        s = resolve(r["name"])
        if not s:
            continue
        for rel in r.get("relationships") or []:
            t = resolve(rel.get("target_name", ""))
            if not t:
                continue  # only draw ties between companies we actually plot
            rtype = rel.get("type")
            cfg = RTYPE_MAP.get(rtype)
            if cfg:
                etype, directed = cfg
                add_edge(
                    s,
                    t,
                    etype,
                    rel.get("note") or rtype,
                    directed,
                    rel.get("verified", False),
                )

    # shared-investor, capped to avoid mega-fund hairballs
    inv_to_companies: dict[str, list[str]] = {}
    for c in companies:
        for inv in c.get("investors", []):
            inv_to_companies.setdefault(inv.lower().strip(), []).append(c["id"])
    for inv, cids in inv_to_companies.items():
        cids = sorted(set(cids))
        if 2 <= len(cids) <= SHARED_INV_CAP:
            for a, b in combinations(cids, 2):
                add_edge(a, b, "shared-investor", f"shared: {inv}", False, True)

    # ---- apply the empirical edge audit (top-priority nodes) ----
    # confirm: flip a matching edge to verified (solid). add: a new, sourced tie.
    ids = {c["id"] for c in companies}
    if EDGE_AUDIT.exists():
        audit = json.loads(EDGE_AUDIT.read_text())
        edge_by_key = {
            (frozenset((e["source"], e["target"])), e["type"]): e for e in edges
        }
        n_conf = 0
        for c in audit.get("confirm", []):
            e = edge_by_key.get((frozenset((c["a"], c["b"])), c["type"]))
            if e and c["a"] in ids and c["b"] in ids:
                if not e["verified"]:
                    n_conf += 1
                e["verified"] = True
        n_before = len(edges)
        for a in audit.get("add", []):
            if a["source"] in ids and a["target"] in ids:
                add_edge(
                    a["source"],
                    a["target"],
                    a["type"],
                    a.get("note", ""),
                    a.get("directed", False),
                    True,
                )
        print(f"  edge audit: {n_conf} confirmed→solid, {len(edges) - n_before} added")

    # ---- priority: "what should AoC learn about first" (drives the /networks bar) ----
    # Interleave the top potential CUSTOMERS with the direct COMPETITORS, 1:1, so
    # the ranking spans both market and competition. Ranked 1..N (lower = higher
    # priority); Agents of Chaos itself is 0 (the anchor, always shown).
    buyer = {(v, s["key"]): s["isBuyer"] for v, items in subcats.items() for s in items}
    deg: Counter = Counter()
    for e in edges:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    maxdeg = max(deg.values(), default=1) or 1

    def central(c: dict) -> float:
        return deg[c["id"]] / maxdeg

    def is_customer(c: dict) -> bool:
        return c["intensity"] >= 4 and buyer.get(
            (c["vertical"], c["subcategory"]), False
        )

    def cust_score(c: dict) -> float:
        base = c["intensity"] / 5 if is_customer(c) else 0.0
        return base * 0.75 + 0.25 * central(c)  # customer/hub claim on attention

    def comp_score(c: dict) -> float:
        return 0.6 + 0.4 * central(c)  # competitor claim, graded by centrality

    pool = [c for c in companies if c["id"] != "agents-of-chaos"]
    customers = sorted(
        (c for c in pool if not c.get("competitor")),
        key=lambda c: (-cust_score(c), -c["intensity"], c["id"]),
    )
    rivals = sorted(
        (c for c in pool if c.get("competitor")),
        key=lambda c: (-comp_score(c), -c["intensity"], c["id"]),
    )
    interleaved = [c for pair in zip_longest(customers, rivals) for c in pair if c]
    # NB: field is priorityRank, NOT "priority" — "priority" is a PRIVATE overlay key
    # (CRM), guarded against leaking into the public file.
    for rank, c in enumerate(interleaved, 1):
        c["priorityRank"] = rank
    for c in companies:
        if c["id"] == "agents-of-chaos":
            c["priorityRank"] = 0  # us — the anchor, always shown regardless of the bar

    # ---- validate output (mirrors src/data/companies.ts + the leakage guard) ----
    ids = {c["id"] for c in companies}
    prios = [c["priorityRank"] for c in companies if c["id"] != "agents-of-chaos"]
    assert set(prios) == set(
        range(1, len(companies))
    ), "priorityRank must be a unique 1..N-1"
    assert len(ids) == len(companies), "duplicate company ids in output"
    for c in companies:
        assert not (
            PRIVATE_KEYS & set(c)
        ), f"{c['id']}: private key leaked into public company!"
    for e in edges:
        assert e["source"] in ids and e["target"] in ids, f"dangling edge {e}"
        assert e["source"] != e["target"], f"self-loop {e}"

    by_vert = dict(Counter(c["vertical"] for c in companies))

    out = {
        "meta": {
            "generated": "build_network.py",
            "source": "research swarm (discover → enrich → verify)",
            "n_companies": len(companies),
            "n_edges": len(edges),
            "by_vertical": by_vert,
            "subcategories": subcats,
        },
        "companies": companies,
        "edges": edges,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    # ---- report (terse, informative) ----
    et = dict(Counter(e["type"] for e in edges))
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  companies: {len(companies)}  (merged {dupes} dupes)")
    print(f"  by vertical: {by_vert}")
    print(f"  edges: {len(edges)}  {et}")
    unverified = sum(1 for e in edges if not e["verified"])
    print(f"  edges unverified (drawn dashed): {unverified}")
    low = sum(1 for c in companies if c["confidence"] == "low")
    print(f"  low-confidence companies: {low}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
