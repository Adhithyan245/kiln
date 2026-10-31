# Thermo's GPU escalation rule (proposal)

Proposed by Adhi (D, Compute Science) on Saturday Oct 31 for **Annamayya** to implement in `src/kiln/agents/thermo.py` and **Hemanath** to freeze in `protocol/protocol.md` at the 7 PM code freeze. Nothing here is in effect until both say yes. Numbers marked *proposed* are placeholders until development profiling.

## The rule

Thermo always starts with the cheapest evidence, `cached_lookup` (Materials Project energies). It escalates to a GB10 tier only when that verdict is **fragile**:

| Escalate when | To |
|---|---|
| (a) the reaction driving force is borderline: \|ΔE_rxn\| ≤ **T_rxn** (*proposed* 0.05 eV/atom), or | `single_point` (MACE energy of every candidate phase) |
| (b) a candidate product lies within **0.08 eV/atom of the hull, including on it** (0 ≤ E_hull ≤ 0.08) | `single_point` |
| the `single_point` result still leaves (a) or (b) true, **or** \|ΔE_mlip − ΔE_mp\| > **T_disagree** (*proposed* 0.05 eV/atom) | `bounded_relaxation` (force **and** stress criteria, step cap) |

Otherwise Thermo stops: the cheap answer is not going to flip.

**Default, not a cage.** The rule is Thermo's default. The agent may deviate (skip or add a request) only with a one-sentence logged reason in the compute request's `reason` field. This keeps the decision an agent's decision, which is what the experiment measures.

**Fairness.** The same rule text, thresholds and override allowance go to every condition that has a thermodynamics role: C1's single agent, C2's isolated Thermo, C3's planner when it buys compute, and C4. Otherwise C4 vs C1 compares rules, not coordination.

## Why 0.08 eV/atom (say this, not "k_BT")

- Most experimentally known metastable inorganic compounds sit within about 0.1 eV/atom of the convex hull (Sun et al., *Science Advances*, 2016, "The thermodynamic scale of inorganic crystalline metastability"). **Check the exact figures in the paper before quoting them on a slide.**
- Within that window, energy differences are comparable to the errors of DFT (GGA/GGA+U) and of MLIPs, so an independent energy estimate can change which phase wins. Far outside it, a second estimate almost never changes the verdict.
- Phases **on** the hull (E_hull = 0) are included: Materials Project energies can be wrong too, and "computed energies were wrong" is one of the failure causes in our pitch.
- Keep one window across the code. `env/gb10/tier_settings.json` currently selects candidate phases with `ehull_max_ev_per_atom: 0.1`; the protocol should freeze one value (0.08 or 0.1) and both places should use it (CJ / Adhi).

## What not to claim

- **Not** "within k_BT, thermal fluctuations decide." At 700–1,200 °C, k_BT is about 84–127 meV per particle, and it is not directly comparable with E_hull; finite-temperature stability depends on entropy (TΔS) and kinetics.
- **Not** "where static 0 K DFT fails." A MACE relaxation is also a static 0 K calculation. It gives a **second, independent energy and a relaxed structure**, not temperature effects.

## What the GB10 buys, honestly

A second, independent 0 K energy (MACE-MPA-0) on the Materials Project scale (MP2020 correction applied), plus a relaxed structure with honest convergence status. Every request logs `dE_mlip_minus_mp_ev_per_atom`; a disagreement above the protocol threshold raises a `conflict` review flag (Annamayya's `kiln.review.flags`).

**Judge answer:** "It spent 8 GPU-seconds because the product was within 80 meV/atom of the hull, where DFT and MLIP errors are large enough to change the answer, so a second method was worth paying for. Here's the logged before and after, and whether it changed the prediction."

## Decisions needed

| # | Decision | Who |
|---|---|---|
| 1 | Adopt the rule in Thermo, with the logged-override default | Annamayya |
| 2 | Freeze T_rxn, the hull window (0.08 or 0.1) and T_disagree in the protocol | Hemanath, from Adhi's profiling |
| 3 | Same rule for C1, C2 and C3's thermodynamics decisions | CJ (runners), Annamayya |
| 4 | One hull window in `tier_settings.json` | CJ, Adhi |
