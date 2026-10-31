# Proposal 0001: Standard-Firing Claim, Baseline Revisions, and Evaluation Subsets

Status: PROPOSAL (for Hemnaath to accept or reject; protocol.md remains an unfrozen DRAFT)  
Author: Evaluation (Hemanath)  
Target: protocol/protocol.md

## 1. Claim Reframe: Standard One-Hour Firing
- **Reviewer assertion [UNVERIFIED]:** The Precursor Genome contains no temperature variation: each pair was fired once for 1 h dwell at a temperature set by Tammann's rule (2/3 of the lower precursor melting point, rounded down to the nearest 100 °C). The temperature unit was unspecified by the reviewer.
- **Proposed reframe:** Reframe the evaluation claim from predicting reaction across arbitrary conditions to: "will this pair react under a standard one-hour firing".
- **Proposed label-free check:** T1 worker runs an aggregation script strictly over agent-visible `Item` fields (`temperature_c`, `dwell_h`, melting points) once the ledger is ingested, reporting: (a) number of distinct temperatures, (b) number of distinct dwell values, and (c) number of items matching the 2/3 rule testing both kelvin and degrees-C readings of precursor melting points.
- **Consequence if verified:** `temperature_c` is approximately a deterministic function of precursor melting points. Any baseline relying on the Tammann fraction $T / T_{\text{melt}}$ becomes circular with the experimental setup.
- **Affected protocol.md sections:** §1 (Question and scope), §2.2 (Confirmed aggregate counts), §4.2 (Baselines), §13 (Limitations).

## 2. Baseline Revisions: B0-T Ratio and B60meV Regime Marker
- **B0-T replacement (spec only):** Replace the Tammann fraction with the ratio $T_{\text{dwell}} / T_{\text{melt}}(\text{higher})$, evaluated in kelvin from `Item.temperature_c` and the higher melting point of the two precursors.
- **B60meV margin feature / regime marker (spec only):** Add baseline feature B60meV as a thermodynamic-competition margin feature and regime marker, rather than a predictor of reaction.
  - *Theoretical grounding:* Szymanski et al. (2024) observed in an in situ study of 37 reactant pairs (ternary metal oxides) that the first-forming product is predictable when its driving force exceeds all competing phases by $\ge 60$ meV/atom. They reported that 15% of possible Materials Project reactions fall in this regime (a Materials Project statistic, not a Precursor Genome rate). The paper does not claim whether a precursor pair reacts or does not react. Selectivity metrics derive from McDermott et al. (2023).
  - *Protocol policy caveat:* Because the 60 meV/atom margin governs which first phase forms rather than whether a reaction occurs, mapping this margin to $p_{\text{react}}$ or four-class `Category` is a protocol policy decision. Propose a new OPEN item (OPEN-25, alongside OPEN-08 for B0). Frame B60meV strictly as a regime marker.
- **Affected protocol.md sections:** §4.2 (Baselines), §8 (Statistical comparison), §15 (OPEN register: OPEN-08, OPEN-25).

## 3. Pre-Unblinding Definition of the 'Hard' Subset
- **Definition:** Fixed strictly prior to seeing any labels. An item is designated 'hard' if its thermodynamic competition margin is $< 60$ meV/atom (from accepted evidence) OR either precursor formula contains a carbonate, hydroxide, or ammonium group (decided from formula text only).
- **Formula rules & edge cases (evaluated on formula text only):**
  - *Exact rule:* String search on precursor formulas for carbonate (`CO3`), hydroxide (`OH`), and ammonium (`NH4`).
  - *Edge cases:*
    1. Bicarbonates: Formulas containing bicarbonate (`HCO3`) contain carbonate groups; classified as hard.
    2. Hydrates: Formulas with crystal water (e.g., `·H2O`, `*nH2O`, `5H2O`) require tokenization so water of hydration is distinguished from hydroxide groups.
    3. Mixed anions: Formulas with multiple anionic groups (e.g., basic carbonates like malachite, oxychlorides) match if any target group is present; classified as hard.
    4. Formulas with brackets: Formulas formatted with brackets or parentheses (e.g., `(NH4)2SO4`, `Ca(OH)2`) require group parsing rather than raw character matching.
- **Unknown bucket:** Items whose thermodynamic margin is unknown and which match no formula rule enter an 'unknown' bucket that is reported, never dropped.
- **Reporting:** Hard-subset metrics are reported separately and in addition to all-pairs metrics.
- **Affected protocol.md sections:** §7 (Metrics), §11 (Contamination control), §12 (Label safety), §15 (OPEN register: OPEN-14).

