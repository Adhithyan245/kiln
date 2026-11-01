# ⚠️ INVALID RUN — DO NOT CITE, USE, OR PRESENT (STUB BACKEND DEFECT)

> [!CAUTION]
> **INVALID RUN (DECLARED INVALID IN `protocol/amendments.md` ON 2026-11-01):**
> This Night 2 GB10 run executed with `KILN_COMPUTE_BACKEND=stub` (fake energies, `model: stub`).
> Every metric below is invalid and must not be used, cited, or presented on slides.
> The valid primary experimental result is the H100 run (`results-h100/`).

---

## Kiln evaluation: C1-gemini-3.8-flash-s2-heldout

Split heldout, source precursor_genome, n = 346. Predictions sha256 `b20f1e67b4144f15c66cb93bfc8ba10e4e4aa1f2467561dabf4cc6f94b5c85d7`; manifest sha256 `b44cf1261297a1fa6e1c2925fb6c738b585fc468d2df3d105e8d489c8696e46f` confirmed as posted by `manual` (message 1566368553345613947).

| Metric (all pairs, flagged included) | Value |
|---|---|
| AUROC (reacted vs not) | 0.694 |
| Brier | 0.239 |
| Four-class accuracy | 0.257 |
| Four-class macro-F1 | 0.165 |
| Coverage (unflagged share) | 0.315 |
| Flagged accuracy (n = 228) | 0.206 |
| Unflagged accuracy (n = 107) | 0.364 |

| Class | Support | Predicted | F1 |
|---|---|---|---|
| unreacted | 137 | 166 | 0.416 |
| transformed | 108 | 3 | 0.018 |
| partially_reacted | 33 | 162 | 0.226 |
| completely_reacted | 57 | 4 | 0.000 |

| Compute tier | Requests | Compute units | GPU-seconds | Moved toward label (known) |
|---|---|---|---|---|
| cached_lookup | 346 | 34.60 | 0.0 | 0 (0) |
| single_point | 9 | 9.00 | 0.0 | 0 (0) |
| bounded_relaxation | 0 | 0.00 | 0.0 | 0 (0) |
| decomposition_reeval | 9 | 1.80 | 0.0 | 0 (0) |
| **total** | 364 | 45.40 | 0.0 | 0 (0) |

- Hard subset: Unavailable: no per-item margins and margin threshold were supplied.
- Bootstrap intervals: Unavailable: an agreed and validated bootstrap method for overlapping precursor clusters is required.
- Correct changes: Unavailable: no agreed definition; changed_prediction is OPEN-17 and extra allocation tables are OPEN-14.
- Review flags are flags, not calibrated probabilities or validated failure causes.
