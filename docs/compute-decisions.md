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

- `nvalchemi` (ALCHEMI Toolkit) batched backend: to build on the GB10 from the kit's recipe and check against the ASE path (see `src/kiln/compute/tiers.py`).
- Hull window: `tier_settings.json` uses 0.1 eV/atom, `docs/escalation-rule.md` proposes 0.08; freeze one value.
