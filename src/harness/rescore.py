"""Re-score completed runs against corrected labels, without re-running anything.

Run records keep each item's gold label alongside the prediction, so a label
correction can be applied to work already done. That makes "does this conclusion
survive the labels being wrong?" a free question rather than a $0.16 one.

It is a robustness check on the *dataset*, not on the models — the counterpart to the
bootstrap, which checks robustness to sampling. A finding that flips when two labels
are corrected was never a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from triage.models import TriageDecision

from .dataset import Dataset
from .runner import RunRecord


@dataclass
class Correction:
    issue_number: int
    corrected: TriageDecision
    source: str          # who confirmed it
    note: str = ""


def apply(run: RunRecord, corrections: dict[int, TriageDecision]) -> RunRecord:
    """A copy of `run` with corrected gold labels. Predictions are untouched."""
    clone = run.model_copy(deep=True)
    for item in clone.items:
        fixed = corrections.get(item.issue_number)
        if fixed is not None:
            item.gold = fixed
    clone.run_id = f"{run.run_id}__rescored"
    return clone


def corrected_dataset(dataset: Dataset, corrections: dict[int, TriageDecision]) -> Dataset:
    clone = dataset.model_copy(deep=True)
    for item in clone.items:
        fixed = corrections.get(item.issue_number)
        if fixed is not None:
            item.gold = fixed
            item.verified = True
    return clone


def load_runs(root: Path = Path("runs")) -> list[RunRecord]:
    return sorted((RunRecord.load(p) for p in Path(root).glob("*.json")),
                  key=lambda r: r.config_name)
