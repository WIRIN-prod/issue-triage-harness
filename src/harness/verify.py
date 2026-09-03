"""Verification of the gold labels.

SPEC.md §5.4 asks for a human to check a stratified sample, because a model cannot
validate itself. Two distinct things live here and must not be confused in reporting:

  * **human verification** — a person labels the sample; kappa against the labeller is
    the real trust signal, and the only one that breaks the circularity.
  * **cross-model check** — a frontier model from a different lineage labels the same
    sample. Cheap and useful in one direction only: low agreement is strong evidence
    the labels are unreliable, high agreement is weak evidence they are fine, since two
    models can share a blind spot in a way a person would not.

The sample is stratified over gold categories. Twenty-five consecutive `bug` items
would estimate kappa for one class and say nothing about the rest.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from triage.models import TriageDecision

from .agreement import Agreement, compare_labels, disagreements
from .dataset import Dataset, GoldItem

VERIFIER = "x-ai/grok-4.6"     # different lineage from both labeller and configs


def sample(dataset: Dataset, n: int = 25, seed: int = 20260903) -> list[GoldItem]:
    rng = random.Random(seed)
    by_cat: dict[str, list[GoldItem]] = defaultdict(list)
    for item in dataset.items:
        by_cat[item.gold.category].append(item)
    for v in by_cat.values():
        rng.shuffle(v)

    chosen: list[GoldItem] = []
    order = sorted(by_cat, key=lambda c: len(by_cat[c]))   # scarcest class first
    while len(chosen) < n and any(by_cat[c] for c in order):
        for c in order:
            if by_cat[c] and len(chosen) < n:
                chosen.append(by_cat[c].pop())
    return sorted(chosen, key=lambda i: i.issue_number)


def export_for_human(items: list[GoldItem], jsonl: Path, markdown: Path) -> dict:
    """Write a template to fill in, and a readable version to label from.

    The gold label is deliberately **absent** from both. Showing it would anchor the
    verifier to the answer being checked, and the agreement number would measure
    compliance rather than independent judgement.
    """
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("w") as fh:
        for i in items:
            fh.write(json.dumps({
                "issue_number": i.issue_number,
                "decision": {"category": "", "urgency": "", "needs_human": None},
                "disputed": False,
            }) + "\n")

    lines = ["# Verification sample", "",
             "Label each issue against `docs/rubric.md`. Fill in the matching line in",
             f"`{jsonl.name}`. Gold labels are withheld on purpose — seeing them first would",
             "turn this into agreement-by-anchoring.", "",
             "Set `disputed: true` only where the rubric genuinely underdetermines the answer,",
             "not merely where the issue is low quality.", ""]
    for i in items:
        body = " ".join((i.body or "").split())[:700]
        lines += [f"## #{i.issue_number}", f"**{i.title}**", "",
                  f"{body}{'…' if len(i.body or '') > 700 else ''}", ""]
        if i.maintainer_labels:
            lines.append(f"_maintainer labels: {', '.join(i.maintainer_labels)}_\n")
        lines.append(f"<{i.url}>\n")
    markdown.write_text("\n".join(lines))
    return {"items": len(items), "jsonl": str(jsonl), "markdown": str(markdown)}


def load_external(path: Path) -> dict[int, tuple[TriageDecision, bool]]:
    out: dict[int, tuple[TriageDecision, bool]] = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        d = row["decision"]
        if not d.get("category") or not d.get("urgency") or d.get("needs_human") is None:
            continue        # unfilled template line
        out[int(row["issue_number"])] = (TriageDecision(**d), bool(row.get("disputed", False)))
    return out


def apply_verification(
    dataset: Dataset,
    verified: dict[int, tuple[TriageDecision, bool]],
    source: str,
) -> tuple[Dataset, list[Agreement], list[dict]]:
    """Record the second opinion on the dataset and report agreement.

    The gold label is **not** overwritten. A disagreement is evidence about label
    quality, not proof the verifier was right — so both opinions are kept and the
    conflict is flagged, which is what `disputed` exists for.
    """
    items = {i.issue_number: i for i in dataset.items}
    pairs_gold, pairs_other, numbers = [], [], []
    for n, (decision, disputed) in verified.items():
        item = items.get(n)
        if item is None:
            continue
        item.verified = True
        item.human_label = decision
        if disputed:
            item.disputed = True
        pairs_gold.append(item.gold)
        pairs_other.append(decision)
        numbers.append(n)

    agreements = compare_labels(pairs_gold, pairs_other) if pairs_gold else []
    diffs = disagreements(pairs_gold, pairs_other, numbers)
    return dataset, agreements, diffs
