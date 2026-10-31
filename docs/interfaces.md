# Interfaces: how the pieces fit together

Models live in `src/kiln/schemas.py`; owners are in `AGENTS.md`. **Build the 11 AM vertical slice first**: one development item through every step below.

## Flow for one item in one run
1. **Hemanath** `kiln.data.load_items(split) -> list[Item]`: pair, temperature, melting points. Never labels.
2. **Adhi** `kiln.board.Board(run_dir)`:
   - `post_artifact(a: Artifact)`, `post_need(n: Need)`
   - `open_needs(item_id, types) -> list[Need]`, `claim(need_id, agent) -> bool` (one winner), `fulfill(need_id, artifact_id)`
   - `accepted_artifacts(item_id) -> list[Artifact]`
   Files: `runs/<run_id>/board/artifacts.jsonl`, `needs.jsonl`.
3. **Adhi** `kiln.budget.Budget(config)`: `charge_tool_call()`, `charge_tokens(in, out)`, `charge_compute(units)`, `remaining()`. Raises `BudgetExceeded`. Every agent and the compute client go through it.
4. **CJ** compute service, `kiln.compute.client.request(item, agent, tier, reason, inputs, budget) -> ComputeRequest`:
   - charges the frozen tier price **before** running (even on cache hits), then serves from cache or runs on the GB10;
   - tiers: `cached_lookup`, `single_point`, `bounded_relaxation` (force + stress criteria, step cap), `decomposition_reeval`;
   - returns `status` ok / cached / not_converged / failed, `result`, measured `gpu_seconds`;
   - the caller fills `p_react_before` / `p_react_after` by calling Hemanath's `score.provisional(...)` before and after;
   - appends to `runs/<run_id>/compute_requests.jsonl`.
   Health check: `kiln.compute.client.healthy() -> bool`. Same API on the GB10 and the Brev backup.
5. **Annamayya** specialists subclass `kiln.agents.base.Agent` (Adhi) and implement `step(item, board, budget)`:
   - **Thermo:** starts with `cached_lookup`; escalates to `single_point` or `bounded_relaxation` only by its escalation rule; answers `firm_up_energy` and `reaction_energy` needs.
   - **Kinetics:** `kiln.tools.tammann.tammann_c(...)` for both precursors; posts `firm_up_energy` when the driving force is borderline.
   - **Precursor:** `kiln.tools.precursors.props(formula)` from `data/precursor_props.csv`; when a precursor breaks down below the furnace temperature, requests `decomposition_reeval`.
   Every claim has `falsified_if`; every artifact lists the `compute_requests` it used.
6. **Adhi** comparators: `agents/single.py` (C1: one agent, all tools and tiers) and `agents/planner.py` (C3: decides which specialist runs and which compute to buy), same budget.
7. **Hemanath** `kiln.verifier.verify(artifact, board) -> (VerifierStatus, notes)` on every artifact before others can use it.
8. **Annamayya** `kiln.review.flags(item, accepted, requests) -> list[ReviewFlag]`: missing evidence, failed computation, conflict, outside applicability (thresholds from the protocol).
9. **Hemanath** `kiln.scoring.score.score(item, accepted, requests, flags) -> Prediction`, and `score.provisional(item, accepted) -> (p_react, category)` for the before/after log. Fixed rules; never sees labels.
10. **Adhi** `kiln.runners.conditions.run(config: RunConfig, items) -> Path` writes `runs/<run_id>/predictions.jsonl`.
11. **Hemanath** `kiln.scoring.evaluate`: hash predictions → post hash → load labels → AUROC on **all** pairs (flagged included), four-class accuracy, Brier, coverage, flagged vs unflagged accuracy, compute-allocation tables; fills `moved_toward_label` on compute requests.
12. **Adhi** app reads `runs/` and `results/` only.

## Need types
| Need | Asked by | Answered by | Payload |
|---|---|---|---|
| `firm_up_energy` | Kinetics | Thermo (decides which tier) | `{"formula": "CaTiO3", "current_dE_ev_per_atom": -0.04}` |
| `decomposition_products` | Thermo, Kinetics | Precursor | `{"formula": "CaCO3", "temperature_c": 900}` |
| `reaction_energy` | Precursor, Kinetics | Thermo | `{"species": ["CaO", "TiO2"]}` |

## Value keys (units in the name)
`dE_ev_per_atom`, `dE_mlip_minus_mp_ev_per_atom`, `tammann_a_c`, `tammann_b_c`, `decomposes_at_c`, `decomposition_product`, `volatile_above_c`.

## Run folders
`runs/<run_id>/config.json`, `board/`, `compute_requests.jsonl`, `predictions.jsonl`, `prediction.sha256`, `cost.json`, `verifier.log`.
