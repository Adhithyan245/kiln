## Kiln evaluation: C3-gemini-3.8-flash-s1-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `a473f19b3dca83a8ac1c1bcd2f7815c74ec28e9e774a30ac4278b0d855163d50`; manifest sha256 `cf6699f7f614e3b593fa31f4f6b3b24e4cccc09faf091f66468ef4800f45c78f` confirmed as posted by `discord` (message 1566496777790554284).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.736 |
| Brier | 0.178 |
| Four-class accuracy | 0.385 |
| Four-class macro-F1 | 0.178 |
| Coverage (unflagged share) | 0.301 |
| Flagged accuracy (n = 233) | 0.365 |
| Unflagged accuracy (n = 102) | 0.431 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 305 | 0.566 |
| transformed | 108 | 8 | 0.000 |
| partially_reacted | 33 | 22 | 0.145 |
| completely_reacted | 57 | 0 | 0.000 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 348 | 34.80 | 0.0 | 0 (0) |
| single_point | 121 | 121.00 | 3.4 | 0 (0) |
| bounded_relaxation | 92 | 2760.00 | 6275.6 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 569 | 2917.40 | 6278.9 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
