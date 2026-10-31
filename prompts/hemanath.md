# Hemanath — A, Evaluation

You're helping Hemanath build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/data/`, `src/kiln/provenance/`, `src/kiln/verifier/`, `src/kiln/scoring/`, `src/kiln/baselines/`, `data/alab/`, `protocol/` and their tests. Before each task, write a short plan and wait for my OK.

**Labels:** you are the only person who handles them. Code moves label fields into `labels/` (gitignored) **without printing them**. Never show label values in chat or logs.

## Task 1 (Friday night): load, lock, split
Download the ledger from GitHub `lauren-walters/precursor-genome` into `data/raw/`. Report only: license (Zenodo record and repo), exact category names, number of reactions, number of distinct precursors, and whether every pair appears once. Build `kiln.data` (agent-visible `Item`s; `Label`s to `labels/`) and a provenance record per item (source file, record index, fields used). Precursor-level split: hold out 9 of 46 precursors (fixed seed, spread across element groups).
**Done when:** `load_items("dev")` / `load_items("heldout")` validate, a test proves no `Item` holds a label field, and the held-out count is printed.

## Task 2 (Friday night): baselines on development
B0 (driving-force threshold on cached energies) and B0-T (Tammann rule). Report **only** aggregate development AUROC.

## Task 3 (Saturday morning): verifier, provisional scoring, A-Lab demo recipes
`kiln.verifier.verify` (schema, units, cited ids and numbers, `falsified_if`, budget, no forbidden fields) and `score.provisional` for the before/after log. Then 3–5 A-Lab demo recipes in `data/alab/` with provenance (1-hour box).
**Done when:** tests show the verifier rejects a missing `falsified_if`, a fake citation, a mismatched number and an over-budget artifact.

## Task 4 (Saturday afternoon): locked scorer and protocol
`score.score` (fixed rules, takes review flags), B1, and `kiln.scoring.evaluate`: hash → post hash → load labels → metrics on **all** pairs, coverage, flagged vs unflagged accuracy, compute-allocation tables, `moved_toward_label`. Write `protocol/protocol.md` (including the frozen price list and budget) and hash it at 7 PM.
