# Decision-Grounded LLM Router Agent & Visual Studio

A skill-driven **Multi-Decision LLM Router Agent** and **Visual Studio** built on **Google's Decisions API (`gemini-decision-1`)** (`https://aistudio.google.com/docs/decisions-api`) and inspired by `kylancholt/llm-inference-engineering/tree/main/05_routing`.

Every session starts **completely virgin**—with no predefined scenarios, topics, or sample prompts—so the router is constructed strictly from your own plain-text requirements and feedback.

## Workflow

1. **Tab 1 — Router Architect Agent**:
   - Powered by 3 workspace skills under `.agents/skills/` (`topic-threshold-discovery`, `feedback-to-decisions-translator`, `decision-weighted-routing`).
   - Interviews you or translates your plain-text routing priorities directly into validated `gemini-decision-1` `noul`, `choice`, and `score` calls, weights, and thresholds.
2. **Tab 2 — Step-by-Step Pipeline Trace**:
   - Evaluates your own prompts across your custom router (`0` decision output tokens billed), visualizing `Call #1` (Hard Gates & Stage-1 Topics), `Call #2` (Rubric Scoring), the Weighted Score & Tier Threshold Ruler, the Candidate LLM Collection, and `Call #3` (Post-Generation Decision Quality Gate + Fallback Chain).
3. **Tab 3 — Topics, Weights & Thresholds**:
   - Interactive sliders and JSON manifest inspector for the topics, weights, and cutoffs synthesized during your session.

## Quickstart

```bash
# Optional: set GEMINI_API_KEY in .env (or configure it directly inside the UI header)
cp .env.example .env

# Run tests
.venv/bin/pytest -v

# Start the Studio server
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```
