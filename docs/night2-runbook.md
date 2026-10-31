# Night 2 runbook (operator: Adhi, from a laptop over Tailscale)

CJ's laptop can't reach the GB10 remotely tonight, so Adhi runs Night 2. Everything runs **on the GB10 inside `tmux`**; the laptop only starts it, watches it and brings results back. Closing the laptop or losing Wi-Fi does not stop the run.

Facts checked on the GB10 (Sat ~5 PM): `tmux` installed; idle suspend off while the desktop session stays logged in (**never log out of the GB10's desktop**: the login screen can suspend the box); 1.3 TB disk and 116 GB RAM free; no API keys or webhooks set yet; the repo's `origin` is a bundle file and the GB10 cannot push to GitHub (results come back through the laptop); `~/kiln-items.jsonl` holds 346 held-out and 635 dev items, agent-visible fields only.

## 1. Gates before launch (all must be true)

| Gate | Owner | Check |
|---|---|---|
| Real Thermo, Kinetics, Precursor agents, tools, `precursor_props.csv`, review flags on dev | Annamayya | Without them the runner only has stand-ins (`--stubs`), which are never experiment results |
| Frozen scoring rules wired into the runner | Hemanath | Not the stand-in scorer |
| Protocol frozen, hashed and posted (prices, budget, thresholds, model) | Hemanath | Hash posted before any held-out run |
| `protocol/prices_proposal.json` reviewed; prices and per-item budget frozen | Adhi, Hemanath | From the profiling rerun after the phase-set fix |
| Night 2 plan updated (`src/kiln/night/plans/night2.toml`, CJ's file) | CJ | `run_conditions` passes `--items-file ~/kiln-items.jsonl`, `--tier-prices` and `--budget` (frozen files); `[caps]` set from the dry run |
| Dry run on 5 dev items with the real agents and real Gemini | CJ, Adhi | `python -m kiln.runners.conditions --split dev --all-conditions --seed 0 --model gemini-3.8-flash --items-file ~/kiln-items.jsonl --limit 5 ...`; then a night-runner dry run that survives kill and restart |
| `dev` merged into `main` at the freeze | Adhi | After the protocol hash |

## 2. Put the frozen code on the GB10 (laptop → GB10)

```bash
cd D:/Adhit/Downloads/kiln && git pull && git bundle create kiln.bundle dev && scp kiln.bundle gb10:kiln.bundle
ssh gb10 'cd ~/kiln && git fetch origin && git checkout dev && git reset --hard origin/dev && git log -1 --oneline'
```

The printed commit must be the frozen one (the commit whose protocol hash was posted).

## 3. Keys and webhooks on the GB10 (once; hidden input, never printed)

On the GB10 (`ssh gb10`), for each name, paste the value only when asked:

```bash
for v in GEMINI_API_KEY KILN_ALERT_WEBHOOK KILN_PREREG_WEBHOOK; do read -rsp "$v: " x && echo && echo "export $v='$x'" >> ~/.bashrc; done; unset x
```

- `GEMINI_API_KEY`: the team's AI Studio key (optionally also `GEMINI_API_KEY_2`).
- `KILN_ALERT_WEBHOOK`: the `kiln-night-runner` Discord webhook (progress, failures, heartbeats).
- `KILN_PREREG_WEBHOOK`: where the prediction hash is posted (OPEN-16; the same webhook unless the team chose a separate channel).

## 4. Launch (7:30 PM)

```bash
ssh gb10
nvidia-smi                               # nothing else running
tmux new -s night2
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True && source ~/.bashrc && source ~/alchemi/venv/bin/activate && cd ~/kiln
python -m kiln.night run src/kiln/night/plans/night2.toml --dry-run    # shows the steps; nothing runs
python -m kiln.night run src/kiln/night/plans/night2.toml
```

Detach with **Ctrl+B, then D**; the run keeps going. Re-attach any time with `ssh gb10` then `tmux attach -t night2`.

## 5. Watching it (until 2 AM, then phone alerts)

- `#kiln-alerts` gets a heartbeat every 30 minutes and a message on any failure. Turn on phone notifications for that channel.
- Progress: `ssh gb10 'ls ~/kiln/runs; tail -5 ~/kiln/runs/_night/night2/alerts.log'`.
- **If it stops** (failure alert, no heartbeat for 60 minutes, or a GB10 reboot): `ssh gb10`, `tmux attach -t night2` (or `tmux new -s night2` after a reboot, plus `bash ~/kiln/env/gb10/tailscale.sh`), and rerun the same `python -m kiln.night run ...` command. Finished steps and finished items are skipped.
- **Expected failures, not emergencies:** `fetch_labels`, `score` and `figures` are not built yet and fail loudly by design; `push` fails because the GB10 has no GitHub access. The predictions, manifest and posted hash are what must succeed tonight.
- Never copy label files to the GB10; the runner refuses to start if labels are present.

## 6. Sunday morning: bring results back and push

```bash
cd D:/Adhit/Downloads/kiln
scp -r gb10:kiln/runs gb10:kiln/protocol/predictions.manifest.json gb10:kiln/protocol/posts.jsonl .   # into the matching folders
git add runs protocol && git commit -m "night2: predictions, manifest and posted-hash receipt" && git push
```

Then Hemanath scores on his machine (labels never leave it), after checking the posted hash matches the manifest (plan §8, Sunday 8 AM). `python -m kiln.compute.accounting runs/<run>...` gives the compute-allocation table.

## 7. Capacity (filled in from the profiling rerun)

- Main run: 346 held-out items x 4 conditions x 3 seeds = 4,152 item runs.
- Per-item worst case and whether it fits one GB10 overnight: *see `protocol/prices_proposal.json` after the rerun*. If it doesn't fit: fill the relaxation cache for held-out pairs before 7:30 PM (cache hits are still charged in full, so fairness is unchanged), add Brev workers, or drop to 2 seeds (the plan's cut list).
