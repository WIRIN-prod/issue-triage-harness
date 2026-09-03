"""Pull a candidate pool of issues from GitHub.

Scoped to issues created shortly before the pinned commit (see `WINDOW`). The graph
is a snapshot at one SHA; an issue from 2024 references modules that have since moved
or been deleted, so retrieval would fail on it for reasons that have nothing to do
with retrieval quality. Restricting the window keeps the context experiment measuring
what it claims to measure — and matches how triage actually works, on incoming issues
against the code as it stands today.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic import BaseModel, Field

from . import settings

API = "https://api.github.com"
REPO = "BerriAI/litellm"
WINDOW = "2026-06-01..2026-09-03"   # three months up to the pinned commit date
BODY_CAP = 20_000                    # a few issues paste entire logs

# Bot-authored issues are automation talking to itself, not triage inputs.
BOT_SUFFIXES = ("[bot]", "-bot")
BOT_LOGINS = {"dependabot", "github-actions", "renovate", "codecov-commenter", "sweep-ai"}


class Issue(BaseModel):
    number: int
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    author: str
    state: str
    created_at: str
    comments: int
    url: str

    @property
    def is_bot(self) -> bool:
        low = self.author.lower()
        return low in BOT_LOGINS or low.endswith(BOT_SUFFIXES)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {settings.github_token()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "issue-triage-harness",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _to_issue(raw: dict) -> Issue:
    return Issue(
        number=raw["number"],
        title=raw["title"] or "",
        body=(raw.get("body") or "")[:BODY_CAP],
        labels=[l["name"] for l in raw.get("labels", [])],
        author=(raw.get("user") or {}).get("login", "unknown"),
        state=raw["state"],
        created_at=raw["created_at"],
        comments=raw.get("comments", 0),
        url=raw["html_url"],
    )


def fetch_pool(repo: str = REPO, window: str = WINDOW, max_issues: int = 1000) -> list[Issue]:
    """Search returns issues only (never PRs) and caps at 1000 results per query."""
    out: list[Issue] = []
    query = f"repo:{repo} type:issue created:{window}"
    for page in range(1, 11):
        params = urllib.parse.urlencode(
            {"q": query, "per_page": 100, "page": page, "sort": "created", "order": "desc"}
        )
        data = _get(f"{API}/search/issues?{params}")
        items = data.get("items", [])
        out.extend(_to_issue(i) for i in items)
        if len(items) < 100 or len(out) >= max_issues:
            break
        time.sleep(2.1)   # authenticated search allows 30/min
    return out[:max_issues]


def save(issues: list[Issue], path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([i.model_dump() for i in issues], indent=1))
    return {"path": str(path), "count": len(issues)}


def load(path: Path) -> list[Issue]:
    return [Issue(**d) for d in json.loads(Path(path).read_text())]
