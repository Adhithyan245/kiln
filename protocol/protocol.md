# Kiln evaluation protocol

> **Status: DRAFT. Not frozen, not hashed, not posted. Not ready for held-out runs.**
>
> - Owner: Hemanath (A, Evaluation). Drafted 2026-10-31.
> - `prompts/hemanath.md` plans to freeze and hash this file at 7 PM Saturday. This draft does not meet that bar: every `OPEN-nn` item in §15 must be closed by its owner first.
> - `OPEN-nn` marks a decision nobody has made yet. An assistant must not fill one in. Values come from the named owner, together with their source (a profiling log, a commit, or a team decision).
> - "Settled" means the rule is already written in `AGENTS.md`, `docs/interfaces.md`, `src/kiln/schemas.py` or a team prompt. The source is cited each time.

Sources used for this draft: `AGENTS.md`; `docs/interfaces.md`; `src/kiln/schemas.py`; `prompts/*.md`; the descriptions and code of PRs #5 (verifier), #6 (data and split), #7 (scoring stubs), #8 (evaluator), #9 (B1 folds) and #10 (B0, B0-T); and the Gate 0 license and category evidence (kiln-9 artifact `gate0-license-evidence.md`). PRs #5 to #10 were open when this draft was first written; all six were merged into `dev` on 2026-10-31 (checked with `gh pr view` and against `origin/dev`). §4.2 also draws on the `b0.py` docstrings of PR #19, which is **open, not merged**, and OPEN-25 and OPEN-26 on `protocol/proposals/0001-standard-firing-claim.md`, a proposal that awaits Hemanath's decision.

---

## 1. Question and scope

**Question.** At one locked compute budget, does a collective of specialist agents (Thermo, Kinetics, Precursor) that coordinate through a shared need board, with no central planner, predict solid-state reaction outcomes on held-out precursors better than a single agent, isolated specialists or a central planner? And how does each condition spend its compute? (`AGENTS.md`, project summary.)

**In scope for the first complete experiment** (`AGENTS.md` hard rule 11): conditions C1 to C4 at one locked budget; baselines B0, B0-T and B1; the Precursor Genome held-out split.

**Out of scope** (`AGENTS.md` hard rule 11): Glass/MD, extra model families, extra agents, live new-candidate mode, and a second budget level unless the team agrees after profiling. Experiment runs use the Gemini key only. The A-Lab demo recipes in `data/alab/` are for the demo and are not scored here.

`ConditionId` in `schemas.py` also lists `N1` and `N2`. No repo file defines them, and this protocol does not use them (**OPEN-21**).

## 2. Data

### 2.1 Source

- **Dataset:** Precursor Genome, v1.0, version DOI `10.5281/zenodo.21285546` (concept DOI `10.5281/zenodo.21285545`), published 2026-07-09, license CC BY 4.0. License, access, version and date were rechecked against the Zenodo API on 2026-10-31.
- **File used:** only `ledger_precursor_genome.json` from GitHub `lauren-walters/precursor-genome`, at commit `78cb026aa6c9b53aa0ec26ea5611d523bc3c320a`. It is downloaded to `data/raw/`, which is gitignored. The Zenodo XRD, refinement and microscopy archives are not used, because they contain label material (Gate 0 evidence, §1).
- **Fields agents may see:** only those in `Item` (`schemas.py`): pair, furnace temperature (°C), dwell, melting points, split, and `item_id`. PR #6 decodes only `sample_id`, the precursor formulas and melting points, `synthesis.heating_temperature` and `synthesis.heating_time`, and records per-item provenance (source file, record index, fields used).

### 2.2 Confirmed aggregate counts

| Quantity | Value | Basis |
|---|---|---|
| Reactions | 1,035 | PR #6 projection of the ledger; README lines 20 and 35 |
| Distinct unordered pairs | 1,035 (each pair appears once) | PR #6 internal check; consistent with C(46,2) = 1,035 |
| Distinct precursors | 46 | PR #6; README line 36 |
| Development pairs | 666 | PR #6 split, seed 42; C(37,2) = 666 |
| Held-out pairs | 369 | PR #6 split; C(9,2) + 9 × 37 = 36 + 333 = 369 |
| Records missing a heating temperature | 54 (40 of them have no synthesis object) | PR #6; **unresolved, OPEN-13** |

