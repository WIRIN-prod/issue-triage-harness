"""Evaluate the dataset, not the configs.

The harness spent most of its life scoring configs against labels it assumed were
correct. That is backwards in one important way: a config that shares the labeller's
biases scores well for the wrong reason, and nothing in the config tables can reveal it.

This reports what the *labels* look like, independent of any model:

  * class balance, and how far stratification pushed it from the source pool
  * the escalation base rate per category — the number that made the flagship
    near-degenerate at 76%
  * metric leverage: how much of the total achievable error each field can contribute,
    which is a property of the labels rather than of any config
  * agreement with an independent label set, when one exists

A dataset that scores badly here does not invalidate the configs, but it bounds what any
comparison between them can mean.
"""

from __future__ import annotations

from collections import Counter

from triage.models import URGENCY_RANK, TriageDecision

from .dataset import Dataset
from .metrics import WEIGHTS

CATS = ("bug", "feature", "docs", "question", "security")


def escalation_rates(ds: Dataset, split: str | None = None) -> dict[str, tuple[int, int]]:
    items = ds.split_items(split) if split else ds.items
    out = {}
    for c in CATS:
        sub = [i for i in items if i.gold.category == c]
        out[c] = (sum(1 for i in sub if i.gold.needs_human), len(sub))
    return out


def metric_leverage(ds: Dataset, split: str | None = None) -> dict[str, float]:
    """How much error weight each field could contribute if a config got it entirely wrong.

    This is a property of the labels alone. On this dataset escalation dominates not
    because escalation is intrinsically important, but because 76% of items are positive
    and a miss costs 10x — so the metric's shape was decided when the labels were written.
    """
    items = ds.split_items(split) if split else ds.items
    n = len(items) or 1
    nh = sum(1 for i in items if i.gold.needs_human)
    worst_escalation = nh * WEIGHTS["missed_escalation"] + (n - nh) * WEIGHTS["unnecessary_escalation"]
    worst_category = n * WEIGHTS["wrong_category"]
    worst_urgency = sum(
        WEIGHTS["urgency_per_step"][max(URGENCY_RANK[i.gold.urgency], 3 - URGENCY_RANK[i.gold.urgency]) or 1]
        for i in items)
    total = worst_escalation + worst_category + worst_urgency
    return {
        "escalation": worst_escalation / total,
        "category": worst_category / total,
        "urgency": worst_urgency / total,
    }


def trivial_floor(ds: Dataset, split: str | None = None) -> float:
    """Error weight of always answering the majority of every field."""
    from .metrics import score
    items = ds.split_items(split) if split else ds.items
    gold = [i.gold for i in items]
    cat = Counter(g.category for g in gold).most_common(1)[0][0]
    urg = Counter(g.urgency for g in gold).most_common(1)[0][0]
    hum = Counter(g.needs_human for g in gold).most_common(1)[0][0]
    const = [TriageDecision(category=cat, urgency=urg, needs_human=hum)] * len(gold)
    return score(list(zip(const, gold)), [0.0] * len(gold)).error_weight_per_issue


def render(ds: Dataset, split: str | None = None, pool_counts: dict | None = None) -> str:
    items = ds.split_items(split) if split else ds.items
    n = len(items)
    L = [f"dataset {ds.content_hash()} · rubric v{ds.rubric_version} · "
         f"{split or 'all'} · n={n}", ""]

    L.append("class balance" + ("  (vs candidate pool, to show stratification distortion)"
                                if pool_counts else ""))
    counts = Counter(i.gold.category for i in items)
    for c in CATS:
        share = 100 * counts[c] / max(n, 1)
        extra = ""
        if pool_counts and pool_counts.get(c):
            pool_share = 100 * pool_counts[c] / max(sum(pool_counts.values()), 1)
            extra = f"   pool {pool_share:>4.1f}%   {'oversampled' if share > pool_share * 1.3 else ''}"
        L.append(f"  {c:<10}{counts[c]:>4}  {share:>5.1f}%{extra}")

    L += ["", "escalation base rate — the number that shapes the flagship metric"]
    for c, (t, tot) in escalation_rates(ds, split).items():
        flag = "  <- effectively definitional" if tot and t == tot else ""
        L.append(f"  {c:<10}{t:>4}/{tot:<4} {100*t//max(tot,1):>4}%{flag}")
    nh = sum(1 for i in items if i.gold.needs_human)
    L.append(f"  {'ALL':<10}{nh:>4}/{n:<4} {100*nh//max(n,1):>4}%")

    lev = metric_leverage(ds, split)
    L += ["", "metric leverage — share of achievable error each field can contribute",
          "  (a property of the labels, not of any config)"]
    for k in ("escalation", "category", "urgency"):
        bar = "#" * int(lev[k] * 40)
        L.append(f"  {k:<12}{100*lev[k]:>5.1f}%  {bar}")

    floor = trivial_floor(ds, split)
    L += ["", f"trivial floor (majority of every field): {floor:.2f} error weight/issue",
          "  Any config not beating this has earned nothing. A high floor means the labels",
          "  themselves make the task easy to fake, which bounds what a comparison can show."]
    return "\n".join(L)
