---
name: topic-threshold-discovery
description: >-
  Guides the agent to interview the user from a clean slate and uncover the
  specific routing topics, risk guardrails, probability/confidence thresholds,
  and candidate LLM collection needed to build a custom Decision-Grounded LLM
  Router. Use when starting a new virgin session or clarifying routing priorities.
---

# Topic & Threshold Discovery Skill

Start every new session completely neutral—do **not** preload domain presets or assume topics the user has not mentioned. Investigate four core dimensions with the user:

1. **Routing Topics (`score`, `choice`, `noul`)**:
   - Ask what dimensions matter when deciding between a fast/lightweight model and a frontier reasoning model for their tasks, and how heavily each topic should be weighted ($w_i$).
2. **Hard Threshold Guardrails (`noul`)**:
   - Ask whether any binary conditions should bypass weighted averaging when `gemini-decision-1` returns probability $P \ge \theta_g$ ($\theta_g \in [0.01, 0.99]$) and immediately enforce a minimum LLM tier.
3. **Candidate LLM Collection**:
   - Confirm the short collection of tiered LLMs to route across (default Gemini catalog when unspecified: `gemini-3.5-flash-lite`, `gemini-4-hydrogen`, `gemini-4-neon`, `gemini-4-carbon`).
4. **Tier Cutoffs, Confidence & Quality Gate**:
   - Elicit their cost-vs-capability preference for composite score cutoffs ($\tau_1 < \tau_2 < \tau_3$), minimum Decision confidence ($\theta_{\text{conf}}$), and post-generation Quality Gate threshold ($\theta_{\text{quality}}$).

Once the user responds in plain text, hand off to [`feedback-to-decisions-translator`](file:///usr/local/google/home/jeromemassot/VIBE-CODING/llm-router-decision/.agents/skills/feedback-to-decisions-translator/SKILL.md) to synthesize the custom `RouterSpec`.
