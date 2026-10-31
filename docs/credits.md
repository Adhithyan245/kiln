# Credits: every one has a job

Approved by Adhi on Saturday Oct 31. Every credit the event gave us is used; none sits idle. Keys always come from environment variables, never from files in the repo.

| Credit | Job | Owner | When |
|---|---|---|---|
| **Gemini Tier 1** (Google accounts 1 and 2) | The experiment's LLM: C1–C4, all **3** seeds (don't cut to 2), full development set, N2 via the Batch API. Account 2's key (`GEMINI_API_KEY_2`) adds throughput and is the first fallback | Runner (Adhi) | Sat dev runs, Night 2 |
| **Google Compute Engine** (both accounts) | Account 1: scoring, bootstrap CIs, figures. Account 2: CPU pymatgen work for the Materials Project cache and decomposition products | Hemanath (1), CJ (2) | Sat–Sun |
| **Google Cloud Run** (both accounts) | Account 1: the Kiln Triage app. Account 2: a warm mirror of the same container, the fallback URL during judging | Adhi | Sat afternoon, Sun 8:30 AM |
| **DGX Spark (GB10)** | Primary compute service for every condition | CJ | Throughout |
| **NVIDIA Brev** ($150 × 4 accounts) | Each person redeems their own credits and runs a compute-service worker (same API, same models, same frozen tier prices): development profiling, then parallel workers in Night 2. Every request logs which backend served it, so GB10 use is reported exactly. Stop every instance after Night 2 (`brev ls`, `brev stop`) | CJ leads; each person launches on their own account | Sat, Night 2 |
| **Nebius H100s** (shared pool, one GPU per job) | Profiling batches and a third compute backend for overflow | CJ | Sat |
| **Nebius Scientific AI Platform** (one per team) | 10 GB bucket: off-laptop backup of `runs/` and `results/` before the Google accounts are deleted Sunday night; MCP for library documentation in Claude Code | CJ | Night 2, Sun |
| **Claude API** ($100 × 4) | Secondary result: Claude replication on ~120 held-out pairs, 1 seed (`ANTHROPIC_API_KEY`). Also: backup provider wired into `llm_call`, the alphaXiv write-up, slides, commit review, judge Q&A prep | Adhi + everyone | Night 2 (after the main run), Sun |
| **OpenAI API** ($50 × 4) | Secondary result: N2 memorization probe on an OpenAI model (`OPENAI_API_KEY`). Also: backup provider, second reviewer | Adhi | Night 2, Sun |
| **Edison** (~20 free calls/day) | Every free call, every day (Fri, Sat, Sun). Single-precursor property questions only | Annamayya | Daily |
| **NVIDIA API key** | `read-papers`: A-Lab SI tables for the demo recipes; check every number by hand | Hemanath | Sat |
| **Materials Project** (free key) | Tier 1 cache | CJ | Night 1 |
| **Coding seats** | Each person's coding assistant; separate from experiment budget | Everyone | Throughout |

## Rules that still hold
- The main comparison table is Gemini only. Claude and OpenAI results are **secondary** and reported in their own table.
- Every condition gets the same budget, models and compute prices, whichever backend serves a request.
- Every run logs its tokens and dollars per item (`Prediction.cost.usd`), so spend is checked after the first 20 runs.
