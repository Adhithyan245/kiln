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

## Gate H record (Night 2 GB10 primary run - DECLARED INVALID)

> [!WARNING]
> **Superseded and declared invalid (2026-11-01):** As recorded in the Amendments section below, the GB10 run was discovered to have executed with the stub compute backend (`KILN_COMPUTE_BACKEND=stub`), producing mock energies (`model: stub`). This run is invalid and discarded. The H100 replication run is designated as the sole valid experimental result.

Gate H verification for the primary run happened on 2026-11-01. The Night 2 GB10 run produced 4,152 predictions across 12 runs (C1–C4 × 3 seeds × 346 held-out items), run at code `040f65d129 0d9ebadfd6 4ef33e6528 572bff923b` (`040f65d`), containing Gate P commit `c283468633 4c6bc768fd 0654a220b9 0df8b4985c`. Results, manifest and receipt were committed on `dev` at `e4854073b4 54b8ce96ab ae42e2813d 0fdaef7458` (`e4854073`). 5 items were scored on empty evidence after Gemini 503 errors (OPEN-23): C2-s0, C2-s1, C3-s0, C3-s2, C4-s0, one each. Full SHAs are written in blocks because `tests/protocol/test_protocol.py` rejects unbroken 40- to 64-character hex strings in this file. Join the blocks to compare.

| Field | Value |
|---|---|
| Target / Scope | Night 2 primary run (GB10): C1–C4 × s0–s2 (12 runs, 4,152 total predictions) |
| Manifest path | `protocol/predictions.manifest.json` |
| Manifest SHA-256 | `b44cf1261297a1fa 6e1c2925fb6c738b 585fc468d2df3d10 5e8d489c8696e46f` |
| Posted where and when (channel per OPEN-16, `protocol.md` §10) | #kiln-receipts (channel 1566322635749597355), through its dedicated prereg webhook: Discord message 1566368553345613947, 2026-11-01T08:29:24.838Z, recorded in `protocol/posts.jsonl` |
| Posted by Adhi; receipt independently checked by Hemanath (`protocol.md` §10) | **Posted by Adhi** via `kiln.night.prereg`. **Independently verified by Hemanath on 2026-11-01:** the message was recorded with message id 1566368553345613947; the manifest SHA-256 matches the posted digest; all 12 prediction files match the manifest digests byte-for-byte; all 12 files contain exactly 346 lines (4,152 total predictions); post timestamp (08:29:24Z) is before label loading or unblinding; `.gitattributes` ensures line-ending stability across platforms. |
| Run commit | `040f65d129 0d9ebadfd6 4ef33e6528 572bff923b` (`040f65d`) |
| Commit containing results | `e4854073b4 54b8ce96ab ae42e2813d 0fdaef7458` (`e4854073`) |

Record written on 2026-11-01. All 12 prediction files were verified locally against `protocol/predictions.manifest.json` and confirmed byte-exact before labels were loaded.


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

### 2026-11-01: GB10 primary run invalidation due to stub backend defect; H100 replication adopted as experimental result

- **What changed:**
  1. The Night 2 GB10 primary run (`runs/`) is declared **invalid** and discarded.
  2. The Night 2 H100 replication run (`runs-h100/`) is adopted as the sole valid experimental evaluation result.
  3. The H100 plan GPU-hour safety cap was increased mid-run from 8.0 to 14.0 GPU-hours.
- **Why (GB10 defect discovery):**
  Inspection of the compute logs (`runs/*/compute_requests.jsonl` on `dev`) revealed that `KILN_COMPUTE_BACKEND` had defaulted to `"stub"` on the GB10 host machine and was never set to `"local"`. As a result, every single-point and relaxation compute request on the GB10 returned fake energies with `result.model: "stub"` and recorded `0.0` GPU-seconds. This defect was undetected by preflight checks because `stub_parts` only monitors LLM stand-in agents and the rule scorer, not the underlying MLIP compute backend. Crucially, this defect was discovered **from the compute logs and hardware telemetry (0.0 GPU-seconds recorded), not from evaluation scores or label inspection**.