The 666 and 369 are **projected pair counts, not validated `Item` counts**. Full ingest fails closed on the 54 records without a heating temperature, so 981 records currently validate as `Item`s. How the 54 fall across development and held-out is not reported here.

### 2.3 Split (settled method, PR #6)

- Hold out 9 of the 46 precursors. Every pair that touches a held-out precursor is held out: the 36 pairs with two held-out precursors and the 333 pairs with one held-out and one development precursor.
- Selection uses `random.Random(42)`. Precursors are grouped by the first element symbol of their formula, the groups are shuffled, and one precursor is drawn from each group in turn until 9 are chosen. The same ledger and seed give the same selection regardless of record order.
- `python -m kiln.data` prints the held-out precursor list and the split counts without any label.
- The task asked for a spread "across element groups". First-element groups give a deterministic spread, not a verified periodic-group stratification (PR #6 limitation). Whether that is acceptable, and the held-out precursor list itself, must be recorded here at freeze (**OPEN-18**).

### 2.4 Missing heating temperatures (unresolved)

The 54 records have no heating temperature. None has a non-null profile temperature, the workflow's nominal parameters include no temperature key, and the 981 populated profile temperatures are arrays that cannot directly fill the scalar `temperature_c` (PR #6). No value has been invented and no record has been dropped. Whether these records are excluded and reported, kept with a recorded temperature from some other field, or handled another way is **OPEN-13**. It decides the denominator of every "all pairs" metric in §7.

## 3. Outcomes

### 3.1 Four-class outcome

`Category` in `schemas.py` has four classes: `unreacted`, `transformed` (a precursor changed on its own but did not react with the other), `partially_reacted` and `completely_reacted`.

The dataset README documents **five** display names: transformed, unreacted, completely reacted, partially reacted and **unclassified** (Gate 0 evidence, §2). The ledger schema stores `reaction_category` as a free `Optional[str]` with no enum.

- How stored strings map onto `Category` (case, spaces versus underscores) is unconfirmed. Confirming it means printing the set of distinct stored values, with no counts and no pairs, and only with Hemanath's approval (**OPEN-11**).
- How `unclassified` labels, and any null category, are handled (exclude, score separately, or something else) is **OPEN-12**. `Category` has no fifth class, so the current evaluator cannot load such a label.

### 3.2 Binary outcome

**Settled** (`schemas.py`, `Label.reacted`): `reacted = True` exactly when the category is `partially_reacted` or `completely_reacted`. `unreacted` and `transformed` count as not reacted. The evaluator in PR #8 rejects any label whose `reacted` disagrees with its category.

### 3.3 Prediction

Each condition produces one `Prediction` per item (`schemas.py`). It has `p_react` in [0, 1] (the single score used for AUROC and Brier), a four-class `category`, a `cause`, a `fix`, evidence ids, compute request ids, disagreements, `needs_review`, `review_flags`, applicability notes and cost. Predictions come only from `kiln.scoring.score.score` applied to verifier-accepted artifacts (`schemas.py`, interfaces step 9). How `score` computes `p_react`, `category`, `cause` and `fix` is **OPEN-05**. PR #7 deliberately raises an error until those rules are frozen.

## 4. Conditions

### 4.1 Agent conditions, all at one equal locked budget

| ID | Condition | Definition (source) |
|---|---|---|
| C1 | Single agent | One agent with all tools and tiers (interfaces step 6, `agents/single.py`) |
| C2 | Isolated specialists **or** need-board collective | **OPEN-01** |
| C3 | Central planner | Decides which specialist runs and which compute to buy (interfaces step 6, `agents/planner.py`). A core comparator, not optional (`schemas.py`) |
| C4 | Need-board collective **or** isolated specialists | **OPEN-01** |

`AGENTS.md` names four arms: the collective, a single agent, isolated specialists and a central planner. Interfaces step 6 fixes only C1 and C3. No repo file says which of C2 and C4 is the collective. "Isolated specialists" is also not defined beyond its name, for example whether needs are disabled and whether specialists can read each other's artifacts. Both are **OPEN-01**.

**Settled invariants across C1 to C4** (`prompts/cj.md` Task 3; `AGENTS.md` rules 7, 8 and 11):

- same items, locked budget, frozen tier prices and compute client;
- same LLM provider (Gemini key only) and same model (**OPEN-04**);
- same verifier, review-flag function, scoring call and output format;
- LLM agents choose what to compute and write rationales but never set numbers.

### 4.2 Baselines (reference points, not equal-budget comparators)

| ID | Rule | Status |
|---|---|---|
| B0 | Driving-force threshold: predict a reaction when the cached `dE_ev_per_atom` is at or below a threshold (PR #10) | Threshold **OPEN-08** |
| B0-T | Temperature ratio: rank items by `T_dwell / T_melt(higher)`, both in kelvin, from `Item.temperature_c` and the higher of the two melting points. Predict a reaction when the ratio is at or above `TemperatureRatioConfig.ratio_threshold`, which comes from config and has no default (PR #19, open) | Threshold **OPEN-25** |
| B60meV | Competition-margin feature and regime marker, not a rule for whether a pair reacts: `margin = dE_competing − dE_best` in eV/atom (never negative), and `decisive = margin ≥ CompetitionMarginConfig.margin_threshold_ev_per_atom`, from config with no default. It has no `reacts`, `p_react` or category field (PR #19, open) | Threshold, and any mapping to `p_react` or `Category`, **OPEN-25** |
| B1 | Logistic regression on development data, with leave-one-precursor-out folds that drop the left-out precursor from both pair positions (PR #9) | Features, fit and fold aggregation **OPEN-09** |

- **B0-T replaces a Tammann-fraction rule.** PR #10 put that rule on `dev`: predict a reaction when the furnace temperature reaches a Tammann temperature, `fraction × (mp_c + 273.15) − 273.15`, with a configured fraction and an either/both choice. `dev` still runs it until PR #19 merges. The ratio needs no fitted value; only its decision threshold comes from config. The two-thirds fraction that `prompts/annamayya.md` specifies for `kiln.tools.tammann` is therefore not a B0-T setting.
- **Reason for the swap: reviewer-sourced and UNVERIFIED**, not checked against the dataset's own documentation. The dataset's firing temperature is reportedly set by Tammann's rule, which would make a rule that compares the furnace temperature with a Tammann temperature circular. If that holds, `temperature_c` depends on the melting points, and so does the ratio (PR #19 notes this).
- **B60meV is a margin feature and regime marker only.** Its name comes from Szymanski et al., *Science Advances* 10(27), 2024, DOI `10.1126/sciadv.adp3309`, who found the **first product to form** predictable when its driving force exceeds that of every competing phase by at least 60 meV/atom. That finding is about which product forms first, not whether a pair reacts, so B60meV is never a validated reacts-or-does-not-react rule. The 60 meV/atom value is not a default; the threshold comes from config and is recorded on every result.
- **B60meV is not a `ConditionId`** in `schemas.py`, so no `RunConfig` can name it and it yields no `Prediction`. Whether it should become one needs a shared-schema change. That is an open question; this draft does not settle it.
- B0 outputs a binary decision with a signed margin in eV/atom. B0-T outputs a binary decision with the ratio as its ranking score. Neither is a probability. How a B0 or B0-T decision becomes a `Prediction` (`p_react` in [0, 1] and a four-class category), and how B0's `cached_lookup` requests are charged and logged, is **OPEN-08**. `to_predictions` fails closed for B0 and B0-T on `dev` (PR #12), and PR #19 keeps it failing closed with B60meV added.
- Missing inputs are never imputed: B0, B0-T and B60meV return an undetermined result with a `missing_evidence` flag (PR #10; PR #19 for the B0-T ratio and B60meV). For B0-T, one missing melting point leaves the decision undetermined, because the missing one could be the higher.
- B1 needs development labels to fit. See **OPEN-10**.

## 5. Locked budget and frozen price list

**Settled charging rules** (`AGENTS.md` rule 8; interfaces steps 3 and 4):

- Every compute request goes through `kiln.compute.client.request` and `kiln.budget.Budget`. Agents never call ALCHEMI directly.
- The frozen tier price is charged **before** the request runs, even on a cache hit. Every request is logged to `runs/<run_id>/compute_requests.jsonl` with a one-sentence reason.
- `Budget` raises `BudgetExceeded` when a limit is reached. Running out before a key check raises a `missing_evidence` review flag (`schemas.py`, `ReviewReason`).
- `not_converged` and `failed` requests are logged as such and raise a `failed_computation` flag. They are never silently replaced or dropped (rule 9).
- One budget level only (rule 11).

**Not yet set:**

| Item | Current state | Status |
|---|---|---|
| Tier prices for `cached_lookup`, `single_point`, `bounded_relaxation`, `decomposition_reeval` | `RunConfig.tier_prices` is empty, "frozen in the protocol at code freeze" | **OPEN-03** (Adhi proposes from profiling, for Hemanath to freeze, `prompts/adhi.md` Task 4) |
| `max_compute_units_per_item` | Schema placeholder; "final value set from profiling" | **OPEN-02** |
| `max_tool_calls_per_item`, `max_tokens_per_item`, `coordination_rounds` | Schema defaults exist; nothing says they are the locked values | **OPEN-02** |
| Experiment USD cap (`Cost.usd`) | Tracked per item; no cap stated | **OPEN-02** |
| Whether unused budget carries over between items | Not stated (budget is per item in `RunConfig`) | **OPEN-20** |

## 6. How one item is processed

The flow, settled in `docs/interfaces.md`:

1. `load_items(split)` gives `Item`s.
2. Agents post needs and artifacts on the board and buy compute.
3. `kiln.verifier.verify` checks every artifact. Only `accepted` artifacts feed review flags and scoring.
4. `kiln.review.flags` adds missing-evidence, failed-computation, conflict and outside-applicability flags.
5. `score.score` produces the `Prediction`.
6. The runner writes `runs/<run_id>/predictions.jsonl`.

- The verifier (PR #5) checks: `falsified_if`, citations, documented value keys and units, forbidden label keys, cited compute request ids, numbers matching cited compute results or recomputed tool values, compute charges and item budgets.
- Contract gaps that block artifacts from being accepted: the full `verify` signature in interfaces step 7, the `item_cost` accessor on `Budget`, and the tool APIs that produce `tool_values`. Until these close, Kinetics and Precursor artifacts stay `inconclusive` (**OPEN-24**).
- Review-flag thresholds come from this protocol (interfaces step 8). These include the MLIP versus Materials Project disagreement threshold and the applicability limits (**OPEN-06**).
- Specialist escalation rules decide when a costlier tier is justified, for example Thermo's margin around the driving-force threshold. They are owned by Annamayya and must be recorded here before freeze (**OPEN-07**).
- If a condition produces no prediction for an item (crash, timeout, unrecoverable error), the handling is **OPEN-23**. The evaluator requires exactly one prediction per item.

## 7. Metrics

Every metric is computed on **all held-out pairs**, flagged ones included, for each run (one condition, one seed). There is no abstention; review flags never remove an item from the denominator (interfaces step 11). The held-out denominator depends on **OPEN-12** and **OPEN-13**.

As implemented in the PR #8 evaluator (synthetic tests only):

| Metric | Definition |
|---|---|
| AUROC (binary) | Mann–Whitney estimate of `p_react` against `reacted`, with ties counted as one half. Undefined when one class is absent |
| Brier (binary) | Mean of `(p_react − reacted)²` |
| Four-class accuracy | Fraction of pairs where the predicted `category` equals the label category |
| Coverage | Fraction of pairs with `needs_review = False` |
| Flagged and unflagged accuracy | Four-class accuracy within flagged pairs and within unflagged pairs, with both counts |

- The evaluator also requires `p_react` to be finite and in [0, 1], `needs_review` to equal `bool(review_flags)`, a single run, condition and seed per file, and the same item set in predictions, items and labels.
- Which metric is the primary endpoint is **OPEN-14**. Interfaces step 11 lists AUROC first but declares nothing primary. So are any secondary metrics (for example binary accuracy at a stated threshold) and any subgroup reporting (for example the 36 two-held-out pairs versus the 333 one-held-out pairs).
- `p_react` is a fixed-rule score. Brier measures how far it sits from the outcomes; it does not make `p_react`, a review flag or a stated cause a calibrated probability or a validated failure cause (`AGENTS.md` rule 10).

## 8. Statistical comparison

- **Pairing.** Every condition predicts the same held-out items, so each comparison between conditions is paired item by item.
- **Planned contrasts.** The collective against C1, against isolated specialists and against C3. Each agent condition against B0, B0-T and B1. The decision rule ("the collective is better if …") and any multiplicity adjustment are **OPEN-14**.
- **Uncertainty: precursor-clustered paired bootstrap.** Each replicate resamples precursor clusters and recomputes the metric difference between two conditions on the same resampled pairs. Every pair belongs to **two** precursor clusters: held-out pairs touch 9 held-out and 37 development precursors, so the clusters overlap and form a crossed design. The resampling scheme for overlapping clusters, the number of replicates, the interval type and level, and the seed are all **OPEN-15**. Candidate families to consider include precursor-level (vertex) resampling of the pair graph and multiway cluster bootstrap. None is chosen, and none has been validated.
- The PR #8 evaluator returns **no intervals** on purpose. Its `bootstrap_samples=1000` and `bootstrap_seed=0` arguments are code placeholders, not protocol values. Until OPEN-15 closes, no interval, p-value or significance claim may be reported.
- **Repeated LLM runs.** LLM conditions are not deterministic. The number of seeds per condition, and how seeds are combined, is **OPEN-04**.

## 9. Compute allocation

These questions are reported for every agent condition: was extra computation worth spending, and where did it go?

**Implemented in PR #8**, a table per run by `(tier, status)`:

- number of requests;
- compute units charged;
- measured GPU-seconds (for reporting only);
- number of requests whose movement is known;
- number that moved toward the label.

`moved_toward_label` is filled **only after unblinding**, by the evaluator, on copies of the requests. The append-only log is never edited.

- **Moved toward label:** `|p_react_after − y| < |p_react_before − y|`, where `y` is the binary label.
- A missing before or after score leaves movement unknown. Equal distance counts as False.

**Logged before unblinding:**

- `p_react_before` and `p_react_after` (and the categories) from `score.provisional`, around each request (interfaces step 4);
- `changed_prediction`. Its definition, and who fills it, is **OPEN-17**.

Extra breakdowns that are not implemented yet: by agent, compute units per item against flagged status, items that hit the budget limit, and the share of units spent on requests that changed the prediction. Which of these to report is **OPEN-14**.

All allocation figures are descriptive. `moved_toward_label` measures how a provisional score moved, not the causal value of a computation. Cache hits are charged at full price but can report near-zero GPU-seconds, so GPU-seconds depend on run order and cache state (**OPEN-20**).

## 10. Two-step protocol and hash gates

Labels are never loaded before an **independently verified post** of the commitment that protects them.

### Step 1: protocol commitment (Gate P)

- **P1.** Owners close every `OPEN-nn` item and write the values here with their sources.
- **P2.** Record the code-freeze commit SHA for scoring, verifier, review flags, compute tiers, agents and runner.
- **P3.** Commit the closed protocol and push the commit to `dev`, which blocks force-pushes and deletion (`docs/github-setup.md`), so the commit stays reachable. That commit is the **Gate P commit**. The digest is the SHA-256 of `protocol/protocol.md` as stored in that commit, `git cat-file blob <gate-p-commit>:protocol/protocol.md | shasum -a 256`. It is never taken from a checked-out copy, so line endings and checkout settings cannot change it. Post the full Gate P commit SHA **together with** the digest through the channel in **OPEN-16**, and verify the receipt independently. Anyone can check the commitment by rerunning that command against the posted commit.
- **P4.** Only after P3 may held-out runs start. Development runs may happen earlier.
- **P5.** After the Gate P commit, `protocol/protocol.md` is never edited. The Gate P record (commit SHA, digest, posting receipt) and every later change go in `protocol/amendments.md`, which is never part of the Gate P hash. Writing the record into this file would change the bytes being committed to.

### Step 2: prediction commitment (Gate H), per run

- **H1.** The run writes `runs/<run_id>/predictions.jsonl`: one run, one condition, one seed.
- **H2.** Compute the SHA-256 of the exact file bytes, write it to `runs/<run_id>/prediction.sha256` (interfaces, run folders) and post it. CJ's night runner posts the prediction hash before scoring (`prompts/cj.md` Task 4).
- **H3.** Verify the post independently. A local hash file, a posting attempt, or a receipt that has not been verified is **not** proof (PR #8). The posting channel and the receipt proof, meaning what independent check confirms that the posted digest equals the file digest and was posted before unblinding, are **OPEN-16**.
- **H4.** Only after H3 does `kiln.scoring.evaluate` load labels. The evaluator fails closed with `EvaluationLockedError` unless a caller-supplied verifier returns the literal `True` for the digest.
- **H5.** After unblinding, no prediction file changes. A re-run gets a new `run_id` and its own hash, and is reported next to the original.

**Amendments.** Any change after Gate P is recorded in `protocol/amendments.md` with the date, the reason and who made it. That file is outside the Gate P hash; this file stays exactly as it was in the Gate P commit. Analyses decided after unblinding are labeled post hoc.

This draft has not been hashed, posted or frozen.

## 11. Contamination control

**Settled measures:**

1. Kiln agents have no web access at runtime. Their only tools are `src/kiln/tools/` and the compute service (`AGENTS.md` rule 3).
2. LLMs never set numbers (rule 7). The verifier rejects numbers that do not trace to a cited compute result or a recomputed tool value (PR #5).
3. Agents see only the `Item`. A test in PR #6 checks that no `Item` holds a label field.
4. `data/precursor_props.csv` holds the properties of one precursor at a time, never whether two precursors react (`prompts/annamayya.md`).
5. Team members and their assistants never look up experimental outcomes online (rule 2).
6. Held-out pairs are never used to set a threshold, price, rule, escalation margin or B1 feature: not their outcomes and not any run on them. Sources:
   - the experiment is split by precursor (`AGENTS.md` project summary; `prompts/hemanath.md` Task 1);
   - baselines report development metrics only (`prompts/hemanath.md` Task 2);
   - B1 rejects any row whose split is not `dev` (PR #9);
   - held-out runs start only after Gate P (§10, P4).

   Whether any of these values may be set from development **labels**, and how, depends on **OPEN-10**. Until it closes, no value is set from development outcomes (§12).
7. B0, B0-T and B1 use no LLM and serve as LLM-free reference points.

**Residual risk.** A-Lab outcomes and the Precursor Genome (published 2026-07-09) are public, so LLM pretraining may include them. Because LLMs cannot set numbers, recall could act only through which evidence an agent buys and through text fields (rationale, claims, cause and fix). Whether such text can influence `category` depends on the scoring rules (**OPEN-05**).

**Open (OPEN-19):**

- PR #6 uses the upstream `sample_id` as `item_id`, and agents see `item_id`. Whether agents should get opaque item ids instead (the mapping would live in provenance) is undecided.
- Whether to run a memorization probe is undecided.
- Which Gemini model is used, and therefore its training cutoff relative to 2026-07-09, is undecided (**OPEN-04**).

## 12. Label safety

These rules are settled (`AGENTS.md` rule 1; `prompts/hemanath.md`; `.gitignore`):

- Label fields are moved into `labels/` (gitignored) **by code, without printing them**. Nobody opens, prints, copies or summarizes `labels/`, or the ledger's label fields: XRD patterns, refinement results, phase weights, reviewer annotations and reaction category.
- Only `src/kiln/scoring/evaluate.py` may load labels, and only after Gate H (§10).
- `Item`s carry no label fields, and the verifier rejects artifacts that use forbidden label keys (PR #5).
- Counts reported before unblinding are label-free: pairs, precursors, split sizes and missing conditions. Per-category counts are label data and are never reported before unblinding (Gate 0 evidence, §2).
- Confirming the stored category strings (**OPEN-11**) means printing distinct values only, with no counts and no pairs, and only with Hemanath's approval.
- **Development labels.** Hard rule 1 allows label access only through `evaluate.py` after a posted prediction hash. Yet B1 needs development labels to fit, Task 2 asks for development AUROC for B0 and B0-T, and setting B0 thresholds may use development outcomes. The approved path for development labels is **OPEN-10**. Until it closes, no development metric is computed.

## 13. Limitations

- **One dataset, one lab.** 46 precursors, 1,035 pairs, each run once at one furnace condition, so temperature effects are confounded with the pair.
- **Few held-out clusters.** Only 9 precursors are held out, so intervals will be wide. 333 of the 369 held-out pairs share a development precursor; by design, the split tests generalization to new precursors, not to new chemistry on both sides.
- **Label noise.** Categories are expert assignments from XRD refinement. `unclassified` labels and the 54 records with missing temperatures reduce or change the evaluated set (OPEN-12, OPEN-13).
- **Fixed-rule scores and flags.** `p_react` is not a calibrated probability. Review flags are not validated failure causes. Coverage depends on flag thresholds frozen before the runs.
- **LLM variation and contamination.** LLM runs vary between seeds, and pretraining contamination cannot be ruled out (§11).
- **Compute accounting.** GPU-seconds depend on cache state and run order. `moved_toward_label` is descriptive.
- **Untested on real data.** The evaluator, verifier, scorer stubs, baselines and split code are tested on synthetic data only. They are merged into `dev` (PRs #5 to #10, with follow-ups #12, #13, #15 and #16). The B0-T ratio, B60meV and evaluator changes in PR #19 are not merged.

## 14. Gate 0 decisions

Based on the Gate 0 evidence (kiln-9 artifact, checked 2026-10-31 from public metadata only). License, access and version were rechecked live on 2026-10-31.

| Item | Status | Basis |
|---|---|---|
| License: Zenodo record and GitHub repo are both CC BY 4.0; Kiln may share and adapt the data | Settled by evidence | Zenodo API, DataCite, repo `LICENSE`, README, `metadata/datacite.json`. The GitHub detector's `NOASSERTION` is a format mismatch, not a different license |
| Obligations: credit the authors with title, DOI and license link, and indicate changes. Derived `Item`s and the precursor-level split are changes | Settled by license | CC BY 4.0 |
| Cite the version DOI `10.5281/zenodo.21285546`, not the concept DOI in the README | Recommended; Hemanath to confirm | Only one version exists; a version DOI is reproducible |
| Use the README author list, not the Zenodo creator list (four names appear swapped) | Recommended; Hemanath to confirm | Gate 0 evidence §4.5 |
| Use only `ledger_precursor_genome.json`; do not use the Zenodo XRD, refinement or microscopy archives | Recommended; Hemanath to confirm | Those archives are label material |
| The README's "restricted access" note is out of date; Zenodo reports open access | Noted | Zenodo API, rechecked live |
| Exact stored category strings | **OPEN-11** | The schema allows any string |
| Handling of `unclassified` | **OPEN-12** | Taxonomy has five names; `Category` has four |
| Exact attribution text (title, authors, change notice) for the README and app | **OPEN-22** | Not drafted |

This is not legal advice.

## 15. OPEN register

None of these may be filled in by an assistant. Each needs its owner's decision and a source.

| ID | Decision needed | Owner | Blocks |
|---|---|---|---|
| OPEN-01 | Which of C2 and C4 is the need-board collective and which is isolated specialists; what "isolated" means | Adhi | §4, every contrast |
| OPEN-02 | Locked per-item budget: compute units, tool calls, tokens, coordination rounds, USD cap | Adhi (profiling) and team | §5, Gate P |
| OPEN-03 | Frozen price per compute tier | Adhi proposes from profiling; Hemanath freezes | §5, Gate P |
| OPEN-04 | Gemini model id and settings; number of seeds per condition and how they are combined | Adhi and team | §4, §8, §11 |
| OPEN-05 | Scoring rules: `p_react`, category boundaries, cause and fix, evidence selection, in `score.score` and `score.provisional` | Hemanath | §3.3, every metric |
| OPEN-06 | Review-flag thresholds (MLIP versus Materials Project disagreement, applicability limits) | Annamayya; values recorded here | §6, coverage |
| OPEN-07 | Specialist escalation rules and margins | Annamayya; recorded here | §6, §9 |
| OPEN-08 | B0 threshold; mapping a B0 or B0-T decision to `p_react` and category; charging of B0's cached lookups | Hemanath | §4.2 |
| OPEN-09 | B1 feature set, model settings, fold aggregation (a pair appears in two folds), final fit | Hemanath | §4.2 |
| OPEN-10 | Approved access path for development labels (B1 fitting, development AUROC, threshold setting), given hard rule 1 | Hemanath and team | §4.2, §12 |
| OPEN-11 | Mapping from stored category strings to `Category` | Hemanath (approval needed to print distinct values) | §3.1 |
| OPEN-12 | Handling of `unclassified` and null category labels | Hemanath | §3, §7 denominator |
| OPEN-13 | Handling of the 54 records with no heating temperature | Hemanath | §2.4, §7 denominator |
| OPEN-14 | Primary endpoint, decision rule, multiplicity, secondary metrics, subgroups, extra allocation tables | Hemanath and team | §7, §8, §9 |
| OPEN-15 | Bootstrap for overlapping precursor clusters: scheme, replicates, interval type and level, seed | Hemanath | §8 |
| OPEN-16 | Posting channel and receipt proof for protocol and prediction hashes | Hemanath, CJ and Adhi | Gate P, Gate H |
| OPEN-17 | Definition of `changed_prediction`, and who fills it | Hemanath and CJ | §9 |
| OPEN-18 | Held-out precursor list as recorded at freeze; whether first-element grouping is an acceptable spread | Hemanath | §2.3 |
| OPEN-19 | Opaque item ids for agents; memorization probe | Hemanath | §11 |
| OPEN-20 | Run order and cache sharing across conditions; whether unused budget carries over | Adhi and CJ | §5, §9 |
| OPEN-21 | Definition of conditions N1 and N2, or their removal from this experiment | Team | §1 |
| OPEN-22 | Exact attribution text for the dataset | Hemanath | §14 |
| OPEN-23 | Handling of an item with no prediction from a condition | Adhi and Hemanath | §6, §7 |
| OPEN-24 | Verifier contract gaps: `verify` signature in interfaces, `item_cost` accessor, tool APIs for `tool_values` | Adhi, Annamayya and Hemanath | §6 |
| OPEN-25 | Mapping from the B60meV margin (or its `decisive` marker) to `p_react` or `Category`, if any; threshold values for B0-T (`ratio_threshold`) and B60meV (`margin_threshold_ev_per_atom`). Proposed in `protocol/proposals/0001` | Hemanath | §4.2 |
| OPEN-26 | Label-free check of the ledger's formula notation. The carbonate, hydroxide and ammonium formula rules for the hard subset may miss pymatgen-style formulas such as `LiHO` or `H4NCl`. Proposed in `protocol/proposals/0001` (§3, hard subset); the notation gap was raised in PR #19 | Hemanath | Hard subset (proposal 0001 §3), if adopted |

## 16. Amendments

Amendments live in `protocol/amendments.md`, not here, so this file's bytes match the Gate P commit (§10, P3 and P5). That file also holds the Gate P record. It is never part of the Gate P hash.
