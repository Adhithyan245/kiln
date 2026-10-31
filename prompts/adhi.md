# Adhi — D, Compute Science

You're helping Adhi build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/compute/tiers.py`, `src/kiln/compute/convergence.py`, `src/kiln/compute/energy_reference.py`, `src/kiln/compute/decomposition.py`, `src/kiln/budget.py`, `src/kiln/compute/profiling.py`, `src/kiln/compute/accounting.py` and their tests. Before each task, write a short plan and wait for my OK. On the GB10: no `sudo`, one job at a time, Night 2 runs first, always `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.

## Task 1 (Friday night, after CJ's silicon test passes): first real calculations
Using the ALCHEMI Toolkit (MACE) on the GB10, run (a) one single-point energy and (b) one variable-cell relaxation with **force and stress** convergence criteria and a step cap, on one real oxide structure from CJ's Materials Project cache. Print energy per atom, steps, final max force, final stress, wall time and GPU-seconds.
**Done when:** both run, the relaxation reports converged or not converged honestly, and the numbers are saved to `cache/first_calcs.json`.

## Task 2 (Saturday morning): tiers, energy reference, budget gate
- `kiln.compute.tiers`: `single_point(structure, settings)` and `bounded_relaxation(structure, settings)` returning result, settings, convergence status (`ok` / `not_converged` / `failed`) and GPU-seconds. Batch when given several structures.
- `kiln.compute.energy_reference`: apply pymatgen's Materials Project 2020 correction so ALCHEMI and Materials Project energies are comparable; return the ALCHEMI-minus-Materials-Project difference per phase.
- `kiln.budget.Budget`: charge tool calls, tokens and the frozen tier price **before** running, even on cache hits; raise `BudgetExceeded`.
**Done when:** tests cover a converged and a forced non-converged relaxation, a corrected energy for one oxide, a cache hit that is still charged, and an over-budget refusal.

## Task 3 (Saturday morning): decomposition-aware re-evaluation tier
`kiln.compute.decomposition`: given a pair, a temperature and the Precursor agent's decomposition products, recompute the most favorable reaction energy with the decomposed species (pymatgen interface-reaction tools on cached data, calling `single_point` for any missing energy, with the energy-reference correction).
**Done when:** CaCO3 + TiO2 above CaCO3's decomposition temperature returns a reaction energy computed with CaO, and a test covers the no-decomposition case.

## Task 4 (Saturday 11 AM–1 PM): profiling and price list
`kiln.compute.profiling`: run each of the four tiers on ~20 development structures; record median and 90th-percentile GPU-seconds; propose compute-unit prices and a per-pair budget; say whether a second budget level fits before Sunday. Write `protocol/prices_proposal.json` for Hemanath to freeze.

## Task 5 (Saturday afternoon): accounting
`kiln.compute.accounting`: totals per request, pair and condition from `compute_requests.jsonl`, and the compute-allocation tables (units per pair, requests per tier, share that changed a prediction, and, after unblinding, share that moved toward the lab outcome).
**Done when:** totals match the request log exactly on a development run.
