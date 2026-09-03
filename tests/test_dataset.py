"""Dataset identity and sampling. These protect the comparison, not the model."""

import json

import pytest

from harness.dataset import Dataset, GoldItem
from harness.labelling import (FileLabeller, LabelResult, assign_splits,
                               select_stratified)
from triage.models import TriageDecision


def _item(n: int, cat="bug", urg="P2", split="dev", disputed=False) -> GoldItem:
    return GoldItem(
        issue_number=n, title=f"issue {n}", body="body",
        gold=TriageDecision(category=cat, urgency=urg, needs_human=False),
        labeller="test/model", split=split, disputed=disputed,
    )


def _ds(items) -> Dataset:
    return Dataset(repo="a/b", commit="c" * 40, graph_sha256="deadbeef",
                   rubric_version="1", rubric_sha256="cafe", labeller="test/model",
                   window="w", items=items)


def test_hash_ignores_item_order():
    a, b = _item(1), _item(2)
    assert _ds([a, b]).content_hash() == _ds([b, a]).content_hash()


def test_hash_ignores_rationale_text():
    """Two labellers can word a rationale differently and still mean the same label."""
    a = _item(1)
    b = _item(1)
    b.gold = b.gold.model_copy(update={"rationale": "completely different wording"})
    assert _ds([a]).content_hash() == _ds([b]).content_hash()


@pytest.mark.parametrize("mutate", [
    lambda d: d.items.append(_item(99)),
    lambda d: setattr(d.items[0], "split", "holdout"),
    lambda d: setattr(d.items[0], "disputed", True),
    lambda d: setattr(d, "rubric_sha256", "different"),
    lambda d: setattr(d, "graph_sha256", "different"),
])
def test_anything_that_changes_meaning_changes_the_hash(mutate):
    d = _ds([_item(1), _item(2)])
    before = d.content_hash()
    mutate(d)
    assert d.content_hash() != before


def test_loading_an_edited_dataset_is_refused(tmp_path):
    """Silently fixing one label invalidates every result already computed against it."""
    path = tmp_path / "gold.json"
    _ds([_item(1), _item(2)]).save(path)

    raw = json.loads(path.read_text())
    raw["items"][0]["gold"]["category"] = "docs"     # tamper, keep the stated hash
    path.write_text(json.dumps(raw))

    with pytest.raises(ValueError, match="edited in place"):
        Dataset.load(path)


def test_roundtrip_preserves_the_hash(tmp_path):
    path = tmp_path / "gold.json"
    original = _ds([_item(1), _item(2, cat="docs", urg="P3")])
    original.save(path)
    assert Dataset.load(path).content_hash() == original.content_hash()


def test_undisputed_view_excludes_disputed_items():
    d = _ds([_item(1), _item(2, disputed=True)])
    assert len(d.undisputed()) == 1


# --- sampling --------------------------------------------------------------

def _res(n, cat, urg):
    return LabelResult(n, TriageDecision(category=cat, urgency=urg, needs_human=False))


def test_stratification_rescues_scarce_cells_from_a_skewed_pool():
    """Random sampling would return ~0 security issues; those are the cells that matter."""
    pool = [_res(i, "bug", "P2") for i in range(400)]
    pool += [_res(1000 + i, "security", "P0") for i in range(5)]
    pool += [_res(2000 + i, "docs", "P3") for i in range(20)]

    chosen, cells = select_stratified(pool, n=30)
    assert len(chosen) == 30
    assert cells.get("security/P0", 0) == 5          # every scarce item taken
    assert cells["bug/P2"] < 25                       # the bulk class does not crowd out


def test_stratification_is_deterministic():
    pool = [_res(i, "bug", "P2") for i in range(50)] + [_res(100 + i, "docs", "P3") for i in range(50)]
    assert select_stratified(pool, 20)[0] == select_stratified(pool, 20)[0]


def test_split_is_deterministic_and_respects_the_fraction():
    nums = list(range(100))
    a = assign_splits(nums, dev_frac=0.6)
    assert a == assign_splits(nums, dev_frac=0.6)
    assert sum(1 for v in a.values() if v == "dev") == 60
    assert sum(1 for v in a.values() if v == "holdout") == 40


# --- out-of-band labels ----------------------------------------------------

