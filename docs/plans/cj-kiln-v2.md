# Kiln build plan: branch `cj/kiln-v2`

Status: **plan only, nothing implemented.** Branch `cj/kiln-v2` is cut from local `dev` at `f8b8ec8`.

Goal of this branch: **better code plus the add-ons, while still merging cleanly into `dev`.** So the interfaces on `dev` (`docs/interfaces.md`, `src/kiln/schemas.py`) are the contract this branch builds against. Where the pasted brief disagrees with them, `dev` wins for the core and the brief's extras come in as add-ons (§B). The conflicts are still listed in §0 because the team has to settle them before the add-ons can be used in experiment runs.

## A. Merge-clean rules for this branch
1. **New files over edits.** New behaviour goes in new modules. Files owned by others (see `AGENTS.md`) are not edited here. If one needs a hook, the hook is a small, separate commit that the owner can review or cherry-pick.
2. **Schema changes are additive only:** new optional fields, new `Literal`/enum members, never a rename or removal. Each goes in its own commit that also updates `docs/interfaces.md`, so it can be cherry-picked to `dev` once the team says yes.
3. **Add-ons are off by default.** They are enabled per run through `RunConfig` or a registry. With every add-on off, a run on this branch behaves exactly as on `dev`. That keeps rule 11 intact until the team agrees otherwise.
4. **Sync often:** merge `dev` into this branch at least before each gate; run the full test suite after each merge. (Note: `git fetch` failed from this shell with an SSH key error for the `github-new` remote alias, so the local `dev` may be behind. Hemanath already has remote branches for data, baselines, verifier, scoring, evaluator, B1 and protocol.)
5. **Hard rules never relax in the branch:** labels, no outcome lookups, no agent web access, no secrets, no push to `main`, GB10 rules, LLMs never set numbers, all compute through the budget, failures always visible.
6. **Pushing:** this branch is pushed only when you say so. Merging into `dev` happens by PR or by the team's usual route, not by force.

## B. Add-ons (all behind flags, all additive)
Order is the brief's. Each starts only after Gate 1 is met on the core.

