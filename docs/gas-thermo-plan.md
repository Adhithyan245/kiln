# Kiln: accounting for gas release and temperature (plan for expert review)

**From:** Adhi (Kiln, compute science) · **Status:** proposal, not built · **Date:** Sat Oct 31

## The gap you pointed out

Kiln's reaction energies are 0 K energies (Materials Project DFT, and the MACE machine-learned potential). Many precursors release a gas when heated: carbonates give CO2, hydroxides give H2O, ammonium salts give NH3, nitrates give NOx. Gas release is driven mostly by entropy (the TΔS term in ΔG = ΔH − TΔS), which a 0 K energy leaves out. So:

- a carbonate such as CaCO3 looks stable at any temperature, and
- reactions that release a gas look less favourable than they really are at furnace temperature.

## What Kiln already does

- **A Precursor specialist** checks each precursor at the furnace temperature against a property table in which every value has a source: decomposition temperature, decomposition product, volatility.
- **If a precursor decomposes below the furnace temperature**, the reaction is recomputed with what it becomes. On real Materials Project data, CaCO3 + TiO2 has no favoured reaction as written, while CaO + TiO2 forms CaTiO3 at about −133 meV/atom.
- **The gap:** this relies on the table (an unknown temperature means "not decomposed"), and the energies themselves still ignore gas entropy.

## What we propose to build

**1. Temperature-dependent free energies, with gases included.**
- Solids: Gibbs free energy at temperature from the SISSO descriptor (Bartel et al., *Nat. Commun.* 2018, as implemented in pymatgen), from the DFT formation enthalpy, valid 300–2000 K.
- Gases: experimental Gibbs free energies (pymatgen's built-in data covers CO2, CO, H2O, NH3, NO, NO2, N2O, SO2, H2S, HCl, HF and others).
- Gas partial pressure as a setting: ΔG = ΔG° + RT ln p, for firing in air, inert flow or 1 atm.

**2. A computed decomposition check for each precursor.** The temperature at which its decomposition (for example CaCO3 → CaO + CO2) becomes favourable at the chosen atmosphere. It is used to fill gaps in the sourced table (labelled "computed, not sourced") and to cross-check sourced values.

**3. The pair's reaction free energy at the furnace temperature**, with gas products allowed to leave, reported next to the 0 K value. Where the two disagree in sign, the pair gets a "needs review" flag.

## A first sanity check, which failed and so shapes the plan

| CaCO3 → CaO + CO2 | Experiment | Our first computed value |
|---|---|---|
| At 1 atm CO2 | about 1170 K (~900 °C) | not favourable below 1500 K |
| In air (pCO2 ≈ 4×10⁻⁴ atm) | lower; roughly 800–900 K | about 1300 K (~1030 °C) |

The computed ΔG of decomposition is about 0.9 eV per CaCO3 too high, which we attribute to combining the experimental CO2 free energy with a GGA-based carbonate formation enthalpy (a class with known DFT errors). So:

**4. Calibration comes before any use.** We benchmark the computed decomposition temperature against well-known single-precursor decompositions (carbonates such as CaCO3, SrCO3, BaCO3, Li2CO3, MgCO3; hydroxides such as Mg(OH)2 and Ca(OH)2; an ammonium salt), using literature values with sources. Then:

- report the error per chemical class;
- apply a computed value only for classes where it agrees with experiment within an agreed tolerance;
- elsewhere, stay with the sourced table and flag "unknown" honestly.

If calibration fails broadly, a fallback is experimental thermochemistry (ΔH°f and S° from a standard compilation) for the precursors that have it, instead of the DFT + descriptor estimate.

## What it will and won't change, and when

- **Tonight (before our 7 PM protocol freeze):** extra evidence and review flags only. Predictions still come from the scoring rules frozen in our protocol, so nothing pre-registered changes meaning.
- **Not in this version:** volatility and evaporation (no vapour-pressure data in our sources; it stays table-based), kinetics of decomposition (onset vs equilibrium, heating rate), and using ΔG(T) inside the scoring.
- **Wording:** computed decomposition temperatures are estimates with a measured error, never presented as measured values.

## Questions for you

1. **Atmosphere:** is air the right default for the furnace firings in the Precursor Genome, or is it inert flow? It shifts carbonate decomposition by hundreds of degrees.
2. **Onset vs equilibrium:** for the decomposition check, should we compare against the equilibrium temperature (ΔG = 0) or a typical onset temperature, given real heating rates?
3. **Tolerance:** what agreement with experiment (for example ±50 °C or ±100 °C) would make a computed decomposition temperature useful to you?
4. **Fallback data:** which experimental thermochemistry source do you trust for precursors (for example NIST-JANAF, or Barin's tables)?
5. **Coverage:** beyond carbonates, hydroxides and ammonium salts, which gas-releasing precursor classes matter most to you (nitrates, oxalates, acetates, sulfates)?
