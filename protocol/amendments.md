# Kiln evaluation protocol: Gate P record and amendments

This file is **not** part of the Gate P hash. `protocol/protocol.md` is never edited after the Gate P commit. The Gate P record and every later change go here instead (`protocol.md` §10, P3 and P5).

## Gate P record

Gate P happened on 2026-11-01. `protocol/protocol.md` is frozen at the Gate P commit below and is never edited again (`protocol.md` §10, P5); held-out runs may start (P4). Full SHAs are written in blocks, commit SHAs as four 10-character blocks and the digest as four 16-character blocks, because `tests/protocol/test_protocol.py` rejects unbroken 40- to 64-character hex strings in this file. Join the blocks to compare.

| Field | Value |
|---|---|
| Gate P commit (full SHA, pushed to `dev`) | `c283468633 4c6bc768fd 0654a220b9 0df8b4985c` (`c283468`): the merge of PR #26 into `dev`, committed 2026-11-01T05:32:57Z |
| SHA-256 of `git cat-file blob <gate-p-commit>:protocol/protocol.md` | `3ca68ee18b1ccc35 4167c2fa744923c4 cbcaba5cbfbdc986 819d45f58f2edf7b` |
| Posted where and when (channel per OPEN-16, `protocol.md` §10) | #kiln-receipts (channel 1566322635749597355), through its own webhook, separate from the alerts webhook: Discord message 1566325150582964286, 2026-11-01T05:36:56.813Z, https://discord.com/channels/1566155357875867772/1566322635749597355/1566325150582964286 |
| Posted by Adhi; receipt independently checked by Hemanath (`protocol.md` §10) | **Posted by Adhi** through the #kiln-receipts webhook. **Independently verified by Hemanath on 2026-11-01:** the message was fetched from Discord through the receipts webhook; its webhook id, 1566322680859205672, matches the #kiln-receipts webhook; the message was not edited; its content contains the exact Gate P commit SHA and digest; the digest recomputed from the commit matches; and the post time (05:36:56Z) is after the commit time (05:32:57Z) |
| P2 code-freeze commit (`protocol.md` §10) | `d9a2993997 530fa4cee0 f9216b78df 2b5189b127` (`d9a2993`, as in `protocol.md` §10). No code or settings change between P2 and the Gate P commit: `git diff --stat d9a2993 c283468 -- src env data/precursor_props.csv protocol/frozen_settings.json protocol/scoring_rules.json pyproject.toml uv.lock` prints nothing. Re-recorded here if a later code or settings commit lands before Night 2 |

Record written on 2026-11-01 from the values relayed by the orchestrator. When it was written, the Gate P commit, its commit time, its parents (`de0e33f` and `3ecfb37`), the digest (recomputed with the P3 command) and the P2 check were rechecked against `dev` at `c283468`. The Discord message was not fetched again for this record. The webhook URL is a secret and is not written here or anywhere in the repo (`AGENTS.md` rule 4).

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
