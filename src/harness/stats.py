"""Paired bootstrap, and the discipline to say "I can't tell".

Two noise sources sit between a measurement and a conclusion (SPEC.md §5.5): the model
is non-deterministic, and a 40-item holdout has wide error bars. Neither is assumed
away — non-determinism is measured by repeating a config, sampling noise by
resampling the items.

Comparisons are **paired**: both configs saw the same issues, so each bootstrap
resample draws the same item indices for both arms. That removes item difficulty from
the comparison and is far more sensitive than comparing two independent means.

`NO_SIGNIFICANT_DIFFERENCE` is a first-class verdict. A harness that always names a
winner is a harness that ships noise with a straight face.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Callable, Sequence

Verdict = str
A_BETTER = "A_BETTER"
B_BETTER = "B_BETTER"
INCONCLUSIVE = "NO_SIGNIFICANT_DIFFERENCE"

Z95 = 1.959963985

# Beyond this, "collect more data" stops being advice. An observed difference that
# would need a hundred thousand items to resolve is not a small effect waiting for a
# bigger sample — it is an absence of one, and saying so is more useful than printing
# a seven-digit number.
MAX_USEFUL_N = 100_000


@dataclass
class Comparison:
    metric: str
    a: float
    b: float
    diff: float               # b - a
    ci_low: float
    ci_high: float
    verdict: Verdict
    higher_is_better: bool
    n_items: int
    n_boot: int
    se: float
    n_needed: int | None = None   # items required to resolve, when inconclusive
    effect_too_small: bool = False
    family_adjusted: bool = False  # demoted by multiple-comparison correction

    @property
    def significant(self) -> bool:
        return self.verdict != INCONCLUSIVE

    def line(self) -> str:
        arrow = "→" if self.significant else "·"
        if self.family_adjusted:
            need = "  (was significant alone; not after family-wise correction)"
        elif self.effect_too_small:
            need = "  (effect indistinguishable from zero)"
        elif self.n_needed is not None:
            need = f"  (needs ~{self.n_needed} items)"
        else:
            need = ""
        return (f"{self.metric:<28} A={self.a:>9.4f}  B={self.b:>9.4f}  "
                f"Δ={self.diff:>+9.4f} [{self.ci_low:>+8.4f},{self.ci_high:>+8.4f}] "
                f"{arrow} {self.verdict}{need}")


def paired_bootstrap(
    items_a: Sequence,
    items_b: Sequence,
    metric: Callable[[Sequence], float],
    name: str,
    higher_is_better: bool,
    n_boot: int = 10_000,
    alpha: float = 0.05,
    seed: int = 20260903,
) -> Comparison:
    if len(items_a) != len(items_b):
        raise ValueError("paired comparison requires aligned item lists")
    n = len(items_a)
    if n == 0:
        raise ValueError("nothing to compare")

    a_obs, b_obs = metric(items_a), metric(items_b)
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]          # same draw for both arms
        diffs.append(metric([items_b[i] for i in idx]) - metric([items_a[i] for i in idx]))
    diffs.sort()

    lo = diffs[int(alpha / 2 * n_boot)]
    hi = diffs[min(int((1 - alpha / 2) * n_boot), n_boot - 1)]
    se = pstdev(diffs) if n_boot > 1 else 0.0
    observed = b_obs - a_obs

    if lo > 0:
        verdict = B_BETTER if higher_is_better else A_BETTER
    elif hi < 0:
        verdict = A_BETTER if higher_is_better else B_BETTER
    else:
        verdict = INCONCLUSIVE

    n_needed, too_small = None, False
    if verdict == INCONCLUSIVE and se > 0:
        if abs(observed) <= 1e-12:
            too_small = True
        else:
            # items required for a CI half-width smaller than the observed effect
            need = int(((Z95 * se * (n ** 0.5)) / abs(observed)) ** 2) + 1
            if need > MAX_USEFUL_N:
                too_small = True
            else:
                n_needed = need

    return Comparison(
        metric=name, a=a_obs, b=b_obs, diff=observed, ci_low=lo, ci_high=hi,
        verdict=verdict, higher_is_better=higher_is_better, n_items=n,
        n_boot=n_boot, se=se, n_needed=n_needed, effect_too_small=too_small,
    )


def holm_bonferroni(comparisons: list[Comparison], alpha: float = 0.05) -> list[Comparison]:
    """Adjust a family of comparisons for multiple testing, in place.

    Running six tests at alpha=0.05 and reading each as if it stood alone gives roughly
    a 26% chance of at least one false positive. A harness built to avoid over-claiming
    should not then over-claim by arithmetic.

    Holm-Bonferroni rather than plain Bonferroni: it is uniformly more powerful and
    still controls the family-wise error rate. Significance is approximated from how far
    the bootstrap CI sits from zero, since the bootstrap gives an interval rather than a
    p-value: p ~ 2 * (1 - Phi(|diff| / se)).
    """
    from math import erf, sqrt

    def p_of(c: Comparison) -> float:
        if c.se <= 0:
            return 0.0 if abs(c.diff) > 0 else 1.0
        z = abs(c.diff) / c.se
        return max(0.0, min(1.0, 2 * (1 - 0.5 * (1 + erf(z / sqrt(2))))))

    ordered = sorted(comparisons, key=p_of)
    m = len(ordered)
    survived = True
    for rank, c in enumerate(ordered):
        threshold = alpha / (m - rank)
        if not survived or p_of(c) > threshold:
            survived = False
            if c.verdict != INCONCLUSIVE:
                c.verdict = INCONCLUSIVE
                c.family_adjusted = True
    return comparisons


@dataclass
class Variance:
    """Run-to-run spread for one config, from repeated runs on the same items."""

    metric: str
    values: list[float]

    @property
    def mean(self) -> float:
        return mean(self.values)

    @property
    def sd(self) -> float:
        return pstdev(self.values) if len(self.values) > 1 else 0.0

    @property
    def spread(self) -> float:
        return max(self.values) - min(self.values) if self.values else 0.0

    def line(self) -> str:
        return (f"{self.metric:<28} mean={self.mean:>9.4f}  sd={self.sd:>8.4f}  "
                f"range={self.spread:>8.4f}  (n={len(self.values)} runs)")


def dominated_by_noise(comparison: Comparison, variance: Variance | None) -> bool:
    """Is the measured difference smaller than the same config's own run-to-run spread?

    If rerunning config A twice moves the metric more than switching to config B does,
    the difference is not a property of the change. Statistical significance over items
    does not save you from this — it is a separate failure, and reporting it separately
    is the point.
    """
    if variance is None or variance.sd == 0:
        return False
    return abs(comparison.diff) < variance.sd
