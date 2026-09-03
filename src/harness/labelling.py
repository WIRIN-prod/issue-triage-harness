"""Two-stage labelling: a cheap pass to stratify, a frontier pass to label.

Stratification needs approximate labels for the whole pool, but it is a *sampling
aid*, not ground truth — so it does not need frontier quality (DECISIONS.md D18).
Labelling all 991 candidates at frontier quality would cost roughly ten times more
for labels discarded the moment sampling finishes.

The labeller sees exactly what the service sees, repo context included. If gold
labels were produced without context while the service had it, a better-informed
config would score *worse* for knowing more than the referee (DECISIONS.md D2).
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Callable, Protocol

from graph.retrieve import Context, GraphIndex, retrieve
from graph.vocab import Vocabulary
from triage.agent import triage
from triage.config import TriageConfig
from triage.models import TriageDecision

from .dataset import Dataset, GoldItem, rubric_fingerprint
from .github import Issue


class TooManyFailures(RuntimeError):
    """Raised rather than quietly building a dataset out of the survivors.

    A labelling run that loses 80% of its calls to transient errors still produces a
    file that hashes cleanly and looks like a dataset. That is the exact failure this
    project exists to catch, so a thinned run is an error, not a smaller result.
    """


@dataclass
class LabelResult:
    issue_number: int
    decision: TriageDecision
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    context_empty: bool = True
    context_tokens: int = 0
    error: str = ""


class Labeller(Protocol):
    name: str

    def label(self, issue: Issue, context: Context | None) -> LabelResult: ...


@dataclass
class ModelLabeller:
    """Labels via OpenRouter. Reproducible: same config, same dataset, re-runnable."""

    config: TriageConfig

    @property
    def name(self) -> str:
        return self.config.model

    def label(self, issue: Issue, context: Context | None) -> LabelResult:
        run = triage(issue.number, issue.title, issue.body, self.config, context)
        return LabelResult(
            issue_number=issue.number,
            decision=run.decision,
            cost_usd=run.cost_usd,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            context_empty=run.context_empty,
            context_tokens=run.context_tokens,
            error=run.error,
        )


@dataclass
class FileLabeller:
    """Labels supplied out-of-band — by a human, or by an agent session.

    Free, but not reproducible: nobody can re-run the labelling pass to check it.
    Acceptable for the human *verification* sample, where that is the point;
    a weak choice for the bulk gold pass, where re-runnability is the point.
    """

    path: Path
    name: str = "file"
    _cache: dict[int, TriageDecision] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for line in Path(self.path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            self._cache[int(row["issue_number"])] = TriageDecision(**row["decision"])

    def label(self, issue: Issue, context: Context | None) -> LabelResult:
        d = self._cache.get(issue.number)
        if d is None:
            return LabelResult(issue.number, TriageDecision(
                category="question", urgency="P3", needs_human=True),
                error="no label supplied for this issue")
        return LabelResult(
            issue.number, d,
            context_empty=(context is None or context.is_empty),
            context_tokens=(context.est_tokens if context else 0),
        )


class LabelCache:
    """Append-only checkpoint of successful labels, keyed by issue and config.

    Written as each call returns, not at the end. A run that fails the success-rate
    guard once discarded 86 good frontier labels and $1.10 with them; with a
    checkpoint, a re-run pays only for what is still missing. Failures are
    deliberately not cached — they are exactly what a re-run should retry.
    """

    def __init__(self, path: Path, config_hash: str):
        self.path = Path(path)
        self.config_hash = config_hash
        self._hits: dict[int, LabelResult] = {}
        self._lock = Lock()
        if self.path.is_file():
            for line in self.path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("config_hash") != config_hash:
                    continue          # a different config means different labels
                self._hits[int(row["issue_number"])] = LabelResult(
                    issue_number=int(row["issue_number"]),
                    decision=TriageDecision(**row["decision"]),
                    cost_usd=row.get("cost_usd", 0.0),
                    tokens_in=row.get("tokens_in", 0),
                    tokens_out=row.get("tokens_out", 0),
                    context_empty=row.get("context_empty", True),
                    context_tokens=row.get("context_tokens", 0),
                )

    def __len__(self) -> int:
        return len(self._hits)

    def get(self, issue_number: int) -> LabelResult | None:
        return self._hits.get(issue_number)

    def put(self, result: LabelResult) -> None:
        if result.error:
            return
        with self._lock:
            self._hits[result.issue_number] = result
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps({
                    "config_hash": self.config_hash,
                    "issue_number": result.issue_number,
                    "decision": result.decision.model_dump(),
                    "cost_usd": result.cost_usd,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "context_empty": result.context_empty,
                    "context_tokens": result.context_tokens,
                }) + "\n")


# --- passes ---------------------------------------------------------------


def _contexts(issues: list[Issue], index: GraphIndex, vocab: Vocabulary,
              budget: int) -> dict[int, Context]:
    return {i.number: retrieve(index, vocab, i.title, i.body, budget_tokens=budget)
            for i in issues}


def run_pass(
    issues: list[Issue],
    labeller: Labeller,
    contexts: dict[int, Context],
    workers: int = 6,
    on_progress: Callable[[int, int], None] | None = None,
    cache: LabelCache | None = None,
) -> list[LabelResult]:
    # `if cache` would be False for an empty cache, since LabelCache defines
    # __len__ — and an empty cache is exactly the fresh run that most needs writing.
    cached = {i.number: cache.get(i.number) for i in issues} if cache is not None else {}
    todo = [i for i in issues if not cached.get(i.number)]

    def one(issue: Issue) -> LabelResult:
        res = labeller.label(issue, contexts.get(issue.number))
        if cache is not None:
            cache.put(res)
        return res

    fresh: list[LabelResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, i) for i in todo]
        for n, f in enumerate(futures, 1):
            fresh.append(f.result())
            if on_progress:
                on_progress(n, len(futures))

    by_num = {r.issue_number: r for r in fresh}
    return [cached.get(i.number) or by_num[i.number] for i in issues]


def select_stratified(
    results: list[LabelResult],
    n: int,
    seed: int = 20260903,
) -> tuple[list[int], dict[str, int]]:
    """Fill category x urgency cells as evenly as the pool allows.

    Random sampling would return ~2 security issues and ~2 P0s — cells where no metric
    can move except by noise, and the cells that matter most (SPEC.md §5.4). Rarest
    cells are drawn from first so scarce classes are not crowded out by bugs.
    """
    rng = random.Random(seed)
    cells: dict[str, list[int]] = defaultdict(list)
    for r in results:
        if r.error:
            continue
        cells[f"{r.decision.category}/{r.decision.urgency}"].append(r.issue_number)
    for v in cells.values():
        rng.shuffle(v)

    chosen: list[int] = []
    order = sorted(cells, key=lambda k: len(cells[k]))   # scarcest first
    while len(chosen) < n and any(cells[k] for k in order):
        for k in order:
            if cells[k] and len(chosen) < n:
                chosen.append(cells[k].pop())
    taken = defaultdict(int)
    lookup = {r.issue_number: r for r in results}
    for num in chosen:
        d = lookup[num].decision
        taken[f"{d.category}/{d.urgency}"] += 1
    return chosen, dict(sorted(taken.items()))


def assign_splits(numbers: list[int], dev_frac: float = 0.6, seed: int = 20260903) -> dict[int, str]:
    """Dev/holdout, not train/test — nothing is trained (DECISIONS.md D13).

    The split governs what *the developer* may look at: iterate on dev, decide on
    holdout. Shuffled with a fixed seed so the assignment is reproducible.
    """
    rng = random.Random(seed)
    shuffled = list(numbers)
    rng.shuffle(shuffled)
    cut = int(len(shuffled) * dev_frac)
    return {**{n: "dev" for n in shuffled[:cut]},
            **{n: "holdout" for n in shuffled[cut:]}}


def error_summary(results: list[LabelResult]) -> dict[str, int]:
    """Group by class *and* HTTP status. "ModelHTTPError: 13" is not actionable;
    knowing whether those were 429s or 402s is the whole diagnosis."""
    import re

    counts: dict[str, int] = {}
    for r in results:
        if not r.error:
            continue
        key = r.error.split(":")[0].strip() or "unknown"
        if m := re.search(r"status_code:?\s*(\d{3})", r.error):
            key = f"{key}/{m.group(1)}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def build_dataset(
    issues: list[Issue],
    gold: list[LabelResult],
    labeller_name: str,
    repo: str,
    commit: str,
    graph_sha256: str,
    window: str,
    rubric_path: Path,
    min_success_rate: float = 0.95,
) -> Dataset:
    ok = [g for g in gold if not g.error]
    rate = len(ok) / len(gold) if gold else 0.0
    if rate < min_success_rate:
        raise TooManyFailures(
            f"only {len(ok)}/{len(gold)} labels succeeded ({rate:.0%}); "
            f"minimum is {min_success_rate:.0%}. Errors: {error_summary(gold)}. "
            f"Building a dataset from the survivors would produce a file that hashes "
            f"cleanly and is silently a fifth of the intended size."
        )
    by_num = {i.number: i for i in issues}
    splits = assign_splits([g.issue_number for g in gold if not g.error])
    version, digest = rubric_fingerprint(rubric_path)
    items = []
    for g in gold:
        if g.error:
            continue
        iss = by_num[g.issue_number]
        items.append(GoldItem(
            issue_number=iss.number, title=iss.title, body=iss.body, url=iss.url,
            maintainer_labels=iss.labels, gold=g.decision, labeller=labeller_name,
            split=splits[g.issue_number],
            context_empty=g.context_empty, context_tokens=g.context_tokens,
        ))
    return Dataset(
        repo=repo, commit=commit, graph_sha256=graph_sha256,
        rubric_version=version, rubric_sha256=digest,
        labeller=labeller_name, window=window, items=items,
    )


def estimate_cost(issues: list[Issue], contexts: dict[int, Context],
                  price_in: float, price_out: float,
                  prompt_tokens: int, out_tokens: int = 120) -> dict:
    """Rough spend before committing to it. Prices are $/M tokens."""
    tin = sum(
        prompt_tokens
        + min(len(i.body), 6000) // 4
        + len(i.title) // 4
        + (contexts[i.number].est_tokens if i.number in contexts else 0)
        for i in issues
    )
    tout = out_tokens * len(issues)
    return {
        "issues": len(issues),
        "est_tokens_in": tin,
        "est_tokens_out": tout,
        "est_usd": round(tin / 1e6 * price_in + tout / 1e6 * price_out, 4),
    }
