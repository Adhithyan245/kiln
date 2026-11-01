## Kiln evaluation: C3-gemini-3.8-flash-s2-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `bc3decbdff27b8a69951631c6e38230cb1679ca6498fae3bdac253bee902af33`; manifest sha256 `cf6699f7f614e3b593fa31f4f6b3b24e4cccc09faf091f66468ef4800f45c78f` confirmed as posted by `discord` (message 1566496777790554284).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.735 |
| Brier | 0.179 |
| Four-class accuracy | 0.385 |
| Four-class macro-F1 | 0.178 |
| Coverage (unflagged share) | 0.303 |
| Flagged accuracy (n = 232) | 0.362 |
| Unflagged accuracy (n = 103) | 0.437 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 305 | 0.566 |
| transformed | 108 | 8 | 0.000 |
| partially_reacted | 33 | 22 | 0.145 |
| completely_reacted | 57 | 0 | 0.000 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 348 | 34.80 | 0.0 | 0 (0) |
| single_point | 123 | 123.00 | 1.2 | 0 (0) |
| bounded_relaxation | 94 | 2820.00 | 6767.0 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 573 | 2979.40 | 6768.2 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
