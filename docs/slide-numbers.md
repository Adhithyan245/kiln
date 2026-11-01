# Kiln: numbers for the slides

All numbers are from the **H100 full run** (346 held-out pairs × 4 conditions × 3 seeds = 4,152 predictions; manifest `cf6699f7…`, receipt message `1566496777790554284`), unless marked as the declared 16:15 result. Costs come from the run logs. Gemini spend is metered; GPU dollars are estimates at the VM's on-demand rate of $4.50/h.

---

## Science

**Pre-registered question:** does coordination among agents improve ranking accuracy at the same budget?

| Condition | AUROC | Brier ↓ |
|---|---|---|
| C1 single agent | 0.728 | 0.182 |
| C2 isolated specialists | 0.739 | 0.177 |
| C3 central planner | 0.736 | 0.178 |
| **C4 collective** | **0.739** | **0.177** |

- **Primary endpoint ΔAUROC(C4 − C1) = +0.011** (seeds +0.012, +0.012, +0.010).
- The declared 16:15 UTC result (301 pairs every run had finished) gave **+0.013**. Same sign, same size.
- **Coordination changed nothing:** C4 and C2 made identical decisions.
- **No confidence intervals:** with 9 held-out precursor clusters in a crossed design, no resampling method is validated. Say "ranked better on this held-out set", not "significantly better".
- **Honest limit:** four-class accuracy is 0.39, **below** always answering "unreacted" (0.41); macro-F1 is 0.18. The system ranks reasonably but does not classify the four outcomes well.

---

## Business

**Where the compute went (per pair)**

| Condition | Pairs sent to GPU relaxation | Compute units | Gemini tokens | Gemini cost |
|---|---|---|---|---|
| C1 single agent | **0%** (single point on 6%) | **0.18** | 2,388 | 0.69¢ |
| C2 isolated specialists | **47%** (single point on 51%) | **14.8** | 1,295 | 0.29¢ |
| C3 central planner | 27% | 8.4 | 2,550 | 0.67¢ |
| C4 collective | **47%** (single point on 51%) | **14.8** | 1,571 | 0.36¢ |

- **Headline:** the specialist setups spend **about 80× the compute** for **+0.011 AUROC**. The single agent gets **98% of the AUROC at about 1% of the compute**.
- **Twist:** the single agent uses about **twice the Gemini tokens** per pair. It reasons more instead of computing more: cheap tokens replace expensive GPU work.
- **Whole experiment (4,152 predictions):**
  - Gemini: **$20.93** (metered, 8.1 M tokens)
  - GPU: **18.6 GPU-hours logged**, about **6 hours of one H100** (12 runs shared the card), about **$27** at $4.50/h (estimate)
  - **About $50 total, roughly 1¢ per prediction**
- **Pitch line:** "Spend GPU time only where it changes the answer." Every one of the 4,152 decisions is logged with its cost and its reason, so a lab can audit what each dollar bought.

---

## Integrity

- Protocol hashed and posted **before** any held-out run (Gate P `c283468`, `protocol.md` digest `3ca68ee1…`).
- Every prediction set hashed and posted **before** grading; the scorer refuses to read labels until the posted hash checks out.
- **We caught our own failure:** the first GB10 run silently used fake "stub" energies. We found it in the compute logs (0 GPU-seconds), not the scores, declared it invalid publicly, and reran on real compute.
- Two independent scorings of the 16:15 result (Discord-verified and manual) gave identical numbers.

---

## Cautions for the presenter

- Do not price GPU per condition as GPU-seconds × $4.50/h. The 12 runs overlapped on one GPU, so their GPU-seconds add up to more than the clock time (that method gives about $83 for 6 hours of a $4.50/h machine). Use compute units or the share of pairs escalated.
- These are costs on borrowed hackathon hardware: say "on our setup", not "in production".
- The triage app **replays** recorded pairs from the run (every held-out pair). With live mode on, a **new** pair runs through the real agents and compute; a live result is a demo, not part of the scored experiment.
