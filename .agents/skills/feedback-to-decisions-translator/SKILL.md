---
name: feedback-to-decisions-translator
description: >-
  Translates plain-text user requirements and iterative routing critiques into
  validated Gemini Decision 1 API (gemini-decision-1) questions (noul, choice,
  score), topic weights, hard threshold gates, and tier cutoffs. Use whenever the
  user describes their desired router from scratch or gives plain-text feedback.
---

# Plain-Text Feedback to Decisions API Translator

Compile natural-language user intent or iterative feedback into a validated `RouterSpec` JSON configuration backed by `gemini-decision-1` calls. Consult [decisions_api_rules.md](file:///usr/local/google/home/jeromemassot/VIBE-CODING/llm-router-decision/.agents/skills/feedback-to-decisions-translator/references/decisions_api_rules.md) for strict API rules.

## Translation Mapping

1. **Initial Creation from Plain Text (`current_spec == null`)**:
   - Extract each distinct topic or priority mentioned by the user into atomic `score` (`0..K-1` ordered rubric criteria), `choice` (mutually exclusive intent options with `"other"` catch-all), or `noul` (positively phrased binary probability) questions.
   - Extract any non-negotiable escalation triggers into `hard_gates` (`noul` threshold inside `[0.05, 0.95]` + `min_tier`).
   - Assign normalized weights $w_i$ and monotonic `tier_cutoffs` (`standard < complex < expert`) reflecting the user's stated cost/quality balance.
2. **Iterative Critique & Refinement (`current_spec != null`)**:
   - Add, remove, or re-weight `topics`, adjust `hard_gates` thresholds, tune `tier_cutoffs`, or modify `confidence_threshold` / `quality_gate.threshold` strictly according to the user's feedback.

## Validation Helper

```bash
.venv/bin/python .agents/skills/feedback-to-decisions-translator/scripts/validate_router_spec.py <path/to/router_spec.json>
```
