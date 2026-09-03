"""Harness CLI. `python -m harness.cli <command>`"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph import vocab as V
from graph.build import LITELLM, EXPECTED_GRAPH_SHA256
from graph.retrieve import GraphIndex
from triage.config import TriageConfig
from triage.configs import LABELLER, TIERS

from . import github, labelling
from .dataset import Dataset

DATA = Path("data")
POOL = DATA / "issues" / "litellm-pool.json"
GRAPH = DATA / "graphs" / "litellm-raw.json"
REPO_DIR = DATA / "repos" / "litellm"
DATASET = DATA / "dataset" / "gold.json"
RUBRIC = Path("docs/rubric.md")

STRATIFY_CONFIG = TriageConfig(
    name="stratify", model=TIERS["cheap"][0], rationale_mode="off", context="graph",
)
GOLD_CONFIG = TriageConfig(
    name="gold", model=LABELLER, rationale_mode="pre", context="graph",
)


def _load_env():
    issues = github.load(POOL)
    index = GraphIndex(GRAPH, repo_root=str(REPO_DIR))
    voc = V.build(REPO_DIR, LITELLM.owner_repo, LITELLM.commit[:8])
    return issues, index, voc


def cmd_estimate(args):
    issues, index, voc = _load_env()
    ctx = labelling._contexts(issues, index, voc, STRATIFY_CONFIG.context_budget_tokens)
    fired = sum(1 for c in ctx.values() if not c.is_empty)

    stratify = labelling.estimate_cost(
        issues, ctx, TIERS["cheap"][1], TIERS["cheap"][2],
        prompt_tokens=len(STRATIFY_CONFIG.prompt_text) // 4, out_tokens=30)
    sample = issues[: args.n]
    gold = labelling.estimate_cost(
        sample, ctx, 2.0, 10.0,
        prompt_tokens=len(GOLD_CONFIG.prompt_text) // 4, out_tokens=220)

    print(f"pool: {len(issues)} issues · context fires on {fired} "
          f"({100*fired//len(issues)}%)\n")
    print(f"stage 1 stratify  {STRATIFY_CONFIG.model}")
    print(f"  {stratify['issues']} issues · {stratify['est_tokens_in']:,} in / "
          f"{stratify['est_tokens_out']:,} out · ${stratify['est_usd']}")
    print(f"stage 2 gold      {GOLD_CONFIG.model}")
    print(f"  {gold['issues']} issues · {gold['est_tokens_in']:,} in / "
          f"{gold['est_tokens_out']:,} out · ${gold['est_usd']}")
    print(f"\ntotal estimate: ${round(stratify['est_usd'] + gold['est_usd'], 4)}")


def cmd_label(args):
    issues, index, voc = _load_env()
    ctx = labelling._contexts(issues, index, voc, STRATIFY_CONFIG.context_budget_tokens)

    def progress(stage):
        def show(n, total):
            if n % 25 == 0 or n == total:
                print(f"\r  {stage}: {n}/{total}", end="", flush=True, file=sys.stderr)
        return show

    print(f"stage 1 — stratifying {len(issues)} issues with {STRATIFY_CONFIG.model}",
          file=sys.stderr)
    coarse = labelling.run_pass(issues, labelling.ModelLabeller(STRATIFY_CONFIG), ctx,
                                workers=args.workers, on_progress=progress("stratify"))
    spent = sum(r.cost_usd for r in coarse)
    failed = sum(1 for r in coarse if r.error)
    print(f"\n  done · ${spent:.4f} · {failed} failed", file=sys.stderr)

    chosen, cells = labelling.select_stratified(coarse, args.n)
    print(f"\nstage 1 cells (target {args.n}):", file=sys.stderr)
    for k, v in cells.items():
        print(f"  {k:<20} {v}", file=sys.stderr)

    sample = [i for i in issues if i.number in set(chosen)]
    labeller = (labelling.FileLabeller(Path(args.from_file)) if args.from_file
                else labelling.ModelLabeller(GOLD_CONFIG))
    print(f"\nstage 2 — gold labels for {len(sample)} issues with {labeller.name}",
          file=sys.stderr)
    gold = labelling.run_pass(sample, labeller, ctx, workers=args.workers,
                              on_progress=progress("gold"))
    gold_spent = sum(r.cost_usd for r in gold)
    print(f"\n  done · ${gold_spent:.4f}", file=sys.stderr)

    ds = labelling.build_dataset(
        sample, gold, labeller.name, LITELLM.owner_repo, LITELLM.commit,
        EXPECTED_GRAPH_SHA256, github.WINDOW, RUBRIC)
    ds.save(DATASET)
    print(json.dumps({**ds.summary(), "spend_usd": round(spent + gold_spent, 4),
                      "path": str(DATASET)}, indent=1))


def cmd_dataset(args):
    ds = Dataset.load(DATASET)
    print(json.dumps(ds.summary(), indent=1))
    print("\ncells:")
    for k, v in ds.cells().items():
        print(f"  {k:<20} {v}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("estimate", help="dry-run cost, no API calls that spend")
    e.add_argument("-n", type=int, default=100)
    e.set_defaults(func=cmd_estimate)

    l = sub.add_parser("label", help="two-stage labelling -> frozen dataset")
    l.add_argument("-n", type=int, default=100, help="gold set size")
    l.add_argument("--workers", type=int, default=6)
    l.add_argument("--from-file", help="JSONL of out-of-band labels instead of the frontier model")
    l.set_defaults(func=cmd_label)

    d = sub.add_parser("dataset", help="summarise the frozen dataset")
    d.set_defaults(func=cmd_dataset)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
