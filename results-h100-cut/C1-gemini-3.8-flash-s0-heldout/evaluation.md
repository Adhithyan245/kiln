## Kiln evaluation: C1-gemini-3.8-flash-s0-heldout

Split heldout, source precursor_genome, n = 301. Predictions sha256 `58b9b21d1e0c8b57535f2095f7b2f7914edf01fdeafc033863fc17f3b7f5ba3d`; manifest sha256 `9cb24cb49164521029690d2a3625d0b1591a9089251d6bdd36141237cd915264` confirmed as posted by `discord` (message 1566485753733578907).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.712 |
| Brier | 0.174 |
| Four-class accuracy | 0.386 |
| Four-class macro-F1 | 0.165 |
| Coverage (unflagged share) | 0.259 |
| Flagged accuracy (n = 216) | 0.375 |
| Unflagged accuracy (n = 77) | 0.416 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 122 | 272 | 0.563 |
| transformed | 100 | 8 | 0.000 |
| partially_reacted | 28 | 13 | 0.098 |
| completely_reacted | 43 | 0 | 0.000 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 301 | 30.10 | 0.0 | 0 (0) |
| single_point | 17 | 17.00 | 67.6 | 0 (0) |
| bounded_relaxation | 1 | 30.00 | 31.7 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 327 | 78.70 | 99.3 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
