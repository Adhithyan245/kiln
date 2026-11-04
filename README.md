# Kiln

Kiln is a system that predicts whether two precursor chemicals will react in a furnace, and it only spends expensive computing where that is worth it.

**The problem.** Labs waste days trying precursor pairs that never react. Running heavy simulations on every pair is too costly, so the real question is where extra computation actually pays off.

**How it works**

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

The question is whether coordination adds measurable accuracy for the same spend. The protocol (`protocol/protocol.md`) was frozen and its hash posted (Gate P) before any held-out run, and the scoring code refuses to read labels until the prediction file's hash has been posted.

**Related work.** Kiln does not claim its coordination method is new: it builds on multi-agent science systems such as AutoScientists and the ScienceClaw + Infinite framework this hackathon is built around. Prior work on solid-state synthesis prediction (ARROWS3, reaction networks, LLM and ML synthesis predictors) is summarised with sources in `docs/related-work.md`.

Built at the ScienceClaw hackathon (MIT Media Lab, Oct 30–Nov 1, 2026) by Adhi, Hemanath, CJ and Annamayya.

For contributors: project rules for every coding assistant in `AGENTS.md`, shared formats in `docs/interfaces.md`, branching in `docs/github-setup.md`, first tasks in `prompts/`.

## Results (Night 2, real compute)

**Pre-registered verdict (protocol §8):** the primary endpoint is ΔAUROC = AUROC(C4) − AUROC(C1), averaged over 3 seeds. It is **+0.013**, so **"C4 ranked better than C1 on this held-out set."** All three seeds agree in sign (the seed spread is about 0.001). As pre-registered (OPEN-15), **no confidence interval or significance test is reported**: every pair belongs to two precursor clusters (a crossed design), and no resampling scheme has been validated for overlapping clusters. So no difference is called significant or general.