- **H100 run verification:**
  Telemetry and compute logs from the H100 instance (`runs-h100/`) were inspected and confirmed genuine:
  - `KILN_COMPUTE_BACKEND=local` was confirmed active in the running process environment.
  - All `single_point` and `bounded_relaxation` tiers log `result.model: "medium-mpa-0"` (0 stub entries across all 12 runs).
  - All MLIP tiers use `result.backend: "nvalchemi+ase"`.
  - Realistic non-zero GPU execution times are logged (e.g. 28 s for single point, up to 345 s for relaxations).
  - `cached_lookup` tiers verify as `source: "materials_project"`.
- **H100 safety cap adjustment:**
  The H100 run paused at 09:29 UTC after reaching 2,953 / 4,152 predictions when cumulative GPU time across 12 concurrent workers reached the 8.0 GPU-hour cap. The 8.0-hour cap was originally copied from the GB10 plan (where stubs spent 0 GPU-seconds). Because real parallel relaxations consume concurrent GPU time across parallel workers, the cap was increased to 14.0 GPU-hours via `~/kiln-h100/night2-h100-resume.toml` to allow completion of the remaining ~1,196 items.
- **Who made the change:** Hemanath and Adhi.
- **Decision timing:** Decided on 2026-11-01 **before unblinding or scoring of the H100 run**. The H100 run remains blinded; labels will only be loaded after the H100 run finishes and its prediction manifest hash is independently verified in #kiln-receipts.

### 2026-11-01: GB10 rerun with local compute backend launched as replication of adopted H100 result

A GB10 rerun with real compute started on 2026-11-01 at 12:57:47Z.

- **Configuration:**
  - Code: frozen code `040f65d129 0d9ebadfd6 4ef33e6528 572bff923b` (`040f65d`), containing Gate P commit `c283468633 4c6bc768fd 0654a220b9 0df8b4985c`.
  - Settings & data: `protocol/frozen_settings.json`, agent-visible items file `~/kiln-items.jsonl` (SHA-256 `0a97babfab 2f2ce4d345 9b8e9d83ba 1f2544acf5 0feb3687be f0e47afd17 f663`), and Materials Project cache in `~/kiln/cache/` (digest `e12434966d c3b24f5a89 b48de7b51c 6bfaec739e 3717df3d0a 6499351de3 96a453`).
  - Only change: `KILN_COMPUTE_BACKEND=local`, confirmed set in the live process environment.
- **Cache purge & validation:**
  - Before launch, the invalid stub run's outputs and the 1,045 fake cache entries were quarantined and moved to `~/kiln/stub-invalid-20261101/`. Because compute cache keys do not embed the backend name, moving them was required to ensure no stub results are reused.
  - A 2-item dry run check before launching verified real calculation results: `materials_project` lookups, `medium-mpa-0` single-point taking 5.0 GPU-s, and bounded relaxation taking 410.8 GPU-s.
- **Role and status:**
  - The GB10 rerun serves as a secondary replication of the adopted H100 result. It will be reported in its own table and is never used to select or pool results.
  - Expected completion is between 16:00 and 17:00 UTC (noon to 1:00 PM Eastern).
- **Who made the change:** Adhi and Hemanath.
- **Decision timing:** Decided and recorded on 2026-11-01 while the GB10 rerun and H100 run are both in progress, before either run's predictions are unblinded or scored.


### 2026-11-01: H100 GPU-hour cap raised a second time, from 14.0 to 20.0

