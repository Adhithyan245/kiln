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

Items that `protocol.md` §17 lists as still to do. If one is still open when the Gate P commit is made, it gets a dated entry below instead:

- OPEN-06 and OPEN-07: Annamayya's confirmation of `docs/escalation-rule.md` (until then, no shared rule).
- OPEN-05: `protocol/scoring_rules.json` on `dev`, cited by commit.
- OPEN-16: CJ's confirmation of the webhook destination, and Adhi's agreement to check receipts.
- OPEN-02 and OPEN-03: Adhi's review of the prices and budget copied from `protocol/prices_proposal.json` at `e5d81a2`, including whether the per-item cap is 31.0 or 31.3 units.
- The `gemini-3.8-flash` training cutoff, with its source (Adhi; `protocol.md` §11).
- OPEN-22: the dataset attribution text.
- Opaque item ids, only if that code lands before the held-out runs (OPEN-19).

## Amendments

None. Each amendment after Gate P gets a dated entry: what changed, why, who made it, and whether it was decided before or after unblinding. Anything decided after unblinding is labeled post hoc.
