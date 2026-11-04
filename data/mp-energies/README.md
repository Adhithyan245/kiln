# Energies-only Materials Project cache

One gzipped JSON file per chemical system: 2,524 systems, every candidate pair system of the 159 precursors in `data/precursor_props_extended.csv` (the first 702 are the pair systems of the study's 46 precursors). Each entry keeps only composition, uncorrected energy, MP2020 correction and Materials Project id: no structures. The original 702 were written by `python -m kiln.recipe --compact-cache` from `cache/mp/`; the other 1,822 were fetched in the same form (GGA/GGA+U thermo type, all subsystems) with `mp_api`. `kiln.recipe` reads `.json` and `.json.gz` alike, and the screen gives the same results from this cache as from the full one. The MACE check needs the full cache, which is not committed.

Data from the [Materials Project](https://materialsproject.org) (A. Jain et al., APL Materials 1, 011002, 2013), licensed CC BY 4.0. Used here for the post-study recipe finder only.