- **What changed:** the H100 replication's GPU-hour safety cap, from 14.0 to 20.0 GPU-hours, in a new resume plan on the VM (`~/kiln-h100/night2-h100-resume20.toml`, SHA-256 `5a62257b34c999b2775a2e36a436948eaf285255c120d735b77e8f6316417bbe`). That is the only line that differs from `night2-h100-resume.toml`. Code, settings, items file, MP cache, model and key split are unchanged. The run resumed in the same shell, and the new process environment was checked: `KILN_COMPUTE_BACKEND=local`, `KILN_TIER_SETTINGS=env/h100/tier_settings.json`, `GEMINI_API_KEY_2` set and `GEMINI_API_KEY` unset.
- **Why:** the 14.0 figure was set at 09:29 UTC from a rough estimate. The 11:54 to 13:23 UTC stretch averaged about 0.0076 GPU-hours per prediction (738 predictions for 5.59 GPU-hours), which suggested about 17.8 GPU-hours in total for the 413 predictions left, plus up to about 0.6 for the stop grace period, so 20.0 was chosen. That estimate was too low: after the resume, the remaining C2 to C4 items ran at about 0.027 GPU-hours per prediction (51 predictions for 1.36 GPU-hours, 15:36 to 15:55 UTC), so 20.0 will not cover the whole run either. See the next entry. Tokens (7.37 M of 12 M) and USD ($19.15 of $30) were well inside their caps and are unchanged.
- **Stop and resume:** the cap was reached at 13:29:44 UTC (14.04 GPU-hours). The in-flight work ended at 13:34:44 UTC, when the stop grace period ran out, leaving 3,739 predictions and 14.68 GPU-hours spent. It resumed at 15:36:30 UTC. Predictions already written are kept. Items interrupted at the stop are rerun from the start, as the runner does on any resume.
- **Who made the change:** Hemanath.
- **Decision timing:** the raise was decided at 13:24 UTC and the 20.0 figure at 15:35 UTC on 2026-11-01. Both were decided while the H100 run was blind: no predictions unblinded, nothing scored, labels not loaded. The cap only decides whether the run finishes; it does not change how any prediction is made, budgeted or scored.

### 2026-11-01: H100 run scored from a 16:15 UTC copy on the items every run completed; the full run continues and is reported separately

- **What changed:** results are needed before the 1:00 PM Eastern deadline, and the H100 run cannot finish in time: at 15:55 UTC it was making about 2.7 predictions a minute with 362 left. The run is **not stopped**. Instead:
  1. At 16:15 UTC, `runs-h100/` on the VM is copied to `runs-h100-cut/`. The live run keeps writing only to `runs-h100/`.
  2. **Common item set:** the held-out items that have a prediction in all 12 runs (C1 to C4 x s0 to s2) in the copy. Each run in the copy is filtered to that set: `predictions.jsonl` and `compute_requests.jsonl` keep only those items' lines, and a matching items file (`kiln-items-cut.jsonl`, a subset of `~/kiln-items.jsonl` with SHA-256 `0a97babf...d617f663`) is written. No prediction or compute line is edited, only dropped.
  3. On the copy, the frozen steps run unchanged: `kiln.runners.finalize`, which has nothing to fill once the items file matches, then `kiln.night.prereg manifest` to `protocol/predictions-h100-cut.manifest.json`, then `kiln.night.prereg post` to `protocol/posts-h100-cut.jsonl` in #kiln-receipts.
  4. The copy is scored locally with `kiln.scoring` (`evaluate.py` unchanged) against that manifest and receipt, with the common items file. This is the **H100 result presented on 2026-11-01**, labelled as covering N of 346 held-out items, with N and the item ids published with it.
  5. The full run continues to completion and gets its own manifest, hash post and score later, reported in its own table. It is never pooled with the copy's result, and it does not replace it after the fact.
- **Why the common set:** every run takes the items in the same file order, so the items finished by all 12 runs are the same leading part of the list for every condition and seed, not a set chosen by outcome. Scoring the unreached items on empty evidence (OPEN-23 `finalize`) would be valid but would penalize C2 to C4, whose runs are behind, against C1, which had finished, so it is not used for the comparison.
- **Why this cannot affect the live run:** labels never go to the VM, and the agents never see scores. Scoring the copy cannot change what the live run predicts.
- **Who made the change:** Hemanath.
- **Decision timing:** decided at 16:05 UTC on 2026-11-01 and pushed before the copy was taken. The H100 run was blind: no predictions unblinded, nothing scored, labels not loaded.
