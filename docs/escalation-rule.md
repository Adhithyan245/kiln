# Thermo's GPU escalation rule (proposal)

Proposed by Adhi (D, Compute Science) on Saturday Oct 31 for **Annamayya** to implement in `src/kiln/agents/thermo.py` and **Hemanath** to freeze in `protocol/protocol.md` at the 7 PM code freeze. Nothing here is in effect until both say yes. Numbers marked *proposed* are placeholders until development profiling.

## The rule

Thermo always starts with the cheapest evidence, `cached_lookup` (Materials Project energies). It escalates to a GB10 tier only when that verdict is **fragile**:

| Escalate when | To |
|---|---|
| (a) the reaction driving force is borderline: \|ΔE_rxn\| ≤ **T_rxn** (*recommended* 0.02 eV/atom from development data, below; was 0.05), or | `single_point` (MACE energy of every candidate phase) |
| (b) a competing phase on the a–b join lies **just above the hull**: 0 < `competitor_e_hull_ev_per_atom` ≤ **0.1** with `competitor_e_hull_status` = `ok` (from `cached_lookup`; `none_on_join` never triggers). The reaction's own products are hull phases (E_hull = 0 by construction), so testing them would fire on every reacting pair | `single_point` |
| the `single_point` result still leaves (a) or (b) true, **or** \|ΔE_mlip − ΔE_mp\| > **T_disagree** (*recommended* 0.05 eV/atom, checked below) | `bounded_relaxation` (force **and** stress criteria, step cap) |

Otherwise Thermo stops: the cheap answer is not going to flip.

**Default, not a cage.** The rule is Thermo's default. The agent may deviate (skip or add a request) only with a one-sentence logged reason in the compute request's `reason` field. This keeps the decision an agent's decision, which is what the experiment measures.

**Fairness.** The same rule text, thresholds and override allowance go to every condition that has a thermodynamics role: C1's single agent, C2's isolated Thermo, C3's planner when it buys compute, and C4. Otherwise C4 vs C1 compares rules, not coordination.

## Why 0.1 eV/atom (say this, not "k_BT")

- Most experimentally known metastable inorganic compounds sit within about 0.1 eV/atom of the convex hull (Sun et al., *Science Advances*, 2016, "The thermodynamic scale of inorganic crystalline metastability"). **Check the exact figures in the paper before quoting them on a slide.**
- Within that window, energy differences are comparable to the errors of DFT (GGA/GGA+U) and of MLIPs, so an independent energy estimate can change which phase wins. Far outside it, a second estimate almost never changes the verdict.
- Phases **on** the hull (E_hull = 0) are included: Materials Project energies can be wrong too, and "computed energies were wrong" is one of the failure causes in our pitch.
- One window across the code (decided by Adhi, Sat Oct 31): **0.1 eV/atom**, the same value `env/gb10/tier_settings.json` uses (`ehull_max_ev_per_atom`) to pick the near-hull competitors an MLIP re-ranks. Hemanath's B60meV (60 meV/atom) is a different quantity, the margin between competing products, and stays separate.

## T_rxn and T_disagree from development data (Adhi, Sat Oct 31, evening)

Development pairs only: no labels, no held-out pair (protocol §11 rule 6). Materials Project reaction energies for all 635 development pairs from the GB10's MP cache; MLIP-minus-MP gaps from the 20 profiled development pairs (`runs/profile-promaxgb10-99ea-s0` on the GB10).

| T_rxn | Development pairs with \|ΔE_rxn\| ≤ T_rxn | Excluding ΔE_rxn = 0 |
|---|---|---|
| 0.01 | 46% | 8% |
| **0.02** | **58%** | **20%** |
| 0.03 | 67% | 29% |
| 0.05 | 78% | 40% |
| 0.10 | 92% | 54% |

- 38% of development pairs have ΔE_rxn = 0 exactly (no product below the join in Materials Project). Non-zero \|ΔE_rxn\|: p25 0.017, median 0.032, p75 0.064 eV/atom.
- **T_rxn 0.02 recommended.** At 0.05, 78% of pairs count as borderline, and a single point rarely moves ΔE by more than 0.02, so most of them also go on to a relaxation: escalation becomes nearly automatic and the conditions stop differing in where they spend compute. 0.02 matches the measured MLIP-vs-MP gap, which is the size of change a second energy can make.
- **T_disagree 0.05 recommended (kept).** \|ΔE_mlip − ΔE_mp\| on the 20 profiled pairs: at most 0.035 eV/atom for single points (0.038 relaxed); 18 of 20 at most 0.017. So 0.05 fires only on a clear disagreement and does not flood the `conflict` review flag. 20 pairs is too few to justify a finer value.
- **Still Annamayya's call:** whether ΔE_rxn = 0 counts as borderline. Counting it is defensible (a near-hull competitor could become stable) but adds 38 percentage points of escalations.

