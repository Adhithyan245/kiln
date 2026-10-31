# Adhi — D, Integration & Product

You're helping Adhi build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/board/`, `src/kiln/agents/base.py`, `src/kiln/agents/single.py`, `src/kiln/agents/planner.py`, `src/kiln/runners/`, `src/kiln/budget.py`, `app/` and their tests. Before each task, write a short plan and wait for my OK.

## Task 1 (Friday night): need board and budget
`kiln.board.Board` and `kiln.budget.Budget` per `docs/interfaces.md`. Append-only JSON Lines; `claim()` safe under concurrent claims (file lock). `Budget` charges tool calls, tokens and compute units and raises `BudgetExceeded`. Add `kiln.agents.base.Agent` with abstract `step(item, board, budget)`, and two dummy agents exchanging one `firm_up_energy` need.
**Done when:** `pytest tests/board tests/test_budget.py` passes, including a two-process claim race with one winner.

## Task 2 (Saturday morning): vertical slice, then the runner
First, with the team, push **one** development item through every step in `docs/interfaces.md` using whatever pieces exist (stubs are fine). Then `kiln.runners.conditions.run` for C1, C2, C3 and C4: same budget, same compute client, same scoring call, same output format.
**Done when:** the vertical slice produces one valid `Prediction` and one evidence card by 11 AM; then all four conditions write valid `predictions.jsonl` on 5 development items.

## Task 3 (Saturday afternoon): evidence-card UI
Rebuild the Kiln Triage prototype in `app/` reading only `runs/` and `results/`: review queue (flagged first), evidence card per pair (prediction and applicability notes, calculations and settings, citations, disagreements, compute requests with reason, cost and before/after, review flags), pair checker, results tab with coverage and compute allocation. `Dockerfile` listening on `$PORT` for Cloud Run.
**Done when:** it runs on development outputs and deploys once to Cloud Run.
