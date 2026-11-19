# Decision-Grounded LLM Router Agent & Visual Studio

<p>
  <img src="https://img.shields.io/badge/Gemini_Decision_1-4285F4?style=for-the-badge&logo=googlegemini&logoColor=white" alt="Gemini Decision 1" />
  <img src="https://img.shields.io/badge/Google_GenAI_SDK-1A73E8?style=for-the-badge&logo=google&logoColor=white" alt="Google GenAI SDK" />
  <img src="https://img.shields.io/badge/Agent_Skills-0F9D58?style=for-the-badge&logo=sparkles&logoColor=white" alt="Agent Skills" />
  <img src="https://img.shields.io/badge/Python_3.13-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.13" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Pydantic_v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white" alt="Pydantic v2" />
  <img src="https://img.shields.io/badge/Uvicorn-2F3640?style=for-the-badge&logo=lightning&logoColor=white" alt="Uvicorn" />
  <img src="https://img.shields.io/badge/JavaScript_ESM-F7DF1E?style=for-the-badge&logo=javascript&logoColor=111111" alt="JavaScript ESM" />
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white" alt="HTML5" />
  <img src="https://img.shields.io/badge/Vanilla_CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white" alt="Vanilla CSS3" />
  <img src="https://img.shields.io/badge/Pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white" alt="Pytest" />
</p>

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
