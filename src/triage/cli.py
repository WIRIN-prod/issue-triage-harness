"""Service entry point: triage one issue. `python -m triage.cli <url|number|file>`

The harness exercises the service in bulk; this is the single-issue path a human
actually uses, and the one SPEC.md §6 documents. It prints the decision plus what the
call cost, because a service that cannot report its own cost cannot be priced (§4.2).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from graph.retrieve import Context, GraphIndex, retrieve
from graph.vocab import Vocabulary, build as build_vocab

from .configs import CONFIGS, get
from .agent import triage

DATA = Path("data")
GRAPH = DATA / "graphs" / "litellm-raw.json"
REPO_DIR = DATA / "repos" / "litellm"
DEFAULT_REPO = "BerriAI/litellm"


def _fetch_issue(repo: str, number: int) -> tuple[str, str]:
    from harness.settings import github_token

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{number}",
        headers={"Authorization": f"Bearer {github_token()}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "issue-triage-harness"})
    with urllib.request.urlopen(req) as r:
        d = json.load(r)
    return d["title"] or "", (d.get("body") or "")[:20_000]


def resolve_issue(target: str) -> tuple[int, str, str]:
    """Accept a GitHub URL, a bare issue number, or a local JSON/text file."""
    if m := re.match(r"https?://github\.com/([^/]+/[^/]+)/issues/(\d+)", target):
        repo, number = m.group(1), int(m.group(2))
        title, body = _fetch_issue(repo, number)
        return number, title, body

    if target.isdigit():
        title, body = _fetch_issue(DEFAULT_REPO, int(target))
        return int(target), title, body

    path = Path(target)
    if not path.is_file():
        raise SystemExit(f"not a URL, issue number, or readable file: {target}")
    if path.suffix == ".json":
        d = json.loads(path.read_text())
        return int(d.get("number", 0)), d.get("title", ""), d.get("body", "")
    text = path.read_text()
    title, _, body = text.partition("\n")
    return 0, title.strip(), body.strip()


def _context(title: str, body: str, budget: int) -> Context | None:
    if not GRAPH.exists() and not GRAPH.with_suffix(".json.gz").exists():
        print("note: no repo graph found — running without context "
              "(`python -m graph.build` to create one)", file=sys.stderr)
        return None
    index = GraphIndex(GRAPH, repo_root=str(REPO_DIR))
    vocab: Vocabulary = build_vocab(REPO_DIR, DEFAULT_REPO, "658f5066")
    return retrieve(index, vocab, title, body, budget_tokens=budget)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="triage", description="Triage one GitHub issue.")
    p.add_argument("target", help="GitHub issue URL, bare issue number, or a local file")
    p.add_argument("--config", default="baseline",
                   help=f"one of: {', '.join(sorted(CONFIGS))}")
    p.add_argument("--json", action="store_true", help="emit the full run envelope")
    args = p.parse_args(argv)

    number, title, body = resolve_issue(args.target)
    config = get(args.config)
    ctx = _context(title, body, config.context_budget_tokens) if config.context == "graph" else None
    run = triage(number, title, body, config, ctx)

    if args.json:
        print(run.model_dump_json(indent=1))
        return

    if run.error:
        print(f"FAILED after {run.attempts} attempt(s): {run.error}", file=sys.stderr)
        raise SystemExit(1)

    d = run.decision
    print(f"#{number}  {title[:88]}")
    print(f"  category     {d.category}")
    print(f"  urgency      {d.urgency}")
    print(f"  needs_human  {d.needs_human}")
    if d.rationale:
        print(f"  rationale    {' '.join(d.rationale.split())[:300]}")
    print()
    print(f"  config       {config.name} [{run.config_hash}] {run.model}")
    ctx_note = ("none" if run.context_empty
                else f"{run.context_tokens} tokens"
                + (f" from {', '.join(ctx.modules[:2])}" if ctx and ctx.modules else ""))
    print(f"  context      {ctx_note}")
    print(f"  cost         ${run.cost_usd:.6f}"
          f"{'' if run.cost_reported else '  (gateway reported none)'}")
    print(f"  tokens       {run.tokens_in} in / {run.tokens_out} out")
    print(f"  latency      {run.latency_ms} ms"
          f"{'' if run.attempts == 1 else f'  ({run.attempts} attempts)'}")


if __name__ == "__main__":
    main()
