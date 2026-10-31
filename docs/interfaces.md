# Interfaces: how the pieces fit together

Models live in `src/kiln/schemas.py`; owners are in `AGENTS.md`. **Build the 11 AM vertical slice first**: one development item through every step below.

## Flow for one item in one run
1. **Hemanath** `kiln.data.load_items(split) -> list[Item]`: pair, temperature, melting points. Never labels.
2. **CJ** `kiln.board.Board(run_dir)`:
   - `post_artifact(a: Artifact)`, `post_need(n: Need)`
   - `open_needs(item_id, types) -> list[Need]`, `claim(need_id, agent) -> bool` (one winner), `fulfill(need_id, artifact_id)`
   - `accepted_artifacts(item_id) -> list[Artifact]`
   Files: `runs/<run_id>/board/artifacts.jsonl`, `needs.jsonl`.
3. **Adhi** `kiln.budget.Budget(config)`: `charge_tool_call()`, `charge_tokens(in, out)`, `charge_compute(units)`, `remaining()`. Raises `BudgetExceeded`. Every agent and the compute client go through it.
4. Compute service: **CJ** owns `kiln.compute.client.request(item, agent, tier, reason, inputs, budget) -> ComputeRequest` (routing, caching, request log, health check); **Adhi** owns what runs behind it: `kiln.compute.tiers` (single point, bounded relaxation), `kiln.compute.convergence`, `kiln.compute.energy_reference` (Materials Project 2020 correction), `kiln.compute.decomposition` (decomposition-aware re-evaluation), prices from `kiln.compute.profiling`, totals from `kiln.compute.accounting`:
   - calls Adhi's budget gate to charge the frozen tier price **before** running (even on cache hits), then serves from cache or runs on the GB10;
   - tiers: `cached_lookup`, `single_point`, `bounded_relaxation` (force + stress criteria, step cap), `decomposition_reeval`;
   - returns `status` ok / cached / not_converged / failed, `result`, measured `gpu_seconds`;
   - the caller fills `p_react_before` / `p_react_after` by calling Hemanath's `score.provisional(...)` before and after;
   - appends to `runs/<run_id>/compute_requests.jsonl`.
   Health check: `kiln.compute.client.healthy() -> bool`. Same API on the GB10 and the Brev backup.
5. **Annamayya** specialists subclass `kiln.agents.base.Agent` (CJ) and implement `step(item, board, budget)`:
   - **Thermo:** starts with `cached_lookup`; escalates to `single_point` or `bounded_relaxation` only by its escalation rule; answers `firm_up_energy` and `reaction_energy` needs.
   - **Kinetics:** uses each precursor's `melting_point_c` from `kiln.tools.precursors.props(...)` with `kiln.tools.tammann.tammann_c(...)`; retains its source and semantics alongside the result; posts `firm_up_energy` when the driving force is borderline.
   - **Precursor:** `kiln.tools.precursors.props(formula)` from `data/precursor_props.csv`; when a precursor breaks down below the furnace temperature, requests `decomposition_reeval`.
   Every claim has `falsified_if`; every artifact lists the `compute_requests` it used.
6. **CJ** comparators: `agents/single.py` (C1: one agent, all tools and tiers) and `agents/planner.py` (C3: decides which specialist runs and which compute to buy), same budget.
7. **Hemanath** `kiln.verifier.verify(artifact, board) -> (VerifierStatus, notes)` on every artifact before others can use it.
8. **Annamayya** `kiln.review.flags(item, accepted, requests) -> list[ReviewFlag]`: missing evidence, failed computation, conflict, outside applicability (thresholds from the protocol).
9. **Hemanath** `kiln.scoring.score.score(item, accepted, requests, flags) -> Prediction`, and `score.provisional(item, accepted) -> (p_react, category)` for the before/after log. Fixed rules; never sees labels.
10. **CJ** `kiln.runners.conditions.run(config: RunConfig, items) -> Path` writes `runs/<run_id>/predictions.jsonl`.
11. **Hemanath** `kiln.scoring.evaluate`: hash predictions → post hash → load labels → AUROC on **all** pairs (flagged included), four-class accuracy, Brier, coverage, flagged vs unflagged accuracy, compute-allocation tables; fills `moved_toward_label` on compute requests.
12. **Annamayya** app reads `runs/` and `results/` only.