| # | Add-on | Where it lives | Schema change needed | Hook needed in someone else's file |
|---|---|---|---|---|
| B1 | **Glass & MD** (NVT Langevin with MACE-MPA-0) as a compute tier `md_nvt`, used by a Glass agent for melt/amorphous precursors | `src/kiln/compute/tiers_md.py` (B), `src/kiln/addons/glass.py` | `ComputeTier += md_nvt`, `AgentName += glass`, `Artifact.type += glass_report` | Runner agent list (Adhi): agent registry instead of a hard-coded list |
| B2 | **Skeptic**: reads accepted artifacts, posts a `challenge_claim` need naming the cheapest computation that would test the claim's `falsified_if`; never writes numbers | `src/kiln/addons/skeptic.py` | `AgentName += skeptic`, `NeedType += challenge_claim` | Same registry; need-answerer table in `interfaces.md` |
| B3 | **Claude replication** (~120 held-out pairs, 1 seed) | `src/kiln/addons/llm/claude.py`, a provider adapter | None (`RunConfig.model` already exists) | `agents/base.llm_call` (Adhi) must pick the provider from `RunConfig.model` |
| B4 | **Fix check** | — | — | Not designed: the brief does not say what it checks (§0 #14) |
| B5 | **GPU timing table** A6000 / H100 / GB10 → `results/hardware.json` | `src/kiln/compute/bench.py` (B) | None | None |
| B6 | **Second MLIP** for disagreement flags (from the Nebius Scientific Platform) | `src/kiln/compute/tiers.py` setting `model=` (B), `src/kiln/addons/mlip_disagreement.py` | `ReviewReason` stays `conflict`; detail string names the models | `review.flags` (Annamayya) gets extra flag producers through a registry |

Every add-on gets its own tests, and each one has a "flag off gives the `dev` result exactly" test on the 5-pair fixture.

Today is **Saturday 31 Oct**. Gate 0 ("Fri ~1 AM") has already passed on the calendar, so §5 should be checked against what actually exists before anyone starts work.

---

## 0. Conflicts and ambiguities to resolve first

Ranked by how much they block. Each line gives the plan's default and the decision still needed.

| # | Brief says | Repo (`AGENTS.md` / interfaces) says | Plan default | Decide |
|---|---|---|---|---|
| 1 | B0/B0-T scored "on dev"; "tune only on dev pairs" | Hard rule 1: only `evaluate.py` reads labels, and only after the hash is posted | Two label files: `labels/dev.jsonl` and `labels/heldout.jsonl`. `evaluate.py --split dev` returns **aggregate metrics only**, needs no hash, and is the only way to tune. `--split heldout` requires a posted hash. | Team agrees, and `AGENTS.md` rule 1 is amended to allow it |
| 2 | Night 1 relaxations on **Nebius H100 + Brev**; GPU timing on A6000/H100/GB10 | Compute runs on the **GB10**, with Brev as the same-API backup; Nebius not mentioned | GB10 primary, Brev backup. Nebius only as a third backend behind the same `client.request` API, and only if it is actually provisioned | Is Nebius in or out? |
| 3 | Add-ons: Glass & MD, Skeptic | Rule 11: no Glass/MD, no additional agents | Built in this branch as flagged add-ons (§B); off in experiment runs | Team agrees to turn them on |
| 4 | Gemini 3 seeds, **Claude replication ~120 pairs**, OpenAI fallback | Rule 11: "Experiment runs use the Gemini key only" | Gemini for the main runs. Claude adapter built as add-on B3; run only with team sign-off | Is the Claude replication allowed? |
| 5 | Layout `ingest/`, `conditions/c1..c4/`, `runner/`, `agents/<name>/` | `data/`, `runners/conditions.py`, `agents/<name>.py`, `night/` | Keep the repo layout | None: repo wins |
| 6 | App contract `runs/<condition>/<seed>/{candidates,pairs,artifacts/*,provenance}.json` | `runs/<run_id>/{config.json, board/*.jsonl, predictions.jsonl, …}` | Keep the repo layout, add `runs/index.json` (run_id → condition, seed, split, model), and map field names (§2.6) | Adhi confirms before the app freezes |
| 7 | Artifact fields `id, summary, numbers, evidence, falsified_if` | `artifact_id, values, claims[{statement, evidence, falsified_if}]` | Schema wins; the mapping is in §2.6 | None |
| 8 | Role B owns the **Thermo agent** | `thermo.py` belongs to Annamayya (C); B owns compute and `tools/mp.py` | Follow `AGENTS.md` | None |
| 9 | Budget = "identical tool-call and token caps" | `RunConfig`: compute units are "the ONE primary locked budget", plus tool and token caps | All three caps, per item, identical across C1–C4 | None |
| 10 | Install `nvalchemi-toolkit[cu13,mace,ase]` unpinned, Python 3.12 | CJ prompt: NVIDIA kit lock file, Python 3.12.16 | Lock file. Unpinned install only as the documented fallback | None |
| 11 | Hash "the prediction file" | 4 conditions × 3 seeds = 12 `predictions.jsonl` | Hash a **manifest** (`protocol/predictions.manifest.json`, sha256 of every prediction file) and post the manifest's hash once | Hemanath confirms |
| 12 | "Agent processes never mount" labels | All work happens under one Unix user on one VM | Labels are **not on the run VM** until the hash is posted; see risk R1 | Where do labels live overnight? |
| 13 | `harness/` reusable comparison skill, `paper/`, `demo/` | Not in the ownership table | Deferred; no owner | Owner, or cut |
| 14 | "fix check" add-on | `Prediction.fix` exists; no check is defined | Undefined, so not planned | What is it? |
| 15 | — | `ConditionId` includes `B1`, `N1`, `N2` | Assumed: B1 = Hemanath's rule baseline, N1/N2 = night smoke runs | Confirm meaning |
| 16 | Hold out 9 precursors with a "fixed seed" | Prompt: "spread across element groups" | Stratified draw with a fixed seed; the strata are written into the protocol | Hemanath picks the strata |
| 17 | Edison jobs in Night 1 | Edison not in `AGENTS.md` | Edison is a **human-reviewed** offline input to `data/precursor_props.csv` (C), not a night-runner step | Confirm |

Sanity check on the split numbers: 1,035 = C(46, 2), so every pair appears once. Pairs with both precursors in dev = C(37, 2) = **666**, and pairs touching at least one held-out precursor = 1,035 − 666 = **369**. The brief's numbers are consistent, assuming Hemanath confirms one record per pair.

---

## 1. Module map

All models come from `src/kiln/schemas.py`. "Offline" means the module runs with no network, given a warm `cache/`.

### A: Evaluation (Hemanath)
| Module | Responsibility | Public API |
|---|---|---|
| `kiln.data` | Load the ledger, strip labels, build the split, produce agent-visible items | `strip_labels(raw: Path, out_dir: Path) -> LabelStripReport` (counts only, never values) · `make_split(precursors: list[str], seed: int, n_holdout: int = 9) -> SplitManifest` · `load_items(split: Literal["dev","heldout"]) -> list[Item]` |
| `kiln.provenance` | One provenance record per item (source file, record index, fields used) | `provenance(item_id: str) -> Provenance` *(new model: needs a schema commit)* |
| `kiln.baselines` | B0 driving-force threshold, B0-T Tammann rule, B1 | `b0(item, mp: PhaseCache) -> Prediction` · `b0_t(item) -> Prediction` · `b1(...) -> Prediction` |
| `kiln.verifier` | Deterministic gate, no LLM | `verify(a: Artifact, board: Board, budget: BudgetView) -> tuple[VerifierStatus, str]` |
| `kiln.scoring.score` | Fixed rules turning evidence into a prediction | `provisional(item, accepted: list[Artifact]) -> tuple[float, Category]` · `score(item, accepted, requests: list[ComputeRequest], flags: list[ReviewFlag], cfg: RunConfig) -> Prediction` |
| `kiln.scoring.evaluate` | The only label reader | `hash_predictions(paths: list[Path]) -> Manifest` · `post_hash(manifest, webhook_env="KILN_PREREG_WEBHOOK") -> PostReceipt` · `evaluate(split, manifest, receipt) -> Results` (refuses heldout without a matching receipt) |

### B: Compute (CJ)
| Module | Responsibility | Public API |
|---|---|---|
| `kiln.tools.mp` | Materials Project phases near the hull, cached per chemical system | `fetch_chemsys(chemsys: str) -> None` (online, Night 1 only) · `phases(chemsys: str, ehull_max_ev: float = 0.100) -> list[Phase]` (offline) · `reaction_energy(species: list[str], products: list[str] \| None = None) -> ReactionEnergy` (pymatgen `InterfacialReactivity` or a balanced reaction, eV/atom) |
| `kiln.compute.accounting` | Frozen prices, cache keys | `price(tier: ComputeTier) -> float` · `cache_key(tier, inputs: dict, settings: dict) -> str` (sha256 of canonical JSON) |
| `kiln.compute.cache` | Content-addressed result store under `cache/compute/` | `get(key: str) -> dict \| None` · `put(key: str, result: dict) -> None` (atomic write: temp file then rename) |
| `kiln.compute.convergence` | Convergence tests | `converged(fmax_ev_a: float, smax_ev_a3: float, f_tol: float, s_tol: float) -> bool` |
| `kiln.compute.tiers` | Physics for each tier (runs on the GPU host) | `run(tier, inputs, settings) -> TierResult` with `status`, `result`, `gpu_seconds` |
| `kiln.compute.service` | A small HTTP service on the GPU host with one GPU worker queue | `POST /request`, `GET /healthz`. Standard-library `http.server`; no web framework |
| `kiln.compute.client` | The only door to compute. It charges, logs and calls a backend | `request(item: Item, agent: AgentName, tier: ComputeTier, reason: str, inputs: dict, budget: Budget) -> ComputeRequest` · `healthy() -> bool`. Backend chosen by `KILN_COMPUTE_BACKEND = stub \| local \| http` |
| `kiln.night` | Night 1 and Night 2 runners (§4) | `python -m kiln.night {night1,night2} --plan <yaml> [--dry-run]` |

Inside `client.request` the order is fixed: **charge (raises `BudgetExceeded`) → compute cache key → cache hit returns `cached` → otherwise call the backend → write to cache only if `ok` → append `ComputeRequest` to `compute_requests.jsonl`.** Failed and not-converged results are logged and never cached as `ok`.

### C: Chemistry (Annamayya)
| Module | Responsibility | Public API |
|---|---|---|
| `kiln.tools.tammann` | ⅔·T_m in kelvin, returned in °C | `tammann_c(melting_point_c: float) -> float` |
| `kiln.tools.precursors` | Lookups into the cited precursor table | `props(formula: str) -> PrecursorProps` (unknowns explicit) |
| `kiln.agents.thermo` / `kinetics` / `precursor` | Specialists. The LLM picks actions; numbers come from tools | `class Thermo(Agent): def step(self, item, board, budget) -> list[Artifact \| Need]` (the same for each) |
| `kiln.review` | Review flags and disagreement text | `flags(item, accepted, requests) -> list[ReviewFlag]` · `disagreements(accepted) -> list[str]` |

### D: Integration and product (Adhi)
| Module | Responsibility | Public API |
|---|---|---|
| `kiln.board` | Append-only need board (§2) | `Board(run_dir)`, with `post_artifact`, `post_need`, `open_needs`, `claim`, `fulfill`, `decline`, `accepted_artifacts` |
| `kiln.budget` | Per-item caps for tool calls, tokens, compute units and USD | `Budget(cfg: RunConfig, item_id: str)`, with `charge_tool_call()`, `charge_tokens(i, o)`, `charge_compute(units)`, `remaining() -> Cost`, `spent() -> Cost`. Raises `BudgetExceeded` |
| `kiln.agents.base` | Agent ABC and the LLM wrapper that counts tokens | `class Agent(ABC): name: AgentName; def step(...)` · `llm_call(prompt, tools, budget, seed) -> LLMResponse` (charges tokens from the provider's usage metadata) |
| `kiln.agents.single` / `planner` | C1 and C3 comparators | Same `step` signature |
| `kiln.runners.conditions` | Runs one condition × seed × split | `run(cfg: RunConfig, items: list[Item]) -> Path` |
| `app/` | Kiln Triage (Streamlit), reading `runs/` and `results/` only | — |

The LLM never sees a tool that returns a number it can then write into `values`. Agents fill `values` only by copying tool outputs **in code**. The verifier re-checks each number against the cited `ComputeRequest.result` or tool output (rule 7).

---

## 2. Need-board protocol

### 2.1 Files (per run)
```
runs/<run_id>/board/
  artifacts.jsonl   # one Artifact per line, written once, with its final verifier status
  needs.jsonl       # need posts AND status events (append-only; current state is a fold)
  board.lock        # file lock (filelock package: works on Windows and Linux)
```
`Need.status` cannot be updated in place in an append-only file, so `needs.jsonl` holds **events**:

```json
{"event":"post","need":{...Need...},"ts":"..."}
{"event":"claim","need_id":"r1:need:3","agent":"thermo","ts":"..."}
{"event":"fulfill","need_id":"r1:need:3","artifact_id":"r1:thermo:7","ts":"..."}
{"event":"decline","need_id":"r1:need:3","agent":"thermo","reason":"budget_exhausted","ts":"..."}
```
A need's state is the fold of its events in file order. **Claim rule:** while holding the lock, read the state; if it is `open`, append `claim`. The first claim in the file wins, and the two-process race test checks this.

### 2.2 JSON Schemas
Generated from Pydantic, not written by hand: `python -m kiln.schemas --export protocol/schemas/` writes `Artifact.json`, `Need.json`, `BoardEvent.json`, `ComputeRequest.json` and `Prediction.json`. They are hashed with the protocol. Abbreviated:

```json
{"$id":"Need","type":"object",
 "required":["need_id","run_id","item_id","type","from_agent","payload"],
 "properties":{
  "need_id":{"type":"string","pattern":"^.+:need:\\d+$"},
  "type":{"enum":["firm_up_energy","decomposition_products","reaction_energy"]},
  "from_agent":{"enum":["thermo","kinetics","precursor","single","planner"]},
  "payload":{"type":"object"},
  "status":{"enum":["open","claimed","fulfilled","declined"]}}}

{"$id":"Artifact","type":"object",
 "required":["artifact_id","run_id","item_id","agent","type","values","claims","compute_requests","verifier"],
 "properties":{
  "type":{"enum":["reaction_report","kinetics_report","precursor_report"]},
  "values":{"type":"object","propertyNames":{"pattern":"_(ev_per_atom|c|k)$|^decomposition_product$"}},
  "claims":{"type":"array","minItems":1,"items":{"required":["cause","statement","evidence","falsified_if"],
            "properties":{"falsified_if":{"type":"string","minLength":1}}}},
  "cites":{"type":"array","items":{"type":"string"}},
  "fulfills_need":{"type":["string","null"]},
  "verifier":{"enum":["accepted","rejected","inconclusive"]}}}
```
Payload schemas for each need type follow the `docs/interfaces.md` table and are checked by the verifier.

### 2.3 Lifecycle
1. **Post:** an agent returns `Need` objects from `step()`. The board drops duplicates, meaning the same `(item_id, type, canonical payload)` while one is still open or fulfilled. Limit: 2 new needs per agent per round.
2. **Claim:** at the start of its turn, each agent calls `open_needs(item_id, types=<types it answers>)` and claims at most one. Answerers are fixed by the table in `docs/interfaces.md`.
3. **Fulfill:** the claimer posts an artifact with `fulfills_need=<id>`. The board appends `fulfill` **only if the verifier accepted** that artifact. If it was rejected or inconclusive, the need goes back to `open` and can be claimed again next round.
4. **Decline:** if the budget is exhausted or the request is out of scope, the agent appends `decline` with a reason. `review.flags` turns declined and still-open needs into `missing_evidence`.

### 2.4 Rounds
`coordination_rounds = 3` (`RunConfig`). Each round, every agent calls `step()` once, in a fixed order (`precursor → thermo → kinetics`). The order is part of the protocol and is not shuffled by seed, so seed effects come only from the LLM. A need posted in round *r* can be claimed in round *r* or later. After the last round all open needs are declined (`rounds_exhausted`), then flags and scoring run. The run also stops early when a round posts no new need and no new artifact.

### 2.5 Where the verifier sits
`Board.post_artifact(a)` calls `verifier.verify(a, board, budget.view())` **before** appending, sets `a.verifier` and `a.verifier_notes`, then appends the artifact once. Rejected artifacts are still written (rule 9) and also go to `verifier.log`. `accepted_artifacts()` and the scoring call see only `accepted`. A citation is valid only if it points to an artifact that was already accepted, which prevents cycles. The verifier is pure, deterministic code, so replaying a board reproduces the same verdicts; this is a test.

### 2.6 Mapping to the app contract (brief → repo)
`id`→`artifact_id` · `summary`→`claims[0].statement` · `numbers`→`values` · `evidence`→`claims[].evidence` + `cites` · `falsified_if`→`claims[].falsified_if` · `verifier status`→`verifier` · `fulfills_need`→`fulfills_need` · `cost`→`cost`. `pairs.json` → `predictions.jsonl` + `load_items`. `candidates.json` → `cache/mp/<chemsys>.json` exported to `results/candidates/`. `provenance.json` → `kiln.provenance`. **The app never reads `cache/` directly.** Night 2 exports what the app needs into `results/`.

---

## 3. Condition runner (fairness)

`kiln.runners.conditions.run(cfg, items)`. One function, one code path; the condition only changes which agents run and whether `post_need` is enabled.

| | Agents | Board needs | Who chooses compute |
|---|---|---|---|
| C1 single | `single` (every tool and tier) | Off | The single agent |
| C2 isolated | thermo, kinetics, precursor | **Off**: `post_need` is logged as `need_suppressed`, never delivered | Each specialist for itself |
| C3 planner | `planner` + specialists as callees | Off between specialists; the planner assigns work | The planner |
| C4 Kiln | thermo, kinetics, precursor | On | Each specialist, through needs |

**Shared, so the comparison is fair:**
- The same `Item` list, tool registry (`kiln.tools.*`), compute client and backend, `cache/` (warmed by Night 1), verifier, `review.flags` and `score.score`.
- **One `Budget` per item for the whole condition.** Every agent in that condition draws from the same pool, including the C3 planner's own LLM tokens. Caps come from `RunConfig` (`max_tool_calls_per_item`, `max_tokens_per_item`, `max_compute_units_per_item`), are frozen in the protocol, and are identical for C1–C4.
- Cache hits are charged the frozen tier price (rule 8), so condition **order does not matter**. Measured `gpu_seconds` is reported only.
- Tool calls are charged whether the tool is a cache read or not. A tool call is any call into `kiln.tools.*` or `compute.client`. LLM calls are charged as tokens, not tool calls.
- When the budget runs out mid-item, the runner stops that item's agents, scores what was accepted, and records `missing_evidence`. The item is never skipped.

**Seeds:** `seeds = [0, 1, 2]`. A seed is passed to the provider as the generation seed where supported, with `temperature` fixed in the protocol. `run_id = f"{condition}-{model_tag}-s{seed}-{split}"`. `config.json` records the git SHA, protocol hash, model id, price table, caps and seed. Items are processed in a fixed sorted order. Parallelism runs across items, with one board per run, and the lock makes it safe.

**Outputs:** `runs/<run_id>/{config.json, board/, compute_requests.jsonl, predictions.jsonl, cost.json, verifier.log}`, plus `runs/index.json`.

---

## 4. Night runner (B, `kiln.night`)

### 4.1 Common machinery
- **Where it runs:** `tmux new -s kiln-night` on the orchestration host. Default: the GB10 home folder, which is where the compute service runs anyway (rule 6: no sudo, venv in `~`). Brev is the fallback host and runs the same code.
- **Plan as a DAG of steps** in `night/<name>.yaml`. Each step has `cmd`, `inputs`, `timeout_s`, `retries`, and `caps`.
- **Resumable:** each step writes `runs/_night/<night>/<step>.done` containing a hash of its inputs. On restart, done steps with matching hashes are skipped. Steps that loop over items (relaxations, condition runs) skip any item whose output already exists, using the cache key or the existing `predictions.jsonl` line.
- **Retries:** exponential backoff with jitter (base 30 s, factor 2, max 3 tries, then the step is marked `failed` with an alert, and the night continues with independent steps). Every subprocess and HTTP call has a timeout.
- **Hard caps,** checked before each unit of work from `runs/_night/spend.json` (summed from `cost.json` and `compute_requests.jsonl`): `max_tokens`, `max_usd`, `max_gpu_hours`. A breach is a **clean stop**: finish the current item, flush, write state, alert. It is never a silent cut.
- **Alerts:** a heartbeat thread posts to `KILN_ALERT_WEBHOOK` every 30 min (steps done, items done per run, spend vs caps, compute `healthy()`), and posts immediately on step failure, cap breach or exit. Webhook failures are logged and never crash the night.
- **Clean shutdown:** a SIGINT/SIGTERM handler sets a stop flag; workers finish their current item. JSONL writes are always a full line flushed under the lock. `atexit` posts a final status.
- **Secrets:** `MP_API_KEY`, `GEMINI_API_KEY`, `KILN_ALERT_WEBHOOK`, `KILN_PREREG_WEBHOOK` and `BREV_*` are read from the environment only (rule 4).

### 4.2 Night 1 (Friday night; may already be partly done)
1. `mp_fetch`: for every chemical system in all 1,035 pairs (dev and held-out; no labels involved), call `tools.mp.fetch_chemsys` → `cache/mp/`. Online, rate-limited, resumable per chemsys.
2. `candidates`: phases within 100 meV/atom of the hull for each pair → `cache/mp/candidates/`.
3. `relax_batch`: pre-warm `single_point` and `bounded_relaxation` for candidate and precursor structures through **`compute.client` with a dedicated `night1-prewarm` budget and log** (rule 8). This is not a back door: experiment runs are still charged when they hit this cache.
4. `known_answer`: `alchemi-mlip-test.py mace_si` must give −5.41238 eV/atom (±1e-4) before step 3 starts. If it fails, step 3 does not run.
5. Edison: **not a night step** (§0 #17).

### 4.3 Night 2 (Saturday night → Sunday)
1. `preflight`: protocol hash file exists and matches `protocol/protocol.md`; `git status` is clean; compute `healthy()`; caps loaded; **the labels directory is absent on this host** (the step fails if it is present).
2. `run_conditions`: C1–C4 × seeds 0–2 on **held-out** items (dev results come from the Saturday 7 PM dry run). Each run is resumable per item.
3. `manifest`: `evaluate.hash_predictions` over every `predictions.jsonl` → `protocol/predictions.manifest.json` + `.sha256`.
4. `post_hash`: post to `KILN_PREREG_WEBHOOK` and save the response (message id, timestamp) to `protocol/posts.jsonl`. If the post fails, scoring is blocked and the runner retries, then alerts.
5. `fetch_labels`: **the only step that brings labels to the host.** It runs only when the receipt exists and the manifest still matches the files on disk. The label source is open (§0 #12).
6. `score`: `evaluate.evaluate("heldout", manifest, receipt)` → `results/comparison.json`, which fills `moved_toward_label`.
7. `figures` → `results/figures/`, plus `results/hardware.json` (from profiling logs).
8. `push`: commit `runs/`, `results/` and `protocol/` (no labels, checked by a pre-commit check), `git pull --rebase`, push to `dev`.
9. `stop_brev`: `brev stop <instance>` if Brev was used. Always attempted in a `finally`.

`--dry-run` runs the same DAG on 5 dev items with the stub backend and a test webhook. That is the Saturday 7 PM rehearsal.

---

## 5. Task list by role and gate

Estimates are focused hours. "✓?" marks Friday-night tasks that may already be done; check before planning further.

### Gate 0: Friday ~1 AM (now overdue on the calendar)
| Role | Task | h |
|---|---|---|
| A | ✓? Ledger download, label strip into two files, precursor split, `load_items`, no-label test | 2.5 |
| A | ✓? B0 / B0-T, dev **aggregate** AUROC through `evaluate --split dev` | 1.5 |
| B | ✓? GB10 environment from the lock file, `env/gb10/setup.sh`, known-answer test | 2 |
| B | ✓? `tools.mp` fetch + cache for all chemical systems, MP2020 correction helper | 2 |
| C | ✓? `tammann_c` + tests; `precursor_props.csv` for 46 precursors with sources | 3 |
| D | ✓? `Board`, `Budget`, `Agent` ABC, two dummy agents exchanging a `firm_up_energy`, claim-race test | 3 |

### Saturday 11 AM: vertical slice (from `AGENTS.md`)
| All | One dev item: agents → `compute.client` (stub or GB10) → verifier → score → evidence card | 2 |

### Gate 1: Saturday 1 PM, all agents pass the verifier on ~60 dev pairs, ≥1 cross-agent need fulfilled
| Role | Task | h |
|---|---|---|
| A | Verifier with the four rejection tests; `score.provisional`; A-Lab demo recipes (1-hour box) | 4 |
| B | Compute service: 4 tiers, charge-before-run, cache, honest statuses, `healthy()`, Brev parity | 4 |
| B | Profiling → price list and per-pair budget proposal | 1.5 |
| C | Thermo / Kinetics / Precursor with written escalation rules; carbonate chain test | 4 |
| D | `runners.conditions` for C1–C4 on 5 items, then 60 | 3 |

### Code freeze: Saturday 7 PM
| Role | Task | h |
|---|---|---|
| A | `score.score`, B1, `evaluate` (hash → post → labels → metrics), `protocol/protocol.md` + hash | 4 |
| B | `kiln.night` + Night 2 `--dry-run` on dev | 3.5 |
| C | `review.flags` (one test per reason), disagreement text, mentor sanity check | 3 |
| D | App on dev outputs, Dockerfile, one Cloud Run deploy | 4 |

### Add-ons (this branch; only after Gate 1 on the core)
Built behind flags per §B; using them in experiment runs still needs team sign-off under rule 11. C3 is already core (the schema comment says so), so it is not an add-on.
| # | Add-on | h |
|---|---|---|
| B1 | Glass & MD: `md_nvt` tier + Glass agent + tests | 4 |
| B2 | Skeptic agent + `challenge_claim` need + tests | 2.5 |
| B3 | Claude provider adapter + replication run config | 1 |
| B5 | GPU timing table (GB10 alone if the others aren't provisioned) | 1.5 |
| B6 | Second-MLIP disagreement flags | 2 |
| — | Registry hooks for agents and flag producers, offered to Adhi and Annamayya | 1.5 |

---

## 6. Test plan (`tests/` mirrors `src/`)

| Area | Tests |
|---|---|
| Units | `tammann_c` known values (T_m 1000 °C → ⅔·1273.15 K − 273.15); °C→K conversion happens in exactly one helper (grep test: no `273.15` outside `kiln/units.py`); value keys must end with a unit suffix |
| Split leakage | No held-out precursor appears in any dev item; dev ∪ held-out = all 1,035; counts are 666 / 369; the split is stable under a fixed seed |
| Label isolation | `Item` has no label fields (introspection); importing any `kiln.*` module except `scoring.evaluate` never opens `labels/` (monkeypatched `open`); heldout `evaluate` refuses without a matching receipt |
| Verifier | Rejects: missing `falsified_if`, fake citation, number mismatched with the cited request result, over-budget artifact, wrong unit key, label-field read; accepts a clean artifact; deterministic on replay |
| Scoring | Golden cases: fixed inputs give fixed `p_react` and category; flags pass through; no LLM import in `kiln.scoring` |
| Budget | Each charge type hits its cap and raises; a cache hit is charged the full tier price; C3 planner tokens count; the per-item pool is shared across agents |
| Board | Claim race with two processes and one winner; fold reproduces state; duplicate need dropped; rejected fulfillment re-opens the need |
| Compute | Cache key is stable under dict ordering; `not_converged` is never cached as `ok`; stress criterion is enforced (a cell relaxation with forces converged but stress not converged gives `not_converged`); stub backend parity |
| Night | Resume skips done steps; a cap breach gives a clean stop; scoring blocked without a receipt; preflight fails when labels are present |
| End to end | **Fixture: 5 dev pairs** (`tests/fixtures/pairs5/`), with a frozen MP cache snippet, stub compute results and recorded LLM responses (replayed, no network). The run produces valid `Prediction`s for C1–C4 and a renderable evidence card. Choose the 5 to include a carbonate, a borderline driving force, a failed relaxation and a needs-conflict case. Chosen by **chemistry only, never by label** |

CI: `pytest -q` with no network and no GPU (stub backend, recorded LLM).

---

## 7. Risks, ranked

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Label leakage.** One VM and one user, so "never mount" is not enforceable by permissions; tuning on dev needs dev labels | Labels stay off the run host until `fetch_labels` (§4.3). Dev metrics come only as aggregates from `evaluate --split dev`. Preflight fails if `labels/` exists. Grep test for label field names outside `evaluate.py` |
| R2 | **LLM volume and cost for Night 2.** Held-out only: 369 × 4 × 3 = 4,428 item-runs × up to 40k tokens ≈ 177 M tokens, plus rate limits | Measure tokens per item and throughput in the 7 PM dry run; set `max_usd` and concurrency from that; order runs so that one seed of every condition finishes first (C4 s0, C1 s0, C2 s0, C3 s0, then s1…) so a partial night is still a valid comparison |
| R3 | **Compute service not ready, or GB10 unavailable,** blocking everyone | Stub backend from hour 0; `cached_lookup`-only path still gives a full prediction; Brev with the same API; Night 1 pre-warm makes Night 2 mostly cache hits |
| R4 | **MLIP vs MP energy mismatch.** MP2020 corrections apply to GGA/GGA+U `ComputedEntry` objects; applying them to MACE energies needs the right `parameters` (run type, Hubbard U), or the comparison is wrong | One helper (`tools.mp.to_mp_compatible_entry`) with a test against an MP entry recomputed by MACE; review-flag threshold for MLIP − MP frozen from dev profiling |
| R5 | **Fairness disputes** (C3 overhead, cache warmth, C1 having all tools) | One per-item pool; cache hits charged; caps identical and frozen; every charge logged, so the audit is reproducible |
| R6 | **Non-convergence floods review flags** | Step cap and tolerances set from profiling; report the flag rate per tier; flags never dropped (rule 9) |
| R7 | **Brief and repo drift** (layout, contract, scope) | Resolve §0 before coding; schema changes only through a commit that updates `schemas.py` and `interfaces.md` together |
| R8 | **Concurrent JSONL writes,** Windows dev machines vs Linux hosts | `filelock` (cross-platform), one writer per line, a validator (`python -m kiln.schemas --check runs/`) in preflight |
| R9 | **Pre-registration post fails** (webhook down) | Retry with backoff; scoring blocked until a receipt exists; receipt saved in the repo |
| R10 | **Scope creep** (Glass, Skeptic, second MLIP) | Rule 11; add-ons need explicit sign-off in Discord |

---

## 8. Instructions for future sessions

`CLAUDE.md` already imports `AGENTS.md` and says not to add rules there, so the right change is an **amendment to `AGENTS.md`** (a shared file: tell the team first). Proposed additions, to merge into the existing sections:

```markdown
## Hard rules — amendments
1a. Labels live in two files, `labels/dev.jsonl` and `labels/heldout.jsonl`, never on the run host
    before the prediction hash is posted. Dev labels are reachable only through
    `kiln.scoring.evaluate --split dev`, which prints aggregate metrics and nothing per item.
    Held-out evaluation refuses to run without a saved post receipt whose hash matches the
    predictions manifest on disk.
12. The split is by precursor: 9 of 46 held out (fixed seed, strata in protocol/). Tune only on dev.
    No held-out precursor may appear in any dev item; a test enforces this.
13. Pre-registration has two hashes: `protocol/protocol.md` at code freeze, and
    `protocol/predictions.manifest.json` before scoring. Both are posted to `KILN_PREREG_WEBHOOK`,
    with the receipts saved in `protocol/posts.jsonl`.
14. C1–C4 share one code path, tool registry, compute client, cache, verifier and scoring function,
    and one per-item budget pool (tool calls, tokens, compute units) with frozen identical caps.
    Planner tokens count. Cache hits are charged.

## How we build — additions
- Everything must run offline from `cache/`. Tests use the stub compute backend
  (`KILN_COMPUTE_BACKEND=stub`) and recorded LLM responses; CI needs no network or GPU.
- Units: eV/atom internally, meV/atom on display; °C in data; K only inside calculations, through
  one helper. Value keys carry their unit suffix.
- Variable-cell relaxations must use force AND stress criteria and a hard step cap.
- Apply the MP2020 correction (through the one helper in `kiln.tools.mp`) before comparing
  ALCHEMI and Materials Project energies.
- Night runs live in tmux, are resumable from done-markers and the cache, retry with backoff,
  respect hard caps on tokens, USD and GPU-hours, alert to `KILN_ALERT_WEBHOOK` every 30 minutes
  and on failure, and shut down cleanly.
- Secrets come from the environment only: MP_API_KEY, GEMINI_API_KEY, KILN_ALERT_WEBHOOK,
  KILN_PREREG_WEBHOOK, BREV_*.
```

---

## What I need from the team before any code
1. Decisions on §0 items 1, 2, 4, 11, 12 (these block design), then 3, 13, 14, 15, 16, 17.
2. Which Gate 0 items are actually done (§5 ✓? rows).
3. Whose task to start first. If this session is CJ's (B), I suggest the compute client with the stub backend plus `accounting` and `cache`: it unblocks C and D for the 11 AM slice.
