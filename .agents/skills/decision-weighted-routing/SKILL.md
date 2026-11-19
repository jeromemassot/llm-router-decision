---
name: decision-weighted-routing
description: >-
  Executes the multi-call Decision-Grounded LLM Routing pipeline using
  gemini-decision-1: Stage 1 Gatekeeper & Intent Triage, Stage 2 Multi-Topic
  Rubric Scoring, Stage 3 Weighted Score Aggregation & Tier Resolution, Stage 4
  Candidate LLM Dispatch, and Stage 5 Post-Generation Decision Quality Gate with
  Fallback Escalation. Use when routing tasks through a user-configured RouterSpec.
---

# Decision-Weighted Routing Execution Skill

Routes user tasks through a custom `RouterSpec` across a short collection of LLMs and produces a complete step-by-step trace:

1. **Call #1 — Gatekeepers & Stage-1 Topics (`gemini-decision-1`)**: Evaluates `hard_gates` (`noul`) and stage-1 `choice`/`noul`/`score` questions with `0` output tokens.
2. **Call #2 — Stage-2 Rubric Scoring (`gemini-decision-1`)**: Evaluates continuous `score` and `noul` topics (or batches Call #1 + Call #2 in Single-Pass Mode).
3. **Weighted Score & Threshold Resolution**: Computes $S = \frac{\sum w_i \tilde{d}_i}{\sum w_i} \in [0, 1]$, applies hard-gate floors and low-confidence tier escalation ($\bar{c} < \theta_{\text{conf}}$), and selects the winning model.
4. **Target LLM Dispatch & Call #3 Quality Gate**: Generates the response with the chosen LLM, verifies quality via `gemini-decision-1` (`0` output tokens), and escalates up the fallback chain if quality $\le \theta_{\text{quality}}$.

## CLI Helper

```bash
.venv/bin/python .agents/skills/decision-weighted-routing/scripts/route_prompt.py \
  --config <path/to/user_router.json> \
  --prompt "<user prompt>"
```
