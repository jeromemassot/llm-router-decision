# Decision-Grounded LLM Router Workspace

This workspace implements a **Skill-Driven Decision-Grounded LLM Router Agent** and its **Dedicated Visual Studio**, starting completely clean on every new session so the router is built purely from the user's own topics, thresholds, and plain-text feedback:

- **Google AI Studio Decisions API (`gemini-decision-1`)**: Zero-output-token calibrated probability evaluation (`noul`, `choice`, `score`) over text and multimodal inputs (`POST /v1beta/decisions` via `google-genai >= 3.2`).
- **Multi-Decision Weighted LLM Routing**: Inspired by `kylancholt/llm-inference-engineering/tree/main/05_routing`, replacing static heuristics with custom multi-call `gemini-decision-1` gates, weighted rubric scores, confidence escalation, and a post-generation Decision Quality Gate + fallback chain.

## Custom Agent & Skills Architecture

Customizations live in `.agents/` and power both workspace coding agents and the in-app **Router Architect Agent** (Tab 1):

- **Agent**: [`.agents/agents/decision-router-architect.md`](file:///usr/local/google/home/jeromemassot/VIBE-CODING/llm-router-decision/.agents/agents/decision-router-architect.md)
- **Skills**:
  1. `topic-threshold-discovery` (`.agents/skills/topic-threshold-discovery/SKILL.md`): Interactive interview playbook to uncover the user's specific routing topics, hard guardrails, thresholds, and candidate LLM collection from a blank slate.
  2. `feedback-to-decisions-translator` (`.agents/skills/feedback-to-decisions-translator/SKILL.md`): Compiles plain-text user requirements and critiques into validated `gemini-decision-1` `noul`, `choice`, and `score` questions, weights, and `[0.01, 0.99]` thresholds.
  3. `decision-weighted-routing` (`.agents/skills/decision-weighted-routing/SKILL.md`): Executes staged or single-pass `gemini-decision-1` calls, computes normalized weighted composite scores, routes across the candidate LLM collection (`gemini-3.5-flash-lite`, `gemini-4-hydrogen`, `gemini-4-neon`, `gemini-4-carbon`), and runs the post-generation Decision Quality Gate + fallback chain.

## Python Environment Invariants

- Always execute Python and `pip` through the workspace virtual environment (`.venv/bin/python`, `.venv/bin/pip`, `.venv/bin/pytest`).
- Never hardcode or log `GEMINI_API_KEY`. Use `google-genai >= 3.2` (`from google import genai`) with `http_options={"api_version": "v1beta"}` for `client.decisions.create(model="gemini-decision-1", ...)` and `client.interactions.create(...)`.
