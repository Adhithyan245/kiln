# Kiln evaluation protocol

> **Status: DRAFT. Not frozen, not hashed, not posted. Not ready for held-out runs.**
>
> - Owner: Hemanath (A, Evaluation). Drafted 2026-10-31; pre-freeze decisions written in on 2026-10-31.
> - Freeze time: `prompts/hemanath.md` plans the freeze and hash for 7 PM Saturday. `docs/plan-changes.md` row 14 lets the team move it to at most 8:30 PM, which is the team's limit tonight. This file stays a draft until Hemanath makes it the Gate P commit (§10).
> - **Delegated decisions.** On 2026-10-31 Hemanath delegated the pre-freeze decisions. A §15 row marked **decided 2026-10-31 by Hemanath, delegated** was written by an assistant under that delegation, from the freeze decision sheet (kiln-33 artifact `kiln-freeze-decision-sheet.md`) and Hemanath's written instructions. Hemanath may veto any of them before the Gate P commit. A row marked **pending** still needs the named person, and its text says what applies until then.
> - **Final pre-freeze revision (2026-10-31, base `0c5eeea` on `dev`).** Writes in the OPEN-05, OPEN-06, OPEN-07, OPEN-16 and OPEN-23 decisions, the Night 2 settings and the model training cutoff, each checked against the cited commit on `dev`, the two-machine Night 2 plan (GB10 primary, H100 replication; §5.2, PC27) and the secondary binary split (§7, PC26). On 2026-11-01 Hemanath approved the remaining items: the §3.3 `p_react`-versus-category paragraph (intended as documented), the decomposable-only review flag (adopted once Adhi merges it, §6), the secondary binary split (secondary and descriptive) and `protocol/frozen_settings.json` (pushed by Adhi in `4055d77`, SHA-256 in §5).
> - **P2 revision (2026-11-01, base `d9a2993` on `dev`).** Records the adopted decomposable-only review flag (PC29), the H100 replication's compute backend (PC28), the `p_react`-versus-category decision (PC30) and the P2 code-freeze commit (§10). Still a draft: not hashed, no Gate P record, not posted.
> - Every value comes with its source: a profiling file at a commit, a repo file, or a team decision.
> - "Settled" means the rule is already written in `AGENTS.md`, `docs/plan-changes.md` (cited as PC and its row number), `docs/interfaces.md`, `src/kiln/schemas.py`, the runner code or a team prompt. The source is cited each time.

Sources used for this draft: `AGENTS.md`; `docs/plan-changes.md`; `docs/interfaces.md`; `docs/compute-decisions.md`; `docs/escalation-rule.md`; `docs/credits.md`; `src/kiln/schemas.py`; `src/kiln/runners/conditions.py`; `src/kiln/runners/finalize.py`; `src/kiln/night/plans/night2.toml`; `src/kiln/agents/thermo.py` and `kinetics.py`; `src/kiln/review/__init__.py`; `protocol/scoring_rules.json`; `prompts/*.md`; the descriptions and code of PRs #5 (verifier), #6 (data and split), #7 (scoring stubs), #8 (evaluator), #9 (B1 folds), #10 (B0, B0-T) and #19 (B0-T ratio, B60meV, hard subset); `protocol/prices_proposal.json`; and the Gate 0 license and category evidence (kiln-9 artifact `gate0-license-evidence.md`). PRs #5 to #10 were merged into `dev` on 2026-10-31, and PR #19 was merged at 2026-10-31T19:20:57Z (checked with `gh pr view 19`). Proposal 0001 (`protocol/proposals/0001-standard-firing-claim.md`) is **accepted by Hemanath**, matching PC10. The proposal's own header line still reads "for Hemnaath to accept or reject"; that line is out of date and PC10 plus this paragraph are the record.

Label-free facts below that come from `~/kiln-items.jsonl` use only `Item` fields (`item_id`, precursor formulas, `temperature_c`, `dwell_h`, melting points, `split`). No file in `labels/` or `data/raw/` was opened, and no outcome was looked up.

---

## 1. Question and scope

**Question.** At one locked compute budget, does a collective of specialist agents (Thermo, Kinetics, Precursor) that coordinate through a shared need board, with no central planner, predict solid-state reaction outcomes on held-out precursors better than a single agent, isolated specialists or a central planner? And how does each condition spend its compute? (`AGENTS.md`, project summary.)

**In scope for the first complete experiment** (`AGENTS.md` hard rule 11): conditions C1 to C4 at one locked budget; baselines B0 and B0-T as reference points, plus the B60meV margin feature (§4.2); the Precursor Genome held-out split.

**Out of scope** (`AGENTS.md` hard rule 11): Glass/MD, extra model families, extra agents, live new-candidate mode, and a second budget level unless the team agrees after profiling. The A-Lab demo recipes in `data/alab/` are for the demo and are not scored here.

**Models and secondary results** (rule 11; PC2; PC6). The main comparison (C1 to C4, all seeds) runs on Gemini only, with `gemini-3.8-flash`. Two **secondary** results run after it and are always reported separately, never pooled with the main table: a Claude replication on about 120 held-out pairs with 1 seed, and the N2 memorization probe on an OpenAI model.

**N1 and N2** (**OPEN-21**). `ConditionId` in `schemas.py` also lists `N1` and `N2`. N1 tags profiling and pre-warm runs (`src/kiln/compute/profile.py`); N1 runs are never scored. N2 is the memorization probe on an OpenAI model, a secondary result reported separately (rule 11; `docs/credits.md`, OpenAI row). `docs/credits.md` also lists "N2 via the Batch API" in its Gemini row; this protocol follows rule 11, which puts N2 on OpenAI. N2's design belongs to CJ (runners). Neither N1 nor N2 enters the main table or the primary endpoint.

## 2. Data

### 2.1 Source

