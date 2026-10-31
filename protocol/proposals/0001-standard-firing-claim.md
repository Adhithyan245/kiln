# Proposal 0001 [proposal sequence]: Standard-Firing Claim, Baseline Revisions, and Evaluation Subsets

Status: PROPOSAL (for Hemnaath to accept or reject; protocol.md remains an unfrozen DRAFT)  
Author: Evaluation (Hemanath)  
Target: protocol/protocol.md

## 1. Claim Reframe: Standard One-Hour Firing
- **Reviewer assertion [UNVERIFIED]:** The Precursor Genome contains no temperature variation: each pair was fired 1 [UNVERIFIED] time, for 1 [UNVERIFIED] h dwell, at a temperature set by Tammann's rule (2/3 [UNVERIFIED] of lower precursor melting point in kelvin, rounded down to the nearest 100 [UNVERIFIED] °C).
- **Proposed reframe:** Reframe evaluation claim from predicting reaction across arbitrary conditions to: "will this pair react under a standard 1-hour [UNVERIFIED] firing".
- **Proposed label-free check:** T1 worker runs an aggregation script strictly over agent-visible `Item` fields (`temperature_c`, `dwell_h`, melting points) once the ledger is ingested, reporting: (a) number of distinct temperatures, (b) number of distinct dwell values, and (c) number of items matching the 2/3 [UNVERIFIED] melting-point rule.
- **Consequence if verified:** `temperature_c` is approximately a deterministic function of precursor melting points. Any baseline relying on Tammann fraction $T / T_{\text{melt}}$ becomes circular with the experimental setup.
- **Affected protocol.md sections:** §1 [protocol.md §1] (Question and scope), §2.2 [protocol.md §2.2] (Confirmed aggregate counts), §4.2 [protocol.md §4.2] (Baselines), §13 [protocol.md §13] (Limitations).

## 2. Baseline Revisions: B0-T Ratio and B0-C Thermodynamic Competition
- **B0-T replacement (spec only):** Replace the Tammann fraction with the ratio $T_{\text{dwell}} / T_{\text{melt}}(\text{higher})$, evaluated in kelvin from `Item.temperature_c` and the higher melting point of the 2 [protocol.md §2.2] precursors.
- **B0-C addition (spec only):** Add baseline B0-C using thermodynamic competition driving force.
  - *Citation correction:* The 60 [Szymanski et al., 2024] meV/atom threshold originates from Szymanski et al., Science Advances 10(27) [Szymanski et al., 2024], 2024 [Szymanski et al., 2024], DOI 10.1126/sciadv.adp3309 [Szymanski et al., 2024] (OSTI 2446600 [Szymanski et al., 2024]). It demonstrates that initial product formation can be predicted when its driving force exceeds all competing phases by $\ge 60$ [Szymanski et al., 2024] meV/atom (evaluated across 37 [Szymanski et al., 2024] reactant pairs in ternary metal oxides; 15% [Szymanski et al., 2024] of possible Materials Project reactions fall in this regime). Selectivity metrics derive from McDermott et al., ACS Central Science 9(10) [McDermott et al., 2023], 2023 [McDermott et al., 2023], DOI 10.1021/acscentsci.3c01051 [McDermott et al., 2023] (the reviewer note incorrectly attributed this to "McDermott/Persson/Ceder").
  - *Caveat:* The 60 [Szymanski et al., 2024] meV/atom margin governs *which* first product forms, not *whether* a pair reacts. Mapping this margin to $p_{\text{react}}$ or 4-class [protocol.md §3.1] `Category` is a protocol decision. Propose a new OPEN item (OPEN-25 [protocol.md §15], paralleling OPEN-08 [protocol.md §15] for B0 [protocol.md §4.2]). B0-C is best framed strictly as a thermodynamic regime marker.
- **Affected protocol.md sections:** §4.2 [protocol.md §4.2] (Baselines), §8 [protocol.md §8] (Statistical comparison), §15 [protocol.md §15] (OPEN register: OPEN-08, OPEN-25).

## 3. Pre-Unblinding Definition of the 'Hard' Subset
- **Definition:** Fixed strictly prior to seeing any labels. An item is designated 'hard' if its thermodynamic margin is $< 60$ [Szymanski et al., 2024] meV/atom (from accepted evidence) OR either precursor formula contains a carbonate, hydroxide, or ammonium group (decided from formula text only).
- **Formula rules & edge cases (evaluated on formula text only):**
  - *Exact rule:* String search on precursor formulas for carbonate (`CO3` [formula text]), hydroxide (`OH` [formula text]), and ammonium (`NH4` [formula text]).
  - *Edge cases:*
    1. Bicarbonates: Formulas containing bicarbonate (`HCO3` [formula text]) contain carbonate groups; classified as hard.
    2. Hydrates: Formulas with crystal water (e.g., `·H2O`, `*nH2O`, `5H2O` [UNVERIFIED]) require tokenization so water of hydration is distinguished from hydroxide groups.
    3. Mixed anions: Formulas with multiple anionic groups (e.g., hydroxycarbonates, oxychlorides) match if any target group is present; classified as hard.
    4. Formulas with brackets: Formulas formatted with brackets or parentheses (e.g., `(NH4)2SO4` [UNVERIFIED], `Ca(OH)2` [UNVERIFIED]) require group parsing rather than raw character matching.
