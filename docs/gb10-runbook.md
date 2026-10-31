# GB10 runbook: Adhi's compute-science runs (for CJ)

Adhi writes the code; CJ runs it on the GB10 and commits the outputs; Adhi reads them and proposes prices. About 30 to 45 minutes of GPU time in total. Run the steps in order and send Adhi a message after each one.

**Before every step:** `nvidia-smi` must show no other job (one GPU job at a time; Night 2 and experiment runs come first). No `sudo`, nothing outside the home folder.

## 0. Once per session

```bash
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
source ~/alchemi/venv/bin/activate
cd ~/kiln && git checkout dev && git pull
mkdir -p results/gb10
```

`MP_API_KEY` must be set for step 1's fetch. Set it without printing it:

```bash
read -rsp "MP key: " MP_API_KEY && export MP_API_KEY && echo
```

## 1. First calculations (Adhi's Task 1), about 3 minutes

```bash
python -m kiln.tools.mp fetch --chemsys Ca-O-Ti
python -m kiln.compute.tiers first-calcs --formula TiO2 --dtype float64 --out results/gb10/first_calcs_float64.json
python -m kiln.compute.tiers first-calcs --formula TiO2 --dtype float32 --out results/gb10/first_calcs_float32.json
```

**Expect:** for each run, two table lines (single point and bounded relaxation), each with a status, energy per atom, max force, max stress, steps, wall time and **non-zero GPU-seconds**. The relaxation may say `not_converged`; that is an honest result, not an error. Energies are near -8.97 eV/atom (what the CPU dry run gave on the same structure, mp-554278).

**Send Adhi:** both printed tables. If anything says `FAILED`, send the error line.

## 2. Tier profiling (Adhi's Task 4), about 15 to 30 minutes

The profiler's backend defaults to `stub`, which gives fake zero timings. **It must be `local` here.**

```bash
export KILN_COMPUTE_BACKEND=local
python -m kiln.tools.mp fetch --all-pairs
python -m kiln.compute.profile --pairs 20 --seed 0 --out results/gb10/profile_s0.json
python -m kiln.compute.profiling --summary results/gb10/profile_s0.json --hours 11 --workers 1 --out protocol/prices_proposal.json
```

- `--all-pairs` and the profiler both read development items through `kiln.data.load_items`, which needs the ledger on this machine. **If the ledger isn't on the GB10** (your `--precursors-file` commit suggests it isn't), tell Adhi: the profiler needs agent-visible development items (formulas and temperatures only) copied here, or a `--items-file` option in `profile.py`. Don't copy the raw ledger: it holds the locked labels.
- `--hours 11` is 7:30 PM to about 6:30 AM. Change `--workers` to the number of GPU workers Night 2 will really have (GB10 plus Brev).

**Expect:** per-tier median and p90 GPU-seconds, then the proposed prices, per-pair budget and whether the main run (and a second budget level) fits Night 2.

**Send Adhi:** the printed proposal. Adhi reviews it before Hemanath freezes anything at 7 PM.

## 3. The kit's ALCHEMI relaxation recipe (for the nvalchemi backend)

Our tiers run MACE through ASE; the NVIDIA prize is judged on using the ALCHEMI Toolkit. The kit's `alchemi-mlip-test.py` (under `~/science-kits-for-agents/kit`) already does a verified nvalchemi relaxation.

**Send Adhi** (privately, not committed: it's NVIDIA's kit file) the part of that script that builds the model wrapper, the batch and the optimizer, and how it handles the cell: fixed or variable, and whether it checks stress.

## 4. Commit the results

```bash
git add results/gb10/ protocol/prices_proposal.json
git commit -m "results: GB10 first calculations and tier profiling"
git pull --rebase && git push
```

`cache/` stays out of git. The files above hold only measurements, no keys and no label data.
