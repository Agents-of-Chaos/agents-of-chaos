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
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "experiments" / "networks" / "raw" / "companies_raw.json"
OUT = ROOT / "src" / "data" / "companies.json"

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
        c = {
            "id": cid,
            "name": r["name"],
            "vertical": vert,
            "blurb": (r.get("blurb") or "").strip(),
            "intensity": intensity,
            "confidence": r.get("confidence", "medium"),
        }
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

    # ---- validate output (mirrors src/data/companies.ts + the leakage guard) ----
    ids = {c["id"] for c in companies}
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
