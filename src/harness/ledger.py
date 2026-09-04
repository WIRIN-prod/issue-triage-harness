"""Reconstruct the optimisation history from run records.

Every run already carries `git_sha`, `timestamp`, `config_hash` and `dataset_hash`, so
the history of what was tried and when is recoverable rather than needing to be
hand-maintained in prose — which drifts.

The number that matters most here is the **dev look count**. Each time a split is
inspected and a change made in response, the developer tunes a little toward it. That is
the leak the dev/holdout split exists to contain (D13), and it is invisible unless
counted. Twenty looks at a 118-item set means the dev figures are optimistic by an
unquantified amount, and the honest response is to say so and to keep decisions on the
holdout.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .runner import RunRecord


@dataclass
class Entry:
    timestamp: str
    config_name: str
    config_hash: str
    dataset_hash: str
    split: str
    repeat: int
    git_sha: str
    subject: str = ""      # commit subject at that sha, when resolvable


def _subject(sha: str) -> str:
    if not sha or sha == "unknown":
        return ""
    r = subprocess.run(["git", "log", "-1", "--format=%s", sha],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def collect(roots=(Path("runs"), Path("runs/archive"))) -> list[Entry]:
    out: list[Entry] = []
    seen_sha: dict[str, str] = {}
    for root in roots:
        for p in Path(root).glob("*.json"):
            try:
                r = RunRecord.load(p)
            except Exception:
                continue
            if r.git_sha not in seen_sha:
                seen_sha[r.git_sha] = _subject(r.git_sha)
            out.append(Entry(r.timestamp, r.config_name, r.config_hash, r.dataset_hash,
                             r.split, r.repeat, r.git_sha, seen_sha[r.git_sha]))
    return sorted(out, key=lambda e: e.timestamp)


def look_counts(entries: list[Entry]) -> dict[str, int]:
    """Distinct occasions a split was evaluated, per dataset version.

    Repeats of one config on one occasion count once: they measure noise, they are not
    an extra opportunity to tune.
    """
    occasions: dict[str, set] = defaultdict(set)
    for e in entries:
        occasions[f"{e.split}@{e.dataset_hash}"].add((e.timestamp[:11], e.config_hash))
    return {k: len(v) for k, v in sorted(occasions.items())}


def render(entries: list[Entry]) -> str:
    lines = ["run ledger — reconstructed from run records, not hand-written", ""]
    lines.append(f"{'when':<18}{'config':<15}{'split':<9}{'r':<3}{'dataset':<18}{'code':<9}")
    lines.append("-" * 90)
    for e in entries:
        lines.append(f"{e.timestamp:<18}{e.config_name:<15}{e.split:<9}{e.repeat:<3}"
                     f"{e.dataset_hash:<18}{e.git_sha:<9}")

    lines += ["", "how often each split has been evaluated"]
    for key, n in look_counts(entries).items():
        split, _, ds = key.partition("@")
        warn = ""
        if split == "dev" and n >= 10:
            warn = "  <- many looks; dev figures are optimistic by an unquantified amount"
        if split == "holdout":
            warn = "  <- decisions only; each look spends it"
        lines.append(f"  {split:<9} on {ds}  {n:>3} occasions{warn}")

    lines += ["", "distinct code versions these runs span:"]
    for sha in sorted({e.git_sha for e in entries}):
        subj = next((e.subject for e in entries if e.git_sha == sha), "")
        lines.append(f"  {sha}  {subj[:70]}")
    return "\n".join(lines)