## Need types
| Need | Asked by | Answered by | Payload |
|---|---|---|---|
| `firm_up_energy` | Kinetics | Thermo (decides which tier) | `{"formula": "CaTiO3", "current_dE_ev_per_atom": -0.04}` |
| `decomposition_products` | Thermo, Kinetics | Precursor | `{"formula": "CaCO3", "temperature_c": 900}` |
| `reaction_energy` | Precursor, Kinetics | Thermo | `{"species": ["CaO", "TiO2"]}` |

## Value keys (units in the name)
`dE_ev_per_atom`, `dE_mlip_minus_mp_ev_per_atom`, `tammann_a_c`, `tammann_b_c`, `decomposes_at_c`, `decomposition_product`, `volatile_above_c`, `melting_point_c`, `melting_point_source`, `melting_point_source_url`, `melting_point_semantics`, `melting_point_semantics_source`, `melting_point_semantics_note`.

`melting_point_semantics` is `as_reported` or `possible_decomposition_or_dehydration`. The second value is a narrow caution for precursor temperatures that could represent decomposition or dehydration in place of melting. It does not remove or replace the dataset's reported temperature. Other value disagreements and phase-form issues are not tagged by this field.

## Run folders
`runs/<run_id>/config.json`, `board/`, `compute_requests.jsonl`, `predictions.jsonl`, `prediction.sha256`, `cost.json`, `verifier.log`.

## Additions since the kit (all on `dev`)
These extend the interfaces above; nothing above was removed. Approved changes are listed in `docs/plan-changes.md`.

- **Budget:** `charge_tokens(tokens_in, tokens_out)` (not `in, out`: `in` is reserved in Python); `record_usd(usd)` records experiment API spend (not capped); `spent` gives a `Cost`.
- **Board:** `Board(run_dir, name="board")` (C2 gives each isolated specialist its own `name`); `new_id(kind)`, `decline(need_id, agent)`, `needs()`, `artifacts()`, `get_need()`, `get_artifact()`. The verifier records a verdict by re-posting the artifact with its new `verifier` status (append-only; the latest record wins).
- **LLM:** `kiln.agents.base.llm_call(prompt, budget, config, *, system="")` and `llm_choose(options, context, budget, config)`: provider from `RunConfig.model` (`gemini-*`, `claude-*`, `gpt-*`, or `offline`), temperature 0, the run's seed, tokens (Gemini thinking included) and dollars charged to the budget. Keys from `GEMINI_API_KEY` (`GEMINI_API_KEY_2` as fallback), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`; a missing key is an error, never a silent switch to `offline`.
- **Tiers (Adhi):** `kiln.compute.tiers.single_point(structures, settings)` and `bounded_relaxation(structures, settings)` return a `TierRun` of per-structure `StructureResult`s (status, energy, max force, max stress, steps) with GPU-seconds. `settings["backend"]` is `"ase"` (default) or `"nvalchemi"`. MLIP tier results also carry `max_abs_phase_mlip_minus_mp_ev_per_atom` (a compute result, not an artifact value key).
- **Energy reference (Adhi):** `kiln.compute.energy_reference.corrected_energy`, `corrected_entry`, `phase_differences`: MLIP energies on the MP2020 scale, ALCHEMI-minus-MP per phase.
- **Decomposition tier (Adhi):** `decomposition_reeval` inputs are `{"precursor_a", "precursor_b", "temperature_c", "properties": {formula: {"decomposes_at_c", "decomposition_product"}}}` (the keys of `data/precursor_props.csv`). A precursor counts as decomposed only if its temperature is known and the furnace is at or above it. The result adds `dE_before_ev_per_atom`, `products_before`, `decomposed`, `decomposition_unknown`, `changed`. The older `{"decomposed": {precursor: product}}` input still works.
- **Profiling and prices (Adhi):** `python -m kiln.compute.profiling --summary <profile.json> --hours H --workers N` writes `protocol/prices_proposal.json` (compute unit = median `single_point` GPU-seconds; per-pair budget = one escalation path; Night 2 fit).
- **Accounting (Adhi):** `python -m kiln.compute.accounting runs/<run>...` writes `results/compute_allocation.json` and `.md`: totals per request, pair and condition, an exact reconciliation of the request log against each prediction's `cost.compute_units`, and the allocation table. `replay_changes(...)` fills "changed a prediction" once OPEN-17 is defined.
