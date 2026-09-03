"""The frozen, hashed evaluation dataset.

Frozen because a set that changes mid-comparison makes two runs incomparable while
still looking comparable. Hashed because the harness must be able to *refuse* that
comparison rather than rely on anyone remembering (SPEC.md §5.4).

The hash covers more than the items. What "correct" means here is a function of the
rubric that produced the labels and the repo graph the labeller saw, so both are part
of the dataset's identity — change either and the labels mean something different.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from triage.models import TriageDecision

Split = Literal["dev", "holdout"]


class GoldItem(BaseModel):
    issue_number: int
    title: str
    body: str
    url: str = ""
    maintainer_labels: list[str] = Field(default_factory=list)

    gold: TriageDecision
    labeller: str                      # model id, or "human"
    split: Split = "dev"

    # human verification (SPEC.md §5.4) — populated for the sampled subset only
    verified: bool = False
    human_label: TriageDecision | None = None
    disputed: bool = False

    # what the labeller saw, so a mismatch is detectable later
    context_empty: bool = True
    context_tokens: int = 0


class Dataset(BaseModel):
    repo: str
    commit: str
    graph_sha256: str
    rubric_version: str
    rubric_sha256: str
    labeller: str
    window: str
    items: list[GoldItem]

    # --- identity ---------------------------------------------------------

    def content_hash(self) -> str:
        payload = {
            "repo": self.repo,
            "commit": self.commit,
            "graph_sha256": self.graph_sha256,
            "rubric_sha256": self.rubric_sha256,
            "items": [
                {
                    "n": i.issue_number,
                    "gold": i.gold.model_dump(exclude={"rationale"}),
                    "split": i.split,
                    "disputed": i.disputed,
                }
                for i in sorted(self.items, key=lambda x: x.issue_number)
            ],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    # --- views ------------------------------------------------------------

    def split_items(self, split: Split | None = None) -> list[GoldItem]:
        return [i for i in self.items if split is None or i.split == split]

    def undisputed(self, split: Split | None = None) -> list[GoldItem]:
        return [i for i in self.split_items(split) if not i.disputed]

    def cells(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.items:
            key = f"{i.gold.category}/{i.gold.urgency}"
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))

    def summary(self) -> dict:
        verified = [i for i in self.items if i.verified]
        return {
            "hash": self.content_hash(),
            "items": len(self.items),
            "dev": len(self.split_items("dev")),
            "holdout": len(self.split_items("holdout")),
            "verified": len(verified),
            "disputed": sum(1 for i in self.items if i.disputed),
            "context_fired": sum(1 for i in self.items if not i.context_empty),
            "categories": {
                c: sum(1 for i in self.items if i.gold.category == c)
                for c in ("bug", "feature", "docs", "question", "security")
            },
            "needs_human": sum(1 for i in self.items if i.gold.needs_human),
        }

    # --- persistence ------------------------------------------------------

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = self.model_dump(mode="json")
        blob["_content_hash"] = self.content_hash()
        path.write_text(json.dumps(blob, indent=1))
        return path

    @classmethod
    def load(cls, path: Path) -> Dataset:
        raw = json.loads(Path(path).read_text())
        stated = raw.pop("_content_hash", None)
        ds = cls(**raw)
        if stated and stated != ds.content_hash():
            raise ValueError(
                f"dataset at {path} has been edited in place: file says {stated}, "
                f"contents hash to {ds.content_hash()}. Corrections go into a new "
                f"version — editing invalidates every result already computed against it."
            )
        return ds


def rubric_fingerprint(path: Path) -> tuple[str, str]:
    text = Path(path).read_text()
    version = "unknown"
    for line in text.splitlines():
        if line.startswith("**Version"):
            version = line.split("**")[1].replace("Version", "").strip()
            break
    return version, hashlib.sha256(text.encode()).hexdigest()[:16]
