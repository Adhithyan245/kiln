# When does a GPU calculation change Kiln's answer?

Post-study analysis of the H100 full run (`runs-h100/`, 346 held-out pairs). **Not part of the pre-registered evaluation.** Reproduce with `uv run python -m kiln.router` (code: `src/kiln/router.py`).

## Label-free by construction

The question is whether the MACE energy would change **Kiln's own call** under the frozen scoring rules, never whether that call was right. The frozen category rules call a pair `no_driving_force` when its reaction energy is at or above −0.05 eV/atom. So a "flip" is a MACE energy on the other side of that threshold from the cheap Materials Project energy. `moved_toward_label` in the compute logs is derived from labels, and is never read.

## Findings

1. **Relaxations cost nearly everything and changed nothing.**
   - C4 spent 5,135 compute units per run, and 95.8% of that went on bounded relaxations at 30 units each.
   - On the 124 pairs that got both a single point (1 unit) and a relaxation, the relaxation changed Kiln's category on **0** of them.
   - The largest energy change was 0.007 eV/atom, which moves the ranking score by at most 0.14 on the logit scale.
   - Keeping the single points and dropping the relaxations would have given C4 the same categories for about 212 units per run, about 4% of what it spent.
2. **Most single points changed nothing either.**
   - 172 pairs got a single point, and 18 of them (10%) flipped Kiln's call.
   - Every flip sits near the threshold, or has a competitor phase within 0.05 eV/atom of the hull.
3. **A two-number rule finds most of the flips from cheap evidence alone.** The rule escalates when |dE_MP + 0.05| ≤ w or the nearest competitor is within c eV/atom of the hull, with a single point and never a relaxation.

| Router | Pairs sent to GPU | Flips caught |
|---|---|---|
| The study's rule (OPEN-07) | 177 / 346 | 18 / 18 |
| w = 0.015, c = 0.05, chosen on this data | 90 / 346 | 18 / 18 |
| The same search, **cross-validated** (leave one precursor out, 46 folds) | 25% of held-out pairs | 32 / 36 (89%) |

The cross-validated row is the honest estimate. Its rule is chosen without the precursor being tested, and each pair is held out once for each of its two precursors.

## Limits

- **Selection bias.** Only pairs the study's rule escalated have a single point. That rule looked at −0.05 ≤ dE ≤ 0.05 and at near-hull competitors. Pairs just below −0.05 were never checked, so flips in the other direction can't be observed here: all 18 observed flips go from "no driving force" to "driving force".
- **One run, one dataset.** 18 flips is a small sample, and the cross-validated recall of 89% is noisy.
- **Agreement is not accuracy.** Keeping C4's calls is not the same as keeping C4's AUROC of 0.739. Checking accuracy needs the outcome labels, and so a protocol of its own.

## What it suggests

- **Default to single points:** escalate to a relaxation only on evidence that it can change the answer, which this run never produced.
- **Route on two numbers:** use the distance to the decision threshold and the competitor energy, not a fixed borderline band.
- **Close the blind spot:** in the next run, also single-point a random sample of pairs that are not escalated, so that flips outside the router's window become observable.