H100 run with the NVIDIA ALCHEMI Toolkit, on the **301 held-out pairs that every run had finished** (a 16:15 UTC copy, declared in `protocol/amendments.md` before scoring; predictions hash posted to #kiln-receipts as message `1566485753733578907` before grading; all 12 files match). Mean of 3 seeds:

| Condition | AUROC | Brier ↓ | 4-class accuracy | Compute units per run |
|---|---|---|---|---|
| C1 single agent | 0.713 | 0.173 | 0.388 | 55 |
| C2 isolated specialists | 0.726 | 0.168 | 0.386 | 4,352 |
| C3 central planner | 0.722 | 0.170 | 0.383 | 2,598 |
| **C4 collective** | **0.726** | **0.168** | 0.386 | 4,352 |

**Full run, all 346 held-out pairs** (reported separately, as declared in `protocol/amendments.md`; never pooled with the table above). The run finished at 16:58 UTC with every pair predicted by its run (none filled in by `finalize`); predictions hash `cf6699f7…` posted to #kiln-receipts as message `1566496777790554284` before grading and checked against Discord by the scorer. Mean of 3 seeds; 335 of 346 pairs have a scoreable outcome:

| Condition | AUROC | Brier ↓ | 4-class accuracy | 4-class macro-F1 | Compute units per run | GPU-seconds per run |
|---|---|---|---|---|---|---|
| C1 single agent | 0.728 | 0.182 | 0.388 | 0.180 | 63 | 72 |
| C2 isolated specialists | 0.739 | 0.177 | 0.388 | 0.186 | 5,135 | 9,364 |
| C3 central planner | 0.736 | 0.178 | 0.386 | 0.181 | 2,909 | 6,066 |
| **C4 collective** | **0.739** | **0.177** | 0.388 | 0.186 | 5,135 | 6,829 |

ΔAUROC(C4 − C1) on the full set is **+0.011** (seeds +0.012, +0.012, +0.010), the same sign and size as the declared result above. Both tables agree; neither has a confidence interval.

**What it means:**
- C4 and C2 are identical, so coordination through the need board changed no decisions.
- The specialist conditions spent about 80× the compute units of the single agent (C2 and C4 ran a MACE relaxation on 47% of pairs and a single point on 51%; C1 ran a relaxation on none and a single point on 6%) for a small AUROC gain. **The single agent reaches about 98% of the AUROC at about 1% of the compute.** GPU-seconds differ between C2 and C4 only because later runs reused cached calculations; the charged compute units are identical.
- Four-class accuracy (about 0.39) is **below** always answering "unreacted" (about 0.41 to 0.42, since that is the most common outcome), and macro-F1 is about 0.18: the models mostly predict "unreacted". Use AUROC (ranking) for claims, not the four-class result.
- Scores and logs: `results-h100-cut/` and `runs-h100-cut/` (declared result), `results-h100/` and `runs-h100/` (full run).

**Integrity: locked before we looked.**
- The protocol was hashed and posted before any held-out run: Gate P commit `c283468`, `protocol.md` digest `3ca68ee1…`.
- Every prediction set was hashed and posted before grading.
- The evaluator refuses to read labels until it verifies the posted hash.
- **The first GB10 run silently used the stub compute backend** (`KILN_COMPUTE_BACKEND` defaulted to `stub`). We found it from the compute logs (`"model": "stub"`), not from the scores, and declared it invalid in `protocol/amendments.md` before scoring the H100 run. The runners now fail closed on a stub or unset backend, and the app refuses to show stub runs. The invalid run is kept, byte-exact, in `stub-invalid-20261101/`.
- A GB10 (DGX Spark) rerun with real compute is a **partial replication only** (all three C1 seeds complete, C2–C4 partial, `runs/`); it is never used to choose or replace the results above.

## Try it

- **App: https://port8080-y5rt4kh4nk91y1g.tunnel.applications.uk-south2.nebius.cloud/** (a Nebius Serverless AI endpoint). It replays any recorded held-out pair step by step from the real H100 run: agent decisions, GPU calculations, convergence, and the result with review flags.
- **Live demo: http://81.85.1.97/** (a Nebius CPU VM). A pair that isn't recorded runs live through the real agents (Gemini) and MACE on CPU; a lookup-only pair takes under a minute, a relaxation several minutes. Live runs are demonstrations, not part of the evaluated results.

Run it yourself (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
uv sync && uv run pytest                                      # install and run the tests
python3 app/server.py                                         # the app (replay), http://127.0.0.1:8080
python -m kiln.night run src/kiln/night/plans/night2.toml     # a night run; see docs/night-runner-walkthrough.md
```

Deployment (Nebius serverless endpoint, VM, Docker): `docs/deploy.md`. GPU host readiness check (setup, known-answer test, canary that refuses stub compute): `env/gb10/ready.sh`.

### Recipe finder (after the hackathon, unvalidated)

The study asks "will these two precursors react?". The recipe finder turns it around: **name a target compound and a furnace temperature, and get the precursor pairs ranked**, with the compute each ranking cost. It is the "screen everything cheaply, spend GPU only where it changes the answer" result put to work. It is **not part of the pre-registered study**. Its ranking is checked against published recipes (below), not against Kiln's own outcome labels.

```bash
uv run python -m kiln.recipe BaTiO3 --temp 900                       # rank pairs from the 46 precursors
uv run python -m kiln.recipe BaTiO3 --temp 900 --learned --cache-dir data/mp-energies   # 159 precursors, learned ranking
uv run python -m kiln.recipe LiMn2O4 --temp 800 --check 3 --device cpu   # MACE-check close calls
uv run python -m kiln.recipe --compact-cache cache/mp-energies        # 23 MB energies-only cache for a server
```

1. **Candidates:** every pair of the 46 precursors that balances to the target, with C, H and N leaving as CO₂, H₂O and N₂ and O₂ exchanged with the air.
2. **Screen (0.1 units each, the frozen `cached_lookup` price):**
   - the reaction energy from Materials Project, plus the gas entropy (−T·S°, NIST-JANAF) at the furnace temperature;
   - whether the target is stable, and its likely byproducts: the phases it sits between on the hull;
   - the Tammann check;
   - decomposition and volatility from `data/precursor_props.csv`.
3. **Check (1 unit each, MACE):** only leading candidates within 0.05 eV/atom of each other, where a better energy could change the order. A clear leader costs no GPU at all.
4. **Learned ranking (`--learned`, and the app):** the screened pairs are ordered by a small pairwise logistic model (`kiln.recipe_rank`, 16 interpretable features: driving force, 0 K energy, precursor stability, precursor families, gas released, Tammann and volatility flags, melting and decomposition points against the furnace temperature, and how often each precursor appears in published recipes). It is fitted on the text-mined solid-state synthesis dataset (Kononova et al., *Sci. Data* 2019, CC BY 4.0) over 159 precursors (`data/precursor_props_extended.csv`, values sourced per row) and 2,524 Materials Project systems (`data/mp-energies`), with a 50/50 dev/test split by chemical system (`data/recipe-benchmark.jsonl`). On the 371 held-out test targets with several screenable pairs, scored once, the published pair ranks first **78%** of the time (MRR 0.87), against 6% (MRR 0.29) for ranking by driving force alone and MRR 0.45 at random. Driving force alone is worse than random because it favours energetic, gas-releasing precursors that labs rarely use. Details: `docs/recipe-ranking.md`.

The app's **Recipe finder** page does the same, and links a recipe to Kiln's recorded study run when that pair was in the held-out set. The server uses the committed `data/mp-energies` with the learned ranking, or `cache/mp` (full, 46 precursors) when the MACE check is allowed with `KILN_RECIPE_CHECK=1`. Limits: pairs only, 159 precursors, solid entropy left out, and the ranking says what chemists tend to use, which is not proof that a pair reacts.

**Built with:** NVIDIA ALCHEMI Toolkit (every GPU calculation in the H100 result, inside the agent loop), NVIDIA DGX Spark (GB10: profiling, dry runs, replication), MACE-MPA-0, Gemini 3.8 Flash (agent decisions), Nebius (serverless endpoint, VM, container registry), the Materials Project, pymatgen and ASE.

## Data and license

- **Code:** MIT License (`LICENSE`).
- **Data:** this project evaluates on *The Precursor Genome: A Pairwise Reaction Dataset for Solid-State Synthesis* (Walters, McDermott et al., [arXiv:2607.09903](https://arxiv.org/abs/2607.09903), 2026; data on [Zenodo](https://zenodo.org/records/21285546) and [GitHub](https://github.com/lauren-walters/precursor-genome)). The dataset is not redistributed here and stays under its own terms; experimental outcome labels never enter this repository. The one exception is `data/heldout-conditions.jsonl`: the furnace conditions of the 346 held-out pairs (precursors, temperature, dwell time and melting points; no outcomes), so the app can show each recorded run's temperature and its temperature what-if. Thermochemistry comes from the [Materials Project](https://materialsproject.org); precursor melting points and decomposition temperatures in `data/precursor_props.csv` carry per-row source citations.
