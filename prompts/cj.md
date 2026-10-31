# CJ — B, Infrastructure & Integration

You're helping CJ build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/compute/service.py`, `src/kiln/compute/client.py`, `src/kiln/tools/mp.py`, `src/kiln/board/`, `src/kiln/agents/base.py`, `src/kiln/agents/single.py`, `src/kiln/agents/planner.py`, `src/kiln/runners/`, `src/kiln/night/`, `env/gb10/`, `cache/` and their tests. Before each task, write a short plan and wait for my OK.

**GB10 rules:** no `sudo`, nothing outside the home folder, don't register it into Brev, always `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`. One GPU job at a time; Night 2 runs first.

## Task 1 (Friday night): GB10 readiness, Materials Project cache, need board
Build the environment from NVIDIA's kit lock file (`kit/dgx-spark/results/alchemi-requirements.lock`): `uv` inside a venv, `~/alchemi/venv` with `--managed-python --python 3.12.16`, install with `--torch-backend cu130 --index-strategy unsafe-best-match`. Save commands to `env/gb10/setup.sh`. Run `alchemi-mlip-test.py mace_si out.jsonl` (expect about **−5.41238 eV/atom in about 61 steps**), post it in the NVIDIA thread, and tell Adhi so he can start.
Then `kiln.tools.mp` (phases within ~100 meV/atom of the stability line for every pair's chemical system) and `kiln.board.Board` with `kiln.agents.base.Agent` and two dummy agents exchanging one `firm_up_energy` need.
**Done when:** the silicon test passes, the cache loads for all development pairs, and `pytest tests/board` passes including a two-process claim race.

## Task 2 (Saturday morning): compute service plumbing and the vertical slice
`kiln.compute.client.request(...)` and the service around Adhi's tiers: routing by tier, caching by `(tier, inputs, settings)`, calling Adhi's budget gate before running, appending every `ComputeRequest` to the log, `healthy()`, and the same API on Brev as backup. Then wire the 11 AM vertical slice with the team.
**Done when:** one development item runs end to end and its compute requests appear in the log.

## Task 3 (Saturday afternoon): runners and the NVIDIA benchmark
`kiln.runners.conditions.run` for C1, C2, C3 (central planner) and C4, all with the same budget, compute client and scoring. Resumable night runner (Section 8a of the plan): retries with backoff, hard caps, Discord alerts from `KILN_ALERT_WEBHOOK`, prediction hash posted before scoring, push results, stop Brev. Then run the GB10 benchmark (cells, atoms, seconds, peak memory) for multi-element oxides and carbonates with Adhi's tiers, for NVIDIA.
**Done when:** all four conditions write valid predictions on 5 development items, and a night-runner dry run survives being killed and restarted.