- **Dataset:** Precursor Genome, v1.0, version DOI `10.5281/zenodo.21285546` (concept DOI `10.5281/zenodo.21285545`), published 2026-07-09, license CC BY 4.0. License, access, version and date were rechecked against the Zenodo API on 2026-10-31.
- **File used:** only `ledger_precursor_genome.json` from GitHub `lauren-walters/precursor-genome`, at commit `78cb026aa6c9b53aa0ec26ea5611d523bc3c320a`. It is downloaded to `data/raw/`, which is gitignored. The Zenodo XRD, refinement and microscopy archives are not used, because they contain label material (Gate 0 evidence, §1).
- **Fields agents may see:** only those in `Item` (`schemas.py`): pair, furnace temperature (°C), dwell, melting points, split, and `item_id`. PR #6 decodes only `sample_id`, the precursor formulas and melting points, `synthesis.heating_temperature` and `synthesis.heating_time`, and records per-item provenance (source file, record index, fields used).
- **Agent-visible items file.** Runs on the GB10 read `~/kiln-items.jsonl`, written by `--export-items --skip-missing-temperature`; the ledger never goes to the GB10 (PC11, PC15).
- **Melting-point provenance and meaning:** retain the 46 temperatures as reported, with their per-precursor citations from Table 1. The paper states that for selected precursors that decompose or dehydrate before melting, the highest relevant decomposition temperature was substituted for `Tm` when choosing the dwell temperature; this is an approximation, not a claim that every value is a literal melting point. `data/precursor_props.csv` marks only possible decomposition/dehydration cases and keeps their published values. It does not flag numeric disagreements or phase-form mismatches. [Precursor Genome, §2.2 and Table 1](https://arxiv.org/pdf/2607.09903).

### 2.2 Confirmed aggregate counts

| Quantity | Value | Basis |
|---|---|---|
| Reactions | 1,035 | PR #6 projection of the ledger; README lines 20 and 35 |
| Distinct unordered pairs | 1,035 (each pair appears once) | PR #6 internal check; consistent with C(46,2) = 1,035 |
| Distinct precursors | 46 | PR #6; README line 36 |
| Development pairs | 666 | PR #6 split, seed 42; C(37,2) = 666 |
| Held-out pairs | 369 | PR #6 split; C(9,2) + 9 × 37 = 36 + 333 = 369 |
| Records missing a heating temperature | 54 (40 of them have no synthesis object; 14 have a null heating temperature) | PR #6; excluded before the freeze (§2.4, **OPEN-13**) |
| Evaluated items after that exclusion | 981: 635 development and 346 held-out | `~/kiln-items.jsonl`, `split` field; PC15 states the same 346 |
| Evaluated held-out items by type | 31 with two held-out precursors, 315 with one | `~/kiln-items.jsonl`, precursor fields |

The 666 and 369 are projected pair counts. The validated `Item` counts are 635 and 346. These counts are label-free: they count pairs and fields, never outcomes.

### 2.3 Split (settled method, PR #6; list recorded under OPEN-18)

- Hold out 9 of the 46 precursors. Every pair that touches a held-out precursor is held out: the 36 pairs with two held-out precursors and the 333 pairs with one held-out and one development precursor.
- Selection uses `random.Random(42)`. Precursors are grouped by the first element symbol of their formula, the groups are shuffled, and one precursor is drawn from each group in turn until 9 are chosen. The same ledger and seed give the same selection regardless of record order.
- `python -m kiln.data` prints the held-out precursor list and the split counts without any label.
- **Held-out precursors at freeze** (**OPEN-18**): `CaCO3`, `Fe2O3`, `HfO2`, `Li2CO3`, `Na2CO3`, `NiO`, `SiO2`, `TiO2`, `WO3`. Derived from the `split` field of `~/kiln-items.jsonl`: these are the 9 formulas that appear in no development item, every one of the 346 held-out items contains at least one of them, and the other 37 formulas are the development precursors. Their first elements (Ca, Fe, Hf, Li, Na, Ni, Si, Ti, W) are 9 different groups, as the method requires. Hemanath reruns `python -m kiln.data` on his machine, which holds the ledger, and checks that it prints the same 9. This is a non-blocking confirmation (§17 table 3): the runs read this same items file, and any mismatch is recorded as a dated entry in `protocol/amendments.md`.
- **Grouping accepted.** First-element groups give a deterministic spread, not a verified periodic-group stratification (PR #6 limitation). The protocol accepts that spread and keeps this caveat (§13).

### 2.4 Missing heating temperatures: documented exclusion before the freeze (OPEN-13)

**Decided** (proposal 0001 §6, Option 2): the 54 records with no heating temperature (40 with no synthesis object, 14 with a null heating temperature; PR #6) are **excluded from every condition, baseline and metric before the freeze**. The evaluated set is the 981 records with a temperature: **346 held-out** and 635 development items (§2.2). Every "all held-out items" metric in §7 and §8 uses those 346 items.

Why: `temperature_c` is required in `Item` (`schemas.py`) and ingest fails closed without it. No temperature can be filled from another field without inventing one (PR #6: no non-null profile temperature, no temperature key in the nominal parameters, and the profile temperatures are arrays). Option 1 would need a shared-schema change, and Option 3 would score items that no condition can run. The exclusion is documented, not silent (rule 9): the count, the per-split counts and the pairs are listed here and are repeated in the denominator note of every results table.

Excluded pairs, derived label-free as the pairs among the 46 precursors that are absent from `~/kiln-items.jsonl`:

- **Held-out (23):** B(HO)3 + SiO2; CaCO3 + Li2CO3; CaCO3 + Sb2O3; CaCO3 + ZrO2; CuO + Fe2O3; Na2CO3 + Sb2O3; Na2CO3 + SnO2; Na2CO3 + SrCO3; Na2CO3 + TiO2; Na2CO3 + WO3; Na2CO3 + Y2O3; Nb2O5 + TiO2; NiO + Sb2O3; NiO + SiO2; NiO + SrCO3; NiO + V2O5; PbO + SiO2; PbO + TiO2; Sb2O3 + SiO2; Sb2O3 + WO3; SiO2 + TiO2; TiO2 + ZrO2; V2O5 + WO3.
- **Development (31):** Ag2O + LiH3O2; Ag2O + V2O5; BaCO3 + Sb2O3; BaCO3 + V2O3; Co3O4 + CoO; Co3O4 + KP(HO2)2; Co3O4 + V2O3; CoO + Cr2O3; CoO + Ga2O3; CoO + Sb2O3; CuO + Fe3O4; CuO + Ga2O3; CuO + GeO2; Fe3O4 + GeO2; FeH4(CO3)2 + La(HO)3; MoO3 + Y2O3; Nb2O5 + Sb2O3; Nb2O5 + SnO2; Nb2O5 + V2O3; Nb2O5 + V2O5; PH6NO4 + Sb2O3; PbO + Sb2O3; PbO + V2O3; PbO + V2O5; Sb2O3 + SnO2; Sb2O3 + SrCO3; Sb2O3 + V2O5; Sb2O3 + Y2O3; V2O5 + Y2O3; V2O5 + ZrO2; Y2O3 + ZrO2.

The ledger `sample_id`s of these records are not listed, because listing them needs the ledger, which this draft did not open. Each pair occurs once, so the pair identifies the record.

## 3. Outcomes

### 3.1 Four-class outcome

`Category` in `schemas.py` has four classes: `unreacted`, `transformed` (a precursor changed on its own but did not react with the other), `partially_reacted` and `completely_reacted`.

The dataset README documents **five** display names: transformed, unreacted, completely reacted, partially reacted and **unclassified** (Gate 0 evidence, §2). The ledger schema stores `reaction_category` as a free `Optional[str]` with no enum.

- **Mapping (OPEN-11), decided without reading any label.** Nobody prints, lists or inspects the stored category strings, so rule 1 holds without exception. `kiln.scoring.evaluate`, and only it, normalizes each stored string (trim, lower-case, spaces and hyphens to underscores) and maps the README's documented names: `unreacted`, `transformed`, `partially_reacted`, `completely_reacted` to the matching `Category`, and `unclassified` (or a null) to the OPEN-12 rule below. Any other string makes the evaluator stop with an error before any metric is computed (fail closed). The normalization is evaluator code that Hemanath writes before Gate H.
- **`unclassified` and null categories (OPEN-12), decided.** Such an item has no outcome to score. It is excluded from AUROC, Brier, four-class accuracy and flagged/unflagged accuracy. Its prediction stays in the hashed prediction file, and coverage (which needs no label) still counts it. The number excluded is reported per run, after unblinding only.

### 3.2 Binary outcome

**Settled** (`schemas.py`, `Label.reacted`): `reacted = True` exactly when the category is `partially_reacted` or `completely_reacted`. `unreacted` and `transformed` count as not reacted. The evaluator in PR #8 rejects any label whose `reacted` disagrees with its category.

### 3.3 Prediction

Each condition produces one `Prediction` per item (`schemas.py`). It has `p_react` in [0, 1] (the single score used for AUROC and Brier), a four-class `category`, a `cause`, a `fix`, evidence ids, compute request ids, disagreements, `needs_review`, `review_flags`, applicability notes and cost. Predictions come only from `kiln.scoring.score.score` applied to verifier-accepted artifacts (`schemas.py`, interfaces step 9).

**Scoring rules (OPEN-05), decided: `protocol/scoring_rules.json` at commit `61f812b`** (Hemanath, "scoring: freeze label-free OPEN-05 rules and wire score/provisional"), merged into `dev` by `88b52e3` (PR #23). The file bytes are the same at `61f812b`, at `88b52e3` and at the `dev` tip `0c5eeea`. Their SHA-256, from `git cat-file blob 61f812b:protocol/scoring_rules.json | shasum -a 256`, is `9094382974bb87b7 53073c200548cfec 7cbea30d48e09ed5 ea41e5b5d8c21d37`, written here in four 16-character blocks because the draft guard in `tests/protocol/test_protocol.py` rejects any unbroken 64-character hex string in this file; join the blocks to compare. The file also carries a `rules_sha256` digest of its `rules` object, and `score.frozen_engine` refuses to score unless that digest equals `FROZEN_RULES_SHA256` in `src/kiln/scoring/score.py`, so an edited rule fails closed. The runner scores real runs with `score.frozen_engine` (`852a811`).

In plain language, the rules do the following. Every input is read from verifier-accepted artifacts only, and no value was set or tuned on outcomes (OPEN-10).

- **Inputs.** (1) The reaction energy ΔE in eV/atom: the Precursor agent's decomposition-aware energy if one was accepted, otherwise Thermo's latest accepted estimate, so an escalated `single_point` or `bounded_relaxation` replaces the `cached_lookup` value. A missing or conflicting energy is taken as 0.0 (neutral) and marked absent. (2) For each precursor, the furnace temperature minus that precursor's Tammann temperature in °C, from Kinetics' tool values (2/3 of the absolute melting point, `kiln.tools.tammann`). A missing Tammann temperature is taken as 0 °C margin (neutral) and raises a `missing_evidence` flag through `kiln.review`.
- **`p_react`.** Logistic of −20 × ΔE + 0.005 × (furnace − Tammann A) + 0.005 × (furnace − Tammann B), with intercept 0. The weights are scale conventions (one logit unit per 50 meV/atom of driving force, and per 200 °C of margin on each precursor), not fitted values.
- **`category`, `cause` and `fix`.** The first matching rule in this order decides: (1) no single accepted reaction energy → `unreacted`, cause `insufficient_evidence` (the rule set's defined fallback, not a call from evidence); (2) a decomposition-aware energy is present and ΔE ≥ −0.05 → `transformed`, `decomposes_only`; (3) ΔE ≥ −0.05 → `unreacted`, `no_driving_force`; (4) the furnace is below both Tammann temperatures → `unreacted`, `kinetically_limited`; (5) or (6) the furnace is below exactly one Tammann temperature → `partially_reacted`, `one_precursor_below_tammann`; otherwise `completely_reacted`, `driving_force_and_mobility`. The −0.05 eV/atom boundary is about two standard deviations of GGA+U reaction-energy error (Hautier et al., *Phys. Rev. B* 85, 155208, 2012, as cited in the file).
- **Flags.** A `conflict` flag counts as a disagreement and an `outside_applicability` flag as an applicability note. B60meV is not used in scoring (§4.2).

**`p_react` and `category` are separate outputs** (*decided 2026-11-01 by Hemanath: intended as documented; `docs/plan-changes.md` row 30*). `p_react` comes from the logistic driving-force score above, and the category comes from the ordered rule list. Nothing ties one to the other, so a high `p_react` can appear with a no-reaction category, for example through a kinetic or a decomposition rule. Illustrative numbers: ΔE = −0.30 eV/atom with the furnace 100 °C below both Tammann temperatures gives a logit of 6 − 1 = 5, `p_react` ≈ 0.99, and category `unreacted` (`kinetically_limited`); ΔE = −0.04 eV/atom with the furnace 300 °C above both gives a logit of 0.8 + 3 = 3.8, `p_react` ≈ 0.98, and category `unreacted` (`no_driving_force`), or `transformed` if a decomposition-aware energy was accepted. `p_react` is the ranking score for AUROC (Brier is also computed from it, §7), and the category is scored by four-class accuracy. Neither is a calibrated probability (`AGENTS.md` rule 10).

## 4. Conditions

### 4.1 Agent conditions, all at one equal locked budget

Decided under **OPEN-01**: the definitions are the ones the runner already codes (`src/kiln/runners/conditions.py`, module docstring, lines 5 to 8), with C2 isolated and C4 the collective.

| ID | Condition | Definition (source: `runners/conditions.py`) |
|---|---|---|
| C1 | Single agent | `SingleAgent` with every specialist skill and every tier; one board; needs suppressed (also interfaces step 6, `agents/single.py`) |
| C2 | **Isolated specialists** | Thermo, Kinetics and Precursor, each on **its own board** (`Board(run_dir, name=...)`, interfaces additions); needs suppressed, so no specialist can ask another for evidence |
| C3 | Central planner | `Planner` with the specialists as callees; one board; needs go to the planner, which decides which specialist runs and which compute to buy (interfaces step 6, `agents/planner.py`). A core comparator, not optional (`schemas.py`) |
| C4 | **Need-board collective (Kiln)** | Thermo, Kinetics and Precursor on **one shared board**; needs delivered; no central planner |

**Settled invariants across C1 to C4** (`runners/conditions.py`; `prompts/cj.md` Task 3; `AGENTS.md` rules 7, 8 and 11):

- same items (the sorted evaluated held-out list), one `Budget` per item drawn on by every agent in the condition (the planner's tokens included), the same frozen tier prices, compute client and result cache (cache hits charged in full);
- same LLM provider and model, `gemini-3.8-flash` (**OPEN-04**). The `gemini-3.1-flash-lite` fallback (PC6) applies to every condition and seed or to none, because one model must serve all of them;
- same verifier, review-flag function, scoring call and output format;
- LLM agents choose what to compute and write rationales but never set numbers.

### 4.2 Baselines (reference points, not equal-budget comparators)

| ID | Rule | Status |
|---|---|---|
| B0 | Driving-force threshold: predict a reaction when the cached `dE_ev_per_atom` is at or below a threshold (PR #10). Ranking score for AUROC: `−dE_ev_per_atom` | Threshold **0 eV/atom** (label-free), decided under **OPEN-08** |
| B0-T | Temperature ratio: rank items by `T_dwell / T_melt(higher)`, both in kelvin, from `Item.temperature_c` and the higher of the two melting points (PR #19, merged). The ratio is the ranking score | **Ranking only.** No `ratio_threshold` is frozen and no reported metric uses one, decided under **OPEN-25**. If the code needs a value to run, the value used is recorded with the output |
| B60meV | Competition-margin feature and regime marker, not a rule for whether a pair reacts: `margin = dE_competing − dE_best` in eV/atom (never negative), and `decisive = margin ≥ CompetitionMarginConfig.margin_threshold_ev_per_atom` (PR #19, merged). It has no `reacts`, `p_react` or category field | Threshold **0.060 eV/atom**, the literature value (Szymanski et al. 2024, below); **no mapping** to `p_react` or `Category`; decided under **OPEN-25** |
| B1 | Logistic regression on development data, with leave-one-precursor-out folds (PR #9) | **Not reported** in this experiment: it needs development labels, and there is no development-label path (**OPEN-09**, **OPEN-10**) |

- **Filing.** The B0-T and B60meV thresholds are OPEN-25 throughout this protocol. How a B0 or B0-T decision becomes a `Prediction`, and how B0's lookups are charged, is OPEN-08. `src/kiln/baselines/b0.py` (its `TemperatureRatioConfig` docstring and its `to_predictions` error text) still cites OPEN-08 for the B0-T threshold and calls OPEN-25 "a new OPEN-25"; those code comments are out of date, and this protocol is the record.
- **How baselines are reported (OPEN-08), decided.** Baselines are reported in their **own table**, on the 346 evaluated held-out items, by **AUROC of their ranking score only**. B0 and B0-T are not mapped to `p_react` or `Category`, so they have no Brier score or category accuracy, and `to_predictions` keeps failing closed. This needs evaluator code that computes AUROC from a ranking score without a `Prediction`; Hemanath writes it before Gate H. A missing input gives an undetermined result with a `missing_evidence` flag (PR #10, PR #19); such an item stays in the table's denominator note and is listed, not imputed. For B0-T, one missing melting point leaves the ratio undetermined, because the missing one could be the higher.
- **Charging B0's lookups (OPEN-08), decided.** B0's `cached_lookup` requests go through the compute client, are charged the frozen `cached_lookup` price (§5) even on a cache hit, and are logged with a reason (rule 8). They are reported in the baseline table and charged to no agent condition.
- **B0-T replaced a Tammann-fraction rule.** PR #10 had put a Tammann-fraction rule on `dev`; PR #19, merged, replaced it with the ratio. The two-thirds fraction that `prompts/annamayya.md` specifies for `kiln.tools.tammann` is not a B0-T setting.
- **Label-free check from proposal 0001 §1** (Item fields only, 981 items): `temperature_c` takes 9 distinct values (200, 300, 400, 500, 700, 800, 900, 1,000 and 1,100 °C), and `dwell_h` takes 2. The reviewer's assertion that every pair was fired at two-thirds of the lower melting point, rounded down to 100 °C, holds for 456 of 981 items when the melting points are read in °C and for 314 when they are read in kelvin. So the furnace temperature is not a deterministic function of the melting points for every item, but it depends on them for many. B0-T therefore stays a ranking reference with this circularity caveat, and the claim is not reframed as "standard one-hour firing".
- **B60meV is a margin feature and regime marker only.** Its name comes from Szymanski et al., *Science Advances* 10(27), 2024, DOI `10.1126/sciadv.adp3309`, who found the **first product to form** predictable when its driving force exceeds that of every competing phase by at least 60 meV/atom. That finding is about which product forms first, not whether a pair reacts, so B60meV is never a validated reacts-or-does-not-react rule. The threshold is recorded on every result.
- **B60meV is not a `ConditionId`** in `schemas.py`, so no `RunConfig` can name it and it yields no `Prediction`. It is used only as the hard-subset margin trigger (§4.3) and as a regime marker.

### 4.3 Hard subset (proposal 0001 §3, accepted; PC10)

An evaluated held-out item is **hard** if its competition margin from accepted evidence is known and below 0.060 eV/atom, **or** either precursor is on the formula list below. An item whose margin is unknown and whose precursors are not on the list goes into an **unknown** bucket, which is reported, never dropped. All other items are **easy**. The hard subset is fixed and its definition hash posted before labels load (`evaluate.py`), and it is reported next to the all-items metrics as a secondary, descriptive result (§8).

**Formula list (OPEN-26), decided.** The ledger writes 9 of the 46 formulas in pymatgen-style notation (`Al(HO)3`, `B(HO)3`, `FeH4(CO3)2`, `K4H6C2O9`, `KP(HO2)2`, `La(HO)3`, `LiH3O2`, `PH6NO4`, `PH9(NO2)2`), so the text rules in `evaluate.py` (`HARD_SUBSET_FORMULA_RULES`: `CO3(?![0-9])`, `OH(?![a-z])`, `NH4(?![0-9])`) do not classify every precursor correctly. Hard-subset membership by formula is therefore this **explicit list**, not the regexes. Compound identities come from the stoichiometry and the notes in `data/precursor_props.csv`:

| Group | Formulas on the list (ledger notation, conventional form) |
|---|---|
| Carbonate | `BaCO3`, `CaCO3`, `Li2CO3`, `Na2CO3`, `SrCO3`, `K4H6C2O9` (K2CO3·1.5H2O, potassium carbonate sesquihydrate) |
| Hydroxide | `Al(HO)3` (Al(OH)3), `La(HO)3` (La(OH)3), `LiH3O2` (LiOH·H2O) |
| Ammonium | `PH6NO4` (NH4H2PO4), `PH9(NO2)2` ((NH4)2HPO4) |

That is 11 precursors, 3 of them held out (`CaCO3`, `Li2CO3`, `Na2CO3`). **Not on the list:** `FeH4(CO3)2` (FeC2O4·2H2O, iron(II) oxalate dihydrate; the `CO3` regex matches it, but oxalate is not carbonate, as the rule's own comment says), `B(HO)3` (boric acid, conventionally H3BO3) and `KP(HO2)2` (KH2PO4). These three are acids or acid salts, not carbonate, hydroxide or ammonium compounds in conventional notation. The regexes miss 6 formulas on the list and wrongly match 1 formula off it, so `evaluate.py` must use this list before the hard-subset hash is computed and posted (Hemanath, scoring code; §17).

## 5. Locked budget and frozen price list

**Settled charging rules** (`AGENTS.md` rule 8; interfaces steps 3 and 4):

- Every compute request goes through `kiln.compute.client.request` and `kiln.budget.Budget`. Agents never call ALCHEMI directly.
- The frozen tier price is charged **before** the request runs, even on a cache hit. Every request is logged to `runs/<run_id>/compute_requests.jsonl` with a one-sentence reason.
- `Budget` raises `BudgetExceeded` when a limit is reached. Running out before a key check raises a `missing_evidence` review flag (`schemas.py`, `ReviewReason`).
- `not_converged` and `failed` requests are logged as such and raise a `failed_computation` flag. They are never silently replaced or dropped (rule 9).
- One budget level only (rule 11; `prices_proposal.json` reports that a second level does not fit Night 2).

**Frozen tier prices and per-item compute budget (OPEN-03, OPEN-02).** Copied verbatim from `protocol/prices_proposal.json` at commit `1e8549be49a1837b5f08c74506bad192ff2b2ea1` (Adhi, 2026-10-31 19:47 EDT, "round the per-item budget up so one full escalation path fits (31 -> 32)"). Measured on the GB10 (`results/gb10/profile_s0_fix.json`, 20 development pairs, seed 0, float32). Adhi settled the per-item cap in that commit. **Any further change to these values is blocking: it is written here before the Gate P commit, never by amendment (§17, table 1).**

| Item | Frozen value | Source |
|---|---|---|
| Compute unit | 1 unit = median `single_point` GPU-seconds = 0.49578814350024913 s | `prices_proposal.json`, `compute_unit` |
| `cached_lookup` price | 0.1 units | `tier_prices` |
| `single_point` price | 1.0 units | `tier_prices` |
| `bounded_relaxation` price | 30.0 units | `tier_prices` |
| `decomposition_reeval` price | 0.2 units | `tier_prices` |
| `max_compute_units_per_item` | 32.0 units | `max_compute_units_per_item` |
| `max_tool_calls_per_item` | 12 | `RunConfig` default in `schemas.py`; **placeholder, not profiled** |
| `max_tokens_per_item` | 40,000 (Gemini thinking tokens count as output tokens against this cap, PC13) | `RunConfig` default; **placeholder, not profiled** |
| `coordination_rounds` | 3 | `RunConfig` default; **placeholder, not profiled** |
| USD cap per item | None. `Budget.record_usd` records spend and does not cap it (interfaces additions) | — |
| Unused budget carry-over between items | None; the budget is per item (**OPEN-20**) | `RunConfig` |

- **Why 32 units.** The proposal's rule is "budget per pair: one escalation path (cached_lookup + single_point + bounded_relaxation + decomposition_reeval)", which costs 0.1 + 1.0 + 30.0 + 0.2 = 31.3 units. In `1e8549b` Adhi rounded the cap up from 31.0 to 32.0 so that the whole path fits. At 31 the 30-unit relaxation was refused in a 1-item GB10 dry run (`prices_proposal.json`, notes).
- `prices_proposal.json` sets no tool-call, token or round cap, so the `RunConfig` defaults are frozen and labelled as placeholders rather than new numbers being guessed.
- **Night-wide stops** (`night2.toml` `[caps]`, set in `e89d25a`): **12,000,000 tokens, USD 30.0, 8.0 GPU-hours**. These are CJ's run-safety limits, not part of the per-item budget. They come from the Sat 7:15 PM GB10 dry run with the real agents on 5 development items: every specialist and every controller calls `gemini-3.8-flash` (the specialists have called the run's model since `9925875`), and scaling the measured tokens and spend per item to 346 items × 3 seeds gives about 9.3 M tokens and about USD 23, so the caps leave about 30% headroom. That 9.3 M and USD 23 is a projection from 5 items, not a measurement of the full night. If a cap is breached and an item gets no prediction, OPEN-23 applies (§6).
- **Parallel runs** (`231e432`). The Night 2 `run_conditions` step uses `--parallel 12`: every condition and seed runs at once, each run keeps its own lock and resumes per item. The compute client holds a per-key file lock around the cache check and the computation, so parallel runs wait for one another and hit the cache instead of computing the same calculation twice. Every request is still charged the full frozen price (rule 8).
- **`protocol/frozen_settings.json`**, which the Night 2 runner reads (`night2.toml`, `--frozen`), carries exactly these values: `tier_prices` 0.1 (`cached_lookup`), 1.0 (`single_point`), 30.0 (`bounded_relaxation`) and 0.2 (`decomposition_reeval`); `max_compute_units_per_item` 32.0; `max_tool_calls_per_item` 12; `max_tokens_per_item` 40,000; `energy_margin_ev_per_atom` 0.05 and `disagreement_threshold_ev_per_atom` 0.05 (§6). The runner refuses to start if the file or any of these keys is missing (`runners/conditions.py`, `_read_frozen`). It does not read `coordination_rounds`, so the `RunConfig` default of 3 applies (`CAP_KEYS`). Hemanath gave his OK on 2026-11-01, and Adhi pushed the file in `4055d77`; its values match this section exactly. SHA-256 of the file at `4055d77`: `2c1f9acbc7e52d14 ff8d88b9e00e9d3a 79baa9963a132f57 91ca3b28aca71377` (four 16-character blocks, for the same reason as in §3.3).

### 5.1 Approved compute and LLM settings recorded at freeze

`docs/compute-decisions.md` says Hemanath freezes the final values here. These settings are approved in `docs/plan-changes.md` and are part of the frozen protocol; they are not OPEN items.

| Setting | Frozen value | Source |
|---|---|---|
| MACE precision | float32 | PC5; `env/gb10/tier_settings.json`; `compute-decisions.md`, "MACE precision" |
| Compute backend | ASE (`FrechetCellFilter` + FIRE2) is the default; the ALCHEMI Toolkit backend (`nvalchemi`) is not the default | PC7; `compute-decisions.md`, "Backend" |
| Phase set for the MLIP tiers | The phases the a-b reaction energy depends on (decomposition along the a-b line, reactants, elemental references), plus near-hull competitors on that line up to `max_structures` | PC8; `tiers.py` `_phase_set` |
| Hull window | 0.1 eV/atom, one value, for near-hull competitors and for Thermo's "product near the hull" trigger. B60meV's 0.060 eV/atom is a different quantity | PC9 |
| Relaxation tier | Element references get a single point; a near-hull competitor that does not converge is dropped and listed; a request is `not_converged` only if a reactant or a product along the a-b line fails | PC16 |
| Experiment LLM | `gemini-3.8-flash` for every condition and seed, called by every specialist and every controller; temperature 0; the run's seed passed to the call (interfaces additions) | PC6; `night2.toml`; `9925875` |
| LLM token accounting | Gemini thinking tokens count as output tokens, billed and charged against the per-item token cap | PC13; `agents/base.py` |

### 5.2 Night 2 on two machines: GB10 primary, H100 replication (PC27)

Approved in `docs/plan-changes.md` row 27 (Adhi, 2026-11-01, `0de530d`; `AGENTS.md`, Night 2 facts). The GB10 runs `src/kiln/night/plans/night2.toml`, and the H100 runs `src/kiln/night/plans/night2-h100.toml` (`2532d78`). Hemanath sets up the H100 (row 27); which H100 machine, and how it is provisioned, is not recorded on `dev`.

- **Two full runs.** The full experiment (C1 to C4, 3 seeds, the 346 evaluated held-out items) runs on the GB10 and again on an H100.
- **GB10 primary, named before grading.** The GB10 run is the **primary** run, named as such before anything is graded. The main table, the primary endpoint (§8) and the results in §7 to §9 come from it. The H100 run is a **full replication**, reported in its own table, never pooled with the primary run and never used to choose results.
- **Same frozen inputs, except the compute backend.** Both runs use the frozen P2 code-freeze commit (§10), `protocol/frozen_settings.json` (§5), `gemini-3.8-flash`, the same items file (below), `--parallel 12` and the same night-wide caps: 12,000,000 tokens, USD 30.0 and 8.0 GPU-hours, applied to each machine separately. Total Gemini spend therefore roughly doubles, to about USD 46 and 19 M tokens (row 27).
- **Compute backend differs (PC28).** The two runs are **not** identical in compute backend. The GB10 primary run keeps the ASE backend (PC7; `env/gb10/tier_settings.json` sets no backend, so the ASE default applies). The H100 replication runs its GPU tiers on backend `"nvalchemi+ase"`, selected with `KILN_TIER_SETTINGS=env/h100/tier_settings.json` (`fcf4e19`; `docs/plan-changes.md` row 28, `d9a2993`): the NVIDIA ALCHEMI Toolkit relaxes each batch on the GPU, and ASE re-runs, from the original structure, only what the Toolkit leaves unconverged or failed. The model (`medium-mpa-0`), precision (float32), phase set (hull window 0.1 eV/atom, at most 40 structures and 200 atoms) and convergence rule (force ≤ 0.05 eV/Å **and** |stress| ≤ 0.001 eV/Å³, at most 500 steps) are the same. The optimizer is not: the Toolkit uses its variable-cell FIRE2 with the step settings in `env/h100/tier_settings.json` (`dt` 0.2, `fire_tmax` 1.0, `fire_maxstep` 0.2), so a relaxation can take a different path to the same convergence rule. The H100 preflight refuses to start unless `KILN_TIER_SETTINGS` names that file, its `bounded_relaxation` backend is `nvalchemi+ase`, and the Toolkit imports. H100 requests record `backend` and `n_finished_by_ase`.
  - **GB10 check of the hybrid backend** (`results/gb10/toolkit_hybrid_check.json`, `d9a2993`): on 40 strained and rattled structures, ASE converged 40, the Toolkit alone 39 and `nvalchemi+ase` 40; the hybrid's energies were within 0.25 meV/atom of ASE's; GPU time was 14.4 s for the hybrid against 27.1 s for ASE. On CaO + TiO2 (not a Precursor Genome pair: CaO is not one of the 46 precursors), the Toolkit left 12 of 40 phases unconverged and ASE finished them; ΔE was −0.1310 eV/atom against Materials Project's −0.1327. This is one check of 40 structures and one pair on the GB10, not a validation that the two backends give equal results on the held-out items.
- **Compute units on the GB10 scale; GPU-seconds per machine.** Prices and the per-item budget stay in compute units exactly as frozen in §5. The unit is the median `single_point` GPU-seconds measured on the GB10, and both runs are charged in those units at the frozen tier prices, so the 32-unit budget is the same on both machines. GPU-seconds are reported per machine; H100 GPU-seconds, which also reflect the different backend, are not comparable to the GB10 profile in `prices_proposal.json` (§9).
- **Separate outputs.** The H100 run is launched with `--runs-dir runs-h100` and writes to `runs-h100/`, `protocol/predictions-h100.manifest.json` and `protocol/posts-h100.jsonl`, so the two runs never overwrite each other when results are combined. Each machine's manifest is hashed and posted on its own through `KILN_PREREG_WEBHOOK`, and Gate H (§10) applies to each.
- **Second Gemini account on the H100.** The H100 run uses the second Gemini account's key. Its preflight step fails unless `GEMINI_API_KEY_2` is set and `GEMINI_API_KEY` is unset, because `llm_call` tries `GEMINI_API_KEY` first (`night2-h100.toml`). Row 27's wording ("as its `GEMINI_API_KEY`") conflicts with that check; the preflight governs (§17).
- **Items file, the same required file on both machines.** Both plans read `${HOME}/kiln-items.jsonl`, which is outside the repo. **Required SHA-256:** `0a97babfab2f2ce4 d3459b8e9d83ba1f 2544acf50feb3687 bef0e47afd17f663` (four 16-character blocks, for the same reason as in §3.3). This reference value is the hash of the copy on Hemanath's machine, taken on 2026-10-31; that copy holds 981 items, 635 `dev` and 346 `heldout` by its `split` field, as in §2.2. Per the team's instruction of 2026-11-01 (not yet written in a doc on `dev`), the copy on the GB10 is replaced with this file and hash-checked before the run, the H100 gets the same file, and the file is kept outside the repo and outside any image.
- **Labels never on either machine.** Both plans set `labels_must_be_absent = true`, and the night runner refuses to start if labels are present. In both plans the `fetch_labels` and `score` steps only stop and alert, so each night ends after the hash post and push. Hemanath scores on his own machine, where the labels stay, after the posted hashes are checked (`docs/night2-runbook.md`).
- **Keys only as hidden environment input.** API keys and webhook URLs reach each machine only as environment variables typed in as hidden input (`read -rsp`, `docs/night2-runbook.md` §3, "Keys and webhooks on the GB10"; the same method applies on the H100), never in the repo, a plan file or an image (`AGENTS.md` rule 4).
- **What a difference between the runs means.** Differences between the two runs mix **hardware, compute backend and LLM run-to-run variation**, and are reported as such, never as the effect of any one of them. The proposed H100 compute check (known-answer test, the 20 profiled pairs and the 40-structure benchmark on the H100, compared with the GB10; listed as proposed in `docs/plan-changes.md`) would help separate them; it is not part of this protocol unless approved.

## 6. How one item is processed

The flow, settled in `docs/interfaces.md`:

1. `load_items(split)` gives `Item`s.
2. Agents post needs and artifacts on the board and buy compute.
3. `kiln.verifier.verify` checks every artifact. Only `accepted` artifacts feed review flags and scoring.
4. `kiln.review.flags` adds missing-evidence, failed-computation, conflict and outside-applicability flags.
5. `score.score` produces the `Prediction`.
6. The runner writes `runs/<run_id>/predictions.jsonl`.

- The verifier (PR #5) checks: `falsified_if`, citations, documented value keys and units, forbidden label keys, cited compute request ids, numbers matching cited compute results or recomputed tool values, compute charges and item budgets.
- **Verifier contract (OPEN-24): closed on `dev` at `0c5eeea` except one latent gap.** `Budget.item_cost` exists (`src/kiln/budget.py`, added in `82eaefc`), and `docs/interfaces.md` step 7 shows the full signature `verify(artifact, board, *, requests, config, item_cost, tool_values)` (also `82eaefc`). The runner passes all four (`runners/conditions.py`): `item_cost` is the item budget's cumulative cost (`budget.spent`, which is what `Budget.item_cost` returns), and `tool_values` comes from `kiln.tools.tammann.item_tool_values`, which recomputes `tammann_a_c` and `tammann_b_c` for the item. So Kinetics' Tammann values and Precursor's compute-backed `dE_ev_per_atom` can be `accepted`, and §3.3 scores from them. In the `388eb76` dry run (5 development items, C1 to C4, real agents, at `e89d25a`), the verifier accepted every artifact (`results/gb10/dryrun_e89d25a/summary.txt`: verifier-not-accepted 0 in every condition). **Still open:** the verifier also treats `decomposes_at_c` and `volatile_above_c` as tool keys, but the runner's `tool_values` does not include them. A Precursor artifact carrying a numeric `decomposes_at_c` would therefore be `inconclusive`. Precursor emits that value only when it answers a `decomposition_products` need, and no agent on `dev` posts that need, so the path does not run today; Precursor's main report carries decomposition evidence only as strings and booleans plus the compute-backed energy, so it is not affected. No agent emits `volatile_above_c`. If the need path starts to run, those artifacts stay `inconclusive` until the runner supplies the values (Annamayya for the tool, CJ for the runner).
- **Specialist escalation rule (OPEN-07), decided 2026-10-31: escalation is a default, not a cage.** Annamayya decided the rule and implemented it in `a10c149` ("agents: implement agreed escalation boundaries"); the zero-tolerance fixes in `0c5eeea` were committed on her behalf at Adhi's request. Hemanath set the thresholds (delegated). The rule and its development-data check are in `docs/escalation-rule.md`, whose own recommendation for T_rxn was 0.02 eV/atom; the decided value is 0.05 (its section "OPEN-07 decision as proposed"). As coded on `dev` at `0c5eeea` (`agents/thermo.py`, `agents/kinetics.py`):
  - **Borderline driving force:** 0 < |ΔE_rxn| ≤ 0.05 eV/atom (`energy_margin_ev_per_atom`). Any |ΔE_rxn| ≤ 1e-6 eV/atom counts as zero (`ZERO_DE_EV_PER_ATOM`), because Materials Project returns "no product below the join" as 0 or as float noise of about 1e-15 (110 of 635 development pairs, `0c5eeea`).
  - **Near-hull competitor:** 0 < `competitor_e_hull_ev_per_atom` ≤ 0.1 eV/atom with `competitor_e_hull_status` = `ok`, from the accepted `cached_lookup` (the nearest off-hull competitor on the a–b join, `b09f550`; `none_on_join` carries no value and never triggers). 0.1 eV/atom is the one hull window of PC9.
  - **Disagreement:** T_disagree = 0.05 eV/atom (`disagreement_threshold_ev_per_atom`) on |ΔE_mlip − ΔE_mp|. A disagreement strictly above it is a reason to go on to `bounded_relaxation`, and the **same** value is the `conflict` review-flag threshold, so the escalation trigger and the flag cannot disagree.
  - **Recommendations.** After `cached_lookup`, Thermo's rule recommends `single_point` when the energy is borderline or a competitor is near the hull. After `single_point`, it recommends `bounded_relaxation` when either still holds or the methods disagree. Otherwise it recommends stopping. Kinetics recommends `firm_up_energy` under the same borderline test, and otherwise recommends skipping; when the model chooses `firm_up_energy`, Kinetics posts that need on the board for Thermo.
  - **A zero alone never recommends escalation, but it does not forbid it.** The model is told the energy is zero and may still escalate within the item's budget. Any choice that differs from the rule's recommendation, in either direction, is explained in a separate, budgeted LLM call, labelled as a post-hoc explanation, and logged in the artifact's rationale; for Thermo the same text is the compute request's logged reason (`0c5eeea`; Kinetics now does this the same way as Thermo). LLM agents still never set numbers (rule 7).
  - **Same rule in every condition.** The runner builds the same specialists with the same two values from `protocol/frozen_settings.json` for C1 to C4 (`runners/conditions.py`, `real_components`), and C1 and C3 call the same specialist code. Because the margins are non-null, Kinetics posts needs: they are delivered in C4 and suppressed in C2, so C2 and C4 are different designs.
  - **The two 0.05 eV/atom values are proposals, not validated accuracy guarantees.** T_rxn rests on the scoring rules' −0.05 boundary and the measured MLIP-versus-MP gap; T_disagree rests on 20 profiled development pairs, where |ΔE_mlip − ΔE_mp| was at most 0.035 eV/atom for single points (`docs/escalation-rule.md`). Neither was set from any outcome.
  - **Known limits** (`docs/escalation-rule.md`, compute outputs on development pairs only; no labels, no held-out pair). **These counts were computed before `0c5eeea`**: in `be51b06` and `56f6be6` (2026-10-31, 20:34 and 20:45 EDT), on the GB10's Materials Project cache, which is not in the repo. `0c5eeea` (23:17 EDT) added the 1e-6 eV/atom zero tolerance afterwards. The doc does not state what zero tolerance its analysis used. Its own distribution suggests the float-noise pairs were counted as zero: it puts only 8% of development pairs (about 51) at 0 < |ΔE_rxn| ≤ 0.01, fewer than the 110 noise pairs of about 1e-15 that `0c5eeea` reports, so those 110 cannot all have been counted as non-zero. If that holds, the counts below match the rule as coded. This is an inference, not a recount; the recount of (a), (b) and their union with `ZERO_DE_EV_PER_ATOM` on the same cache is pending Adhi (§17, table 3). As the doc reports them: the rule recommends escalation for **57%** of development pairs (360 of 635: 253 borderline, 159 with a near-hull competitor, overlapping; 242 pairs have ΔE_rxn = 0). On the 20 profiled development pairs, **2 changed provisional category** by crossing the −0.05 scoring boundary: PG_2940 (−0.046 → −0.053 at `single_point`), which the rule escalates, and **PG_1048 (−0.052 → −0.035), just outside the window**, which the rule does not escalate because |ΔE_rxn| = 0.052 > 0.05. The window lies entirely on the `unreacted` side of that boundary, so 49 development pairs (8%) with −0.07 ≤ ΔE_rxn < −0.05 can flip category but are not recommended for escalation. 20 pairs is a small sample, and the relaxations in that profiling run were `not_converged`.
- **Review flags (OPEN-06), decided 2026-10-31.** `kiln.review.flags` is called with `disagreement_threshold` = 0.05 eV/atom in every condition (`runners/conditions.py`). As coded in `src/kiln/review/__init__.py` on `dev`:
  - **`conflict`:** |ΔE_mlip − ΔE_mp| > 0.05 eV/atom on an accepted artifact.
  - **Kept as they are:** `missing_evidence` when accepted thermodynamic or kinetic evidence is missing, or when the decomposition temperature is unknown for a precursor that can decompose (next bullet); `failed_computation` for every `failed` or `not_converged` request; `missing_evidence` when a decomposition re-evaluation uses literature conditions not verified for this experiment; and `missing_evidence` when a reported melting point may instead be a decomposition or dehydration temperature (`data/precursor_props.csv`, §2.1).
  - **`outside_applicability`:** only when an evidence source explicitly reports that the item is outside its applicability (`outside_applicability` is True on the artifact). No other condition raises it.
  - **Decomposable-only flag: adopted (PC29).** An unknown decomposition temperature is missing evidence **only for a precursor that can decompose**: one containing H, C or N, or one of the oxygen-releasing oxides MnO2, Mn2O3, Fe2O3, Co3O4, CuO, BaO2, Ag2O and PbO2; a formula that cannot be parsed is treated as able to decompose (`can_decompose` in `src/kiln/review/__init__.py`, on `dev` from `7b0f515`, marked approved in `1782ba6`). Approved by Hemanath and Adhi on 2026-11-01 (`docs/plan-changes.md` row 29). It uses no labels. As reported in row 29 and `1782ba6`, it changes the number of flagged pairs from 339 to 183 of the 346 held-out pairs (98% to 53%) and from 614 to 310 of the 635 development pairs.
- **An item with no prediction (OPEN-23), decided and implemented.** The runner calls `score` on whatever accepted evidence exists, which may be none, and an item whose budget runs out is still scored ("No item is skipped", `runners/conditions.py`). An item that crashes, times out or is never reached (for example after a night-wide stop) is handled by `kiln.runners.finalize` (`231e432`), the Night 2 `finalize` step that runs after `run_conditions` and before the prediction manifest is written and hashed. It scores each such item on empty evidence through the run's own scorer, with a `missing_evidence` flag saying why; the item's cost is what its logged compute requests were charged, so accounting still reconciles; and each finalized item is recorded in `finalized_items.jsonl`, with a count per run. The step depends on `run_conditions` succeeding, so a systemic failure (no API key, service down) stops the night instead of hashing empty predictions. The item stays in the denominator, and the count is reported per condition and seed. Real runs score with the frozen scorer, `score.frozen_engine` (`852a811`).

## 7. Metrics

Every metric is computed on **all 346 evaluated held-out items** (§2.4), flagged ones included, for each run (one condition, one seed). There is no abstention; review flags never remove an item from the denominator (interfaces step 11). Items with an `unclassified` or null label are excluded from the label-based metrics only (§3.1, OPEN-12).

As implemented in the PR #8 evaluator (synthetic tests only):

| Metric | Definition |
|---|---|
| AUROC (binary) | Mann–Whitney estimate of `p_react` against `reacted`, with ties counted as one half. Undefined when one class is absent |
| Brier (binary) | Mean of `(p_react − reacted)²` |
| Four-class accuracy | Fraction of pairs where the predicted `category` equals the label category |
| Coverage | Fraction of pairs with `needs_review = False` |
| Flagged and unflagged accuracy | Four-class accuracy within flagged pairs and within unflagged pairs, with both counts |

- The evaluator also requires `p_react` to be finite and in [0, 1], `needs_review` to equal `bool(review_flags)`, a single run, condition and seed per file, and the same item set in predictions, items and labels.
- **Secondary binary split (PC26; kept as secondary and descriptive, decided 2026-11-01 by Hemanath):** `secondary_binary_split` in `src/kiln/scoring/evaluate.py` reports AUROC and Brier with only `completely_reacted` counted as reacted, next to the primary metrics. It is secondary and descriptive. The primary metrics and the primary endpoint keep the §3.2 split (`partially_reacted` or `completely_reacted` counts as reacted). It changes no prediction and runs only at grading.
- **Primary endpoint (OPEN-14):** the paired difference in AUROC, C4 minus C1 (§8). Every other metric is secondary and descriptive.
- `p_react` is a fixed-rule score. Brier measures how far it sits from the outcomes; it does not make `p_react`, a review flag or a stated cause a calibrated probability or a validated failure cause (`AGENTS.md` rule 10).

## 8. Statistical comparison

- **Pairing.** Every condition predicts the same held-out items, so each comparison between conditions is paired item by item.
- **Seeds (OPEN-04), decided.** 3 seeds per condition (seeds 0, 1 and 2; `docs/credits.md`: "all 3 seeds (don't cut to 2)"; `night2.toml`). Every metric is reported for each seed and as the mean of the 3 seeds.
- **Primary endpoint (OPEN-14), decided.** ΔAUROC = AUROC(C4) − AUROC(C1), computed for each seed on the same 346 evaluated held-out items (minus OPEN-12 exclusions) from the GB10 primary run (§5.2), then averaged over the 3 seeds. The report gives the mean, the three per-seed values, and the **9 per-precursor differences**: for each held-out precursor, ΔAUROC on the held-out items that contain it (a pair with two held-out precursors counts in both of their slices), as a mean over the 3 seeds, with a sign count (how many of the 9 are positive, negative or zero). A slice where AUROC is undefined is reported as undefined, not dropped. **Why the escalation rule matters here:** this endpoint tests the collective only because OPEN-06 and OPEN-07 set non-null margins (§6). With both margins null, no agent would post a need, C4 would be the same design as C2, and C4 − C1 would compare one LLM controller with uncoordinated specialists.
- **Decision rule.** A positive mean ΔAUROC is reported as "C4 ranked better than C1 on this held-out set", a negative one as "C1 ranked better". ΔAUROC is reported to three decimal places, and a mean of 0.000 is **reported as a tie**. Seeds that disagree in sign, or per-precursor differences that disagree with the mean, are stated next to the result. Because no interval or test is reported (below), no difference is called significant or general.
- **Multiplicity.** There is one primary contrast, so no adjustment is needed. Everything else is secondary and descriptive, with no adjustment and no significance claim: C4 against C2 and against C3, every other pairwise contrast, Brier, four-class accuracy, coverage, flagged and unflagged accuracy, the hard subset (§4.3), items with two held-out precursors (31) against items with one (315), the baseline table (§4.2), the compute-allocation tables (§9), the secondary binary split (§7) and the H100 replication (§5.2), which is reported in its own table. Proposal 0001 §4 Option B (a within-run accuracy-versus-cumulative-compute curve from the provisional scores) is descriptive only; Option A (a second budget level) is out of scope under rule 11.
- **Uncertainty (OPEN-15), decided: no interval and no significance claim.** Every pair belongs to **two** precursor clusters, so the clusters overlap (a crossed design), and no resampling scheme for overlapping precursor clusters has been validated for this design. No interval, p-value or significance claim is reported for any result. The PR #8 evaluator returns no intervals on purpose; its `bootstrap_samples=1000` and `bootstrap_seed=0` arguments are code placeholders, not protocol values.
- **Secondary model results** (§1) are reported in their own tables and never pooled with the main table or the primary endpoint.

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
- **`changed_prediction` (OPEN-17), decided:** True when the provisional four-class `category` after the request differs from the one before it, False when they are equal, and unknown when either is missing. It is filled by `replay_changes` in `src/kiln/compute/accounting.py` after the run and before unblinding, from the logged requests and the frozen scoring rules. It uses no label.

`python -m kiln.compute.accounting` also writes totals per request, pair and condition, a reconciliation of the request log against each prediction's `cost.compute_units`, and the allocation table (interfaces additions). Those outputs, plus compute units per item against flagged status, items that hit the budget limit, and the share of units spent on requests that changed the prediction, are reported as secondary, descriptive tables (OPEN-14).

**Run order and cache (OPEN-20), decided.** Seed 0 of every condition runs first, then seeds 1 and 2 (`night2.toml`, `run_conditions`). All conditions share one result cache; a cache hit is charged the full frozen price (rule 8), so sharing changes no condition's compute charges. No unused budget carries over between items.

All allocation figures are descriptive. `moved_toward_label` measures how a provisional score moved, not the causal value of a computation. Cache hits are charged at full price but can report near-zero GPU-seconds, so GPU-seconds depend on run order and cache state and are reported as order-dependent.

**GPU-seconds by machine** (§5.2). Compute units and budgets are the same on both machines, because the unit is fixed by the GB10 profile. Measured GPU-seconds are reported separately for each machine: the GB10 (profiling and the primary run) and the H100 (the replication). H100 GPU-seconds are not comparable to the GB10 profile, and they are never pooled with GB10 figures or converted back into compute units. The allocation tables above come from the GB10 primary run; the H100 run's tables are reported with its own replication table.

## 10. Two-step protocol and hash gates

Labels are never loaded before an **independently verified post** of the commitment that protects them.

### Step 1: protocol commitment (Gate P)

- **P1.** Owners close every `OPEN-nn` item and write the values here with their sources (§15). OPEN-06 and OPEN-07 were a hard prerequisite and are now written in §6. Every blocking item in §17 (table 1) is closed and written here before the Gate P commit. Only §17's non-blocking items (table 3) may follow as dated amendments.
- **P2.** Record the code-freeze commit SHA for scoring, verifier, review flags, compute tiers, agents and runner, in the Gate P record in `protocol/amendments.md` (a non-blocking confirmation, §17 table 3).
  - **P2 code-freeze commit:** `d9a2993997530fa4cee0f9216b78df2b5189b127` (`d9a2993` on `dev`, 2026-11-01, "plan: H100 replication on the ALCHEMI Toolkit (row 28), review-flag change approved (row 29), p_react vs category documented (row 30)"). It contains the scoring rules, verifier, review flags (with PC29), compute tiers (with the PC28 backend), agents, runner, both night plans and `protocol/frozen_settings.json`. Both Night 2 runs check out this commit. **Any later commit before Night 2 that changes code or run settings requires re-recording P2**: here, if it lands before the Gate P commit, or in the Gate P record in `protocol/amendments.md` after it. Code or run settings means anything under `src/` or `env/`, `data/precursor_props.csv`, `protocol/frozen_settings.json`, `protocol/scoring_rules.json`, `pyproject.toml` or `uv.lock`; the check is that `git diff --stat d9a2993 <run-commit> -- src env data/precursor_props.csv protocol/frozen_settings.json protocol/scoring_rules.json pyproject.toml uv.lock` prints nothing. Commits that change only `protocol/protocol.md`, `protocol/amendments.md` or `docs/` do not.
- **P3.** Commit the closed protocol and push the commit to `dev`, which blocks force-pushes and deletion (`docs/github-setup.md`), so the commit stays reachable. That commit is the **Gate P commit**. The digest is the SHA-256 of `protocol/protocol.md` as stored in that commit, `git cat-file blob <gate-p-commit>:protocol/protocol.md | shasum -a 256`. It is never taken from a checked-out copy, so line endings and checkout settings cannot change it. Post the full Gate P commit SHA **together with** the digest through the channel in **OPEN-16** (below), and verify the receipt independently. Anyone can check the commitment by rerunning that command against the posted commit.
- **P4.** Only after P3 may held-out runs start. Development runs may happen earlier.
- **P5.** After the Gate P commit, `protocol/protocol.md` is never edited. The Gate P record (commit SHA, digest, posting receipt) and every later change go in `protocol/amendments.md`, which is never part of the Gate P hash. Writing the record into this file would change the bytes being committed to.

**Posting channel and receipt proof (OPEN-16), decided 2026-10-31.** Both kinds of post (the Gate P commit SHA with its digest, and each prediction manifest digest) go through `KILN_PREREG_WEBHOOK`, which `python -m kiln.night.prereg post` already uses, to **their own dedicated channel**, separate from #kiln-alerts, where the night runner's alerts go (`KILN_ALERT_WEBHOOK`, `night/alerts.py`). The channel's name is *pending CJ*. Webhook URLs are secrets and stay in the environment, never in the repo (rule 4). The local receipt line in `protocol/posts.jsonl` is a record, not proof (`night/prereg.py`). **Adhi is the independent receipt checker:** he reads the post in the dedicated channel, reruns the P3 `git cat-file` command against the posted commit (or `shasum -a 256` on the posted manifest for Gate H), confirms the digests match and that the post time is before any label load, and his check is written into the Gate P record in `amendments.md`. Adhi is also the Night 2 operator (PC15), so for any post he makes himself, Hemanath checks it instead, so that the checker is never the poster.

### Step 2: prediction commitment (Gate H), per run

- **H1.** The run writes `runs/<run_id>/predictions.jsonl`: one run, one condition, one seed.
- **H2.** Compute the SHA-256 of the exact file bytes, write it to `runs/<run_id>/prediction.sha256` (interfaces, run folders) and post it. CJ's night runner posts the prediction manifest hash before scoring (`prompts/cj.md` Task 4; `night/prereg.py`).
- **H3.** Verify the post independently, as in OPEN-16 above. A local hash file, a posting attempt, or a receipt that has not been verified is **not** proof (PR #8).
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
6. Held-out pairs are never used to set a threshold, price, rule, escalation margin or feature: not their outcomes and not any run on them. Sources:
   - the experiment is split by precursor (`AGENTS.md` project summary; `prompts/hemanath.md` Task 1);
   - prices and the per-item budget come from profiling on 20 development pairs (`prices_proposal.json`);
   - held-out runs start only after Gate P (§10, P4).

   **No value is set from any outcome, development or held-out (OPEN-10, decided).** There is no development-label path in this experiment: every threshold in this protocol is label-free (B0 at 0 eV/atom, B60meV at the literature 0.060 eV/atom, B0-T ranking only), no development metric is computed, and B1 is not reported (§4.2, §12).
7. B0 and B0-T use no LLM and serve as LLM-free reference points.
8. **Both run machines** (§5.2). Labels are never placed on the GB10 or the H100 (`labels_must_be_absent = true` in both plans). Both read the same agent-visible items file, checked against its required SHA-256 (§5.2) and kept outside the repo and any image. API keys reach each machine only as environment variables entered as hidden input. Both run the frozen P2 commit. Kiln's agents still have no web access at runtime; their only tools are `src/kiln/tools/` and the compute service (rule 3).

**Residual risk.** Earlier A-Lab publications and older syntheses of some of the same pairs are public and may be in LLM training data. The Precursor Genome (published 2026-07-09) postdates the model's documented knowledge cutoff (March 2026, below), so it is unlikely to be in pretraining, but the cutoff guarantees nothing about later post-training data. Because LLMs cannot set numbers, recall could act only through which evidence an agent buys and through text fields (rationale, claims, cause and fix). The frozen scoring rules (OPEN-05, §3.3) read only numeric values from accepted artifacts, so text fields cannot change `p_react` or `category`; recall could still act through which evidence is bought, including an escalation the rule did not recommend (§6).

**Decided (OPEN-19):**

- **Memorization probe:** decided by rule 11. N2 runs on an OpenAI model as a secondary result, reported separately (§1).
- **Opaque item ids: not adopted.** PR #6 uses the upstream `sample_id` as `item_id`, agents see it, and no opaque-id code is on `dev`. This is listed as a limitation (§13). If opaque ids land before the held-out runs, the change is recorded as a dated amendment.
- **Model:** `gemini-3.8-flash` for every condition and seed (PC6; OPEN-04). **Documented knowledge cutoff: March 2026**, with knowledge in some areas limited to January 2025 (Gemini 3 family). Both dates are before the dataset's 2026-07-09 publication, so the Precursor Genome itself is unlikely to be in pretraining. A model-card knowledge cutoff guarantees nothing about later post-training data. Earlier A-Lab publications and older published syntheses of some of the same pairs may be in training data, and the cutoff does not rule that out. Source: `docs/compute-decisions.md` §2, quoting the Google DeepMind *Gemini 3.8 Flash* model card (https://deepmind.google/models/model-cards/gemini-3-8-flash/); the quoted sentence was rechecked on the live card on 2026-10-31.

## 12. Label safety

These rules are settled (`AGENTS.md` rule 1; `prompts/hemanath.md`; `.gitignore`):

- Label fields are moved into `labels/` (gitignored) **by code, without printing them**. Nobody opens, prints, copies or summarizes `labels/`, or the ledger's label fields: XRD patterns, refinement results, phase weights, reviewer annotations and reaction category.
- Only `src/kiln/scoring/evaluate.py` may load labels, and only after Gate H (§10).
- `Item`s carry no label fields, and the verifier rejects artifacts that use forbidden label keys (PR #5).
- Counts reported before unblinding are label-free: pairs, precursors, split sizes, excluded records and formula lists. Per-category counts are label data and are never reported before unblinding (Gate 0 evidence, §2).
- **Category strings (OPEN-11):** nobody prints or inspects the stored category values, not even the distinct values. The mapping in §3.1 is written from the README's documented names, and the evaluator fails closed on anything else.
- **Development labels (OPEN-10), decided:** no development-label path. No development metric is computed, B1 is not fitted or reported, and no threshold is tuned on outcomes.

## 13. Limitations

- **One dataset, one lab.** 46 precursors, 1,035 pairs, each run once at one furnace condition, so temperature effects are confounded with the pair. The furnace temperature also depends partly on the melting points (§4.2, label-free check).
- **Few held-out clusters.** Only 9 precursors are held out. 315 of the 346 evaluated held-out items share a development precursor; by design, the split tests generalization to new precursors, not to new chemistry on both sides. The held-out spread comes from first-element groups, not a verified periodic-group stratification.
- **No uncertainty statement.** No interval, p-value or significance claim is reported (OPEN-15), so a difference between conditions describes this held-out set only.
- **Excluded records.** The 54 records without a heating temperature (23 held-out, 31 development) are excluded before the freeze (§2.4), so results describe the 981 records with a temperature.
- **Label noise.** Categories are expert assignments from XRD refinement. `unclassified` labels reduce the evaluated set for label-based metrics (OPEN-12).
- **Fixed-rule scores and flags.** `p_react` is not a calibrated probability. Review flags are not validated failure causes. `p_react` and `category` come from separate parts of the rule set, so a high `p_react` can appear with a no-reaction category (§3.3; intended as documented, decided 2026-11-01 by Hemanath).
- **Escalation rule limits** (§6). The two 0.05 eV/atom thresholds are proposals, not validated accuracy guarantees. The rule recommends escalation for 57% of development pairs (a count made before the `0c5eeea` zero tolerance; recount pending, §6), so much of the compute is spent by default rather than by choice. Its borderline window lies on the `unreacted` side of the −0.05 scoring boundary: on 20 profiled development pairs, 2 changed provisional category, one of them (PG_1048 at −0.052 eV/atom) just outside the window and not recommended for escalation. Agents may override the rule in either direction, with a logged reason, so conditions can still differ in where they spend compute.
- **Flag coverage.** Even with the adopted decomposable-only rule (§6, PC29), an unknown decomposition temperature flags 183 of the 346 held-out pairs (53%) before any other flag, so coverage is limited and reflects the precursor property data as much as the agents.
- **Placeholder caps.** The tool-call, token and coordination-round caps are schema defaults, not profiled values (§5).
- **LLM variation and contamination.** LLM runs vary between seeds, and pretraining contamination cannot be ruled out (§11). Agents see the upstream `sample_id` as `item_id`; opaque ids were not adopted (OPEN-19).
- **Compute accounting.** GPU-seconds depend on cache state and run order. `moved_toward_label` is descriptive.
- **Untested on real data.** The evaluator, verifier, scorer stubs, baselines and split code are tested on synthetic data only. They are merged into `dev` (PRs #5 to #10, with follow-ups #12, #13, #15, #16 and #19).

## 14. Gate 0 decisions

Based on the Gate 0 evidence (kiln-9 artifact, checked 2026-10-31 from public metadata only). License, access and version were rechecked live on 2026-10-31.

| Item | Status | Basis |
|---|---|---|
| License: Zenodo record and GitHub repo are both CC BY 4.0; Kiln may share and adapt the data | Settled by evidence | Zenodo API, DataCite, repo `LICENSE`, README, `metadata/datacite.json`. The GitHub detector's `NOASSERTION` is a format mismatch, not a different license |
| Obligations: credit the authors with title, DOI and license link, and indicate changes. Derived `Item`s, the precursor-level split and the §2.4 exclusion are changes | Settled by license | CC BY 4.0 |
| Cite the version DOI `10.5281/zenodo.21285546`, not the concept DOI in the README | Recommended; Hemanath to confirm | Only one version exists; a version DOI is reproducible |
| Use the README author list, not the Zenodo creator list (four names appear swapped) | Recommended; Hemanath to confirm | Gate 0 evidence §4.5 |
| Use only `ledger_precursor_genome.json`; do not use the Zenodo XRD, refinement or microscopy archives | Recommended; Hemanath to confirm | Those archives are label material |
| The README's "restricted access" note is out of date; Zenodo reports open access | Noted | Zenodo API, rechecked live |
| Exact stored category strings | Not inspected; mapped from the README's documented names, fail closed (**OPEN-11**, §3.1) | The schema allows any string |
| Handling of `unclassified` | Excluded from label-based metrics, counted after unblinding (**OPEN-12**, §3.1) | Taxonomy has five names; `Category` has four |
| Exact attribution text (title, authors, change notice) for the README and app | Added later as a dated amendment; it is not an analysis choice (**OPEN-22**) | Not drafted |

This is not legal advice.

## 15. OPEN register

Rows marked **decided 2026-10-31 by Hemanath, delegated** were filled in by an assistant under Hemanath's delegation of 2026-10-31, from the freeze decision sheet and his written instructions; each is subject to his veto before the Gate P commit. Rows marked **pending** name who must still act.

| ID | Decision needed | Owner | Blocks | Status and decision |
|---|---|---|---|---|
| OPEN-01 | Which of C2 and C4 is the need-board collective and which is isolated specialists; what "isolated" means | Adhi | §4, every contrast | **Decided 2026-10-31 by Hemanath, delegated.** As the runner codes it: C2 isolated (own boards, needs suppressed), C4 collective (one board, needs delivered) (§4.1) |
| OPEN-02 | Locked per-item budget: compute units, tool calls, tokens, coordination rounds, USD cap | Adhi (profiling) and team | §5, Gate P | **Decided 2026-10-31 by Hemanath, delegated.** 32.0 compute units, verbatim from `prices_proposal.json` at `1e8549b` (Adhi rounded 31 up to 32 so one full escalation path fits); 12 tool calls, 40,000 tokens and 3 rounds as labelled placeholders; no USD cap per item (§5). Any further change is **blocking** (§17, table 1) |
| OPEN-03 | Frozen price per compute tier | Adhi proposes from profiling; Hemanath freezes | §5, Gate P | **Decided 2026-10-31 by Hemanath, delegated.** Verbatim from `prices_proposal.json` at `1e8549b`: 0.1, 1.0, 30.0 and 0.2 units (§5). Any further change is **blocking** (§17, table 1) |
| OPEN-04 | Gemini model id and settings; number of seeds per condition and how they are combined | Adhi and team | §4, §8, §11 | **Decided 2026-10-31 by Hemanath, delegated.** `gemini-3.8-flash`, temperature 0, fallback for all conditions or none; 3 seeds, each reported plus the mean (§4.1, §5.1, §8). Training cutoff March 2026 (some areas January 2025), both before the 2026-07-09 publication; source `docs/compute-decisions.md` §2 (§11) |
| OPEN-05 | Scoring rules: `p_react`, category boundaries, cause and fix, evidence selection, in `score.score` and `score.provisional` | Hemanath and the scoring worker | §3.3, every metric | **Decided 2026-10-31.** `protocol/scoring_rules.json` at `61f812b` (merged as `88b52e3`), described in plain language and cited with its SHA-256 in §3.3; real runs score with `score.frozen_engine` (`852a811`). The §3.3 paragraph (`p_react` and `category` are separate outputs, so a high `p_react` can appear with a no-reaction category): **decided 2026-11-01 by Hemanath, intended as documented** (PC30). Any change to the rules is blocking (§17, table 1) |
| OPEN-06 | Review-flag thresholds (MLIP versus Materials Project disagreement, applicability limits) | Annamayya; values recorded here | §6, coverage | **Decided 2026-10-31: rule by Annamayya, thresholds by Hemanath (delegated).** `conflict` when \|ΔE_mlip − ΔE_mp\| > 0.05 eV/atom (the same T_disagree as OPEN-07); missing-evidence, failed or not-converged, unverified-decomposition and possible decomposition/dehydration melting-value flags kept; `outside_applicability` only on an explicit out-of-scope indication (§6). The decomposable-only unknown-decomposition flag is **adopted** (`1782ba6`, PC29; held-out pairs flagged 339 → 183 of 346) (§6). 0.05 is a proposal, not a validated accuracy guarantee |
| OPEN-07 | Specialist escalation rules and margins | Annamayya; recorded here | §6, §9 | **Decided 2026-10-31: rule by Annamayya (`a10c149`; fixes `0c5eeea`), thresholds by Hemanath (delegated).** A default, not a cage: borderline 0 < \|ΔE\| ≤ 0.05 eV/atom, \|ΔE\| ≤ 1e-6 counts as zero; near-hull 0 < `competitor_e_hull_ev_per_atom` ≤ 0.1 with status `ok`; T_disagree 0.05 eV/atom. A zero alone never recommends escalation, but the agent may still escalate with a logged, budgeted reason. Same rule in every condition. Known limits: 57% of development pairs escalate (counted before `0c5eeea`'s zero tolerance; recount pending Adhi, §6); 2 of 20 profiled pairs changed provisional category, one (PG_1048, −0.052) just outside the window. The 0.05 values are proposals, not validated accuracy guarantees (§6, `docs/escalation-rule.md`) |
| OPEN-08 | B0 threshold; mapping a B0 or B0-T decision to `p_react` and category; charging of B0's cached lookups | Hemanath | §4.2 | **Decided 2026-10-31 by Hemanath, delegated.** B0 at 0 eV/atom; no mapping, baselines reported by AUROC of their ranking score in their own table; lookups charged the frozen `cached_lookup` price (§4.2) |
| OPEN-09 | B1 feature set, model settings, fold aggregation (a pair appears in two folds), final fit | Hemanath | §4.2 | **Decided 2026-10-31 by Hemanath, delegated.** B1 is not reported, because there is no development-label path (OPEN-10) |
| OPEN-10 | Approved access path for development labels (B1 fitting, development AUROC, threshold setting), given hard rule 1 | Hemanath and team | §4.2, §12 | **Decided 2026-10-31 by Hemanath, delegated.** No development-label path: every threshold is label-free, no development metric, B1 not reported (§11, §12) |
| OPEN-11 | Mapping from stored category strings to `Category` | Hemanath | §3.1 | **Decided 2026-10-31 by Hemanath, delegated.** No stored value is printed; `evaluate.py` normalizes the README names and fails closed on anything else (§3.1) |
| OPEN-12 | Handling of `unclassified` and null category labels | Hemanath | §3, §7 denominator | **Decided 2026-10-31 by Hemanath, delegated.** Excluded from label-based metrics, kept in the hashed predictions and in coverage, counted after unblinding (§3.1) |
| OPEN-13 | Handling of the 54 records with no heating temperature | Hemanath (proposal 0001 §6 adds Adhi) | §2.4, §7 denominator | **Decided 2026-10-31 by Hemanath, delegated.** Proposal 0001 §6 Option 2: documented exclusion before the freeze (40 with no synthesis object, 14 with a null heating temperature), leaving 346 held-out items as PC15 states (§2.4) |
| OPEN-14 | Primary endpoint, decision rule, multiplicity, secondary metrics, subgroups, extra allocation tables | Hemanath and team | §7, §8, §9 | **Decided 2026-10-31 by Hemanath, delegated.** Primary: paired ΔAUROC, C4 minus C1, on all evaluated held-out items, mean over 3 seeds; a tie is reported as a tie; the 9 per-precursor differences are shown; everything else secondary (§8) |
| OPEN-15 | Bootstrap for overlapping precursor clusters: scheme, replicates, interval type and level, seed | Hemanath | §8 | **Decided 2026-10-31 by Hemanath, delegated.** No bootstrap: no interval, p-value or significance claim is reported (§8) |
| OPEN-16 | Posting channel and receipt proof for protocol and prediction hashes | Hemanath, CJ and Adhi | Gate P, Gate H | **Decided 2026-10-31 by Hemanath, delegated.** Post through `KILN_PREREG_WEBHOOK` to a dedicated channel, separate from #kiln-alerts; channel name **pending CJ** (non-blocking for the commit, needed before the P3 post, §17 table 3). Adhi checks receipts independently; Hemanath checks any post Adhi makes (§10) |
| OPEN-17 | Definition of `changed_prediction`, and who fills it | Hemanath and CJ | §9 | **Decided 2026-10-31 by Hemanath, delegated.** The provisional four-class category differs before and after the request; `replay_changes` fills it before unblinding (§9) |
| OPEN-18 | Held-out precursor list as recorded at freeze; whether first-element grouping is an acceptable spread | Hemanath | §2.3 | **Decided 2026-10-31 by Hemanath, delegated.** CaCO3, Fe2O3, HfO2, Li2CO3, Na2CO3, NiO, SiO2, TiO2, WO3, from the `split` field of the items file; grouping accepted with its caveat (§2.3) |
| OPEN-19 | Opaque item ids for agents; memorization probe | Hemanath | §11 | **Decided 2026-10-31 by Hemanath, delegated.** Probe is N2 per rule 11; opaque ids not adopted, listed as a limitation (§11) |
| OPEN-20 | Run order and cache sharing across conditions; whether unused budget carries over | Adhi and CJ | §5, §9 | **Decided 2026-10-31 by Hemanath, delegated.** Seed 0 of every condition first; one shared cache charged in full; no carry-over (§9) |
| OPEN-21 | Definition of conditions N1 and N2, or their removal from this experiment | Team | §1 | **Decided 2026-10-31 by Hemanath, delegated.** N1 tags profiling runs and is never scored; N2 is the OpenAI memorization probe, reported separately (§1) |
| OPEN-22 | Exact attribution text for the dataset | Hemanath | §14 | **Decided 2026-10-31 by Hemanath, delegated.** Added later as a dated amendment; not an analysis choice |
| OPEN-23 | Handling of an item with no prediction from a condition | Adhi and Hemanath | §6, §7 | **Decided 2026-10-31 by Hemanath, delegated; implemented in `231e432`.** `kiln.runners.finalize` scores every item with no prediction on empty evidence with a `missing_evidence` flag, cost = its logged requests, before the manifest is hashed; the item stays in the denominator; the count is reported per run (§6) |
| OPEN-24 | Verifier contract gaps: `verify` signature in interfaces, `item_cost` accessor, tool APIs for `tool_values` | Adhi, Annamayya and Hemanath | §6 | **Decided 2026-10-31 by Hemanath, delegated; closed on `dev` except one latent gap.** `Budget.item_cost` and the interfaces step 7 signature are on `dev` (`82eaefc`); the runner passes `item_cost` and the recomputed Tammann tool values, and the `388eb76` dry run had every artifact accepted. Still open: `decomposes_at_c` and `volatile_above_c` are not in the runner's `tool_values`, so a Precursor need answer carrying `decomposes_at_c` would be `inconclusive`; no agent on `dev` posts that need (Annamayya, CJ) (§6) |
| OPEN-25 | Mapping from the B60meV margin (or its `decisive` marker) to `p_react` or `Category`, if any; threshold values for B0-T (`ratio_threshold`) and B60meV (`margin_threshold_ev_per_atom`). From proposal 0001 | Hemanath | §4.2 | **Decided 2026-10-31 by Hemanath, delegated.** No B60meV mapping; B60meV at 0.060 eV/atom (literature value); B0-T ranking only, no threshold frozen (§4.2) |
| OPEN-26 | Label-free check of the ledger's formula notation. The carbonate, hydroxide and ammonium formula rules for the hard subset may miss pymatgen-style formulas such as `LiHO` or `H4NCl`. From proposal 0001 (§3, hard subset); the notation gap was raised in PR #19 | Hemanath | Hard subset (proposal 0001 §3) | **Decided 2026-10-31 by Hemanath, delegated.** 9 of 46 formulas are pymatgen-style, so hard-subset membership by formula is an explicit list of 11 precursors (§4.3) |

## 16. Amendments

Amendments live in `protocol/amendments.md`, not here, so this file's bytes match the Gate P commit (§10, P3 and P5). That file also holds the Gate P record. It is never part of the Gate P hash.

## 17. Still to do before the Gate P commit

The Gate P digest commits only to what is written in this file, or cited from it by commit SHA, at the Gate P commit. So anything that decides how predictions are made, scored or budgeted is **blocking**: it is closed and written here first, and it can never be settled later by an amendment. Only the non-blocking items in table 3 may follow as dated entries in `protocol/amendments.md`.

**1. Blocking: closed and written into this file (or cited by commit SHA) before the Gate P commit.** None of these may move to `protocol/amendments.md`.

| What | Who | Section |
|---|---|---|
| OPEN-02 and OPEN-03: the frozen prices and the 32-unit per-item cap match `protocol/prices_proposal.json` at `1e8549b`, as written in §5. Any further change by Adhi is written in §5 before the Gate P commit | Adhi | §5 |
| `protocol/frozen_settings.json`: done. Hemanath OK given 2026-11-01; pushed by Adhi in `4055d77` with exactly the §5 values; SHA-256 recorded in §5. Any further change to the file is written in §5 and its SHA-256 updated before the Gate P commit | Adhi | §5, §6 |

**Notes for Night 2 launch** (both must hold before either run starts):

- **Gemini key on the H100.** `docs/plan-changes.md` row 27 says the H100 uses the second account's key "as its `GEMINI_API_KEY`". That conflicts with the `night2-h100.toml` preflight, which requires `GEMINI_API_KEY` **unset** and `GEMINI_API_KEY_2` **set**. The preflight governs (§5.2).
- **Items file on the GB10.** The GB10's `~/kiln-items.jsonl` must be replaced with the required file and hash-checked against the SHA-256 in §5.2 before launch, as must the H100's copy.

**2. Code that implements text already fixed here.** These are not decisions, because this file already states what the code must do and the Gate P digest commits to that text. They are not amendments either: the code must match this text by the stated point, and any departure from the text is reported as a deviation.

| What | Who | Due | Section |
|---|---|---|---|
| OPEN-23: the runner scores crashed or unreached items on empty evidence before hashing. **Implemented** in `231e432` (`kiln.runners.finalize`); confirmed at the P2 commit | CJ | P2 commit | §6 |
| OPEN-24: `Budget.item_cost` and the interfaces step 7 text are done (`82eaefc`), and the runner passes the recomputed Tammann tool values. Remaining: supply `decomposes_at_c` (and `volatile_above_c`) in the runner's `tool_values`, or confirm at the P2 commit that no agent emits them as numbers. Until then a Precursor artifact carrying `decomposes_at_c` is `inconclusive`, as §6 states | Annamayya (tools), CJ (runner) | P2 commit | §6 |
| In `evaluate.py`: the explicit hard-subset formula list (OPEN-26), the category normalization (OPEN-11) and baseline AUROC from a ranking score (OPEN-08). The hard-subset definition hash is posted before labels load | Hemanath | Before Gate H | §3.1, §4.2, §4.3 |

**3. Non-blocking confirmations: may follow the Gate P commit as dated entries in `protocol/amendments.md`.** These are confirmations only. None of them changes how a prediction is made, scored or budgeted.

| What | Who | Section |
|---|---|---|
| P2: recorded in §10 as `d9a2993` (full SHA there). If a later commit changes code or run settings before Night 2, P2 is re-recorded: in §10 before the Gate P commit, otherwise in the Gate P record | Hemanath | §10 |
| OPEN-18: rerun `python -m kiln.data` and check that it prints the §2.3 list. A mismatch is recorded as a dated entry | Hemanath | §2.3 |
| OPEN-22: the dataset attribution text | Hemanath | §14 |
| OPEN-16: the name of the dedicated posting channel and who can read it (CJ), and Adhi's agreement to check receipts. Needed before the P3 post, not before the commit | CJ, Adhi | §10 |
| OPEN-19: opaque item ids, only if that code lands before the held-out runs | CJ | §11 |
| OPEN-07 known limits: recount (a), (b) and their union on the development MP cache with `ZERO_DE_EV_PER_ATOM` (1e-6 eV/atom), to confirm or replace the pre-`0c5eeea` 253 / 159 / 360 (57%) counts. Before the Gate P commit if possible; otherwise a dated entry. Descriptive only: it changes no rule or threshold | Adhi | §6 |
| Night 2 machines (§5.2): the H100 is set up (Hemanath), the items file on the GB10 is replaced and both copies are hash-checked against the required SHA-256, and the H100 has `GEMINI_API_KEY_2` set and `GEMINI_API_KEY` unset. Needed before Night 2; none of them changes how a prediction is made, scored or budgeted | Hemanath (H100), Adhi (GB10 operator) | §5.2 |