### OPEN-07 decision as proposed (Sat Oct 31, late evening): 0 < \|ΔE_rxn\| ≤ 0.05; ΔE_rxn = 0 alone never recommends escalation

Checked on development data before the freeze (no labels, nothing held-out):

| Development pairs (635) | Count |
|---|---|
| (a) 0 < \|ΔE_rxn\| ≤ 0.05 | 253 (40%) |
| (b) nearest off-hull competitor ≤ 0.1 eV/atom (`competitor_e_hull_ev_per_atom`) | 159 (25%); 59 of them have ΔE_rxn = 0 |
| **Escalation recommended, (a) or (b)** | **360 (57%)** |
| ΔE_rxn = 0 (never recommended by (a)) | 242 (38%) |

**Does escalation change results?** The frozen scoring rules' category boundary is ΔE_rxn ≥ −0.05 → `unreacted` (`no_driving_force`), so a better energy changes a category only if it crosses −0.05; `p_react` (weight −20 per eV/atom) moves continuously either way. On the 20 profiled development pairs (`runs/profile-promaxgb10-99ea-s0`, single points and relaxations), single points moved ΔE_rxn by at most 0.035 eV/atom, and **2 pairs crossed −0.05**:
- PG_2940: −0.046 → −0.053 (single point), −0.055 (relaxation): `unreacted` → driving force. Escalated under (a).
- PG_1048: −0.052 → −0.035: driving force → `unreacted`. **Not** escalated under (a), because \|ΔE_rxn\| = 0.052 > 0.05.

Implication for the record: the window 0 < \|ΔE_rxn\| ≤ 0.05 sits entirely on the `unreacted` side of the scoring boundary. 49 development pairs (8%) lie just past it (−0.07 ≤ ΔE_rxn < −0.05), where a second energy can flip the category but (a) doesn't recommend one; pairs near −0.01 are escalated although a change of this size can't flip their category. A window centred on the boundary, \|ΔE_rxn + 0.05\| ≤ 0.02, recommends 116 pairs (18%; 237 or 37% with (b)) and would have caught both flips. Recorded for the decision owners; nothing here changes the decision. The relaxations in that profiling run predate the gas-molecule fix and are `not_converged`; their energies are shown for comparison only, and 20 pairs is a small sample.

## What not to claim

- **Not** "within k_BT, thermal fluctuations decide." At 700–1,200 °C, k_BT is about 84–127 meV per particle, and it is not directly comparable with E_hull; finite-temperature stability depends on entropy (TΔS) and kinetics.
- **Not** "where static 0 K DFT fails." A MACE relaxation is also a static 0 K calculation. It gives a **second, independent energy and a relaxed structure**, not temperature effects.

## What the GB10 buys, honestly

A second, independent 0 K energy (MACE-MPA-0) on the Materials Project scale (MP2020 correction applied), plus a relaxed structure with honest convergence status. Every request logs `dE_mlip_minus_mp_ev_per_atom`; a disagreement above the protocol threshold raises a `conflict` review flag (Annamayya's `kiln.review.flags`).

**Judge answer:** "It spent 8 GPU-seconds because the product was within 0.1 eV/atom of the hull, where DFT and MLIP errors are large enough to change the answer, so a second method was worth paying for. Here's the logged before and after, and whether it changed the prediction."

## Decisions needed

| # | Decision | Who |
|---|---|---|
| 1 | Adopt the rule in Thermo, with the logged-override default | Annamayya |
| 2 | Freeze T_rxn, the hull window (0.1, proposed by Adhi) and T_disagree in the protocol | Hemanath, from Adhi's profiling |
| 3 | Same rule for C1, C2 and C3's thermodynamics decisions | CJ (runners), Annamayya |
| 4 | One hull window in `tier_settings.json` | CJ, Adhi |
