"""Shared helpers for the /networks/analyses compute scripts.

Every panel script imports from here: the two PUBLIC graph loaders (never the
private overlays), envelope validation + emission, and determinism helpers.
See CONTRACT.md for the full rules this module enforces.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT_DIR = REPO / "src" / "data" / "analyses"
DERIVED = HERE / "_derived"  # gitignored cache written by prep scripts

COMPANIES_PATH = REPO / "src" / "data" / "companies.json"
FUNDING_PATH = REPO / "src" / "data" / "funding.json"

GRAPHS = ("companies", "funding", "both")
PRIVATE_KEYS = ("warm_path", "stage", "notes")  # must never appear in output
ENVELOPE_KEYS = ("slug", "graph", "title", "sub", "headline", "prose", "inputs", "data")
SIZE_TARGET = 100_000
SIZE_HARD = 300_000


def load_companies() -> dict:
    d = json.loads(COMPANIES_PATH.read_text())
    assert d["companies"] and d["edges"], "companies.json empty?"
    return d


def load_funding() -> dict:
    d = json.loads(FUNDING_PATH.read_text())
    assert d["nodes"] and d["edges"], "funding.json empty?"
    return d


def company_ids(companies: dict) -> set[str]:
    return {c["id"] for c in companies["companies"]}


def funding_ids(funding: dict) -> set[str]:
    return {n["id"] for n in funding["nodes"]}


def stamp(graph_data: dict) -> dict:
    """Content fingerprint for the envelope `inputs` field (drift detection)."""
    if "companies" in graph_data:
        return {
            "nodes": len(graph_data["companies"]),
            "edges": len(graph_data["edges"]),
        }
    return {"nodes": len(graph_data["nodes"]), "edges": len(graph_data["edges"])}


def fix_signs(X):
    """Resolve SVD sign ambiguity: flip each column so its max-|loading| entry is
    positive. Makes embeddings byte-identical across re-runs."""
    import numpy as np

    X = np.asarray(X, dtype=float).copy()
    for j in range(X.shape[1]):
        k = int(np.argmax(np.abs(X[:, j])))
        if X[k, j] < 0:
            X[:, j] = -X[:, j]
    return X


def _walk(value: Any, path: str, node_ids: set[str], errs: list[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k in PRIVATE_KEYS:
                errs.append(f"{path}.{k}: private key in output")
            if k == "id" and isinstance(v, str) and v not in node_ids:
                errs.append(f"{path}.id: {v!r} not in source graphs")
            _walk(v, f"{path}.{k}", node_ids, errs)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk(v, f"{path}[{i}]", node_ids, errs)
    elif isinstance(value, float) and not math.isfinite(value):
        errs.append(f"{path}: non-finite float")


def emit(payload: dict) -> None:
    """Validate the envelope + data, minify, size-cap, write, print the OK line."""
    for k in ENVELOPE_KEYS:
        assert k in payload, f"envelope missing {k!r}"
    assert payload["graph"] in GRAPHS, f"bad graph {payload['graph']!r}"
    for k in ("intro", "how", "method"):
        assert (
            payload["prose"].get(k, "").startswith("<p>")
        ), f"prose.{k} must be <p> html"
    assert (
        "<strong>" in payload["headline"]
    ), "headline needs its key number in <strong>"
    assert re.match(r"^[a-z0-9-]+$", payload["slug"]), "slug must be kebab-case"
    assert (
        isinstance(payload["inputs"], dict) and payload["inputs"]
    ), "inputs stamps required"

    ids: set[str] = set()
    if payload["graph"] in ("companies", "both"):
        ids |= company_ids(load_companies())
    if payload["graph"] in ("funding", "both"):
        ids |= funding_ids(load_funding())
    errs: list[str] = []
    _walk(payload["data"], "data", ids, errs)
    assert not errs, "contract violations:\n  " + "\n  ".join(errs[:20])

    blob = json.dumps(
        payload, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )
    assert len(blob) < SIZE_HARD, f"{len(blob)}B exceeds hard cap {SIZE_HARD}"
    if len(blob) >= SIZE_TARGET:
        print(
            f"[{payload['slug']}] WARN {len(blob) / 1024:.0f}KB over the {SIZE_TARGET // 1000}KB target"
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{payload['slug']}.json").write_text(blob + "\n")
    headline_text = re.sub(r"<[^>]+>", "", payload["headline"])
    print(f"[{payload['slug']}] OK {len(blob) / 1024:.0f}KB — {headline_text}")
