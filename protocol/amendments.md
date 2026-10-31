# Kiln evaluation protocol: Gate P record and amendments

This file is **not** part of the Gate P hash. `protocol/protocol.md` is never edited after the Gate P commit. The Gate P record and every later change go here instead (`protocol.md` §10, P3 and P5).

## Gate P record

Gate P has not happened. `protocol/protocol.md` is still a draft and has not been frozen, hashed or posted.

| Field | Value |
|---|---|
| Gate P commit (full SHA, pushed to `dev`) | not yet |
| SHA-256 of `git cat-file blob <gate-p-commit>:protocol/protocol.md` | not yet |
| Posted where and when (channel per OPEN-16, `protocol.md` §10) | not yet |
| Receipt independently verified by (Adhi; Hemanath for any post Adhi makes, `protocol.md` §10) | not yet |

## Before the Gate P commit (not amendments)

On 2026-10-31 Hemanath delegated the pre-freeze decisions. They are written into `protocol.md` itself (§15, rows marked "decided 2026-10-31 by Hemanath, delegated"), because decisions made before the Gate P commit belong in the hashed file, not here. Hemanath may veto any of them before he makes the Gate P commit.

**Never deferred here (blocking, `protocol.md` §17 table 1).** These decide how predictions are made, scored or budgeted. The Gate P digest commits only to what `protocol.md` says at the Gate P commit, so each must be closed and written there (or cited from it by commit SHA) first. None of them ever gets an amendment entry here in place of that.

- OPEN-06 and OPEN-07: Annamayya's escalation rule and flag thresholds, or an explicit team decision in `docs/plan-changes.md` to freeze the null-margin design knowingly. Under that design no agent posts a need, C2 and C4 are identical, and the need board is never used.
- OPEN-05: the scoring rules, `protocol/scoring_rules.json`, on `dev` and cited by commit SHA.
- OPEN-02 and OPEN-03: Adhi's review of the prices and budget copied from `protocol/prices_proposal.json` at `e5d81a2`, including whether the per-item cap is 31.0 or 31.3 units.
- `protocol/frozen_settings.json` with exactly the frozen values, cited by commit SHA.

The code items in `protocol.md` §17 table 2 (OPEN-23, OPEN-24, and the `evaluate.py` work for OPEN-08, OPEN-11 and OPEN-26) are not amendments either. The hashed text already says what that code must do.

**May follow the Gate P commit as dated entries below (non-blocking confirmations only, `protocol.md` §17 table 3).** None of these changes how a prediction is made, scored or budgeted:

- P2: the code-freeze commit SHA, recorded with the Gate P record.
- OPEN-18: the `python -m kiln.data` rerun. A mismatch with the `protocol.md` §2.3 list is recorded here.
- OPEN-22: the dataset attribution text.
- The `gemini-3.8-flash` training cutoff, with its source (Adhi; `protocol.md` §11).
- OPEN-16: CJ's confirmation of the webhook destination and readers, and Adhi's agreement to check receipts. These are needed before the P3 post.
- OPEN-19: opaque item ids, only if that code lands before the held-out runs.

## Amendments

None. Each amendment after Gate P gets a dated entry: what changed, why, who made it, and whether it was decided before or after unblinding. Anything decided after unblinding is labeled post hoc.
