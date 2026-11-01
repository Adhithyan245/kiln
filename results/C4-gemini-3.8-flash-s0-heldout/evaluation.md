## Kiln evaluation: C4-gemini-3.8-flash-s0-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `1af046c15d4cd83dda3ae3460f5ed7352f13861b10099645b6cccf32196d5d71`; manifest sha256 `b44cf1261297a1fa6e1c2925fb6c738b585fc468d2df3d105e8d489c8696e46f` confirmed as posted by `manual` (message 1566368553345613947).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.684 |
| Brier | 0.274 |
| Four-class accuracy | 0.194 |
| Four-class macro-F1 | 0.137 |
| Coverage (unflagged share) | 0.315 |
| Flagged accuracy (n = 228) | 0.140 |
| Unflagged accuracy (n = 107) | 0.308 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 111 | 0.323 |
| transformed | 108 | 2 | 0.000 |
| partially_reacted | 33 | 215 | 0.194 |
| completely_reacted | 57 | 7 | 0.031 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 345 | 34.50 | 0.0 | 0 (0) |
| single_point | 108 | 108.00 | 0.0 | 0 (0) |
| bounded_relaxation | 24 | 720.00 | 0.0 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 485 | 864.10 | 0.0 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
