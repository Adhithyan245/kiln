# Kiln evaluation protocol: Gate P record and amendments

This file is **not** part of the Gate P hash. `protocol/protocol.md` is never edited after the Gate P commit. The Gate P record and every later change go here instead (`protocol.md` §10, P3 and P5).

## Gate P record

Gate P has not happened. `protocol/protocol.md` is still a draft and has not been frozen, hashed or posted.

| Field | Value |
|---|---|
| Gate P commit (full SHA, pushed to `dev`) | not yet |
| SHA-256 of `git cat-file blob <gate-p-commit>:protocol/protocol.md` | not yet |
| Posted where and when (channel per OPEN-16, `protocol.md` §10) | not yet |
| Posted by Adhi; receipt independently checked by Hemanath (`protocol.md` §10) | not yet |
| P2 code-freeze commit (`protocol.md` §10) | `d9a2993` (full SHA in `protocol.md` §10); re-recorded here if a later code or settings commit lands after the Gate P commit and before Night 2 |

## Before the Gate P commit (not amendments)

On 2026-10-31 Hemanath delegated the pre-freeze decisions. They are written into `protocol.md` itself (§15, rows marked "decided 2026-10-31 by Hemanath, delegated"), because decisions made before the Gate P commit belong in the hashed file, not here. Hemanath may veto any of them before he makes the Gate P commit.

**Never deferred here (blocking, `protocol.md` §17 table 1).** These decide how predictions are made, scored or budgeted. The Gate P digest commits only to what `protocol.md` says at the Gate P commit, so each must be closed and written there (or cited from it by commit SHA) first. None of them ever gets an amendment entry here in place of that.

- OPEN-06 and OPEN-07: written in `protocol.md` §6 (rule by Annamayya, `a10c149` and `0c5eeea`; thresholds 0.05 eV/atom by Hemanath, delegated). The decomposable-only review flag is adopted on `dev` (`1782ba6`, `docs/plan-changes.md` row 29) and described in `protocol.md` §6.
- OPEN-05: the scoring rules, `protocol/scoring_rules.json` at `61f812b`, described and cited with its SHA-256 in `protocol.md` §3.3. The paragraph there on `p_react` and `category` being separate outputs was decided 2026-11-01 by Hemanath: intended as documented.
- OPEN-02 and OPEN-03: the prices and the 32-unit per-item budget copied from `protocol/prices_proposal.json` at `1e8549b`. Any further change is written in `protocol.md` §5 before the Gate P commit.
- `protocol/frozen_settings.json` with exactly the frozen values (`protocol.md` §5): Hemanath OK given 2026-11-01, pushed by Adhi in `4055d77`, SHA-256 recorded in §5.

The code items in `protocol.md` §17 table 2 (OPEN-23, OPEN-24, and the `evaluate.py` work for OPEN-08, OPEN-11 and OPEN-26) are not amendments either. The hashed text already says what that code must do.

**May follow the Gate P commit as dated entries below (non-blocking confirmations only, `protocol.md` §17 table 3).** None of these changes how a prediction is made, scored or budgeted:

- P2: recorded in `protocol.md` §10 (`d9a2993`). Only a re-recording after the Gate P commit goes here.
- OPEN-18: the `python -m kiln.data` rerun. A mismatch with the `protocol.md` §2.3 list is recorded here.
- OPEN-22: the dataset attribution text.
- OPEN-16: the dedicated receipts channel, #kiln-receipts, separate from #kiln-alerts; Adhi posts and Hemanath checks each post. These are needed before the P3 post.
- OPEN-19: opaque item ids, only if that code lands before the held-out runs.

## Amendments

None. Each amendment after Gate P gets a dated entry: what changed, why, who made it, and whether it was decided before or after unblinding. Anything decided after unblinding is labeled post hoc.
