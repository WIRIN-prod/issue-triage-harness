"""Controlled vocabulary mined from a repo's own structure.

The spike (DECISIONS.md D15) showed that matching issue text against arbitrary
tokens retrieves confident noise: an issue mentioning "result" and "errors" pulled
an unrelated module. The fix is to match only against terms the repo itself
defines — provider directories, integration directories, and the shipped model
catalogue — so a match means something rather than merely co-occurring.

Nothing here is hand-written litellm knowledge. Every term is derived from files
in the checkout, which is what lets the same code work on another repo that
happens to organise itself by directory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

TermKind = Literal["provider", "model", "integration", "module"]

# Terms that are real directory names but too generic to be evidence of anything.
# A match on "base" or "utils" tells you nothing about which issue you are reading.
GENERIC = {
    "base", "base_llm", "custom", "custom_llm", "main", "common", "common_utils",
    "utils", "types", "core", "shared", "default", "generic", "misc", "other",
    "handler", "handlers", "client", "clients", "server", "api", "apis", "lib",
    "src", "test", "tests", "docs", "doc", "example", "examples", "template",
    "chat", "text", "files", "batches", "audio", "image", "video", "embedding",
}

MIN_TERM_LEN = 3


class Term(BaseModel):
    text: str          # normalised surface form to match against issue text
    kind: TermKind
    target: str = ""   # repo-relative path prefix this term resolves to ("" = unresolved)
    weight: float = 1.0


class Vocabulary(BaseModel):
    repo: str
    commit: str
    terms: list[Term]

    def by_text(self) -> dict[str, Term]:
        return {t.text: t for t in self.terms}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _dir_terms(root: Path, rel: str, kind: TermKind) -> list[Term]:
    base = root / rel
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.iterdir()):
        if not p.is_dir() or p.name.startswith((".", "_")):
            continue
        name = p.name.lower()
        if name in GENERIC or len(name) < MIN_TERM_LEN:
            continue
        out.append(Term(text=_norm(name), kind=kind, target=f"{rel}/{p.name}", weight=2.0))
    return out


def _model_terms(root: Path, provider_targets: dict[str, str]) -> list[Term]:
    """Model names from the shipped price catalogue, each pointing at its provider.

    This is where aliasing comes from for free: "claude-sonnet-4" resolves to the
    anthropic module without anyone writing down that claude means anthropic.
    """
    catalogue = root / "model_prices_and_context_window.json"
    if not catalogue.is_file():
        return []
    data = json.loads(catalogue.read_text())

    out: list[Term] = []
    seen: set[str] = set()
    for name, meta in data.items():
        if name == "sample_spec" or not isinstance(meta, dict):
            continue
        provider = str(meta.get("litellm_provider", "")).lower()
        if not provider:
            continue
        # strip the "1024-x-1024/50-steps/" style prefixes and provider routing prefix
        bare = name.split("/")[-1]
        t = _norm(bare)
        if len(t) < 6 or t in seen or t in GENERIC:
            continue
        seen.add(t)
        # a long specific model id is strong evidence; a short one is not
        out.append(Term(
            text=t, kind="model",
            target=provider_targets.get(provider, ""),
            weight=3.0 if len(t) > 12 else 1.5,
        ))
    return out


def _module_terms(root: Path, pkg: str) -> list[Term]:
    base = root / pkg
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.iterdir()):
        name = p.stem.lower() if p.suffix == ".py" else p.name.lower()
        if name.startswith((".", "_")) or name in GENERIC or len(name) < MIN_TERM_LEN:
            continue
        if p.is_dir() or p.suffix == ".py":
            out.append(Term(text=_norm(name), kind="module",
                            target=f"{pkg}/{p.name}", weight=1.5))
    return out


class _ProviderResolver(dict):
    """dict-alike that resolves unseen provider ids by longest-prefix directory match."""

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def get(self, key, default=""):
        if key not in self:
            self[key] = self._fn(key)
        return self[key] or default


def build(root: Path, repo: str, commit: str, pkg: str = "litellm") -> Vocabulary:
    providers = _dir_terms(root, f"{pkg}/llms", "provider")
    integrations = _dir_terms(root, f"{pkg}/integrations", "integration")
    strategies = _dir_terms(root, f"{pkg}/router_strategy", "module")
    modules = _module_terms(root, pkg)

    provider_targets = {t.text.replace(" ", "_"): t.target for t in providers}
    # price-map provider ids that have no directory of their own (bedrock_converse
    # -> bedrock) fall back to the longest directory name that prefixes them
    dirs = sorted(provider_targets, key=len, reverse=True)

    def resolve(p: str) -> str:
        if p in provider_targets:
            return provider_targets[p]
        for d in dirs:
            if p.startswith(d):
                return provider_targets[d]
        return ""
    models = _model_terms(root, _ProviderResolver(resolve))

    terms: dict[str, Term] = {}
    for t in [*providers, *integrations, *strategies, *modules, *models]:
        # first writer wins: providers and integrations outrank model ids on collision
        terms.setdefault(t.text, t)
    return Vocabulary(repo=repo, commit=commit, terms=sorted(terms.values(), key=lambda t: t.text))
