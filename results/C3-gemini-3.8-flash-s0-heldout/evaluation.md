# ⚠️ INVALID RUN — DO NOT CITE, USE, OR PRESENT (STUB BACKEND DEFECT)

> [!CAUTION]
> **INVALID RUN (DECLARED INVALID IN `protocol/amendments.md` ON 2026-11-01):**
> This Night 2 GB10 run executed with `KILN_COMPUTE_BACKEND=stub` (fake energies, `model: stub`).
> Every metric below is invalid and must not be used, cited, or presented on slides.
> The valid primary experimental result is the H100 run (`results-h100/`).

---

## Kiln evaluation: C3-gemini-3.8-flash-s0-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `8778f2fb11461823c3422263b2fa5c00f78d8c3104d9755f30a69c5010520248`; manifest sha256 `b44cf1261297a1fa6e1c2925fb6c738b585fc468d2df3d105e8d489c8696e46f` confirmed as posted by `manual` (message 1566368553345613947).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.695 |
| Brier | 0.268 |
| Four-class accuracy | 0.197 |
| Four-class macro-F1 | 0.139 |
| Coverage (unflagged share) | 0.315 |
| Flagged accuracy (n = 228) | 0.145 |
| Unflagged accuracy (n = 107) | 0.308 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 113 | 0.320 |
| transformed | 108 | 2 | 0.000 |
| partially_reacted | 33 | 213 | 0.203 |
| completely_reacted | 57 | 7 | 0.031 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 345 | 34.50 | 0.0 | 0 (0) |
| single_point | 104 | 104.00 | 0.0 | 0 (0) |
| bounded_relaxation | 24 | 720.00 | 0.0 | 0 (0) |
| decomposition_reeval | 8 | 1.60 | 0.0 | 0 (0) |
| **total** | 481 | 860.10 | 0.0 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
