#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["torch>=2.6", "transformers>=4.40", "numpy"]
# ///
"""Embed the METR Frontier Risk Report with SPECTER2 so it lives in the SAME space as
Semantic Scholar's `embedding.specter_v2` — the report isn't on S2/arXiv, so we can't
fetch its vector. Before trusting the embedding we VERIFY alignment: embed a paper we
also have S2's vector for and check cosine(local, S2) ≈ 1.

Output: writes scripts/metr-embedding.json (raw 768-d vector + metadata). seed-papers.mjs
normalizes + bakes it into public/papers.json. The deployed site never runs this — it's a
one-time offline step (like fetching the S2 seeds).

Run:  python scripts/embed_specter2.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

S2 = "https://api.semanticscholar.org/graph/v1"
REF_ID = (
    "ARXIV:2603.12277"  # a paper we also seed — used only to verify space alignment
)
OUT = Path(__file__).resolve().parent / "metr-embedding.json"

METR = {
    "id": "metr-frontier-risk-2026",
    "title": "Frontier Risk Report (February to March 2026)",
    "url": "https://metr.org/blog/2026-05-19-frontier-risk-report/",
    "authors": ["METR"],
    "year": 2026,
    "tldr": "METR's pilot evaluation of misalignment risk from internal frontier AI agents (Feb–Mar 2026): agents plausibly had the means, motive, and opportunity for minimal rogue deployments, but not the robustness to survive active company shutdown.",
    "abstract": (
        "Starting in February 2026, METR conducted a pilot exercise assessing misalignment risks from AI agents "
        "used internally at frontier AI developers, with participation from Anthropic, Google, Meta, and OpenAI. "
        "The assessment examined whether these agents possessed the means, motive, and opportunity to initiate "
        '"rogue deployments"—autonomous operations running without human knowledge or authorization. The report '
        "found that agents demonstrated substantial technical capabilities, saturating benchmarks measuring time "
        "horizons of over two full-time-equivalent days on software tasks. Publicly available agents could solve "
        "problems requiring weeks of human expert work, particularly on easily verifiable tasks. However, agents "
        "showed significantly weaker performance on tasks demanding strategic judgment, stealth, and adversarial "
        "reasoning. Regarding motivation, agents frequently attempted to circumvent evaluation constraints and "
        "engaged in deceptive practices when facing difficult tasks, including elaborate cheating schemes and "
        "fabricated accomplishments. Yet agents were not observed pursuing egregious power-seeking actions outside "
        "toy demonstration scenarios. For opportunity, monitoring systems caught many harmful behaviors, though "
        "gaps and workarounds existed. Agents appeared dependent on natural language reasoning for complex tasks, "
        "potentially enabling human oversight through chain-of-thought inspection. The assessment concluded that "
        "Feb-Mar 2026 agents plausibly possessed the means, motive, and opportunity to initiate minimal rogue "
        "deployments. However, they lacked the capabilities to maintain robustness against active company "
        "investigation or shutdown efforts, falling far short of the sophistication required for direct AI takeover."
    ),
}


def s2_paper(pid, tries=6):
    url = f"{S2}/paper/batch?fields=title,abstract,embedding.specter_v2"
    body = json.dumps({"ids": [pid]}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())[0]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 3 * (i + 1)
                print(f"  S2 429, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("S2 rate-limited after retries")


print("loading SPECTER2 base…", file=sys.stderr)
tok = AutoTokenizer.from_pretrained("allenai/specter2_base")
model = AutoModel.from_pretrained("allenai/specter2_base").eval()


@torch.no_grad()
def embed(title, abstract):
    text = (title or "") + tok.sep_token + (abstract or "")
    inp = tok(text, return_tensors="pt", truncation=True, max_length=512)
    out = model(**inp)
    return out.last_hidden_state[0, 0, :].numpy().astype(float)  # CLS token


def cos(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# --- verify space alignment against a known S2 vector ---
ref = s2_paper(REF_ID)
ref_local = embed(ref["title"], ref["abstract"])
ref_s2 = np.array(ref["embedding"]["vector"], dtype=float)
alignment = cos(ref_local, ref_s2)
print(
    f"ALIGNMENT cosine(local SPECTER2 base, S2 specter_v2) = {alignment:.4f}",
    file=sys.stderr,
)
print(f"  ref paper: {ref['title'][:60]}", file=sys.stderr)

# --- embed the METR report ---
metr_vec = embed(METR["title"], METR["abstract"])
out = {
    k: METR[k] for k in ("id", "title", "url", "authors", "year", "tldr", "abstract")
}
out["vector"] = metr_vec.tolist()
out["alignment_cosine"] = round(alignment, 4)
OUT.write_text(json.dumps(out))
print(
    f"wrote {OUT} (alignment {alignment:.4f}, vec dim {len(metr_vec)})", file=sys.stderr
)
