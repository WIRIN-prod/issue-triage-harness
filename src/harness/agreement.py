"""Inter-rater agreement — the number that says whether labels can be trusted.

Raw percent agreement lies when a class dominates: two raters who both answer "bug"
every time agree 50% of the time on this dataset by chance alone. Cohen's kappa
corrects for that. Roughly: <0.40 poor, 0.40-0.60 moderate, 0.60-0.80 substantial,
>0.80 strong.

Kappa is also the *ceiling*. If two careful raters only agree 0.70 on urgency, a model
scoring 0.75 is at the noise floor of an ambiguous task rather than underperforming —
which is what tells you when to stop optimising.

Urgency uses linear-weighted kappa: it is ordinal, so P0-vs-P3 must count as a worse
disagreement than P0-vs-P1, exactly as in the error model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from triage.models import URGENCY_RANK, TriageDecision


@dataclass
class Agreement:
    field: str
    n: int
    observed: float          # raw percent agreement
    expected: float          # agreement expected by chance
    kappa: float | None      # None when undefined: one class used, no variance to correct for
    weighted: bool = False

    @property
    def reading(self) -> str:
        k = self.kappa
        if k is None:
            return "undefined — both raters used a single class"
        if k < 0.0: return "worse than chance"
        if k < 0.40: return "poor"
        if k < 0.60: return "moderate"
        if k < 0.80: return "substantial"
        return "strong"

    def line(self) -> str:
        tag = " (linear-weighted)" if self.weighted else ""
        k = "   n/a " if self.kappa is None else f"{self.kappa:+.3f}"
        return (f"{self.field:<16} n={self.n:<4} observed={self.observed:.2f}  "
                f"chance={self.expected:.2f}  kappa={k}  {self.reading}{tag}")


def _kappa(a: Sequence, b: Sequence, weights=None) -> tuple[float, float, float]:
    n = len(a)
    labels = sorted(set(a) | set(b))
    idx = {l: i for i, l in enumerate(labels)}

    def w(x, y) -> float:
        # unweighted: credit only for an exact match. Returning 1.0 unconditionally
        # made observed agreement 1.00 for every pair, which the sanity check caught.
        return (1.0 if x == y else 0.0) if weights is None else weights(x, y)

    observed = sum(w(x, y) for x, y in zip(a, b)) / n
    ca = {l: sum(1 for x in a if x == l) / n for l in labels}
    cb = {l: sum(1 for x in b if x == l) / n for l in labels}
    expected = sum(ca[x] * cb[y] * w(x, y) for x in labels for y in labels)
    # With a single class in play, chance agreement is 1.0 and kappa is 0/0 —
    # undefined, not zero. Reporting 0.0 there would read as "poor agreement"
    # for two raters who agreed on everything.
    kappa = (observed - expected) / (1 - expected) if expected < 1 - 1e-12 else None
    return observed, expected, kappa


def _urgency_weight(x: str, y: str) -> float:
    """Linear disagreement weight: full credit for exact, partial for near misses."""
    return 1.0 - abs(URGENCY_RANK[x] - URGENCY_RANK[y]) / 3.0


def compare_labels(a: list[TriageDecision], b: list[TriageDecision]) -> list[Agreement]:
    if len(a) != len(b):
        raise ValueError("agreement needs aligned label lists")
    out = []
    for field, weights, weighted in (("category", None, False),
                                     ("urgency", _urgency_weight, True),
                                     ("needs_human", None, False)):
        xa = [getattr(d, field) for d in a]
        xb = [getattr(d, field) for d in b]
        o, e, k = _kappa(xa, xb, weights)
        out.append(Agreement(field, len(a), o, e, k, weighted))
    return out


def disagreements(a: list[TriageDecision], b: list[TriageDecision],
                  numbers: list[int]) -> list[dict]:
    """Items the two raters disagreed on — candidates for the `disputed` flag."""
    out = []
    for n, x, y in zip(numbers, a, b):
        diffs = {f: (getattr(x, f), getattr(y, f))
                 for f in ("category", "urgency", "needs_human")
                 if getattr(x, f) != getattr(y, f)}
        if diffs:
            out.append({"issue_number": n, "fields": diffs})
    return out


def render(agreements: list[Agreement], title: str) -> str:
    lines = [title, "-" * len(title)]
    lines += ["  " + a.line() for a in agreements]
    scored = [a for a in agreements if a.kappa is not None]
    if scored:
        worst = min(scored, key=lambda a: a.kappa)
        lines += ["", f"  weakest field: {worst.field} at kappa={worst.kappa:+.3f} "
                      f"({worst.reading}) — this is the ceiling for that field."]
    return "\n".join(lines)
