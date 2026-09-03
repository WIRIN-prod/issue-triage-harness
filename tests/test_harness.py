"""Metric behaviour and the refusals that keep a comparison honest."""

import random

import pytest

from harness.compare import NotComparable, check_comparable, compare
from harness.metrics import (WEIGHTS, breakeven_unit_usd, category_scores,
                             error_weight, needs_human_scores, score,
                             urgency_scores)
from harness.runner import ItemResult, RunRecord
from harness.stats import (A_BETTER, B_BETTER, INCONCLUSIVE, Variance,
                           dominated_by_noise, paired_bootstrap)
from triage.models import TriageDecision as D


def d(cat="bug", urg="P2", human=False):
    return D(category=cat, urgency=urg, needs_human=human)


# --- error cost model ------------------------------------------------------

def test_missed_escalation_costs_ten_times_an_unnecessary_one():
    gold_needs = d(human=True)
    gold_not = d(human=False)
    missed = error_weight(d(human=False), gold_needs)
    unnecessary = error_weight(d(human=True), gold_not)
    assert missed == WEIGHTS["missed_escalation"]
    assert missed == 10 * unnecessary


def test_urgency_error_grows_with_distance():
    g = d(urg="P0")
    costs = [error_weight(d(urg=u), g) for u in ("P0", "P1", "P2", "P3")]
    assert costs == sorted(costs) and costs[0] == 0
    assert costs[3] > costs[1] * 2      # off-by-three is worse than twice off-by-one


def test_a_perfect_prediction_is_free():
    g = d(cat="security", urg="P0", human=True)
    assert error_weight(g, g) == 0.0


# --- why macro-F1 rather than accuracy -------------------------------------

def test_accuracy_flatters_a_majority_class_guesser_and_macro_f1_does_not():
    """The whole reason SPEC.md §5.2 rejects accuracy for category."""
    pairs = [(d(cat="bug"), d(cat="bug")) for _ in range(90)]
    pairs += [(d(cat="bug"), d(cat="security")) for _ in range(10)]
    s = category_scores(pairs)
    assert s["accuracy"] == 0.9
    assert s["macro_f1"] < 0.5          # security is never recalled


def test_classes_absent_from_gold_are_not_scored():
    pairs = [(d(cat="bug"), d(cat="bug"))] * 5
    assert category_scores(pairs)["scored_classes"] == 1


def test_urgency_mae_is_ordinal_not_binary():
    near = [(d(urg="P1"), d(urg="P0"))] * 10
    far = [(d(urg="P3"), d(urg="P0"))] * 10
    assert urgency_scores(near)["exact"] == urgency_scores(far)["exact"] == 0.0
    assert urgency_scores(near)["mae"] < urgency_scores(far)["mae"]


def test_needs_human_counts_the_expensive_error_separately():
    pairs = [(d(human=False), d(human=True))] * 3 + [(d(human=True), d(human=False))] * 7
    s = needs_human_scores(pairs)
    assert s["missed_escalations"] == 3
    assert s["unnecessary_escalations"] == 7


# --- flagship + breakeven --------------------------------------------------

def test_breakeven_finds_where_a_cheaper_worse_config_stops_winning():
    cheap = score([(d(cat="docs"), d(cat="bug"))] * 10, [0.0001] * 10)   # 2.0 weight/issue
    dear = score([(d(), d())] * 10, [0.0100] * 10)                        # 0 weight/issue
    u = breakeven_unit_usd(cheap, dear)
    assert u is not None
    assert cheap.total_usd_per_issue(u) == pytest.approx(dear.total_usd_per_issue(u))
    assert cheap.total_usd_per_issue(u / 2) < dear.total_usd_per_issue(u / 2)
    assert cheap.total_usd_per_issue(u * 2) > dear.total_usd_per_issue(u * 2)


def test_breakeven_is_undefined_when_quality_is_identical():
    a = score([(d(), d())] * 5, [0.001] * 5)
    b = score([(d(), d())] * 5, [0.009] * 5)
    assert breakeven_unit_usd(a, b) is None


# --- confidence ------------------------------------------------------------

def _noisy(n, effect, seed):
    rng = random.Random(seed)
    a = [rng.gauss(0.7, 0.15) for _ in range(n)]
    b = [x + effect + rng.gauss(0, 0.15) for x in a]
    return a, b


AVG = lambda xs: sum(xs) / len(xs)


def test_no_real_effect_is_reported_as_inconclusive():
    a, b = _noisy(40, 0.0, 3)
    assert paired_bootstrap(a, b, AVG, "m", True, n_boot=2000).verdict == INCONCLUSIVE


