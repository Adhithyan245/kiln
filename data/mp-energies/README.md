# Energies-only Materials Project cache

One JSON file per chemical system (the 702 pair systems of the 46 precursors). Each entry keeps only composition, uncorrected energy, MP2020 correction and Materials Project id: no structures. Written by `python -m kiln.recipe --compact-cache data/mp-energies` from `cache/mp/`. The recipe finder's screen gives the same results from it as from the full cache. The MACE check needs the full cache, which is not committed.

Data from the [Materials Project](https://materialsproject.org) (A. Jain et al., APL Materials 1, 011002, 2013), licensed CC BY 4.0. Used here for the post-study recipe finder only.
