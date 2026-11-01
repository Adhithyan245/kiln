## Kiln evaluation: C3-gemini-3.8-flash-s2-heldout

Split heldout, source precursor_genome, n = 301. Predictions sha256 `5b78e75d7b0680e1b71a23a1c37b3deac596a0976c020f0d3d5773270cb748f0`; manifest sha256 `9cb24cb49164521029690d2a3625d0b1591a9089251d6bdd36141237cd915264` confirmed as posted by `discord` (message 1566485753733578907).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.721 |
| Brier | 0.170 |
| Four-class accuracy | 0.382 |
| Four-class macro-F1 | 0.163 |
| Coverage (unflagged share) | 0.246 |
| Flagged accuracy (n = 220) | 0.368 |
| Unflagged accuracy (n = 73) | 0.425 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 122 | 267 | 0.566 |
| transformed | 100 | 8 | 0.000 |
| partially_reacted | 28 | 18 | 0.087 |
| completely_reacted | 43 | 0 | 0.000 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 303 | 30.30 | 0.0 | 0 (0) |
| single_point | 105 | 105.00 | 1.2 | 0 (0) |
| bounded_relaxation | 84 | 2520.00 | 6028.4 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 500 | 2656.90 | 6029.6 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
