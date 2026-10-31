"""Night runner: resumable, capped, alerted overnight jobs (plan §4, prompts/cj.md Task 4).

    python -m kiln.night run src/kiln/night/plans/night2.toml --dry-run

Plans live in `plans/`. Labels never reach the run host before the predictions manifest hash is
posted: Night 2 preflights for an absent labels/ folder, and label steps need a matching receipt.
"""
from kiln.night.plan import Plan, PlanError, Step, load_plan
from kiln.night.runner import NightReport, NightRunner

__all__ = ["NightReport", "NightRunner", "Plan", "PlanError", "Step", "load_plan"]
