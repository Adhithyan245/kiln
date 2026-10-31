"""python -m kiln.night run <plan.toml> [--dry-run] [--state-dir DIR] [--runs-dir runs] [--repo-root .]

Meant to run inside tmux on the GPU host. Exit code 0 only if every step finished.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kiln.night.alerts import Alerter, webhook_poster
from kiln.night.plan import load_plan
from kiln.night.runner import NightRunner


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m kiln.night")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("plan")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--state-dir")
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--repo-root", default=".")
    args = p.parse_args(argv)

    plan = load_plan(args.plan)
    state_dir = Path(args.state_dir or Path(args.runs_dir) / "_night" / plan.name)
    alerter = Alerter(state_dir / "alerts.log", webhook_poster(), plan.name)
    runner = NightRunner(plan, state_dir, repo_root=args.repo_root, runs_dir=args.runs_dir, alerter=alerter)
    if args.dry_run:
        print("\n".join(runner.dry_run()))
        return 0
    report = runner.run()
    for name, status in report.status.items():
        print(f"{name}: {status}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