def test_a_large_effect_is_detected():
    a, b = _noisy(40, 0.25, 3)
    assert paired_bootstrap(a, b, AVG, "m", True, n_boot=2000).verdict == B_BETTER


def test_direction_respects_whether_higher_is_better():
    a, b = _noisy(60, 0.25, 5)
    assert paired_bootstrap(a, b, AVG, "m", higher_is_better=False, n_boot=2000).verdict == A_BETTER


def test_inconclusive_results_say_how_many_items_would_settle_it():
    """A real but under-powered effect should name the sample size that resolves it."""
    a, b = _noisy(40, 0.06, 23)
    c = paired_bootstrap(a, b, AVG, "m", True, n_boot=4000)
    assert c.verdict == INCONCLUSIVE
    assert c.n_needed and c.n_needed > 40
    assert not c.effect_too_small


def test_a_vanishing_difference_is_named_rather_than_given_an_absurd_sample_size():
    """"Collect 1.5M items" is not advice; it means there is no effect."""
    a, b = _noisy(40, 0.03, 3)      # sampling noise cancels the effect almost exactly
    c = paired_bootstrap(a, b, AVG, "m", True, n_boot=2000)
    assert abs(c.diff) < 0.005
    assert c.verdict == INCONCLUSIVE
    assert c.effect_too_small
    assert c.n_needed is None
    assert "indistinguishable from zero" in c.line()


def test_an_effect_smaller_than_run_to_run_noise_is_flagged():
    a, b = _noisy(200, 0.02, 7)
    c = paired_bootstrap(a, b, AVG, "m", True, n_boot=2000)
    assert dominated_by_noise(c, Variance("m", [0.70, 0.76, 0.73]))
    assert not dominated_by_noise(c, Variance("m", [0.700, 0.701, 0.700]))


# --- refusals --------------------------------------------------------------

def _run(**kw):
    base = dict(
        run_id="r", config_name="c", config_hash="h", model="m", prompt_version="v",
        rationale_mode="post", context_mode="graph", temperature=0.0,
        temperature_applied=True, dataset_hash="ds1", split="dev", git_sha="g",
        timestamp="t", items=[],
    )
    return RunRecord(**{**base, **kw})


def test_refuses_runs_scored_against_different_datasets():
    with pytest.raises(NotComparable, match="different datasets"):
        check_comparable(_run(), _run(dataset_hash="ds2"))


def test_refuses_runs_from_different_splits():
    with pytest.raises(NotComparable, match="different splits"):
        check_comparable(_run(), _run(split="holdout"))


def test_refuses_when_temperature_was_dropped_for_only_one_arm():
    """DECISIONS.md D19 — that difference would be blamed on the config change."""
    with pytest.raises(NotComparable, match="temperature"):
        check_comparable(_run(), _run(temperature_applied=False))


def test_refuses_when_every_call_failed():
    """A run where nothing returned is refused on run quality, before scoring."""
    a = _run(items=[ItemResult(issue_number=1, predicted=d(), gold=d(), cost_usd=0,
                               tokens_in=0, tokens_out=0, latency_ms=0,
                               context_empty=True, context_tokens=0, error="boom")])
    with pytest.raises(NotComparable, match="answered only 0/1"):
        compare(a, a)


def _item(n, err=""):
    return ItemResult(issue_number=n, predicted=d(), gold=d(), cost_usd=0.001,
                      tokens_in=10, tokens_out=5, latency_ms=1,
                      context_empty=True, context_tokens=0, error=err)


def test_comparison_pairs_only_issues_both_runs_answered():
    """One failure in 20 stays above the run-quality floor; only shared items pair."""
    a = _run(items=[_item(n) for n in range(19)] + [_item(19, err="failed")])
    b = _run(items=[_item(n) for n in range(20)])
    assert compare(a, b, n_boot=200).n_paired == 19


def test_refuses_a_run_that_mostly_failed():
    """free-nvidia scored the best macro-F1 of any config on the 24 of 60 calls that returned."""
    a = _run(items=[_item(n) for n in range(20)])
    b = _run(items=[_item(n) for n in range(8)] + [_item(n, err="boom") for n in range(8, 20)])
    with pytest.raises(NotComparable, match="survivorship"):
        compare(a, b, n_boot=200)


def test_family_wise_correction_demotes_marginal_findings():
    """Six tests at alpha=0.05 give ~26% chance of a false positive if read alone."""
    from harness.stats import holm_bonferroni

    a, b = _noisy(60, 0.06, 31)
    marginal = [paired_bootstrap(a, b, AVG, f"m{i}", True, n_boot=2000) for i in range(6)]
    before = sum(1 for c in marginal if c.significant)
    holm_bonferroni(marginal)
    after = sum(1 for c in marginal if c.significant)
    assert after <= before
