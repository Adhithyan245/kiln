# Kiln and existing methods

How Kiln compares with existing methods for predicting solid-state reactions (Adhi, Oct 31 2026, before the Night 2 freeze). Kiln's own scores come after the held-out predictions are hashed and graded, so this compares designs, not results. Figures for other methods come from their abstracts.

## The short version

- **No published score exists on our task.** The Precursor Genome paper (1,035 pairs, 46 precursors) is a dataset paper and reports no predictive baselines. The literature rules we compare against are our own baselines B0 (driving force) and B0-T (Tammann ratio), run on the same held-out pairs (protocol §4.2).
- **Kiln's combination:** for one pair at one temperature it gives a four-class outcome, a cause and a fix, flags weak evidence, buys GPU calculations only where they can change the answer, and is graded on predictions hashed before grading.
- **Where others are ahead:** literature retrieval, physics-based kinetics, finite-temperature energies. Retrieval is left out on purpose: A-Lab outcomes are public, so it could look up the answers.

## Existing approaches

| Approach | Question it answers | Limit for our task |
|---|---|---|
| Driving-force rule (our B0) | Does the pair react? (MP reaction energy at 0 K ≤ 0) | Ignores temperature, mobility and decomposition; 38% of development pairs have exactly 0 |
| Tammann ratio (our B0-T) | Is the furnace hot enough for atoms to move? | Partly circular: the dataset set many furnace temperatures from the same melting points (456 of 981 items) |
| 60 meV competition margin (Szymanski et al., Sci. Adv. 2024) | Which product forms first? | Not a does-it-react rule; used only as a regime marker and for the hard subset |
| ARROWS3 (Szymanski et al., Nat. Commun. 2023) | Which precursors make a target? | Needs experiments in the loop and a target phase |
| Reaction network (McDermott et al., Nat. Commun. 2021) | Which pathway does a synthesis take? | Thermodynamics only; built for routes to targets |
| Kinetics-aware pathway model (Berkeley Lab, Nature Materials 2026) | What forms, including impurities? | Trained only on Ba–Ti–O so far |
| LLMs with retrieval and tools (Prein et al., AI4MAT @ ICLR 2026) | Which precursors are used for a target? | Different task; retrieval raised top-10 accuracy 77.0% → 83.5%, tools alone 80.6%, and sequential multi-agent workflows often lowered accuracy |
| ML synthesizability models (assessed by Schlesinger et al., 2026) | Can this material be made at all? | Found to over-predict synthesis; per material, not per pair and temperature |

## Where Kiln is weaker, and how the design answers it

| Weaker | Answer |
|---|---|
| No literature retrieval (the biggest gain in the 2026 LLM benchmark) | Left out to avoid leaking public A-Lab outcomes; listed as an after-event ablation with a leakage guard |
| Kinetics is the Tammann rule only | Stated as a limit; a physics-based kinetics model is after-event work |
| Energies at 0 K, no gas or temperature terms (CaCO3 about 0.9 eV off in our check) | Gas/temperature plan waits on the chemistry expert (`docs/gas-thermo-plan.md`) |
| Multi-agent workflows can propagate early errors (2026 LLM benchmark) | Agents never set numbers and every artifact passes the verifier (rules 7–9); C4 is graded against C1, C2 and C3 on the same budget, so harm from coordination would show |

## Improvements and their status

See `docs/plan-changes.md` for approvals. In short: the secondary binary split is built (row 26); the review-flag change, the `p_react`/category question and a boundary-centred escalation window wait on decisions; the H100 reproducibility check and the finite-temperature ranking are secondary results; retrieval, physics-based kinetics, gas terms and a hybrid ALCHEMI-then-ASE relaxation are after-event work.

## Sources

1. Walters, McDermott et al., [The Precursor Genome](https://arxiv.org/abs/2607.09903), arXiv 2607.09903 (2026).
2. Szymanski et al., [Autonomous and dynamic precursor selection for solid-state materials synthesis](https://www.nature.com/articles/s41467-023-42329-9) (ARROWS3), Nature Communications 14, 6956 (2023).
3. McDermott, Dwaraknath and Persson, [A graph-based network for predicting chemical reaction pathways in solid-state materials synthesis](https://pmc.ncbi.nlm.nih.gov/articles/PMC8149458), Nature Communications 12, 3097 (2021).
4. Szymanski et al., Science Advances 10(27), 2024, DOI 10.1126/sciadv.adp3309.
5. Prein et al., [Benchmarking Augmentation Strategies for LLM-Based Solid-State Synthesis Prediction](https://iclr.cc/virtual/2026/10019924), AI4MAT @ ICLR 2026.
6. Schlesinger, Hjaltason, Szymanski and Bartel, [Thermodynamic assessment of machine learning models for solid-state synthesis prediction](https://arxiv.org/abs/2602.04075), arXiv 2602.04075 (2026).
7. [AI models atom movement to predict solid-state reaction pathways](https://phys.org/news/2026-08-ai-atom-movement-solid-state.html), Phys.org on the Berkeley Lab study (Nature Materials, 2026).
