# Recipe finder: learned ranking

Post-hackathon work, not part of the pre-registered study. Kiln's outcome labels are never used.

## Question

Given a target compound, does the recipe finder put the precursor pair chemists actually used first?

## Data

- **Recipes:** the text-mined solid-state synthesis dataset (Kononova et al., *Sci. Data* 6, 203, 2019, CC BY 4.0), 31,782 recipes. Kept: two-precursor recipes with simple formulas whose precursors are both in the pool, with one benchmark item per target. Each item lists every published pair and uses the median of the recipes' maximum heating temperatures, or 900 °C if none was recorded. Built by `python -m kiln.recipe_benchmark build` into `data/recipe-benchmark.jsonl`.
- **Precursor pool:** 159 precursors, listed in `data/precursor_props_extended.csv`.
  - The study's 46 are copied verbatim; `data/precursor_props.csv` is unchanged.
  - 113 are added: the precursors most often used in the dataset that the study lacked.
  - Melting points, decomposition points and volatility come from web research, and every value keeps its source URL. A value without a source is recorded as `unknown`.
- **Energies:** Materials Project, GGA/GGA+U, every subsystem of each candidate pair's chemical system. That is 2,524 systems, gzipped into `data/mp-energies`. All candidate systems were fetched, not only those of the published pairs, so the candidate lists are not biased toward hits.
- **Split:** 50/50 by a sha256 hash of the target's chemical system, so dev and test share no chemical system. That gives 1,422 targets: 733 dev and 689 test. Only targets with at least two fully screened candidates and a published pair among them are scored: 438 dev and 371 test. On average a target has 7.7 candidates.

## Model

`kiln.recipe_rank` is a pairwise logistic ranker in numpy with L2 regularization. It is fitted only on dev, tuned by 5-fold cross-validation inside dev (folds by chemical system), and scored once on test. Features are standardized, and the weights below are per standard deviation:

| feature | weight | meaning |
|---|---|---|
| log_popularity_min | +0.82 | how often the rarer precursor appears in dev-split recipes (the scored target's own recipes left out) |
| n_carbonate | +0.34 | carbonates in the pair |
| gas_per_atom | −0.32 | gas released per reactant atom |
| decomposes_below_T | −0.28 | precursors that decompose below the furnace temperature |
| dG | +0.26 | driving force estimate (eV/atom) |
| melts_below_T | +0.26 | precursors that melt below the furnace temperature (flux-like) |
| n_hydroxide | −0.25 | hydroxides in the pair |
| volatile | −0.20 | volatility flags |
| dE_0K | +0.19 | 0 K reaction energy |
| n_salt | −0.18 | nitrates, phosphates and ammonium salts in the pair |
| below_tammann | −0.11 | furnace below both Tammann temperatures |
| n_oxide | +0.10 | plain oxides in the pair |
| T_over_Tmelt_min, n_peroxide, precursor_e_hull_max, no_driving_force | close to 0 | |

A positive weight on dG means that, other things equal, a pair with a *smaller* driving force ranks higher. The model is not saying that weaker reactions work better. Very exothermic pairs tend to be peroxides, hydroxides and salts, which labs avoid.

## Results

Mean reciprocal rank (MRR) of the best published pair, and top-1 (the published pair ranked first):

| | dev (CV, n=438) | test (once, n=371) |
|---|---|---|
| random order | 0.49 | 0.45 |
| driving force (the screen alone) | 0.31 | 0.29 (top-1 6%) |
| learned ranker | 0.90 | **0.87 (top-1 78%)** |

Ablations on dev, cross-validated:

| | MRR |
|---|---|
| all 16 features | 0.900 |
| the 12 original features | 0.896 |
| without popularity | 0.856 |
| the 12 original features, without popularity | 0.818 |
| popularity alone | 0.869 |

Popularity carries the most signal. The physical features still beat random by a wide margin without it, and the four thermal features from the researched table help most when popularity is missing, which is the case that matters for rarely used precursors.

## Limits

- The ranking predicts what chemists tend to use, which is not proof that a pair reacts best. Text-mined recipes reflect habit and cost as well as chemistry.
- Pairs only. Doped and non-stoichiometric targets, about 30% of the dataset's simple targets, are not in Materials Project and cannot be screened.
- Precursors with no Materials Project entry are shown but not ranked; most of these are acetates and oxalate hydrates.
- With `KILN_RECIPE_CHECK=1` the server uses the full structure cache, which covers only the study's 46 precursors, and falls back to ordering by driving force.
