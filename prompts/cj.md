# CJ — B, Compute

You're helping CJ build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/compute/`, `src/kiln/tools/mp.py`, `src/kiln/night/`, `env/gb10/`, `cache/` and their tests. Before each task, write a short plan and wait for my OK.

**GB10 rules:** no `sudo`, nothing outside the home folder, don't register it into Brev, always `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.

## Task 1 (Friday night): GB10 readiness and Materials Project cache
Build the environment from NVIDIA's kit lock file (`kit/dgx-spark/results/alchemi-requirements.lock`): `uv` inside a venv, `~/alchemi/venv` with `--managed-python --python 3.12.16`, install with `--torch-backend cu130 --index-strategy unsafe-best-match`. Save commands to `env/gb10/setup.sh`. Then `kiln.tools.mp`: cache Materials Project phases within ~100 meV/atom of the stability line for every pair's chemical system.
**Done when:** `alchemi-mlip-test.py mace_si out.jsonl` gives about **−5.41238 eV/atom in about 61 steps** (post it in the NVIDIA thread), and the cache loads for all development pairs.

## Task 2 (Saturday morning): compute service with four tiers
`kiln.compute.client.request(...)` and a service on the GB10: `cached_lookup`, `single_point` (ALCHEMI MACE), `bounded_relaxation` (variable-cell, force **and** stress criteria, hard step cap), `decomposition_reeval`. Charge the price **before** running, even on cache hits; cache by `(tier, inputs, settings)`; log every `ComputeRequest`; return `not_converged` / `failed` honestly; `healthy()` check; same API on Brev as backup. Apply the Materials Project 2020 correction before comparing ALCHEMI and Materials Project energies.
**Done when:** each tier runs on 5 development structures, a cache hit is still charged, and a forced non-convergence returns `not_converged`.

## Task 3 (Saturday late morning): profiling and price list
Measure median GPU-seconds per tier on development pairs; propose compute-unit prices and a per-pair budget; note whether a second budget level would fit before Sunday.

## Task 4 (Saturday afternoon): night runner and NVIDIA benchmark
Resumable night runner (Section 8a of the plan): retries with backoff, hard caps, Discord alerts from `KILN_ALERT_WEBHOOK`, prediction hash posted before scoring, push results, stop Brev. Then a GB10 benchmark table (cells, atoms, seconds, peak memory) for multi-element oxides and carbonates, for NVIDIA.
