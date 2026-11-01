# Night runner: the 10-minute walkthrough (CJ for Adhi, Sat Oct 31)

Companion to `docs/night2-runbook.md`. Everything runs on the GB10 inside tmux, from `~/kiln`.

## Start it

```bash
tmux new -s kiln-night            # reattach later with: tmux attach -t kiln-night
cd ~/kiln && source ~/alchemi/venv/bin/activate
set -a; . ~/.kiln.env; set +a     # MP and Gemini keys live here (and the webhooks, if you put them here)
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True KILN_COMPUTE_BACKEND=local PYTHONPATH=src
python -m kiln.night run src/kiln/night/plans/night2.toml --dry-run   # prints the steps; runs nothing
python -m kiln.night run src/kiln/night/plans/night2.toml
```

Detach with `Ctrl-b d`. The runner refuses to start if the plan's caps are unset or `labels/` exists.

## Read the state

State lives in `runs/_night/night2/`:

| File | What it tells you |
|---|---|
| `state.json` | Each step: `done`, `resumed`, `failed`, `skipped:<why>`, `not_run`; `stopped` says why the night stopped |
| `alerts.log` | Everything that was sent to Discord, with UTC timestamps (also when the webhook is down) |
| `<step>.done` | Done-marker with the step's spec hash; a resume skips steps whose marker matches |

Each condition run has its own folder `runs/<condition>-gemini-3.8-flash-s<seed>-heldout/`:
`predictions.jsonl` (one line per item), `cost.json` (tokens and dollars per item, read by the caps),
`timings.jsonl` (wall seconds per item), `failed_items.jsonl` (items that raised, with the error),
`verifier.log` (artifacts not accepted), `needs_suppressed.jsonl` (C1/C2/C3), `board/<item>/attempt-<n>/`.

Quick progress check from another tmux window:

```bash
wc -l runs/*-heldout/predictions.jsonl     # 346 per run when finished
cat runs/*-heldout/failed_items.jsonl 2>/dev/null | tail
```

## A healthy heartbeat (every 30 min)

```
[night2] heartbeat: {'done': 1} pending=8; tokens 412000/5000000, usd 1.40/20.0, gpu_h 0.61/8.0
```

`done` grows, `pending` shrinks, and tokens, usd and gpu_h climb steadily and stay well under the caps.
Worry if two heartbeats show the same token count during `run_conditions` (stalled), or if a cap passes
about 80% before the last seed. Order of runs: seed 0 of C1, C2, C3, C4, then seed 1, then seed 2, so a
partial night is still a complete comparison for the seeds that finished.

## Resume after a failure

1. Read `alerts.log` and `state.json` for the failed step and its error.
2. **Check for an orphan before restarting:** `pgrep -af kiln.runners`. A killed night runner can leave the
   conditions process running (steps run in their own session), and it keeps calling Gemini outside the
   new runner's caps. Either `kill <pid>` it (it resumes from where it stopped), or leave it: the restarted
   copy waits on each run the orphan holds ("held by another process ... waiting") and then resumes, so
   nothing is predicted twice.
3. Rerun the same command. Done steps are skipped, and `run_conditions` skips every item already in
   `predictions.jsonl`; an interrupted item restarts in a fresh `attempt-<n>` folder.

What stops the night on purpose: a cap breach (clean stop, alert), `labels/` present, or the
`fetch_labels`/`score` placeholders (`on_fail = "stop"`), which run after predictions, manifest, hash
post and the local commit. `push` commits locally and skips the push with a note (no GitHub on the GB10).

Rehearsed on the GB10 (kill -9 of the night runner mid-C1, then restart). The first rehearsal found
duplicate predictions from the orphan (fixed in `b6e4ba0` with a per-run lock); the second found the
restarted step giving up while the orphan held the run (fixed by waiting for it).

## Timing (Sat 7:15 PM dry run, every agent on gemini-3.8-flash)

About 25 s per item per condition, ~28.6 h for the whole night in sequence. `--parallel 12` runs every
condition/seed at once (longest run: C3, ~3.2 h); it is off in `night2.toml` until Adhi agrees.
