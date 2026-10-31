# Approved changes to the plan

**The plan is the Final Build Plan (ScienceClaw 2026) plus every change listed here.** A change in the "Approved" table is part of the plan, not a deviation: build on it. Anything in "Proposed, not approved" is **not** in scope: don't build it, and stop and ask if a task seems to need it. Add a row here (with who approved it) whenever the team agrees a change, in the same commit as the change.

## Approved

| # | Change from the original plan | Approved by | Where it lives |
|---|---|---|---|
| 1 | **Roles:** Adhi D = Compute Science (tiers, convergence, energy reference, decomposition, budget, profiling, accounting); CJ B = Infrastructure & Integration (client and service, MP cache, need board, agents base, runners, night runner); Annamayya C adds the app; Hemanath A adds the public-repo checklist | Team (updated kit) | `AGENTS.md` ownership, `prompts/*.md` |
| 2 | **Credits:** every credit has a job. Claude replication (~120 held-out pairs, 1 seed) and the N2 probe on an OpenAI model run as **secondary results**, reported separately; the main C1–C4 table is Gemini only | Adhi | `AGENTS.md` rule 11, `docs/credits.md` |
| 3 | **Branches:** `dev` takes direct pushes (no PR); no force-push or deletion of `dev`; `main` changes only through a PR from `dev`, merged by Adhi | Adhi | `AGENTS.md` rule 5, `.github/workflows/guard-branches.yml` |
| 4 | **Branch protection** by the guard workflow, because GitHub rulesets need Pro on a private repo; rulesets replace it once the repo is public | Adhi | `docs/github-setup.md` |
| 5 | **MACE precision: float32** (same energies as float64 to 1 µeV/atom on the GB10, about 20% faster, NVIDIA's verified setting) | Adhi | `env/gb10/tier_settings.json`, `docs/compute-decisions.md` §1 |
| 6 | **Experiment LLM: `gemini-3.8-flash`** for every condition and seed; `gemini-3.1-flash-lite` is the fallback if the spend check after 20 runs is high. `gemini-2.5-flash` is closed to new users | Adhi | `docs/compute-decisions.md` §2, `src/kiln/night/plans/night2.toml` |
| 7 | **Compute backend:** ASE (`FrechetCellFilter` + FIRE2) is the default. The ALCHEMI Toolkit backend (`backend: "nvalchemi"`) is built and verified against it (within 0.02 meV/atom) but not the default: on 40 structures it was 1.3x faster yet left 3 of 40 relaxations unconverged | Adhi | `docs/compute-decisions.md` §3, `results/gb10/nvalchemi_*.json` |
| 8 | **Phase set for the MLIP tiers:** the phases the a-b reaction energy depends on (decomposition along the a-b line, reactants, elemental references), plus near-hull competitors on that line up to `max_structures`. Reproduces the MP reaction energy exactly | Adhi | `src/kiln/compute/tiers.py` `_phase_set`, `docs/compute-decisions.md` §4 |
| 9 | **Hull window: 0.1 eV/atom, one value**, for near-hull competitors and for Thermo's "product near the hull" escalation trigger. B60meV (60 meV/atom) is a different quantity and stays separate | Adhi (to freeze in the protocol: Hemanath) | `docs/compute-decisions.md` §4, `docs/escalation-rule.md` |
| 10 | **Baselines, proposal 0001 accepted:** B0-T is the T_dwell / T_melt(higher) ratio; B60meV is a competition-margin feature and regime marker (no `p_react`, not a condition); a hard subset (margin < 60 meV/atom, or a carbonate, hydroxide or ammonium precursor) is fixed before labels load and reported next to all-pairs metrics. Thresholds stay OPEN-25 | Adhi (merged) | `protocol/proposals/0001-*.md`, `src/kiln/baselines/b0.py`, `src/kiln/scoring/evaluate.py` |
| 11 | **Profiling without the ledger:** the GB10 profiles from an agent-visible items file (`--items-file`, made with `--export-items --skip-missing-temperature`). The ledger never goes to the GB10. Skipping records with no temperature is for profiling only; it does not decide OPEN-13 | Team | `src/kiln/compute/profile.py`, `docs/gb10-runbook.md` |
| 12 | **Remote GB10 access** over Tailscale in userspace mode (no `sudo`, home folder only), to be stopped after judging | CJ, Adhi | `env/gb10/tailscale.sh` |
| 13 | **LLM accounting:** Gemini thinking tokens count as output tokens (billed, and against the per-item token cap); prices for Gemini, Claude and OpenAI models are in `PRICES_USD_PER_MTOK` | Adhi | `src/kiln/agents/base.py` |
| 14 | **Code freeze time** is the team's own deadline (plan §8), not the organizers'. It may move to at most 8:30 PM if the team agrees, so Night 2 still finishes by about 8 AM | Team decision needed to move it | — |
| 15 | **Night 2 operator: Adhi** (CJ's laptop can't reach the GB10 remotely). The run stays on the GB10 in `tmux`; results come back through Adhi's laptop because the GB10 can't push to GitHub; Hemanath scores off the GB10 on Sunday morning (labels never go to the GB10). Held-out items come from the agent-visible items file (346 items: held-out records with no temperature are skipped, pending OPEN-13) | Adhi, CJ | `docs/night2-runbook.md` |
| 16 | **Relaxation tier:** element references get a single point (relaxing molecular solids such as O2 doesn't converge and isn't meaningful); a near-hull competitor that doesn't converge is dropped and listed; a request is `not_converged` only if a reactant or a product along the a-b line fails | Adhi | `src/kiln/compute/tiers.py`, `docs/compute-decisions.md` |

## Proposed, not approved (don't build)

| Proposal | Status | Where |
|---|---|---|
| **Thermo escalation rule** (default rule with logged override; same rule for every condition) | Waiting on Annamayya (Thermo) and Hemanath (thresholds in the protocol) | `docs/escalation-rule.md` |
| **Gas release and temperature:** ΔG(T) with experimental gas free energies, a computed decomposition check, calibrated against known decompositions first (a first check on CaCO3 was about 0.9 eV off) | Waiting on the chemistry expert's review; evidence and flags only if approved | `docs/gas-thermo-plan.md` |
| **"Changed a prediction" (OPEN-17)** definition for the accounting replay | Waiting on Hemanath's definition and frozen scoring rules | `src/kiln/compute/accounting.py` `replay_changes` |
| **Thinking-token cap for Gemini** (to control Night 2 cost) | Waiting on CJ and Hemanath | — |
| **Add-ons in CJ's plan** (Glass/MD, Skeptic, extra families beyond item 2) | Outside rule 11; not approved | `docs/plans/cj-kiln-v2.md` |
