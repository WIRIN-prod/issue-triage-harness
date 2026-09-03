"""Degenerate strategies, scored for free.

Every eval needs a floor. A config that cannot beat "guess the majority class" or
"escalate everything" has not earned its inference cost, and without these numbers on
the page a mediocre result reads as a good one.

On this dataset the floor is higher than intuition suggests. `needs_human` is 69%
positive and a missed escalation costs 10x an unnecessary one, so escalating
everything scores better than any other trivial policy — an honest consequence of the
cost model, and the bar a real config has to clear.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from triage.models import TriageDecision

from .dataset import Dataset
from .metrics import Scored, score

CATS = ("bug", "feature", "docs", "question", "security")
URGS = ("P0", "P1", "P2", "P3")


def _const(cat: str, urg: str, human: bool, n: int) -> list[TriageDecision]:
    return [TriageDecision(category=cat, urgency=urg, needs_human=human)] * n


def _random(n: int, seed: int = 20260903) -> list[TriageDecision]:
    rng = random.Random(seed)
    return [TriageDecision(category=rng.choice(CATS), urgency=rng.choice(URGS),
                           needs_human=rng.choice([True, False])) for _ in range(n)]


def _majority(gold: list[TriageDecision]) -> list[TriageDecision]:
    """The strongest trivial strategy: most common value of each field, independently."""
    from collections import Counter
    cat = Counter(g.category for g in gold).most_common(1)[0][0]
    urg = Counter(g.urgency for g in gold).most_common(1)[0][0]
    human = Counter(g.needs_human for g in gold).most_common(1)[0][0]
    return _const(cat, urg, human, len(gold))


@dataclass
class Baseline:
    name: str
    note: str
    scored: Scored


def evaluate(dataset: Dataset, split: str | None = None) -> list[Baseline]:
    items = dataset.split_items(split) if split else dataset.items
    gold = [i.gold for i in items]
    n = len(gold)
    strategies = [
        ("majority-per-field", "most common value of each field", _majority(gold)),
        ("escalate-everything", "always needs_human, majority elsewhere",
         _const("bug", "P2", True, n)),
        ("never-escalate", "never needs_human, majority elsewhere",
         _const("bug", "P2", False, n)),
        ("random", "uniform over every field", _random(n)),
        ("perfect", "the labels themselves", list(gold)),
    ]
    return [Baseline(name, note, score(list(zip(preds, gold)), [0.0] * n))
            for name, note, preds in strategies]


def render(baselines: list[Baseline], unit_usd: float = 1.0) -> str:
    hdr = (f"{'baseline':<22}{'macroF1':>9}{'acc':>7}{'urgMAE':>8}"
           f"{'nh_rec':>8}{'nh_prec':>9}{'err_wt':>8}{'$/issue':>10}")
    lines = [hdr, "-" * len(hdr)]
    for b in baselines:
        s = b.scored
        lines.append(
            f"{b.name:<22}{s.category['macro_f1']:>9.3f}{s.category['accuracy']:>7.2f}"
            f"{s.urgency['mae']:>8.2f}{s.needs_human['recall']:>8.2f}"
            f"{s.needs_human['precision']:>9.2f}{s.error_weight_per_issue:>8.2f}"
            f"{s.total_usd_per_issue(unit_usd):>10.3f}")
    floor = min((b for b in baselines if b.name != "perfect"),
                key=lambda b: b.scored.error_weight_per_issue)
    lines += ["", f"FLOOR: {floor.name} at {floor.scored.error_weight_per_issue:.2f} "
                  f"error weight/issue. A config that does not beat this has earned nothing."]
    return "\n".join(lines)
