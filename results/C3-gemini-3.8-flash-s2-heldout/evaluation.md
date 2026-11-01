## Kiln evaluation: C3-gemini-3.8-flash-s2-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `a6403050d64aabc6dc165e63605f254460483f8f51a1c39711079477e78b59ee`; manifest sha256 `b44cf1261297a1fa6e1c2925fb6c738b585fc468d2df3d105e8d489c8696e46f` confirmed as posted by `manual` (message 1566368553345613947).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.681 |
| Brier | 0.275 |
| Four-class accuracy | 0.197 |
| Four-class macro-F1 | 0.139 |
| Coverage (unflagged share) | 0.312 |
| Flagged accuracy (n = 229) | 0.144 |
| Unflagged accuracy (n = 106) | 0.311 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 111 | 0.323 |
| transformed | 108 | 2 | 0.000 |
| partially_reacted | 33 | 215 | 0.202 |
| completely_reacted | 57 | 7 | 0.031 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 345 | 34.50 | 0.0 | 0 (0) |
| single_point | 107 | 107.00 | 0.0 | 0 (0) |
| bounded_relaxation | 24 | 720.00 | 0.0 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 484 | 863.10 | 0.0 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
