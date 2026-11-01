## Kiln evaluation: C1-gemini-3.8-flash-s1-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `1ace15a492a812b090b7d0ebf0c58dad921fa2217eaf1282752cc3261e1030d1`; manifest sha256 `b44cf1261297a1fa6e1c2925fb6c738b585fc468d2df3d105e8d489c8696e46f` confirmed as posted by `manual` (message 1566368553345613947).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.683 |
| Brier | 0.246 |
| Four-class accuracy | 0.254 |
| Four-class macro-F1 | 0.160 |
| Coverage (unflagged share) | 0.315 |
| Flagged accuracy (n = 228) | 0.202 |
| Unflagged accuracy (n = 107) | 0.364 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 164 | 0.419 |
| transformed | 108 | 2 | 0.000 |
| partially_reacted | 33 | 164 | 0.223 |
| completely_reacted | 57 | 5 | 0.000 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 346 | 34.60 | 0.0 | 0 (0) |
| single_point | 10 | 10.00 | 0.0 | 0 (0) |
| bounded_relaxation | 0 | 0.00 | 0.0 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 364 | 46.20 | 0.0 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
