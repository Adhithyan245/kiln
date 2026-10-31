# Kiln evaluation protocol

> **Status: DRAFT. Not frozen, not hashed, not posted. Not ready for held-out runs.**
>
> - Owner: Hemanath (A, Evaluation). Drafted 2026-10-31; pre-freeze decisions written in on 2026-10-31.
> - Freeze time: `prompts/hemanath.md` plans the freeze and hash for 7 PM Saturday. `docs/plan-changes.md` row 14 lets the team move it to at most 8:30 PM, which is the team's limit tonight. This file stays a draft until Hemanath makes it the Gate P commit (§10).
> - **Delegated decisions.** On 2026-10-31 Hemanath delegated the pre-freeze decisions. A §15 row marked **decided 2026-10-31 by Hemanath, delegated** was written by an assistant under that delegation, from the freeze decision sheet (kiln-33 artifact `kiln-freeze-decision-sheet.md`) and Hemanath's written instructions. Hemanath may veto any of them before the Gate P commit. A row marked **pending** still needs the named person, and its text says what applies until then.
> - Every value comes with its source: a profiling file at a commit, a repo file, or a team decision.
> - "Settled" means the rule is already written in `AGENTS.md`, `docs/plan-changes.md` (cited as PC and its row number), `docs/interfaces.md`, `src/kiln/schemas.py`, the runner code or a team prompt. The source is cited each time.

Sources used for this draft: `AGENTS.md`; `docs/plan-changes.md`; `docs/interfaces.md`; `docs/compute-decisions.md`; `docs/escalation-rule.md`; `docs/credits.md`; `src/kiln/schemas.py`; `src/kiln/runners/conditions.py`; `src/kiln/night/plans/night2.toml`; `prompts/*.md`; the descriptions and code of PRs #5 (verifier), #6 (data and split), #7 (scoring stubs), #8 (evaluator), #9 (B1 folds), #10 (B0, B0-T) and #19 (B0-T ratio, B60meV, hard subset); `protocol/prices_proposal.json`; and the Gate 0 license and category evidence (kiln-9 artifact `gate0-license-evidence.md`). PRs #5 to #10 were merged into `dev` on 2026-10-31, and PR #19 was merged at 2026-10-31T19:20:57Z (checked with `gh pr view 19`). Proposal 0001 (`protocol/proposals/0001-standard-firing-claim.md`) is **accepted by Hemanath**, matching PC10. The proposal's own header line still reads "for Hemnaath to accept or reject"; that line is out of date and PC10 plus this paragraph are the record.

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
- **Held-out precursors at freeze** (**OPEN-18**): `CaCO3`, `Fe2O3`, `HfO2`, `Li2CO3`, `Na2CO3`, `NiO`, `SiO2`, `TiO2`, `WO3`. Derived from the `split` field of `~/kiln-items.jsonl`: these are the 9 formulas that appear in no development item, every one of the 346 held-out items contains at least one of them, and the other 37 formulas are the development precursors. Their first elements (Ca, Fe, Hf, Li, Na, Ni, Si, Ti, W) are 9 different groups, as the method requires. Hemanath should rerun `python -m kiln.data` on his machine, which holds the ledger, and check that it prints the same 9 before the Gate P commit.
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

**Scoring rules (OPEN-05): see `protocol/scoring_rules.json`.**

> **TODO (OPEN-05):** `protocol/scoring_rules.json` is being written by another worker and is not on `dev` at this draft's base commit. Before the Gate P commit, the file must be on `dev`, cited here by its commit SHA, and match `kiln.scoring.score.score` and `score.provisional` at the P2 code-freeze commit. PR #7 makes `score` raise an error until those rules are frozen. This is **blocking** (§17, table 1): the rules decide `p_react` and `category`, which every metric depends on, so they are never settled by an amendment after the hash.

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

