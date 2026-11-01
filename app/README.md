# Kiln Triage UI

## New lab preview

The default `/` now serves `lab.html` and `assets/lab.{css,js}`: a character-free
navy laboratory, precursor selection, manually stepped replay, result/details
dialog, and a Compute page. The previous evidence workspace remains at `/evidence`.
The **Preview the lab** action is explicitly a layout demonstration; it never
creates scientific results. Real replay needs the run exports described below.

New read-only endpoints are `/api/status`, `/api/pairs`, `/api/catalogue`,
`/api/compute`, and `POST /api/triage`. Live execution is unavailable. The catalogue
fallback reads formulas from the existing precursor property CSV. `KILN_ITEMS`
may point to a label-free item JSONL export to supply missing pair metadata;
never point it at the ledger or labels directory.

The compute page reports both non-stub run machines separately and loads prices
from frozen settings. Cache estimates match cache keys **within each machine**,
using the earliest timed original; unmatched reuses contribute no seconds. The
full-check reference is a single pass through the frozen tiers, not a competing
system's measured cost. The Toolkit microbenchmark is labelled separately.

Preview scope: no generated artwork, live mode, energy chart, or automatic
animation timeline. The replay is user-stepped; reduced-motion jumps to its
final state. Full production/browser qualification remains a subsequent pass.

Additional tests: `python -m pytest tests/test_lab_api.py`.

Local implementation of `files/kiln-evidence-strip-prompt.md`, using Primer-style
controls and the [Primer system font stack](https://github.com/primer/css/blob/main/src/support/variables/typography.scss).
The existing standard-library HTTP server is retained; Streamlit is not required.

Run from the repository root with `python app/server.py`, then open
`http://localhost:8080`. `PORT` selects another port; `KILN_ROOT` selects the
directory holding the recorded exports. No model or compute service is called.

The four views provide:
1. **Overview & Precursors:** Architecture walkthrough, locked 32.0-unit tier budget pills, and an interactive **46-Precursor Sourced Property & Tammann Explorer** (`data/precursor_props.csv`).
2. **Ranked results:** Summary KPI cards, condition and review-status filters, and filtered CSV export.
3. **Evidence trail:** Furnace verification bar (`render_evidence_strip`) with heat-gradient accepted segments, striped rejected segments (`dropped from verdict`), flat grey inconclusive segments, interactive step-by-step scrubber (`‹ Step` / `Step ›` / `▶ Play trail`), synchronized timeline card highlighting, **Thermochemical & Tammann Regime Gauges** ($\Delta E$, $\frac{2}{3}T_m$, compute budget), and a **Cross-Condition Comparator (`C1`–`C4`)**.
4. **How good is it?:** Condition comparison table, compute allocation breakdown, cryptographic provenance digests, and an interactive **Make your call** lab bench with precursor Tammann reference chips and embedded evidence-strip replay on reveal.

Light, dark and system themes are supported, along with keyboard shortcuts (`Space` to play/replay, `[` / `]` to step through artifacts, `J` / `K` to switch pairs). Reduced-motion mode immediately shows the final replay state. All scientific content comes from supplied records.


## Required exports and handoff

- Current records: `runs-h100/<run>/predictions.jsonl`, `config.json`,
  `compute_requests.jsonl`, and `board/**/artifacts.jsonl`. Stub runs are excluded.
  The invalidated GB10 JSONL run is not loaded.
- Legacy plan format: `runs/<condition>/<seed>/candidates.json`,
  `artifacts/*.json`, and `provenance.json` with `artifact_order` IDs. These records
  are labelled separately and excluded from H100 comparison metrics.
- Metrics: `results/<run>/evaluation.json` or
  `results/h100/<run>/evaluation.json`. Prediction bytes must match the report's
  digest and its run directory must identify H100. Only aggregate metrics enter
  the UI; evaluation request-level label fields are not exposed.
- **Requested writer additions, not implemented here:** the candidate's explicit
  `risk`, `risk_before`, and `mlip_disagreement`. Hemanath owns scoring these fields;
  CJ owns serializing them in the runner. The UI does not convert a reaction
  category into a new risk scale. Before/after appears only for distinct explicit
  risks with accepted evidence fulfilling a need. Writers must ensure that the
  pre-need risk and fulfilled need describe the same transition.
- **Requested scorer exports, not present by default:**
  `results/app/development_pairs.json` and `results/app/scored_pairs.json`, each a
  JSON list of `{id, precursors: [a,b], temp_c, hours, split, kiln_reacts,
  kiln_cause, real_reacts}`. `split` is `dev` or `heldout`; both reacts fields must
  be booleans explicitly supplied by the approved exporter. Optional `artifacts`
  may accompany the pair. Hemanath should publish these sanitized exports after
  the appropriate release; the UI never opens `labels/` or the raw ledger.
- The supplied plan's held-out gate is preserved: a 64-character prediction hash
  in `protocol/predictions.sha256` AND `results/comparison.json`. The H100 manifest
  alone does not unlock this exercise. Until the team provides those release
  files or approves an updated gate, only published development pairs are used.
  This local-file gate is not independent confirmation of a public hash post.

No actual H100 records or exercise exports are bundled into the UI. Missing data
produces an explicit empty state. Session scores count each exported pair once
per browser tab session. This is a learning interaction, not a secure blind test:
released outcomes are available in the page payload after the server-side gate.

## Checks

`python -m pytest tests/test_viewer.py tests/test_evidence_strip.py`

`node --check app/assets/app.js`

UI tests use synthetic records in temporary directories only. No experimental
outcomes are obtained or invented for previews. No protocol, scoring, or model
logic is changed by this UI.
