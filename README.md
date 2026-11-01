# Kiln

Kiln is a system that predicts whether two precursor chemicals will react in a furnace, and it only spends expensive computing where that is worth it.

**The problem.** Labs waste days trying precursor pairs that never react. Running heavy simulations on every pair is too costly, so the real question is where extra computation actually pays off.

**What we're building**

- **Three specialist agents.** Thermo checks the energies, Kinetics checks whether the temperature is high enough, and Precursor checks whether an ingredient breaks down or evaporates first.
- **A shared need board with no central planner.** A specialist posts what it needs, such as a better energy for a pair, and another picks it up.
- **A GPU compute service.** Every request is priced, logged with a reason, and recorded as to whether it changed the prediction.
- **A verifier and fixed scoring rules.** The language model never sets a number. Every number comes from a tool, passes the verifier, and goes through fixed scoring functions.
- **Review flags.** Where evidence is missing, failed or conflicting, the case is marked "needs review", never silently filled in. Flags are prompts for a human, not probabilities or confirmed causes.
- **The Kiln Triage app.** It shows an evidence card for every pair.

**The experiment.** A retrospective evaluation on public data: the Precursor Genome (1,035 pairwise reactions, split by precursor with 9 of 46 precursors held out). At one locked compute budget we compare:

- a single agent,
- isolated specialists,
- specialists that coordinate through the board (the collective),
- a central planner.

The question is whether coordination adds measurable accuracy for the same spend. The protocol (`protocol/protocol.md`) must be frozen and its hash posted before any held-out run, and the scoring code refuses to read labels until the prediction file's hash has been posted.

Built at the ScienceClaw hackathon (MIT Media Lab, Oct 30–Nov 1, 2026) by Adhi, Hemanath, CJ and Annamayya.

- Project rules for every coding assistant (Claude Code, Codex, Gemini CLI): `AGENTS.md`
- Each person's first tasks: `prompts/`
- Shared formats every module must follow: `docs/interfaces.md`
- Branching and protection: `docs/github-setup.md`

Run instructions, results and the demo link are added before the repo goes public on Sunday.

## Data and license

- **Code:** MIT License (`LICENSE`).
- **Data:** this project evaluates on *The Precursor Genome: A Pairwise Reaction Dataset for Solid-State Synthesis* (Walters, McDermott et al., [arXiv:2607.09903](https://arxiv.org/abs/2607.09903), 2026; data on [Zenodo](https://zenodo.org/records/21285546) and [GitHub](https://github.com/lauren-walters/precursor-genome)). The dataset is not redistributed here and stays under its own terms; experimental outcome labels never enter this repository. Thermochemistry comes from the [Materials Project](https://materialsproject.org); precursor melting points and decomposition temperatures in `data/precursor_props.csv` carry per-row source citations.
