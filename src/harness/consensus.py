"""Consensus labels from several independent labellers, and per-item disagreement.

Two label sets can tell you whether a *ranking* moves. They cannot tell you which
individual items are genuinely ambiguous, because with two raters a disagreement is
just a tie. Three allow a majority, which turns "the labellers disagree somewhere" into
"these specific items are contested, and here is how the results look without them".

The labellers must come from different lineages. Two models from the same family agreeing
is weak evidence — they can share a blind spot in a way independent raters would not.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from triage.models import URGENCY_RANK, TriageDecision

FIELDS = ("category", "urgency", "needs_human")


@dataclass
class ItemConsensus:
    issue_number: int
    consensus: TriageDecision
    unanimous: dict[str, bool]
    votes: dict[str, list]

    @property
    def fully_unanimous(self) -> bool:
        return all(self.unanimous.values())

    @property
    def contested_fields(self) -> list[str]:
        return [f for f, ok in self.unanimous.items() if not ok]


def _majority(values: list):
    """Most common value; ties fall back to the first labeller, which is the gold source."""
    counts = Counter(values)
    top = counts.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return values[0]
    return top[0][0]


def _median_urgency(values: list[str]) -> str:
    """Urgency is ordinal, so the median is the honest centre, not the mode."""
    ranks = sorted(URGENCY_RANK[v] for v in values)
    mid = ranks[len(ranks) // 2]
    return next(k for k, v in URGENCY_RANK.items() if v == mid)


def build(label_sets: list[dict[int, TriageDecision]],
          names: list[str]) -> dict[int, ItemConsensus]:
    if len(label_sets) < 3:
        raise ValueError("consensus needs at least three independent label sets")
    shared = set(label_sets[0])
    for s in label_sets[1:]:
        shared &= set(s)

    out: dict[int, ItemConsensus] = {}
    for n in sorted(shared):
        picks = [s[n] for s in label_sets]
        votes = {f: [getattr(p, f) for p in picks] for f in FIELDS}
        consensus = TriageDecision(
            category=_majority(votes["category"]),
            urgency=_median_urgency(votes["urgency"]),
            needs_human=_majority(votes["needs_human"]),
        )
        out[n] = ItemConsensus(
            issue_number=n, consensus=consensus,
            unanimous={f: len(set(votes[f])) == 1 for f in FIELDS},
            votes=votes,
        )
    return out


def render(cons: dict[int, ItemConsensus], names: list[str]) -> str:
    n = len(cons)
    L = [f"consensus over {len(names)} independent labellers: {', '.join(names)}",
         f"  {n} items\n"]
    for f in FIELDS:
        u = sum(1 for c in cons.values() if c.unanimous[f])
        L.append(f"  {f:<14} unanimous on {u}/{n} ({100*u//max(n,1)}%)")
    full = sum(1 for c in cons.values() if c.fully_unanimous)
    L.append(f"  {'all three':<14} unanimous on {full}/{n} ({100*full//max(n,1)}%)")

    contested = [c for c in cons.values() if not c.fully_unanimous]
    L += ["", f"contested items: {len(contested)} — genuinely ambiguous, not noise",
          "  (reporting metrics with and without these separates 'the config is wrong'",
          "   from 'the labellers could not agree what right was')"]
    for c in contested[:10]:
        bits = ", ".join(f"{f}: {'/'.join(map(str, c.votes[f]))}" for f in c.contested_fields)
        L.append(f"    #{c.issue_number:<7} {bits}")
    if len(contested) > 10:
        L.append(f"    ... and {len(contested)-10} more")
    return "\n".join(L)
