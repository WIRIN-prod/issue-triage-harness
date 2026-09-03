"""Execute one config over the frozen dataset and persist the result.

A run record is `(dataset_hash, config_hash, git_sha) -> results`, reproducible by
construction (SPEC.md §5.7). Per-item outputs are kept, not just aggregates: totals
tell you *whether* something changed, per-item diffs tell you *where*, and only the
second suggests the next hypothesis.
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from graph.retrieve import GraphIndex, retrieve
from graph.vocab import Vocabulary
from pydantic import BaseModel, Field

from triage.agent import sampling_is_honoured, triage
from triage.config import TriageConfig
from triage.models import TriageDecision

from .dataset import Dataset, GoldItem


class ItemResult(BaseModel):
    issue_number: int
    predicted: TriageDecision
    gold: TriageDecision
    cost_usd: float
    cost_reported: bool = True
    tokens_in: int
    tokens_out: int
    latency_ms: int
    context_empty: bool
    context_tokens: int
    error: str = ""


class RunRecord(BaseModel):
    run_id: str
    config_name: str
    config_hash: str
    model: str
    prompt_version: str
    rationale_mode: str
    context_mode: str
    temperature: float
    temperature_applied: bool

    dataset_hash: str
    split: str
    repeat: int = 0

    git_sha: str
    timestamp: str
    items: list[ItemResult] = Field(default_factory=list)

    # --- views ---
    @property
    def ok(self) -> list[ItemResult]:
        return [i for i in self.items if not i.error]

    @property
    def failures(self) -> int:
        return sum(1 for i in self.items if i.error)

    @property
    def total_cost(self) -> float:
        return sum(i.cost_usd for i in self.items)

    def pairs(self) -> list[tuple[TriageDecision, TriageDecision]]:
        return [(i.predicted, i.gold) for i in self.ok]

    def save(self, root: Path) -> Path:
        path = root / f"{self.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=1))
        return path

    @classmethod
    def load(cls, path: Path) -> RunRecord:
        return cls(**json.loads(Path(path).read_text()))


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def run_config(
    dataset: Dataset,
    config: TriageConfig,
    index: GraphIndex,
    vocab: Vocabulary,
    split: str | None = None,
    repeat: int = 0,
    workers: int = 6,
    on_progress: Callable[[int, int], None] | None = None,
) -> RunRecord:
    items = dataset.split_items(split) if split else dataset.items
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record = RunRecord(
        run_id=f"{config.name}__{config.config_hash}__{split or 'all'}__r{repeat}__{stamp}",
        config_name=config.name, config_hash=config.config_hash, model=config.model,
        prompt_version=config.prompt_version, rationale_mode=config.rationale_mode,
        context_mode=config.context, temperature=config.temperature,
        temperature_applied=sampling_is_honoured(config.model),
        dataset_hash=dataset.content_hash(), split=split or "all", repeat=repeat,
        git_sha=_git_sha(), timestamp=stamp,
    )

    def one(item: GoldItem) -> ItemResult:
        ctx = retrieve(index, vocab, item.title, item.body,
                       budget_tokens=config.context_budget_tokens)
        run = triage(item.issue_number, item.title, item.body, config, ctx)
        return ItemResult(
            issue_number=item.issue_number, predicted=run.decision, gold=item.gold,
            cost_usd=run.cost_usd, cost_reported=run.cost_reported,
            tokens_in=run.tokens_in, tokens_out=run.tokens_out,
            latency_ms=run.latency_ms, context_empty=run.context_empty,
            context_tokens=run.context_tokens, error=run.error,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, i) for i in items]
        for n, f in enumerate(futures, 1):
            record.items.append(f.result())
            if on_progress:
                on_progress(n, len(futures))
    record.items.sort(key=lambda i: i.issue_number)
    return record
