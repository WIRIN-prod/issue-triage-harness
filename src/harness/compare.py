"""Compare two runs and return a verdict — including "I can't tell".

Before comparing anything, the harness checks that the two runs are actually
comparable. Two guards, both refusals rather than warnings:

  * **Different dataset hashes.** Editing one label and re-running is the commonest
    way eval results quietly become lies (SPEC.md §5.4).
  * **Different temperature handling.** pydantic-ai silently drops sampling params for
    some providers (DECISIONS.md D19); one arm at temperature 0 and the other at the
    provider default is a confound, not a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .metrics import (ERROR_UNIT_USD, Scored, breakeven_unit_usd, error_weight,
                      score)
from .runner import ItemResult, RunRecord
from .stats import Comparison, Variance, dominated_by_noise, paired_bootstrap


class NotComparable(ValueError):
    pass


def _aligned(a: RunRecord, b: RunRecord) -> tuple[list[ItemResult], list[ItemResult]]:
    """Pair on issue number, keeping only items both runs answered successfully."""
    ok_a = {i.issue_number: i for i in a.ok}
    ok_b = {i.issue_number: i for i in b.ok}
    shared = sorted(set(ok_a) & set(ok_b))
    return [ok_a[n] for n in shared], [ok_b[n] for n in shared]


def check_comparable(a: RunRecord, b: RunRecord) -> None:
    if a.dataset_hash != b.dataset_hash:
        raise NotComparable(
            f"different datasets: A={a.dataset_hash} B={b.dataset_hash}. These runs "
            f"scored against different definitions of correct and cannot be compared."
        )
    if a.split != b.split:
        raise NotComparable(f"different splits: A={a.split} B={b.split}")
    if a.temperature_applied != b.temperature_applied:
        raise NotComparable(
            f"temperature is honoured for one arm and dropped for the other "
            f"(A={a.temperature_applied} B={b.temperature_applied}). The difference "
            f"would be attributed to the config change (DECISIONS.md D19)."
        )


# --- metric adapters over item lists ---------------------------------------

def _score_items(items: list[ItemResult]) -> Scored:
    return score([(i.predicted, i.gold) for i in items], [i.cost_usd for i in items])


def _total_usd(unit: float):
    def f(items: list[ItemResult]) -> float:
        return mean(i.cost_usd + error_weight(i.predicted, i.gold) * unit for i in items)
    return f


METRICS = [
    ("macro_f1 (category)", lambda xs: _score_items(xs).category["macro_f1"], True),
    ("urgency MAE", lambda xs: _score_items(xs).urgency["mae"], False),
    ("needs_human recall", lambda xs: _score_items(xs).needs_human["recall"], True),
    ("needs_human precision", lambda xs: _score_items(xs).needs_human["precision"], True),
    ("error weight / issue", lambda xs: mean(error_weight(i.predicted, i.gold) for i in xs), False),
    ("LLM $ / issue", lambda xs: mean(i.cost_usd for i in xs), False),
]


@dataclass
class Report:
    a: RunRecord
    b: RunRecord
    n_paired: int
    scored_a: Scored
    scored_b: Scored
    comparisons: list[Comparison] = field(default_factory=list)
    flagship: Comparison | None = None
    breakeven: float | None = None
    sensitivity: list[tuple[float, str]] = field(default_factory=list)
    noisy: list[str] = field(default_factory=list)

    def render(self) -> str:
        L = [
            f"A: {self.a.config_name:<16} {self.a.model:<30} [{self.a.config_hash}]",
            f"B: {self.b.config_name:<16} {self.b.model:<30} [{self.b.config_hash}]",
            f"dataset {self.a.dataset_hash} · split {self.a.split} · {self.n_paired} paired items",
            "",
        ]
        if self.flagship:
            L += ["FLAGSHIP — total $/issue (LLM spend + error cost)",
                  "  " + self.flagship.line(), ""]
        L.append("diagnostics")
        L += ["  " + c.line() for c in self.comparisons]
        if self.noisy:
            L += ["", "WARNING — smaller than this config's own run-to-run spread:"]
            L += [f"  {m}" for m in self.noisy]
        if self.sensitivity:
            L += ["", f"sensitivity to the error-cost anchor (default ${ERROR_UNIT_USD}/unit)"]
            L += [f"  ${u:<10.4f} {v}" for u, v in self.sensitivity]
        if self.breakeven is not None:
            L += ["", f"breakeven: the two configs cost the same when one weight unit "
                      f"is worth ${self.breakeven:.4f}"]
        return "\n".join(L)


def compare(
    a: RunRecord,
    b: RunRecord,
    unit_usd: float = ERROR_UNIT_USD,
    n_boot: int = 10_000,
    variances: dict[str, Variance] | None = None,
) -> Report:
    check_comparable(a, b)
    ia, ib = _aligned(a, b)
    if not ia:
        raise NotComparable("no issues answered successfully by both runs")

    rep = Report(a=a, b=b, n_paired=len(ia),
                 scored_a=_score_items(ia), scored_b=_score_items(ib))

    rep.flagship = paired_bootstrap(ia, ib, _total_usd(unit_usd),
                                    "total $/issue", higher_is_better=False, n_boot=n_boot)
    for name, fn, higher in METRICS:
        c = paired_bootstrap(ia, ib, fn, name, higher_is_better=higher, n_boot=n_boot)
        rep.comparisons.append(c)
        if variances and dominated_by_noise(c, variances.get(name)):
            rep.noisy.append(f"{name}: Δ={c.diff:+.4f} vs run-to-run sd="
                             f"{variances[name].sd:.4f}")

    rep.breakeven = breakeven_unit_usd(rep.scored_a, rep.scored_b)
    for unit in (0.01, 0.1, 1.0, 10.0, 100.0):
        ta = rep.scored_a.total_usd_per_issue(unit)
        tb = rep.scored_b.total_usd_per_issue(unit)
        winner = "A" if ta < tb else ("B" if tb < ta else "tie")
        rep.sensitivity.append((unit, f"A=${ta:.5f}  B=${tb:.5f}  → {winner}"))
    return rep