- **Unknown bucket:** Items whose thermodynamic margin is unknown and which match no formula rule enter an 'unknown' bucket that is reported, never dropped.
- **Reporting:** Hard-subset metrics are reported separately and in addition to all-pairs metrics.
- **Affected protocol.md sections:** §7 [protocol.md §7] (Metrics), §11 [protocol.md §11] (Contamination control), §12 [protocol.md §12] (Label safety), §15 [protocol.md §15] (OPEN register: OPEN-14).

## 4. Headline Result: Accuracy vs. Compute Curve
- **Protocol conflict:** AGENTS.md rule 11 [AGENTS.md rule 11] explicitly forbids a second budget level without team agreement after profiling. A multi-point performance-vs-compute curve requires reconciling with this rule.
- **Evaluated options:**
  - *Option A (Multiple budget levels):* Re-run conditions C1–C4 [protocol.md §4.1] across 2 or more [UNVERIFIED] locked budget levels. Cost: Multiplies GPU hours and API tokens proportionally by the number of levels; tightens GB10 contention; requires explicit team agreement under rule 11 [AGENTS.md rule 11].
  - *Option B (Within-run cumulative curve):* Construct accuracy curves using cumulative compute spent from before/after provisional scores logged in `runs/<run_id>/compute_requests.jsonl` [protocol.md §5]. Cost: 0 [protocol.md §5] additional compute expenditure, but provisional scores reflect uncalibrated intermediate states along a single search trajectory rather than isolated lower-budget runs.
- **Recommendation:** Recommend neither option unilaterally; lay out both with costs and refer decision to team under OPEN-14 [protocol.md §15].
- **Affected protocol.md sections:** §1 [protocol.md §1] (Question and scope), §5 [protocol.md §5] (Locked budget), §9 [protocol.md §9] (Compute allocation), §15 [protocol.md §15] (OPEN register: OPEN-14).

## 5. Label-Free Split Verification
- **Precursor split rule:** 9 [protocol.md §2.2] precursors held out via deterministic pseudo-random draw (seed 42 [protocol.md §2.3]) grouped by first element symbol. A pair is held out iff it touches $\ge 1$ [protocol.md §2.3] held-out precursor.
- **Combinatorial check:** Evaluated using no label data: $C(46, 2) - C(37, 2) = 1035 - 666 = 369$ [protocol.md §2.2] (from 46 [protocol.md §2.2] total and 37 [protocol.md §2.2] development precursors, partitioning into 36 [protocol.md §2.2] two-held-out and 333 [protocol.md §2.2] one-held-out pairs).
- **Label safety:** No class counts or outcome distributions are quoted for the held-out set; doing so requires unblinded label fields and remains unverified.
- **Affected protocol.md sections:** §2.2 [protocol.md §2.2] (Confirmed aggregate counts), §2.3 [protocol.md §2.3] (Split), §12 [protocol.md §12] (Label safety).

## 6. Disposition of the 54 Missing Heating Temperature Records (OPEN-13)
- **Problem:** 54 [protocol.md §2.2] records lack heating temperatures, leaving 981 [protocol.md §2.2] items with complete synthesis conditions. Reviewer suggested dropping these 54 [protocol.md §2.2] records to lock 981 [protocol.md §2.2] items. Dropping them conflicts with AGENTS.md rule 9 [AGENTS.md rule 9] ("never silently drop").
- **Options for Hemanath and Adhi (do not decide):**
  - *Option 1 (Keep with explicit flag):* Retain all 1,035 [protocol.md §2.2] records; flag the 54 [protocol.md §2.2] items with `missing_evidence` (`needs_review = True` [protocol.md §7]). Pros: Fully respects rule 9 [AGENTS.md rule 9]; maintains the full 1,035 [protocol.md §2.2] benchmark denominator. Cons: Physical kinetics tools cannot evaluate items lacking firing temperatures.
  - *Option 2 (Documented pre-freeze exclusion rule):* Adopt a formal pre-freeze exclusion rule before Gate P [protocol.md §10], locking evaluation to the 981 [protocol.md §2.2] records with valid temperatures. Pros: Clean physical denominator where all items have thermal processing parameters. Cons: Excludes records and departs from the raw 1,035 [protocol.md §2.2] dataset boundary.
  - *Option 3 (Report both):* Report primary metrics on the 981 [protocol.md §2.2] complete items and sensitivity metrics across all 1,035 [protocol.md §2.2] items. Pros: Full auditability and transparency without discarding records or imputing temperatures. Cons: Adds reporting complexity across tables.
- **Affected protocol.md sections:** §2.2 [protocol.md §2.2] (Confirmed aggregate counts), §2.4 [protocol.md §2.4] (Missing heating temperatures), §7 [protocol.md §7] (Metrics), §15 [protocol.md §15] (OPEN register: OPEN-13).

## 7. Referral: Multi-Agent Probability Redesign
The reviewer's proposed architecture (each specialist agent posts a calibrated probability, escalating on disagreement) conflicts directly with AGENTS.md rule 7 [AGENTS.md rule 7] (LLMs never set numbers), rule 10 [AGENTS.md rule 10] (flags and scores are not calibrated probabilities), and rule 11 [AGENTS.md rule 11] (fixed architecture and scope). Multi-agent coordination belongs to CJ (need board/infrastructure) and Annamayya (chemistry specialist agents). This redesign proposal is referred to the team; Evaluation does not design or adopt it.
- **Affected protocol.md sections:** None in Evaluation scope (would affect §4.1 [protocol.md §4.1] and §6 [protocol.md §6] if adopted by team).
