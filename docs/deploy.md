# Deploying the Kiln triage app

The app (`app/server.py` + `app/index.html`) has three panels: **01 Preparation** (pick two precursors,
temperature, duration, condition, seed), **02 Live triage** (agent decisions and compute requests unfold
step by step, with the phases involved and the reaction energy at each compute tier), and **03 Results**
(prediction, p_react, ΔE MLIP vs Materials Project, cause and fix, review flags, compute used).

Two modes:
- **Replay (default):** RUN TRIAGE on any recorded pair replays the real Night 2 run (GB10 `runs/`, H100
  `runs-h100/`). Needs **only Python 3.10+ and its standard library**: no packages, no GPU, no keys,
  no labels. A run whose compute log contains a stub result is never shown.
- **Live (optional):** a pair that isn't recorded runs once through the real agents and compute.
  Only when the server has all three: `KILN_LIVE=1`, `GEMINI_API_KEY`, and `KILN_COMPUTE_BACKEND=local`
  (plus the Python environment from `uv sync`, the Materials Project cache in `cache/mp/`, and ideally
  a GPU; relaxations take seconds to minutes each). Otherwise the page says "Live mode is off".

Temperatures and durations for recorded pairs come from the agent-visible items file if the server
has one (`KILN_ITEMS=/path/kiln-items.jsonl`, or `kiln-items.jsonl` in the repo root or home folder;
it is never committed). Without it, replay still works and the temperature shows as "not recorded".

## Option A: any Linux VM (Brev or Nebius), no Docker (recommended)

Replay only, on the smallest CPU instance:

```bash
git clone https://github.com/Adhithyan245/kiln.git && cd kiln
PORT=8080 nohup python3 app/server.py > app.log 2>&1 &
curl -s localhost:8080/api/status   # {"live": false}
```

Then expose port **8080**:
- **Brev:** add a public port / tunnel for 8080 on the instance page (or `brev port-forward <instance> -p 8080:8080` from a laptop for a private link).
- **Nebius:** allow inbound TCP 8080 in the VM's security group, then open `http://<public-ip>:8080`.

While the repo is private, clone with a GitHub token that has read access, or copy the repo with `scp`.

### Turning on live mode (GPU instance)

```bash
cd kiln && uv sync                               # the kiln package, MACE, pymatgen
# put the MP cache at cache/mp/ (kiln_mp_cache.tar.gz, manifest e1243496...) and the items file in place
export KILN_LIVE=1 KILN_COMPUTE_BACKEND=local     # GEMINI_API_KEY from a secret, never in a file in the repo
read -rsp "GEMINI_API_KEY: " GEMINI_API_KEY && export GEMINI_API_KEY && echo
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
PORT=8080 nohup uv run python app/server.py > app.log 2>&1 &
curl -s localhost:8080/api/status   # {"live": true}
```

Live runs use the frozen settings (`protocol/frozen_settings.json`) and `gemini-3.8-flash`, write to a
temporary folder, and are not part of the experiment's results.

## Option B: Docker (replay only)

```bash
git clone https://github.com/Adhithyan245/kiln.git && cd kiln
docker build -f app/Dockerfile -t kiln-app .
docker run -d -p 8080:8080 --name kiln-app kiln-app
```

The image copies `runs/` and `runs-h100/` at build time, so rebuild after new results are pushed.

## Option C: Nebius Serverless AI endpoint (managed HTTPS, what the demo link uses)

```bash
export NEBIUS_PROJECT_ID=<project> KILN_REGISTRY=cr.<region>.nebius.cloud/<registry id>
export KILN_ITEMS=~/kiln-items.jsonl            # optional; never committed, baked only into the private image
bash env/nebius/deploy_app.sh [COMMIT]           # default HEAD
```

`env/nebius/deploy_app.sh` builds `env/nebius/Dockerfile.replay` from `git archive COMMIT` (committed code and
runs only), refuses an image that isn't in replay mode, pushes it to the Nebius registry as `:<commit>` and
`:live`, then restarts the `kiln-triage` endpoint (which pulls `:live`) or creates it on a small CPU
(`cpu-d3`, 2 vCPU) the first time. The `https://…nebius.cloud` URL stays the same across redeploys, so
**redeploying after new results or a new UI is one command**. Registry auth goes through
`docker-credential-nebius` and your CLI sign-in; no token is handled. After judging,
`bash env/nebius/teardown.sh --vm kiln-app --registry kiln` removes the endpoint, the VM and the registry
(it asks before each delete). Nebius public IPs pass port 80 but not 8080, which is why the backup VM serves on 80.

## Option D: Render free web service (replay plus the recipe finder, after the hackathon)

`render.yaml` describes the service, and `env/render/Dockerfile` builds it: Python 3.12, pymatgen, and the
committed energies-only cache `data/mp-energies` (23 MB) for the recipe finder's screen. Live mode and the
MACE check stay off.

1. Sign in at https://render.com with GitHub and allow it to read `Adhithyan245/kiln`.
2. **New > Blueprint**, pick the repository, and apply. It builds from `main` and redeploys on every push.
3. The link is `https://kiln-<suffix>.onrender.com`; `/api/status` should report `"recipe": true`.

Free instances have 512 MB of memory (the app uses about 270 MB after several recipe searches) and sleep
after 15 minutes without traffic; the first request after that takes about 30 seconds.

## Updating with new results

Results land on `dev` as `runs-h100/` (H100) and `runs/` (GB10 rerun). For Option A, `git pull` is enough:
the server re-reads the run folders on every request. For Option C, rerun `bash env/nebius/deploy_app.sh`.

## Checks before sharing the link

- The page loads with the three panels; `/api/status` reports the mode you expect.
- RUN TRIAGE on a recorded pair replays it; the results panel shows "GB10 (DGX Spark)" or "H100 (ALCHEMI Toolkit)".
- The compute steps show real models (`medium-mpa-0`) or `materials project`, never `stub`.
