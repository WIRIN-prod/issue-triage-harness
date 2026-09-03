"""Vocabulary-anchored retrieval over a graphify code graph.

Retrieval only fires on terms the repo defines (see vocab.py). If an issue names
nothing the repo knows about, this returns *empty context* rather than the
nearest-looking module. That is the whole point: the spike showed generic token
matching hands back confident, irrelevant code, and irrelevant context is worse
than none — it misleads the model and charges tokens to do it.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from .vocab import Term, Vocabulary

CHARS_PER_TOKEN = 4


class Match(BaseModel):
    text: str
    kind: str
    target: str
    weight: float


class Context(BaseModel):
    """What the retriever decided to hand the model, and why."""

    text: str                      # rendered block, "" when nothing matched
    matches: list[Match] = []
    modules: list[str] = []
    est_tokens: int = 0
    reason: str = ""               # populated when text is empty

    @property
    def is_empty(self) -> bool:
        return not self.text


class GraphIndex:
    """Loads a graphify extraction once and indexes it by source file.

    The graph is ~38MB for litellm; this is built once per process, never per issue.
    """

    def __init__(self, graph_path: Path, repo_root: str = ""):
        g = json.loads(Path(graph_path).read_text())
        self.repo_root = repo_root.rstrip("/") + "/" if repo_root else ""

        by_id = {n["id"]: n for n in g["nodes"]}
        docs: dict[str, str] = {}
        for e in g["edges"]:
            if e.get("relation") == "rationale_for":
                src = by_id.get(e["source"])
                if src and e["target"] not in docs:
                    docs[e["target"]] = src["label"]

        self.by_file: dict[str, list[dict]] = defaultdict(list)
        for n in g["nodes"]:
            if n.get("file_type") != "code":
                continue
            path = n.get("source_file", "")
            if self.repo_root and path.startswith(self.repo_root):
                path = path[len(self.repo_root):]
            n = {**n, "rel_path": path, "doc": docs.get(n["id"], "")}
            self.by_file[path].append(n)

        self.files = sorted(self.by_file)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


FENCE = re.compile(r"```.*?```", re.S)

# Where a term appears is evidence about how much it matters. A provider named in
# the title is what the issue is about; the same name inside a pasted config block
# is usually incidental — issue #39451 is about /v1/models, but a config listing
# Bedrock models outranked the actual subject before this weighting existed.
ZONE_WEIGHT = {"title": 3.0, "prose": 1.0, "code": 0.4}


def _zones(title: str, body: str) -> list[tuple[str, str]]:
    code = " ".join(FENCE.findall(body))
    prose = FENCE.sub(" ", body)
    return [("title", _norm(title)), ("prose", _norm(prose)), ("code", _norm(code))]


def match(vocab: Vocabulary, title: str, body: str = "") -> list[Match]:
    """Terms from the repo's own vocabulary that appear in the issue, weighted by where."""
    zones = [(z, f" {t} ", set(t.split())) for z, t in _zones(title, body)]
    out: list[Match] = []
    for t in vocab.terms:
        best = 0.0
        for zone, padded, tokens in zones:
            hit = t.text in padded if " " in t.text else t.text in tokens
            if hit:
                best = max(best, ZONE_WEIGHT[zone])
        if best:
            out.append(Match(text=t.text, kind=t.kind, target=t.target,
                             weight=t.weight * best))
    # a long specific match subsumes a short one it contains ("claude sonnet 4" vs "claude")
    out.sort(key=lambda m: (-len(m.text), -m.weight))
    kept: list[Match] = []
    for m in out:
        if not any(m.text in k.text and m.text != k.text for k in kept):
            kept.append(m)
    return kept


def retrieve(
    index: GraphIndex,
    vocab: Vocabulary,
    title: str,
    body: str,
    budget_tokens: int = 1500,
    max_modules: int = 3,
    max_files_per_module: int = 4,
) -> Context:
    text = f"{title}\n{body}"
    matches = match(vocab, title, body)
    resolved = [m for m in matches if m.target]

    if not resolved:
        return Context(
            text="", matches=matches, reason=(
                "no repo vocabulary matched — issue names no provider, integration, "
                "model or module this repo defines"
            ),
        )

    # rank modules by the evidence pointing at them
    scores: dict[str, float] = defaultdict(float)
    for m in resolved:
        scores[m.target] += m.weight
    modules = [t for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:max_modules]]

    # within a module, prefer files whose own name echoes the issue's wording
    issue_tokens = set(_norm(text).split())
    blocks: list[str] = []
    used = 0
    for mod in modules:
        cand = [f for f in index.files if f.startswith(mod)]
        ranked = sorted(
            cand,
            key=lambda f: -(len(issue_tokens & set(_norm(f).split())) * 2 + (f.count("/") == mod.count("/") + 1)),
        )[:max_files_per_module]
        lines = [f"### {mod}"]
        for f in ranked:
            nodes = index.by_file.get(f, [])
            documented = [n for n in nodes if n["doc"]][:2]
            names = [n["label"] for n in nodes if n["label"] and not n["label"].endswith(".py")][:6]
            entry = f"- {f}"
            if names:
                entry += f" — {', '.join(names)}"
            lines.append(entry)
            for n in documented:
                doc = " ".join(n["doc"].split())[:180]
                lines.append(f"    {n['label']}: {doc}")
        block = "\n".join(lines)
        cost = len(block) // CHARS_PER_TOKEN
        if used + cost > budget_tokens and blocks:
            break
        blocks.append(block)
        used += cost

    header = "Matched: " + ", ".join(f"{m.text} ({m.kind})" for m in resolved[:6])
    rendered = f"## Repo context — {vocab.repo} @ {vocab.commit}\n{header}\n\n" + "\n\n".join(blocks)
    return Context(
        text=rendered, matches=matches, modules=modules,
        est_tokens=len(rendered) // CHARS_PER_TOKEN,
    )