## 4. Headline Result: Accuracy vs. Compute Curve
- **Protocol conflict:** AGENTS.md rule 11 explicitly forbids a second budget level without team agreement after profiling. A multi-point performance-vs-compute curve requires reconciling with this rule.
- **Evaluated options:**
  - *Option A (Multiple budget levels):* Re-run conditions C1–C4 across two or more locked budget levels. Cost: Multiplies GPU hours and API tokens proportionally by the number of levels; tightens GB10 contention; requires explicit team agreement under rule 11.
  - *Option B (Within-run cumulative curve):* Construct accuracy curves using cumulative compute spent from before/after provisional scores logged in `runs/<run_id>/compute_requests.jsonl`. Cost: Zero additional compute expenditure, but provisional scores reflect uncalibrated intermediate states along a single search trajectory rather than isolated lower-budget runs.
- **Recommendation:** Recommend neither option unilaterally; lay out both with costs and refer decision to the team under OPEN-14.
- **Affected protocol.md sections:** §1 (Question and scope), §5 (Locked budget), §9 (Compute allocation), §15 (OPEN register: OPEN-14).

## 5. Label-Free Split Verification
- **Precursor split rule:** 9 precursors held out via deterministic pseudo-random draw (seed 42) grouped by first element symbol. A pair is held out iff it touches at least one held-out precursor.
- **Combinatorial check:** Evaluated using no label data: $C(46, 2) - C(37, 2) = 1035 - 666 = 369$ (from 46 total and 37 development precursors, partitioning into 36 two-held-out and 333 one-held-out pairs).
- **Label safety:** No class counts or outcome distributions are quoted for the held-out set; doing so requires unblinded label fields and remains unverified.
- **Affected protocol.md sections:** §2.2 (Confirmed aggregate counts), §2.3 (Split), §12 (Label safety).

## 6. Disposition of the 54 Missing Heating Temperature Records (OPEN-13)
- **Problem:** 54 records lack heating temperatures, leaving 981 items with complete synthesis conditions. A reviewer suggested dropping these 54 records to lock 981 items. Dropping them conflicts with AGENTS.md rule 9 ("never silently drop").
- **Options for Hemanath and Adhi (do not decide):**
  - *Option 1 (Keep with explicit flag):* Retain all 1,035 records; flag the 54 items with `missing_evidence` (`needs_review = True`). Pros: Fully respects rule 9; maintains the full 1,035 benchmark denominator. Cons: Physical kinetics tools cannot evaluate items lacking firing temperatures.
  - *Option 2 (Documented pre-freeze exclusion rule):* Adopt a formal pre-freeze exclusion rule before Gate P, locking evaluation to the 981 records with valid temperatures. Pros: Clean physical denominator where all items have thermal processing parameters. Cons: Excludes records and departs from the raw 1,035 dataset boundary.
  - *Option 3 (Report both):* Report primary metrics on the 981 complete items and sensitivity metrics across all 1,035 items. Pros: Full auditability and transparency without discarding records or imputing temperatures. Cons: Adds reporting complexity across tables.
- **Affected protocol.md sections:** §2.2 (Confirmed aggregate counts), §2.4 (Missing heating temperatures), §7 (Metrics), §15 (OPEN register: OPEN-13).

## 7. Referral: Multi-Agent Probability Redesign
The reviewer's proposed architecture (each specialist agent posts a calibrated probability, escalating on disagreement) conflicts directly with AGENTS.md rule 7 (LLMs never set numbers), rule 10 (flags and scores are not calibrated probabilities), and rule 11 (fixed architecture and scope). Multi-agent coordination belongs to CJ (need board/architecture) and Annamayya (chemistry specialist agents). This redesign proposal is referred to the team; Evaluation does not design or adopt it.
- **Affected protocol.md sections:** None in Evaluation scope (would affect §4.1 and §6 if adopted by team).

## References
- Szymanski, N. J., Byeon, Y.-W., Sun, Y., Zeng, Y., Bai, J., Kunz, M., Kim, D.-M., Helms, B. A., Bartel, C. J., Kim, H., Ceder, G. (2024). Quantifying the regime of thermodynamic control for solid-state reactions during ternary metal oxide synthesis. Science Advances 10(27), DOI 10.1126/sciadv.adp3309 (OSTI 2446600).
- McDermott, M. J., McBride, B. C., Regier, C. E., et al. (2023). Assessing Thermodynamic Selectivity of Solid-State Reactions for the Predictive Synthesis of Inorganic Materials. ACS Central Science 9(10), DOI 10.1021/acscentsci.3c01051.
- Kiln Evaluation Protocol (Draft), `protocol/protocol.md`.
- Kiln Project Rules, `AGENTS.md`.
