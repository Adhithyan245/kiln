# Compute decisions (Adhi, D — Compute Science)

Decisions behind the compute tiers, with the evidence for each. Hemanath freezes the final values in `protocol/protocol.md` at the 7 PM code freeze; until then these are the values every profiling and cache-filling run should use, so the frozen settings match what was measured and cached.

## 1. MACE precision: float32 (decided Sat Oct 31)

| Run (GB10, MACE-MPA-0 medium, TiO2 mp-554278, 12 atoms) | float64 | float32 |
|---|---|---|
| Single point, energy | −8.969708 eV/atom | −8.969708 eV/atom |
| Relaxation, energy | −8.970344 eV/atom | −8.970343 eV/atom |
| Relaxation, steps / max force / max stress | 14 / 0.0046 eV/Å / 0.00099 eV/Å³ | 14 / 0.0046 eV/Å / 0.00099 eV/Å³ |
| Relaxation, GPU-seconds | 1.29 | 1.02 |

Source: `results/gb10/first_calcs_float64.json`, `results/gb10/first_calcs_float32.json` (CJ's run of `docs/gb10-runbook.md` step 1).

- Same answer to 1 µeV/atom, identical convergence, about 20% less GPU time; NVIDIA's verified kit run (silicon known-answer test) also used fp32.
- **Action:** `env/gb10/tier_settings.json` `dtype` → `"float32"` for `single_point` and `bounded_relaxation` (CJ's file) **before** tier profiling and before filling the relaxation cache: the cache key includes the settings, so a float64 fill would not be reused.
- Recheck on the profiling run: if any profiled structure's energy differs by more than 1 meV/atom between precisions, say so before the freeze.

## 2. Experiment LLM: gemini-3.8-flash (recommended Sat Oct 31)

- Tested with the team key: `gemini-3.8-flash`, `gemini-3.1-flash-lite` and `gemini-3-flash-preview` all answer. `gemini-2.5-flash` is closed to new users (API returns 404), so nothing may default to it.
- `gemini-3.8-flash` is the newest Flash model available: the strongest agents at Flash cost. Fallback if the spend check after the first 20 runs (plan Section 11) runs high: `gemini-3.1-flash-lite`.
- The same model for every condition and seed (plan Section 6). The exact model id goes into `RunConfig.model` and the protocol.
- **Training cutoff (for protocol §11, OPEN-04):** Google DeepMind's model card states "The knowledge cutoff date for Gemini 3.8 Flash is March 2026", adding that in some areas its knowledge may be limited to January 2025 (Gemini 3 family). Source: [Gemini 3.8 Flash model card](https://deepmind.google/models/model-cards/gemini-3-8-flash/), published 2 September 2026, read Sat Oct 31. Both dates are before the dataset's publication (The Precursor Genome, 2026-07-09), so the model cannot have seen the paper or its labels. It may still know older published syntheses of some of the same pairs; the cutoff alone doesn't rule that out.

## 3. Open

- None. The hull window is decided below.

## 4. Hull window: 0.1 eV/atom, one value (decided Sat Oct 31)

- `ehull_max_ev_per_atom: 0.1` in `env/gb10/tier_settings.json` now only picks the near-hull competitors (on the a-b line) that an MLIP tier re-ranks; the phases the reaction energy depends on are always included (`_phase_set` in `tiers.py`).
- Thermo's escalation rule (`docs/escalation-rule.md`) uses the same 0.1 for "a product near the hull".
- B60meV (60 meV/atom) is a different quantity, the margin between competing products, and stays separate.
- Evidence for the phase set: on CJ's 20 profiling pairs, required phases are 5 to 12 and the full set 8 to 34 (cap 40, was 75 to 440 entries), and the MP reaction energy matches the whole chemical system exactly on every pair.

## 3. Backend: ASE stays the default; the ALCHEMI Toolkit backend is built and verified (decided Sat Oct 31)

`tiers.py` has `backend: "nvalchemi"`: MACE-MPA-0 through the ALCHEMI Toolkit's `MACEWrapper` (cuEquivariance) and `FIRE2VariableCell`, all structures in one GPU batch, converged by **our** rule (max force norm <= 0.05 eV/Å and max |stress component| <= 0.001 eV/Å³, re-checked per structure). Measured on the GB10, float32:

| Check | Result | Source |
|---|---|---|
| Accuracy vs ASE, 4 real MP structures (TiO2, CaO, CaTiO3, CaCO3) | single points within 0.001 meV/atom, relaxations within 0.017 meV/atom, all converged | `results/gb10/nvalchemi_check.json` |
| Steps per structure, Toolkit defaults (tmax 0.08, maxstep 0.1) | 33 to 123, vs ASE 3 to 14 | GB10 run |
| Steps with tuned settings (tmax 1.0, maxstep 0.2, dt 0.2) | 7 to 74, same energies | GB10 run |
| 40 strained and rattled structures, relaxations | Toolkit batch 15.5 s vs ASE one by one 20.8 s (x1.34), but **3 of 40 hit the 500-step cap** (ASE: 40 of 40 converged) | `results/gb10/nvalchemi_batch40.json` |
| 40 structures, single points | Toolkit 1.76 s vs ASE 1.22 s | same |

- **Decision:** ASE (`FrechetCellFilter` + FIRE2) stays the default for Night 2. A 1.3x speed-up does not justify 3 in 40 relaxations failing to converge, which would become review flags. The gap is the cell algorithm, not throughput: per step both are similar, and the Frechet log-strain cell update converges in far fewer steps.
- To use the Toolkit anyway: `"backend": "nvalchemi"`, plus `"fire_tmax": 1.0, "fire_maxstep": 0.2, "dt": 0.2`. A hybrid (Toolkit batch first, ASE to finish what it leaves unconverged) is the natural next step, after the event.

## 5. Prices and per-item budget: proposed (Sat Oct 31, for Hemanath to freeze)

From the GB10 profiling rerun after the phase-set and relaxation fixes (`results/gb10/profile_s0_fix.json`, 20 dev pairs, float32): compute unit = median `single_point` GPU-seconds (0.50 s); **cached_lookup 0.1, single_point 1, bounded_relaxation 30, decomposition_reeval 0.2**; **32 units per item** (one escalation path, 31.3 rounded up so the whole path fits; was 31, which could not afford the relaxation). Night 2: 346 held-out items x 4 conditions x 3 seeds; with the result cache about **4.3 GPU-hours expected** on one GB10 (7.7 usable), so no Brev workers are needed for the GPU. Full numbers and notes: `protocol/prices_proposal.json`.
