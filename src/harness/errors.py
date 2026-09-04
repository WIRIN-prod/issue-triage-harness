"""Error analysis over a completed run — where a config fails, not just how much.

Aggregate scores say *whether* something changed; this says *where*, which is what
suggests the next change. It reads committed run records, so it costs nothing.

The self-contradiction check is the one that earned its place: the rubric handed to the
model says any P0 or P1 must escalate, and baseline violates that on 44% of its own
P0/P1 predictions. A model disagreeing with itself is a different failure from a model
disagreeing with the labels, and only the first has a free fix.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .runner import ItemResult, RunRecord

CATS = ("bug", "feature", "docs", "question", "security")


def confusion(items: list[ItemResult]) -> dict:
    out: dict = defaultdict(int)
    for i in items:
        out[(i.gold.category, i.predicted.category)] += 1
    return out


def self_contradictions(items: list[ItemResult]) -> list[ItemResult]:
    """Predicted P0/P1 but predicted needs_human=False — a rubric violation by the model."""
    return [i for i in items
            if i.predicted.urgency in ("P0", "P1") and not i.predicted.needs_human]


def missed_escalations(items: list[ItemResult]) -> list[ItemResult]:
    return [i for i in items if i.gold.needs_human and not i.predicted.needs_human]


def render(run: RunRecord) -> str:
    items = run.ok
    L = [f"{run.config_name} [{run.config_hash}] · {run.model} · {run.split} · n={len(items)}", ""]

    L.append("category confusion (rows = gold, cols = predicted)")
    m = confusion(items)
    L.append("          " + "".join(f"{c[:7]:>9}" for c in CATS))
    for g in CATS:
        row = "".join(f"{m.get((g, p), 0):>9}" for p in CATS)
        total = sum(m.get((g, p), 0) for p in CATS)
        L.append(f"  {g:<8}{row}   ({total})")

    miss = missed_escalations(items)
    need = sum(1 for i in items if i.gold.needs_human)
    L += ["", f"missed escalations: {len(miss)}/{need} "
              f"({100*len(miss)//max(need,1)}% of items that needed a human)"]
    if miss:
        L.append("  by gold category: " + str(dict(Counter(i.gold.category for i in miss))))
        L.append("  by gold urgency:  " + str(dict(Counter(i.gold.urgency for i in miss))))

    contra = self_contradictions(items)
    hi = [i for i in items if i.predicted.urgency in ("P0", "P1")]
    fixable = [i for i in contra if i.gold.needs_human]
    L += ["", "self-contradiction (model said P0/P1 but not needs_human — its own rubric forbids this)",
          f"  {len(contra)}/{len(hi)} of its P0/P1 predictions "
          f"({100*len(contra)//max(len(hi),1)}%)",
          f"  of those, {len(fixable)} are genuinely needs_human — enforcing the model's own",
          f"  rule would recover {len(fixable)} of {len(miss)} missed escalations, at no cost."]
    return "\n".join(L)