def test_file_labeller_reads_supplied_labels(tmp_path):
    p = tmp_path / "labels.jsonl"
    p.write_text(json.dumps({
        "issue_number": 7,
        "decision": {"category": "docs", "urgency": "P3", "needs_human": False},
    }) + "\n")
    from harness.github import Issue
    iss = Issue(number=7, title="t", body="b", author="u", state="open",
                created_at="2026-01-01T00:00:00Z", comments=0, url="")
    assert FileLabeller(p).label(iss, None).decision.category == "docs"


def test_file_labeller_reports_a_missing_label_rather_than_inventing_one(tmp_path):
    p = tmp_path / "labels.jsonl"
    p.write_text("")
    from harness.github import Issue
    iss = Issue(number=7, title="t", body="b", author="u", state="open",
                created_at="2026-01-01T00:00:00Z", comments=0, url="")
    assert "no label supplied" in FileLabeller(p).label(iss, None).error


def test_a_thinned_labelling_run_is_refused_not_quietly_accepted():
    """80% failures once produced a clean-hashing 20-item dataset that looked fine."""
    from harness.github import Issue
    from harness.labelling import TooManyFailures, build_dataset

    issues = [Issue(number=n, title="t", body="b", author="u", state="open",
                    created_at="2026-01-01T00:00:00Z", comments=0, url="")
              for n in range(10)]
    gold = [LabelResult(n, TriageDecision(category="bug", urgency="P2", needs_human=False))
            for n in range(2)]
    gold += [LabelResult(n, TriageDecision(category="bug", urgency="P2", needs_human=False),
                         error="ModelAPIError: Connection error.") for n in range(2, 10)]

    with pytest.raises(TooManyFailures, match="20%"):
        build_dataset(issues, gold, "m", "r", "c", "g", "w",
                      __import__("pathlib").Path("docs/rubric.md"))


# --- checkpointing ---------------------------------------------------------

def _issue(n):
    from harness.github import Issue
    return Issue(number=n, title="t", body="b", author="u", state="open",
                 created_at="2026-01-01T00:00:00Z", comments=0, url="")


class _CountingLabeller:
    name = "counting"

    def __init__(self, fail_from=None):
        self.calls = []
        self.fail_from = fail_from

    def label(self, issue, context):
        self.calls.append(issue.number)
        err = "ModelHTTPError: status_code: 429" if (
            self.fail_from is not None and issue.number >= self.fail_from) else ""
        return LabelResult(issue.number,
                           TriageDecision(category="bug", urgency="P2", needs_human=False),
                           cost_usd=0.01, error=err)


def test_cache_means_a_rerun_only_pays_for_what_is_missing(tmp_path):
    """A failed run once discarded 86 frontier labels and $1.10 with them."""
    from harness.labelling import LabelCache, run_pass

    issues = [_issue(n) for n in range(6)]
    path = tmp_path / "gold.jsonl"

    first = _CountingLabeller(fail_from=4)          # 0-3 succeed, 4-5 fail
    run_pass(issues, first, {}, workers=1, cache=LabelCache(path, "cfg1"))
    assert len(first.calls) == 6

    second = _CountingLabeller()                    # rerun: only the failures remain
    results = run_pass(issues, second, {}, workers=1, cache=LabelCache(path, "cfg1"))
    assert sorted(second.calls) == [4, 5]
    assert len(results) == 6 and not any(r.error for r in results)


def test_cache_is_scoped_to_the_config_that_produced_it(tmp_path):
    """Labels from a different config are different labels, not a cache hit."""
    from harness.labelling import LabelCache, run_pass

    issues = [_issue(n) for n in range(3)]
    path = tmp_path / "gold.jsonl"
    run_pass(issues, _CountingLabeller(), {}, workers=1, cache=LabelCache(path, "cfg1"))

    other = _CountingLabeller()
    run_pass(issues, other, {}, workers=1, cache=LabelCache(path, "cfg2"))
    assert sorted(other.calls) == [0, 1, 2]


def test_failures_are_not_cached(tmp_path):
    from harness.labelling import LabelCache

    cache = LabelCache(tmp_path / "c.jsonl", "cfg")
    cache.put(LabelResult(1, TriageDecision(category="bug", urgency="P2", needs_human=False),
                          error="boom"))
    assert cache.get(1) is None and len(cache) == 0