**Frozen tier prices and per-item compute budget (OPEN-03, OPEN-02).** Copied verbatim from `protocol/prices_proposal.json` at commit `e5d81a233c26fb7f80c53045cfca4cb6b87b982c` (Adhi, 2026-10-31 17:26 EDT, "price proposal from the GB10 rerun"). Measured on the GB10 (`results/gb10/profile_s0_fix.json`, 20 development pairs, seed 0, float32). **Adhi's review of these frozen values is pending and blocking: it is completed, and any change written here, before the Gate P commit (§17, table 1).**

| Item | Frozen value | Source |
|---|---|---|
| Compute unit | 1 unit = median `single_point` GPU-seconds = 0.49578814350024913 s | `prices_proposal.json`, `compute_unit` |
| `cached_lookup` price | 0.1 units | `tier_prices` |
| `single_point` price | 1.0 units | `tier_prices` |
| `bounded_relaxation` price | 30.0 units | `tier_prices` |
| `decomposition_reeval` price | 0.2 units | `tier_prices` |
| `max_compute_units_per_item` | 31.0 units | `max_compute_units_per_item` |
| `max_tool_calls_per_item` | 12 | `RunConfig` default in `schemas.py`; **placeholder, not profiled** |
| `max_tokens_per_item` | 40,000 (Gemini thinking tokens count as output tokens against this cap, PC13) | `RunConfig` default; **placeholder, not profiled** |
| `coordination_rounds` | 3 | `RunConfig` default; **placeholder, not profiled** |
| USD cap per item | None. `Budget.record_usd` records spend and does not cap it (interfaces additions) | — |
| Unused budget carry-over between items | None; the budget is per item (**OPEN-20**) | `RunConfig` |

- **Note for Adhi's review.** The proposal's rule is "budget per pair: one escalation path (cached_lookup + single_point + bounded_relaxation + decomposition_reeval)". At the frozen prices that path costs 0.1 + 1.0 + 30.0 + 0.2 = 31.3 units, while `max_compute_units_per_item` is 31.0. The value is copied as written. The cap is **blocking**: Adhi settles 31.0 or 31.3 and it is written here before the Gate P commit. It is never settled by an amendment (§17, table 1).
- `prices_proposal.json` sets no tool-call, token or round cap, so the `RunConfig` defaults are frozen and labelled as placeholders rather than new numbers being guessed.
- **Night-wide stops** (`night2.toml` `[caps]`: 5,000,000 tokens, USD 20.0, 8.0 GPU-hours) are CJ's run-safety limits, marked provisional there, and are not part of the per-item budget. If one is breached and an item gets no prediction, OPEN-23 applies.
- `protocol/frozen_settings.json`, which the Night 2 runner reads (`night2.toml`), must carry exactly these values. The runner reads `tier_prices` and the three `max_*` caps from it; it does not read `coordination_rounds`, so the `RunConfig` default of 3 applies (`runners/conditions.py`, `CAP_KEYS`).

### 5.1 Approved compute and LLM settings recorded at freeze

`docs/compute-decisions.md` says Hemanath freezes the final values here. These settings are approved in `docs/plan-changes.md` and are part of the frozen protocol; they are not OPEN items.

| Setting | Frozen value | Source |
|---|---|---|
| MACE precision | float32 | PC5; `env/gb10/tier_settings.json`; `compute-decisions.md`, "MACE precision" |
| Compute backend | ASE (`FrechetCellFilter` + FIRE2) is the default; the ALCHEMI Toolkit backend (`nvalchemi`) is not the default | PC7; `compute-decisions.md`, "Backend" |
| Phase set for the MLIP tiers | The phases the a-b reaction energy depends on (decomposition along the a-b line, reactants, elemental references), plus near-hull competitors on that line up to `max_structures` | PC8; `tiers.py` `_phase_set` |
| Hull window | 0.1 eV/atom, one value, for near-hull competitors and for Thermo's "product near the hull" trigger. B60meV's 0.060 eV/atom is a different quantity | PC9 |
| Relaxation tier | Element references get a single point; a near-hull competitor that does not converge is dropped and listed; a request is `not_converged` only if a reactant or a product along the a-b line fails | PC16 |
| Experiment LLM | `gemini-3.8-flash` for every condition and seed; temperature 0; the run's seed passed to the call (interfaces additions) | PC6; `night2.toml` |
| LLM token accounting | Gemini thinking tokens count as output tokens, billed and charged against the per-item token cap | PC13; `agents/base.py` |

