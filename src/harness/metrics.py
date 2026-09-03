"""Scoring: per-field diagnostics, and one flagship number in dollars.

Each field has a different mathematical nature and cannot share a metric
(SPEC.md §5.2). Category is multi-class, so macro-F1 rather than accuracy — accuracy
flatters a classifier that always guesses the majority class. Urgency is ordinal, so
P0-vs-P3 must cost more than P0-vs-P1. `needs_human` is binary with asymmetric costs,
so recall on the positive class carries the weight.

The flagship metric puts errors and inference on the same scale:

    total cost per issue = LLM spend + expected error cost

Error weights are relative; ERROR_UNIT_USD converts them to dollars. That anchor is
an assumption, so `breakeven_unit_usd` reports the value at which two configs tie —
which is the honest way to present a number that rests on a guess.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

from triage.models import URGENCY_RANK, TriageDecision

CATEGORIES = ("bug", "feature", "docs", "question", "security")

# Relative error weights (SPEC.md §5.3). Disputable on purpose — they are stated here
# so they can be argued with, rather than buried in a scoring function.
WEIGHTS = {
    "missed_escalation": 10.0,      # gold says a human is needed, we said no
    "unnecessary_escalation": 1.0,  # we escalated something routable
    "wrong_category": 2.0,
    "urgency_per_step": {1: 1.0, 2: 3.0, 3: 6.0},
}

# One weight unit in dollars. Anchored to roughly a minute of maintainer attention,
# so an unnecessary escalation costs ~$1 and a missed one ~$10. Every result that
# depends on this is reported with its sensitivity.
ERROR_UNIT_USD = 1.0


def error_weight(pred: TriageDecision, gold: TriageDecision) -> float:
    w = 0.0
    if pred.category != gold.category:
        w += WEIGHTS["wrong_category"]
    step = abs(URGENCY_RANK[pred.urgency] - URGENCY_RANK[gold.urgency])
    if step:
        w += WEIGHTS["urgency_per_step"][step]
    if gold.needs_human and not pred.needs_human:
        w += WEIGHTS["missed_escalation"]
    elif pred.needs_human and not gold.needs_human:
        w += WEIGHTS["unnecessary_escalation"]
    return w


# --- per-field diagnostics -------------------------------------------------


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def category_scores(pairs: list[tuple[TriageDecision, TriageDecision]]) -> dict:
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    for pred, gold in pairs:
        if pred.category == gold.category:
            tp[gold.category] += 1
        else:
            fp[pred.category] += 1
            fn[gold.category] += 1

    per_class, f1s = {}, []
    for c in CATEGORIES:
        support = tp[c] + fn[c]
        p, r, f = _prf(tp[c], fp[c], fn[c])
        per_class[c] = {"precision": p, "recall": r, "f1": f, "support": support}
        if support:                       # a class absent from gold cannot be scored
            f1s.append(f)
    return {
        "macro_f1": mean(f1s) if f1s else 0.0,
        "accuracy": sum(1 for p, g in pairs if p.category == g.category) / len(pairs),
        "per_class": per_class,
        "scored_classes": len(f1s),
    }


def urgency_scores(pairs) -> dict:
    steps = [abs(URGENCY_RANK[p.urgency] - URGENCY_RANK[g.urgency]) for p, g in pairs]
    return {
        "mae": mean(steps),
        "exact": sum(1 for s in steps if s == 0) / len(steps),
        "off_by_one_or_less": sum(1 for s in steps if s <= 1) / len(steps),
        "worst": max(steps),
    }


def needs_human_scores(pairs) -> dict:
    tp = sum(1 for p, g in pairs if p.needs_human and g.needs_human)
    fp = sum(1 for p, g in pairs if p.needs_human and not g.needs_human)
    fn = sum(1 for p, g in pairs if not p.needs_human and g.needs_human)
    tn = sum(1 for p, g in pairs if not p.needs_human and not g.needs_human)
    p, r, f = _prf(tp, fp, fn)
    return {
        "precision": p, "recall": r, "f1": f,
        "missed_escalations": fn,       # the expensive error
        "unnecessary_escalations": fp,
        "true_positives": tp, "true_negatives": tn,
    }


# --- flagship --------------------------------------------------------------


@dataclass
class Scored:
    n: int
    llm_usd_per_issue: float
    error_weight_per_issue: float
    category: dict
    urgency: dict
    needs_human: dict
    schema_failures: int = 0

    def error_usd_per_issue(self, unit_usd: float = ERROR_UNIT_USD) -> float:
        return self.error_weight_per_issue * unit_usd

    def total_usd_per_issue(self, unit_usd: float = ERROR_UNIT_USD) -> float:
        return self.llm_usd_per_issue + self.error_usd_per_issue(unit_usd)


def score(pairs: list[tuple[TriageDecision, TriageDecision]],
          costs: list[float], schema_failures: int = 0) -> Scored:
    return Scored(
        n=len(pairs),
        llm_usd_per_issue=(sum(costs) / len(costs)) if costs else 0.0,
        error_weight_per_issue=mean(error_weight(p, g) for p, g in pairs),
        category=category_scores(pairs),
        urgency=urgency_scores(pairs),
        needs_human=needs_human_scores(pairs),
        schema_failures=schema_failures,
    )


def error_components(pairs: list[tuple[TriageDecision, TriageDecision]]) -> dict[str, float]:
    """Split the error weight into its parts, per issue.

    The flagship is ~72% escalation error on this dataset, which is a deliberate
    consequence of the 10:1 weight — but it should be visible rather than inferred.
    """
    n = len(pairs) or 1
    out = {"wrong_category": 0.0, "urgency": 0.0,
           "missed_escalation": 0.0, "unnecessary_escalation": 0.0}
    for pred, gold in pairs:
        if pred.category != gold.category:
            out["wrong_category"] += WEIGHTS["wrong_category"]
        step = abs(URGENCY_RANK[pred.urgency] - URGENCY_RANK[gold.urgency])
        if step:
            out["urgency"] += WEIGHTS["urgency_per_step"][step]
        if gold.needs_human and not pred.needs_human:
            out["missed_escalation"] += WEIGHTS["missed_escalation"]
        elif pred.needs_human and not gold.needs_human:
            out["unnecessary_escalation"] += WEIGHTS["unnecessary_escalation"]
    return {k: v / n for k, v in out.items()}


def breakeven_escalation_weight(
    a_pairs: list[tuple[TriageDecision, TriageDecision]],
    b_pairs: list[tuple[TriageDecision, TriageDecision]],
) -> float | None:
    """At what missed-escalation weight do these two configs tie?

    The 10:1 ratio is the single most load-bearing assumption in the project — it drives
    ~72% of the flagship. Reporting the weight at which a conclusion flips turns that
    assumption into a number a stakeholder can argue with: "this holds as long as a
    missed escalation costs more than N times an unnecessary one".

    Solves `rest_a + w*miss_a == rest_b + w*miss_b` for w, where `miss` is the *count*
    of missed escalations per issue and `rest` is everything else.
    """
    def parts(pairs):
        n = len(pairs) or 1
        miss = sum(1 for p, g in pairs if g.needs_human and not p.needs_human) / n
        rest = sum(
            (WEIGHTS["wrong_category"] if p.category != g.category else 0.0)
            + WEIGHTS["urgency_per_step"].get(
                abs(URGENCY_RANK[p.urgency] - URGENCY_RANK[g.urgency]), 0.0)
            + (WEIGHTS["unnecessary_escalation"] if p.needs_human and not g.needs_human else 0.0)
            for p, g in pairs) / n
        return miss, rest

    miss_a, rest_a = parts(a_pairs)
    miss_b, rest_b = parts(b_pairs)
    denom = miss_a - miss_b
    if abs(denom) < 1e-12:
        return None            # same miss rate: the weight cannot flip the comparison
    w = (rest_b - rest_a) / denom
    return w if w > 0 else None


def breakeven_usd_per_second(a: Scored, b: Scored,
                             a_p50_ms: float, b_p50_ms: float) -> float | None:
    """At what value of a second does the faster config overtake the better one?

    Latency is measured but deliberately not priced into the flagship: putting a second
    dollar guess beside the error-cost anchor would compound two assumptions instead of
    exposing them. Reporting the breakeven keeps latency in the decision without
    smuggling in a number nobody validated.

    For asynchronous triage a second is worth ~nothing and this rarely binds; for an
    interactive path it can dominate.
    """
    total_a = a.total_usd_per_issue()
    total_b = b.total_usd_per_issue()
    d_sec = (b_p50_ms - a_p50_ms) / 1000.0
    if abs(d_sec) < 1e-9:
        return None
    v = (total_a - total_b) / d_sec
    return v if v > 0 else None


def breakeven_unit_usd(a: Scored, b: Scored) -> float | None:
    """At what value of a weight unit do these two configs cost the same?

    Solving `a.llm + a.err*u == b.llm + b.err*u` for u. Below the breakeven the
    cheaper-but-worse config wins; above it, the dearer-but-better one does. Reporting
    this is more honest than asserting a winner from an anchor nobody validated — and
    when the breakeven is absurd (a fraction of a cent of human time, or thousands of
    dollars), the result does not really depend on the anchor at all.
    """
    denom = a.error_weight_per_issue - b.error_weight_per_issue
    if abs(denom) < 1e-12:
        return None
    u = (b.llm_usd_per_issue - a.llm_usd_per_issue) / denom
    return u if u > 0 else None
