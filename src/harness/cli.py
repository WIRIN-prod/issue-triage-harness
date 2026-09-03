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
from triage.configs import CONFIGS, LABELLER, TIERS

from . import github, labelling
from .compare import NotComparable, compare
from .dataset import Dataset
from .metrics import ERROR_UNIT_USD
from .runner import RunRecord, run_config
from .stats import Variance

DATA = Path("data")
POOL = DATA / "issues" / "litellm-pool.json"
GRAPH = DATA / "graphs" / "litellm-raw.json"
REPO_DIR = DATA / "repos" / "litellm"
DATASET = DATA / "dataset" / "gold.json"
RUNS = Path("runs")
CACHE = DATA / "cache"
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
    label_total = stratify["est_usd"] + gold["est_usd"]
    print(f"\nlabelling subtotal: ${round(label_total, 4)}")

    # eval sweep: every named config over the gold set, repeated to measure
    # run-to-run variance (SPEC.md §5.5)
    price = {m: (pin, pout) for m, pin, pout in TIERS.values()}
    per_issue_in = gold["est_tokens_in"] / max(len(sample), 1)
    print(f"\neval sweep — {len(CONFIGS)} configs x {args.n} issues x {args.repeats} repeats")
    sweep = 0.0
    for name, cfg in sorted(CONFIGS.items()):
        pin, pout = price.get(cfg.model, (0.1, 0.4))
        tin = per_issue_in * args.n * args.repeats
        if cfg.context == "none":
            tin *= 0.55                      # context is roughly 45% of the prompt
        if cfg.prompt_version == "v1_terse":
            tin *= 0.75
        tout = {"pre": 230, "post": 120, "off": 20}[cfg.rationale_mode] * args.n * args.repeats
        usd = tin / 1e6 * pin + tout / 1e6 * pout
        sweep += usd
        print(f"  {name:<15}{cfg.model:<30}${usd:>8.4f}")
    print(f"  {'':<45}${sweep:>8.4f}")
    print(f"\nTOTAL (labelling + one full sweep): ${round(label_total + sweep, 4)}")


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
    c1 = labelling.LabelCache(CACHE / "stratify.jsonl", STRATIFY_CONFIG.config_hash)
    if len(c1):
        print(f"  resuming: {len(c1)} already labelled", file=sys.stderr)
    coarse = labelling.run_pass(issues, labelling.ModelLabeller(STRATIFY_CONFIG), ctx,
                                workers=args.workers, on_progress=progress("stratify"),
                                cache=c1)
    spent = sum(r.cost_usd for r in coarse)
    failed = sum(1 for r in coarse if r.error)
    print(f"\n  done · ${spent:.4f} · {failed}/{len(coarse)} failed "
          f"{labelling.error_summary(coarse) or ''}", file=sys.stderr)

    chosen, cells = labelling.select_stratified(coarse, args.n)
    print(f"\nstage 1 cells (target {args.n}):", file=sys.stderr)
    for k, v in cells.items():
        print(f"  {k:<20} {v}", file=sys.stderr)

    sample = [i for i in issues if i.number in set(chosen)]
    labeller = (labelling.FileLabeller(Path(args.from_file)) if args.from_file
                else labelling.ModelLabeller(GOLD_CONFIG))
    print(f"\nstage 2 — gold labels for {len(sample)} issues with {labeller.name}",
          file=sys.stderr)
    c2 = labelling.LabelCache(CACHE / "gold.jsonl", GOLD_CONFIG.config_hash)
    if len(c2):
        print(f"  resuming: {len(c2)} already labelled", file=sys.stderr)
    gold = labelling.run_pass(sample, labeller, ctx,
                              workers=min(args.workers, args.gold_workers),
                              on_progress=progress("gold"), cache=c2)
    gold_spent = sum(r.cost_usd for r in gold)
    gold_failed = sum(1 for r in gold if r.error)
    print(f"\n  done · ${gold_spent:.4f} · {gold_failed}/{len(gold)} failed "
          f"{labelling.error_summary(gold) or ''}", file=sys.stderr)

    ds = labelling.build_dataset(
        sample, gold, labeller.name, LITELLM.owner_repo, LITELLM.commit,
        EXPECTED_GRAPH_SHA256, github.WINDOW, RUBRIC,
        min_success_rate=args.min_success)
    ds.save(DATASET)
    print(json.dumps({**ds.summary(), "spend_usd": round(spent + gold_spent, 4),
                      "path": str(DATASET)}, indent=1))


def cmd_eval(args):
    from triage.configs import get as get_config

    ds = Dataset.load(DATASET)
    _, index, voc = _load_env()
    cfg = get_config(args.config)
    print(f"{cfg.describe()}\n  dataset {ds.content_hash()} split={args.split} "
          f"repeats={args.repeats}", file=sys.stderr)

    paths = []
    for r in range(args.repeats):
        def show(n, total, r=r):
            if n % 20 == 0 or n == total:
                print(f"\r  repeat {r+1}/{args.repeats}: {n}/{total}", end="",
                      file=sys.stderr, flush=True)
        rec = run_config(ds, cfg, index, voc, split=args.split, repeat=r,
                         workers=args.workers, on_progress=show)
        paths.append(str(rec.save(RUNS)))
        print(f"\n  ${rec.total_cost:.4f} · {rec.failures} failed", file=sys.stderr)

    print(json.dumps({"runs": paths}, indent=1))


def cmd_compare(args):
    a, b = RunRecord.load(Path(args.a)), RunRecord.load(Path(args.b))
    variances = None
    if args.repeats_of_a:
        reps = [RunRecord.load(Path(p)) for p in args.repeats_of_a]
        from .compare import METRICS, _score_items
        variances = {
            name: Variance(name, [fn([i for i in r.ok]) for r in reps])
            for name, fn, _ in METRICS
        }
    try:
        print(compare(a, b, unit_usd=args.unit_usd, n_boot=args.boot,
                      variances=variances).render())
    except NotComparable as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        raise SystemExit(2)


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
    e.add_argument("--repeats", type=int, default=3, help="repeats per config, for variance")
    e.set_defaults(func=cmd_estimate)

    l = sub.add_parser("label", help="two-stage labelling -> frozen dataset")
    l.add_argument("-n", type=int, default=100, help="gold set size")
    l.add_argument("--workers", type=int, default=6)
    l.add_argument("--from-file", help="JSONL of out-of-band labels instead of the frontier model")
    l.add_argument("--gold-workers", type=int, default=2,
                   help="frontier labelling concurrency; low, to stay under new-account RPM caps")
    l.add_argument("--min-success", type=float, default=0.95,
                   help="refuse to build a dataset below this label success rate")
    l.set_defaults(func=cmd_label)

    v = sub.add_parser("eval", help="run one config over the dataset")
    v.add_argument("--config", required=True)
    v.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    v.add_argument("--repeats", type=int, default=1)
    v.add_argument("--workers", type=int, default=6)
    v.set_defaults(func=cmd_eval)

    c = sub.add_parser("compare", help="A vs B with confidence intervals")
    c.add_argument("a"); c.add_argument("b")
    c.add_argument("--unit-usd", type=float, default=ERROR_UNIT_USD,
                   help="dollar value of one error weight unit")
    c.add_argument("--boot", type=int, default=10000)
    c.add_argument("--repeats-of-a", nargs="*", default=[],
                   help="other runs of config A, to measure run-to-run noise")
    c.set_defaults(func=cmd_compare)

    d = sub.add_parser("dataset", help="summarise the frozen dataset")
    d.set_defaults(func=cmd_dataset)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