## 6. How one item is processed

The flow, settled in `docs/interfaces.md`:

1. `load_items(split)` gives `Item`s.
2. Agents post needs and artifacts on the board and buy compute.
3. `kiln.verifier.verify` checks every artifact. Only `accepted` artifacts feed review flags and scoring.
4. `kiln.review.flags` adds missing-evidence, failed-computation, conflict and outside-applicability flags.
5. `score.score` produces the `Prediction`.
6. The runner writes `runs/<run_id>/predictions.jsonl`.

- The verifier (PR #5) checks: `falsified_if`, citations, documented value keys and units, forbidden label keys, cited compute request ids, numbers matching cited compute results or recomputed tool values, compute charges and item budgets.
- **Verifier contract gaps (OPEN-24).** These are code facts, not analysis choices, and they close in code at the P2 commit. Interfaces step 7 shows `verify(artifact, board)`, but the code takes four more keyword arguments, `requests`, `config`, `item_cost` and `tool_values` (`src/kiln/verifier/__init__.py`); `docs/interfaces.md` is a shared file and needs that update. `Budget` on `dev` has `spent` but no `item_cost` accessor (Adhi). The tool APIs that produce `tool_values` belong to Annamayya. Until these close, Kinetics and Precursor artifacts stay `inconclusive`.
- **Review-flag thresholds (OPEN-06) and specialist escalation rules (OPEN-07): no shared rule, pending Annamayya.** `docs/escalation-rule.md` is listed as "Proposed, not approved" in `docs/plan-changes.md`, and Annamayya has not confirmed it. Until she does, this protocol sets **no shared escalation rule and no review-flag thresholds**: `protocol/frozen_settings.json` carries `energy_margin_ev_per_atom: null` and `disagreement_threshold_ev_per_atom: null` (the runner allows null for "a threshold the protocol leaves unset", `runners/conditions.py`), `kiln.review.flags` is called with `disagreement_threshold=None`, and so no MLIP-versus-Materials-Project `conflict` flag is raised (`src/kiln/review/__init__.py`). **Consequences, stated plainly: under this no-shared-rule state the main comparison does not test the need board.**
  - **No need is posted in any condition.** Kinetics is the only agent in `src/kiln/agents/` that calls `board.post_need`, and with a null margin `Kinetics.step` returns before it can post one (`agents/kinetics.py`, the `energy_margin is None` return). Thermo and Precursor only answer needs; they never post them.
  - **C2 and C4 are identical, and the need board is never used.** With no needs, C2 (own boards, needs suppressed) and C4 (one board, needs delivered) run the same rule-based specialists in the same order. Thermo reads only its own artifacts. Kinetics stops before it reads Thermo's. Precursor reads only its own. The runner pools the accepted artifacts from every board before scoring (`runners/conditions.py`, `run_item`). Nothing else differs, so C2 and C4 produce identical predictions.
  - **The primary endpoint stops testing the collective.** C4 − C1 (§8) then measures only whether an LLM controller choosing a subset of the same skills does worse than running all of them. It says nothing about need-board coordination.
  - **No condition buys a GPU tier.** Thermo never escalates past `cached_lookup` (`agents/thermo.py`). C1 and C3 call the same specialist code, so the compute-allocation question in §9 has no variation to report.
  - **Hard prerequisite.** For these reasons OPEN-06 and OPEN-07 are a **hard prerequisite for the Gate P commit** (§10, P1; §17). The Gate P commit is not made until one of two things happens: Annamayya decides OPEN-06 and OPEN-07 and the values are written here, or the team records an explicit decision in `docs/plan-changes.md`, with who approved it, to freeze this degenerate design knowingly. In the second case the main result is reported as a test of the LLM controller, not of the collective. This item may not be deferred to `protocol/amendments.md`.

  If she confirms before the Gate P commit, the rule is recorded here as written in `docs/escalation-rule.md`: the same rule in every arm (its Fairness paragraph), the 0.1 eV/atom hull window (PC9), T_rxn from Adhi's profiling, and one T_disagree used for both the escalation trigger and the conflict flag, so the two cannot disagree.
- **An item with no prediction (OPEN-23), decided.** The runner calls `score` on whatever accepted evidence exists, which may be none. Empty evidence gives a `missing_evidence` flag, and the item stays in the denominator. `runners/conditions.py` already does this when the budget runs out ("No item is skipped"). An item that crashes, times out or is never reached (for example after a night-wide stop) is resumed; if it still has no prediction, the runner scores it on empty evidence before the prediction file is hashed (CJ, runner). The count of such items is reported per condition and seed.

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
- **Primary endpoint (OPEN-14):** the paired difference in AUROC, C4 minus C1 (§8). Every other metric is secondary and descriptive.
- `p_react` is a fixed-rule score. Brier measures how far it sits from the outcomes; it does not make `p_react`, a review flag or a stated cause a calibrated probability or a validated failure cause (`AGENTS.md` rule 10).

## 8. Statistical comparison

- **Pairing.** Every condition predicts the same held-out items, so each comparison between conditions is paired item by item.
- **Seeds (OPEN-04), decided.** 3 seeds per condition (seeds 0, 1 and 2; `docs/credits.md`: "all 3 seeds (don't cut to 2)"; `night2.toml`). Every metric is reported for each seed and as the mean of the 3 seeds.
- **Primary endpoint (OPEN-14), decided.** ΔAUROC = AUROC(C4) − AUROC(C1), computed for each seed on the same 346 evaluated held-out items (minus OPEN-12 exclusions), then averaged over the 3 seeds. The report gives the mean, the three per-seed values, and the **9 per-precursor differences**: for each held-out precursor, ΔAUROC on the held-out items that contain it (a pair with two held-out precursors counts in both of their slices), as a mean over the 3 seeds, with a sign count (how many of the 9 are positive, negative or zero). A slice where AUROC is undefined is reported as undefined, not dropped. **Caveat:** this endpoint tests the collective only if OPEN-06 and OPEN-07 set non-null margins. Under the no-shared-rule state, C4 is identical to C2 and C4 − C1 compares an LLM controller with running every skill (§6). That is why OPEN-06 and OPEN-07 are a hard prerequisite for the Gate P commit.
- **Decision rule.** A positive mean ΔAUROC is reported as "C4 ranked better than C1 on this held-out set", a negative one as "C1 ranked better". ΔAUROC is reported to three decimal places, and a mean of 0.000 is **reported as a tie**. Seeds that disagree in sign, or per-precursor differences that disagree with the mean, are stated next to the result. Because no interval or test is reported (below), no difference is called significant or general.
- **Multiplicity.** There is one primary contrast, so no adjustment is needed. Everything else is secondary and descriptive, with no adjustment and no significance claim: C4 against C2 and against C3, every other pairwise contrast, Brier, four-class accuracy, coverage, flagged and unflagged accuracy, the hard subset (§4.3), items with two held-out precursors (31) against items with one (315), the baseline table (§4.2), and the compute-allocation tables (§9). Proposal 0001 §4 Option B (a within-run accuracy-versus-cumulative-compute curve from the provisional scores) is descriptive only; Option A (a second budget level) is out of scope under rule 11.
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

## 10. Two-step protocol and hash gates

Labels are never loaded before an **independently verified post** of the commitment that protects them.

### Step 1: protocol commitment (Gate P)

- **P1.** Owners close every `OPEN-nn` item and write the values here with their sources (§15). OPEN-06 and OPEN-07 are a hard prerequisite: the Gate P commit is not made while they are pending, unless the team has recorded the explicit decision described in §6. Every blocking item in §17 (table 1) is closed and written here before the Gate P commit. Only §17's non-blocking items (table 3) may follow as dated amendments.
- **P2.** Record the code-freeze commit SHA for scoring, verifier, review flags, compute tiers, agents and runner.
- **P3.** Commit the closed protocol and push the commit to `dev`, which blocks force-pushes and deletion (`docs/github-setup.md`), so the commit stays reachable. That commit is the **Gate P commit**. The digest is the SHA-256 of `protocol/protocol.md` as stored in that commit, `git cat-file blob <gate-p-commit>:protocol/protocol.md | shasum -a 256`. It is never taken from a checked-out copy, so line endings and checkout settings cannot change it. Post the full Gate P commit SHA **together with** the digest through the channel in **OPEN-16** (below), and verify the receipt independently. Anyone can check the commitment by rerunning that command against the posted commit.
- **P4.** Only after P3 may held-out runs start. Development runs may happen earlier.
- **P5.** After the Gate P commit, `protocol/protocol.md` is never edited. The Gate P record (commit SHA, digest, posting receipt) and every later change go in `protocol/amendments.md`, which is never part of the Gate P hash. Writing the record into this file would change the bytes being committed to.

**Posting channel and receipt proof (OPEN-16), draft, pending CJ and Adhi confirmation.** Both kinds of post (the Gate P commit SHA with its digest, and each prediction manifest digest) go through `KILN_PREREG_WEBHOOK`, which `python -m kiln.night.prereg post` already uses. The webhook URL is a secret and stays in the environment, never in the repo (rule 4). The local receipt line in `protocol/posts.jsonl` is a record, not proof (`night/prereg.py`). **Adhi is the independent receipt checker:** he reads the post at the webhook's destination, reruns the P3 `git cat-file` command against the posted commit (or `shasum -a 256` on the posted manifest for Gate H), confirms the digests match and that the post time is before any label load, and his check is written into the Gate P record in `amendments.md`. CJ confirms where the webhook posts and who can read it; Adhi confirms he will check. Adhi is also the Night 2 operator (PC15), so for any post he makes himself, Hemanath checks it instead, so that the checker is never the poster.

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

**Residual risk.** A-Lab outcomes and the Precursor Genome (published 2026-07-09) are public, so LLM pretraining may include them. Because LLMs cannot set numbers, recall could act only through which evidence an agent buys and through text fields (rationale, claims, cause and fix). Whether such text can influence `category` depends on the scoring rules (OPEN-05, `protocol/scoring_rules.json`).

**Decided (OPEN-19):**

- **Memorization probe:** decided by rule 11. N2 runs on an OpenAI model as a secondary result, reported separately (§1).
- **Opaque item ids: not adopted.** PR #6 uses the upstream `sample_id` as `item_id`, agents see it, and no opaque-id code is on `dev`. This is listed as a limitation (§13). If opaque ids land before the held-out runs, the change is recorded as a dated amendment.
- **Model:** `gemini-3.8-flash` for every condition and seed (PC6; OPEN-04). Its documented training cutoff relative to the dataset's 2026-07-09 publication is not recorded in the repo; Adhi adds it with its source, as a dated amendment if it arrives after the Gate P commit.

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
- **Fixed-rule scores and flags.** `p_react` is not a calibrated probability. Review flags are not validated failure causes.
- **If OPEN-06 and OPEN-07 stay unset, the design is degenerate** (§6). This applies only if the team knowingly freezes without Annamayya's decision. No agent posts a need, so **C2 and C4 are identical and the need board is never used**. The primary endpoint C4 − C1 then measures an LLM controller choosing a subset of the same skills, not the collective. No condition buys a GPU tier. No MLIP-versus-Materials-Project conflict flag is raised, so coverage reflects only the other flags.
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
| OPEN-02 | Locked per-item budget: compute units, tool calls, tokens, coordination rounds, USD cap | Adhi (profiling) and team | §5, Gate P | **Decided 2026-10-31 by Hemanath, delegated.** 31.0 compute units, verbatim from `prices_proposal.json` at `e5d81a2`; 12 tool calls, 40,000 tokens and 3 rounds as labelled placeholders; no USD cap per item (§5). Adhi's review pending and **blocking**, including the 31.0 versus 31.3 cap (§17, table 1) |
| OPEN-03 | Frozen price per compute tier | Adhi proposes from profiling; Hemanath freezes | §5, Gate P | **Decided 2026-10-31 by Hemanath, delegated.** Verbatim from `prices_proposal.json` at `e5d81a2`: 0.1, 1.0, 30.0 and 0.2 units (§5). Adhi's review pending and **blocking** (§17, table 1) |
| OPEN-04 | Gemini model id and settings; number of seeds per condition and how they are combined | Adhi and team | §4, §8, §11 | **Decided 2026-10-31 by Hemanath, delegated.** `gemini-3.8-flash`, temperature 0, fallback for all conditions or none; 3 seeds, each reported plus the mean (§4.1, §5.1, §8). Training cutoff: Adhi adds |
| OPEN-05 | Scoring rules: `p_react`, category boundaries, cause and fix, evidence selection, in `score.score` and `score.provisional` | Hemanath | §3.3, every metric | **Pending; blocking for the Gate P commit.** The rules are to be `protocol/scoring_rules.json`, which is not on `dev` yet, so nothing about their content has been decided. The file must be on `dev` and cited in §3.3 by commit SHA before the Gate P commit; it can never be settled by an amendment (§17, table 1) |
| OPEN-06 | Review-flag thresholds (MLIP versus Materials Project disagreement, applicability limits) | Annamayya; values recorded here | §6, coverage | **Pending Annamayya; hard prerequisite for the Gate P commit.** No shared rule until she confirms: no thresholds, so no conflict flag. Under that state C2 and C4 are identical (§6) |
| OPEN-07 | Specialist escalation rules and margins | Annamayya; recorded here | §6, §9 | **Pending Annamayya; hard prerequisite for the Gate P commit.** No shared rule until she confirms `docs/escalation-rule.md`. With both margins null, no agent posts a need, C2 and C4 are identical, and no condition buys a GPU tier. The only alternative is an explicit team decision, recorded in `docs/plan-changes.md`, to freeze that design knowingly (§6) |
| OPEN-08 | B0 threshold; mapping a B0 or B0-T decision to `p_react` and category; charging of B0's cached lookups | Hemanath | §4.2 | **Decided 2026-10-31 by Hemanath, delegated.** B0 at 0 eV/atom; no mapping, baselines reported by AUROC of their ranking score in their own table; lookups charged the frozen `cached_lookup` price (§4.2) |
| OPEN-09 | B1 feature set, model settings, fold aggregation (a pair appears in two folds), final fit | Hemanath | §4.2 | **Decided 2026-10-31 by Hemanath, delegated.** B1 is not reported, because there is no development-label path (OPEN-10) |
| OPEN-10 | Approved access path for development labels (B1 fitting, development AUROC, threshold setting), given hard rule 1 | Hemanath and team | §4.2, §12 | **Decided 2026-10-31 by Hemanath, delegated.** No development-label path: every threshold is label-free, no development metric, B1 not reported (§11, §12) |
| OPEN-11 | Mapping from stored category strings to `Category` | Hemanath | §3.1 | **Decided 2026-10-31 by Hemanath, delegated.** No stored value is printed; `evaluate.py` normalizes the README names and fails closed on anything else (§3.1) |
| OPEN-12 | Handling of `unclassified` and null category labels | Hemanath | §3, §7 denominator | **Decided 2026-10-31 by Hemanath, delegated.** Excluded from label-based metrics, kept in the hashed predictions and in coverage, counted after unblinding (§3.1) |
| OPEN-13 | Handling of the 54 records with no heating temperature | Hemanath (proposal 0001 §6 adds Adhi) | §2.4, §7 denominator | **Decided 2026-10-31 by Hemanath, delegated.** Proposal 0001 §6 Option 2: documented exclusion before the freeze (40 with no synthesis object, 14 with a null heating temperature), leaving 346 held-out items as PC15 states (§2.4) |
| OPEN-14 | Primary endpoint, decision rule, multiplicity, secondary metrics, subgroups, extra allocation tables | Hemanath and team | §7, §8, §9 | **Decided 2026-10-31 by Hemanath, delegated.** Primary: paired ΔAUROC, C4 minus C1, on all evaluated held-out items, mean over 3 seeds; a tie is reported as a tie; the 9 per-precursor differences are shown; everything else secondary (§8) |
| OPEN-15 | Bootstrap for overlapping precursor clusters: scheme, replicates, interval type and level, seed | Hemanath | §8 | **Decided 2026-10-31 by Hemanath, delegated.** No bootstrap: no interval, p-value or significance claim is reported (§8) |
| OPEN-16 | Posting channel and receipt proof for protocol and prediction hashes | Hemanath, CJ and Adhi | Gate P, Gate H | **Decided 2026-10-31 by Hemanath, delegated (draft); pending CJ and Adhi confirmation, which is non-blocking for the commit but needed before the P3 post (§17, table 3).** Post through `KILN_PREREG_WEBHOOK`; Adhi checks receipts independently, Hemanath checks any post Adhi makes (§10) |
| OPEN-17 | Definition of `changed_prediction`, and who fills it | Hemanath and CJ | §9 | **Decided 2026-10-31 by Hemanath, delegated.** The provisional four-class category differs before and after the request; `replay_changes` fills it before unblinding (§9) |
| OPEN-18 | Held-out precursor list as recorded at freeze; whether first-element grouping is an acceptable spread | Hemanath | §2.3 | **Decided 2026-10-31 by Hemanath, delegated.** CaCO3, Fe2O3, HfO2, Li2CO3, Na2CO3, NiO, SiO2, TiO2, WO3, from the `split` field of the items file; grouping accepted with its caveat (§2.3) |
| OPEN-19 | Opaque item ids for agents; memorization probe | Hemanath | §11 | **Decided 2026-10-31 by Hemanath, delegated.** Probe is N2 per rule 11; opaque ids not adopted, listed as a limitation (§11) |
| OPEN-20 | Run order and cache sharing across conditions; whether unused budget carries over | Adhi and CJ | §5, §9 | **Decided 2026-10-31 by Hemanath, delegated.** Seed 0 of every condition first; one shared cache charged in full; no carry-over (§9) |
| OPEN-21 | Definition of conditions N1 and N2, or their removal from this experiment | Team | §1 | **Decided 2026-10-31 by Hemanath, delegated.** N1 tags profiling runs and is never scored; N2 is the OpenAI memorization probe, reported separately (§1) |
| OPEN-22 | Exact attribution text for the dataset | Hemanath | §14 | **Decided 2026-10-31 by Hemanath, delegated.** Added later as a dated amendment; not an analysis choice |
| OPEN-23 | Handling of an item with no prediction from a condition | Adhi and Hemanath | §6, §7 | **Decided 2026-10-31 by Hemanath, delegated.** The runner scores empty accepted evidence, giving a `missing_evidence` flag; the item stays in the denominator; the count is reported per condition (§6) |
| OPEN-24 | Verifier contract gaps: `verify` signature in interfaces, `item_cost` accessor, tool APIs for `tool_values` | Adhi, Annamayya and Hemanath | §6 | **Decided 2026-10-31 by Hemanath, delegated.** Code facts that close at the P2 commit. Still open on `dev`: `item_cost` (Adhi), tool APIs (Annamayya), the interfaces step 7 text (§6) |
| OPEN-25 | Mapping from the B60meV margin (or its `decisive` marker) to `p_react` or `Category`, if any; threshold values for B0-T (`ratio_threshold`) and B60meV (`margin_threshold_ev_per_atom`). From proposal 0001 | Hemanath | §4.2 | **Decided 2026-10-31 by Hemanath, delegated.** No B60meV mapping; B60meV at 0.060 eV/atom (literature value); B0-T ranking only, no threshold frozen (§4.2) |
| OPEN-26 | Label-free check of the ledger's formula notation. The carbonate, hydroxide and ammonium formula rules for the hard subset may miss pymatgen-style formulas such as `LiHO` or `H4NCl`. From proposal 0001 (§3, hard subset); the notation gap was raised in PR #19 | Hemanath | Hard subset (proposal 0001 §3) | **Decided 2026-10-31 by Hemanath, delegated.** 9 of 46 formulas are pymatgen-style, so hard-subset membership by formula is an explicit list of 11 precursors (§4.3) |

## 16. Amendments

Amendments live in `protocol/amendments.md`, not here, so this file's bytes match the Gate P commit (§10, P3 and P5). That file also holds the Gate P record. It is never part of the Gate P hash.

## 17. Still to do before the Gate P commit

The Gate P digest commits only to what is written in this file, or cited from it by commit SHA, at the Gate P commit. So anything that decides how predictions are made, scored or budgeted is **blocking**: it is closed and written here first, and it can never be settled later by an amendment. Only the non-blocking items in table 3 may follow as dated entries in `protocol/amendments.md`.

**1. Blocking: closed and written into this file (or cited by commit SHA) before the Gate P commit.** None of these may move to `protocol/amendments.md`.

| What | Who | Section |
|---|---|---|
| OPEN-06 and OPEN-07: Annamayya decides the escalation rule and flag thresholds (confirming or rejecting `docs/escalation-rule.md`, with T_rxn and T_disagree from Adhi's profiling) and the values are written in §6. The only alternative is an explicit team decision, recorded in `docs/plan-changes.md` with who approved it, to freeze knowingly the null-margin design in which C2 and C4 are identical and the need board is never used | Annamayya; Adhi for the values; or the team | §6 |
| OPEN-05: the scoring rules. `protocol/scoring_rules.json` is on `dev`, cited in §3.3 by its commit SHA, and matches `score.score` and `score.provisional` at the P2 commit | Hemanath and the scoring worker | §3.3 |
| OPEN-02 and OPEN-03: Adhi reviews the frozen prices and budget, and the per-item cap (31.0 or 31.3 units) is settled and written in §5 | Adhi | §5 |
| `protocol/frozen_settings.json` is written with exactly the §5 values and the OPEN-06/07 thresholds (or their nulls), and is cited by commit SHA | CJ (runner), checked by Adhi | §5, §6 |
| OPEN-18: rerun `python -m kiln.data` and check it prints the §2.3 list | Hemanath | §2.3 |
| P2: record the code-freeze commit SHA for scoring, verifier, review flags, compute tiers, agents and runner | Hemanath | §10 |

**2. Code that implements text already fixed here.** These are not decisions, because this file already states what the code must do and the Gate P digest commits to that text. They are not amendments either: the code must match this text by the stated point, and any departure from the text is reported as a deviation.

| What | Who | Due | Section |
|---|---|---|---|
| OPEN-23: the runner scores crashed or unreached items on empty evidence before hashing | CJ | P2 commit | §6 |
| OPEN-24: `Budget.item_cost`, the tool APIs, and the interfaces step 7 text. While they are missing, Kinetics and Precursor artifacts stay `inconclusive`, as §6 states | Adhi, Annamayya, team | P2 commit | §6 |
| In `evaluate.py`: the explicit hard-subset formula list (OPEN-26), the category normalization (OPEN-11) and baseline AUROC from a ranking score (OPEN-08). The hard-subset definition hash is posted before labels load | Hemanath | Before Gate H | §3.1, §4.2, §4.3 |

**3. Non-blocking: may follow the Gate P commit as dated entries in `protocol/amendments.md`.** None of these changes how a prediction is made, scored or budgeted.

| What | Who | Section |
|---|---|---|
| OPEN-22: the dataset attribution text | Hemanath | §14 |
| The documented training cutoff of `gemini-3.8-flash`, with its source | Adhi | §11 |
| OPEN-16: confirmation of the webhook destination and readers, and of Adhi as receipt checker. Needed before the P3 post, not before the commit | CJ, Adhi | §10 |
| OPEN-19: opaque item ids, only if that code lands before the held-out runs | CJ | §11 |
