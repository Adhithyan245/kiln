# AGENTS.md: shared rules for every coding assistant on Kiln

Claude Code, Codex and Gemini CLI all follow this file (Codex reads it directly; Claude Code and Gemini CLI load it through `CLAUDE.md` and `GEMINI.md`, which just import it). It is the **only** copy of the project rules. Change it on `dev` and tell the team.

## The project in six lines
Kiln is an auditable, budget-aware triage system for solid-state reactions. Specialist agents (Thermo, Kinetics, Precursor) decide, for each precursor pair, whether two precursors react at a given furnace temperature, and **when extra computation is worth spending** on the GB10. They coordinate through a shared **need board** with no central planner. Every compute request is priced, logged and checked for whether it changed the prediction. A deterministic **verifier** checks every artifact, fixed **scoring functions** turn accepted evidence into predictions, and **review flags** mark missing, failed or conflicting evidence. We compare the collective with a single agent, isolated specialists and a central planner at one locked budget on the **Precursor Genome** (1,035 A-Lab reactions, split by precursor). The **Kiln Triage** app shows an evidence card for every pair.

## Hard rules (never break these)
1. **Never open, read, print, copy or summarize anything in `labels/`**, and never read the label fields of the Precursor Genome ledger (XRD patterns, refinement results, phase weights, reviewer annotations, reaction category). Only `src/kiln/scoring/evaluate.py`, run after the prediction hash is posted, may read them. If a task seems to need labels, stop and ask.
2. **Never look up experimental outcomes online**: no searching for Precursor Genome results, A-Lab outcomes, or whether specific precursors react. Reading library documentation is fine.
3. **Kiln's own agents get no web access** at runtime. Their only tools are in `src/kiln/tools/` and the compute service.
4. **Never commit secrets**: API keys, webhook URLs, `.env` files, tokens. Read them from environment variables.
5. **Never push to `main`.** Push your work to `dev` (no PR needed). Run `git pull --rebase` before pushing, and never force-push or delete `dev`. Only Adhi merges `dev` into `main`, through a PR.
6. **The GB10 is borrowed:** no `sudo`, no system packages, no changes outside the home folder, don't register it into Brev. Always set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before running PyTorch on it.
7. **LLM agents never set numbers.** They choose what to compute and write rationales; every number in a prediction comes from tool and compute-service outputs through the scoring functions.
8. **All computation goes through the compute service and the budget.** Every request is charged at the frozen price for its tier, **even on a cache hit**, and logged with a reason. Never call ALCHEMI directly from an agent, and never bypass the budget.
9. **Never hide failures.** A non-converged relaxation, an errored request or a missing property is logged as such and raises a review flag; it is never silently replaced or dropped.
10. **Flags are flags.** Never present review flags, scores or stated causes as calibrated probabilities or validated failure causes.
11. **Scope for the first complete experiment is fixed:** no Glass/MD, no extra model families, no additional agents, no live new-candidate mode, and no second budget level unless the team agrees after profiling. The main comparison (C1–C4, all seeds) runs on Gemini only. Two **secondary** results run after it and are always reported separately, never pooled with the main table: a Claude replication on ~120 held-out pairs (1 seed) and the N2 memorization probe on an OpenAI model. Credit use is in `docs/credits.md`.

## How we build
- **The plan is the Final Build Plan plus `docs/plan-changes.md`.** Every change listed there as approved is part of the plan, not a deviation; anything listed as proposed is out of scope until approved. Settings and their evidence are in `docs/compute-decisions.md`. When the team agrees a new change, add a row to `docs/plan-changes.md` in the same commit.
- **One complete example first.** Until the 11 AM Saturday vertical slice works (one development pair through agents → GB10 request → verifier → score → evidence card), prefer wiring things together over adding features.
- Read `docs/interfaces.md`. All data passed between modules uses `src/kiln/schemas.py`. Don't add fields without a commit that updates both files.
- Only edit files in **your own folders** (below). If you need a change elsewhere, ask the owner.
- **Sharing the GB10:** one job at a time; experiment runs (Night 2) take priority over profiling and benchmarks. Check `nvidia-smi` and the team queue before starting a GPU job.
- Start each task by writing a short plan and waiting for the human's OK.

## Ownership
| Folder / file | Owner |
|---|---|
| `src/kiln/data/`, `src/kiln/provenance/`, `src/kiln/verifier/`, `src/kiln/scoring/`, `src/kiln/baselines/`, `data/alab/`, `protocol/` | Hemanath (A — Evaluation) |
| `src/kiln/compute/service.py`, `src/kiln/compute/client.py` (routing, caching, request log, health check), `src/kiln/tools/mp.py`, `src/kiln/board/`, `src/kiln/agents/base.py`, `src/kiln/agents/single.py`, `src/kiln/agents/planner.py`, `src/kiln/runners/`, `src/kiln/night/`, `src/kiln/compute/backends.py`, `src/kiln/compute/cache.py`, `src/kiln/compute/profile.py`, `env/gb10/`, `cache/` | CJ (B — Infrastructure & Integration) |
| `src/kiln/agents/thermo.py`, `src/kiln/agents/kinetics.py`, `src/kiln/agents/precursor.py`, `src/kiln/tools/tammann.py`, `src/kiln/tools/precursors.py`, `src/kiln/review/`, `data/precursor_props.csv`, `app/` | Annamayya (C — Chemistry & Product) |
| `src/kiln/compute/tiers.py` (single point, bounded relaxation), `src/kiln/compute/convergence.py`, `src/kiln/compute/energy_reference.py`, `src/kiln/compute/decomposition.py`, `src/kiln/budget.py`, `src/kiln/compute/profiling.py`, `src/kiln/compute/accounting.py` | Adhi (D — Compute Science) |
| `src/kiln/schemas.py`, `docs/interfaces.md`, `AGENTS.md` | Shared: change only after telling the team |

## Conventions
- Python 3.12, managed with `uv`. Pydantic v2 for all data models. Type hints everywhere.
- Energies in **eV/atom** internally (display meV/atom); temperatures in **°C** in data files, converted to K only inside calculations.
- Board files, compute logs and run outputs are **JSON Lines**, append-only.
- Tests with `pytest` in `tests/`, mirroring the source path. A task is done when its test passes.
- Small commits with clear messages, e.g. `compute: add bounded relaxation tier with stress criterion`.

## Definition of done for any task
1. The stated check passes (a test, a printed number, or a working command).
2. Outputs validate against `src/kiln/schemas.py`.
3. No secrets or label data in the diff.
4. Committed and pushed to `dev` with a clear message.
