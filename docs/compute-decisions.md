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

## 3. Open

- Hull window: `tier_settings.json` uses 0.1 eV/atom, `docs/escalation-rule.md` proposes 0.08; freeze one value.

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
