"""FastAPI backend serving the Decision-Grounded LLM Router Studio (virgin session startup)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.architect_agent import RouterArchitectAgent, load_installed_skills
from backend.decisions_client import (
    DecisionsGateway,
    get_active_api_key,
    has_live_api_key,
    mask_api_key,
    set_runtime_api_key,
)
from backend.router_engine import DecisionGroundedRouter
from backend.schemas import (
    ArchitectChatRequest,
    ArchitectChatResponse,
    RecomputeRequest,
    RouteRequest,
    RouteResult,
    RouterSpec,
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = WORKSPACE_ROOT / "frontend"

app = FastAPI(
    title="Decision-Grounded LLM Router Studio",
    description="Custom multi-decision LLM router built from user plain-text priorities via Google's Gemini Decision 1 API (gemini-decision-1).",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_static_cache(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith(("/src/", "/styles/")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response

gateway = DecisionsGateway()
router_engine = DecisionGroundedRouter(gateway=gateway)
architect = RouterArchitectAgent(gateway=gateway)

# Virgin state: no predefined router spec until the user creates one in their session
_ACTIVE_SPEC: Optional[RouterSpec] = None


class ApiKeyUpdate(BaseModel):
    api_key: Optional[str] = None


@app.get("/api/status")
def get_status() -> Dict[str, Any]:
    key = get_active_api_key()
    return {
        "live_api_available": has_live_api_key(),
        "masked_api_key": mask_api_key(key),
        "decision_model": "gemini-decision-1",
        "has_active_spec": _ACTIVE_SPEC is not None,
        "active_spec_name": _ACTIVE_SPEC.name if _ACTIVE_SPEC else None,
        "skills_count": len(load_installed_skills()),
        "stats": router_engine.get_cumulative_stats(),
    }


@app.post("/api/session/reset")
def reset_session() -> Dict[str, Any]:
    """Reset the session to a completely virgin state (no active router, zero routed history)."""
    global _ACTIVE_SPEC
    _ACTIVE_SPEC = None
    router_engine.history.clear()
    return get_status()


@app.post("/api/session/api-key")
def update_session_api_key(payload: ApiKeyUpdate) -> Dict[str, Any]:
    set_runtime_api_key(payload.api_key)
    key = get_active_api_key()
    return {
        "live_api_available": has_live_api_key(),
        "masked_api_key": mask_api_key(key),
    }


@app.get("/api/skills")
def list_skills() -> Dict[str, Any]:
    skills = load_installed_skills()
    return {
        "agent": {
            "name": "decision-router-architect",
            "path": ".agents/agents/decision-router-architect.md",
        },
        "skills": [
            {"name": s["name"], "description": s["description"], "path": s["path"]}
            for s in skills
        ],
    }


@app.get("/api/config")
def get_active_config() -> Optional[RouterSpec]:
    return _ACTIVE_SPEC


@app.post("/api/config")
def set_active_config(spec: RouterSpec) -> RouterSpec:
    global _ACTIVE_SPEC
    _ACTIVE_SPEC = spec
    return _ACTIVE_SPEC


@app.post("/api/config/validate")
def validate_config_payload(raw_spec: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validated = RouterSpec.model_validate(raw_spec)
        return {"valid": True, "spec": validated.model_dump(), "errors": []}
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)]}


@app.post("/api/route", response_model=RouteResult)
def route_task(req: RouteRequest) -> RouteResult:
    spec = req.router_spec or _ACTIVE_SPEC
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail="No custom router configured yet. Create your router in Tab 1 (Router Architect Agent) first.",
        )
    try:
        return router_engine.route(
            prompt=req.prompt,
            spec=spec,
            simulate_low_quality_first_attempt=req.simulate_low_quality_first_attempt,
            skip_generation=req.skip_generation,
            force_simulation=req.force_simulation,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/recompute-score")
def recompute_score(req: RecomputeRequest) -> Dict[str, Any]:
    gate_evals, topic_scores, resolution = router_engine.resolve_from_answers(
        spec=req.router_spec,
        hard_gate_answers=req.hard_gate_answers,
        topic_answers=req.topic_answers,
    )
    return {
        "hard_gate_evaluations": [g.model_dump() for g in gate_evals],
        "topic_scores": [t.model_dump() for t in topic_scores],
        "resolution": resolution.model_dump(),
    }


@app.post("/api/architect/chat", response_model=ArchitectChatResponse)
def architect_chat(req: ArchitectChatRequest) -> ArchitectChatResponse:
    try:
        return architect.handle_message(
            message=req.message,
            current_spec=req.current_spec,
            conversation_history=req.conversation_history,
            last_route_result=req.last_route_result,
            force_simulation=req.force_simulation,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    return router_engine.get_cumulative_stats()


if FRONTEND_DIR.exists():
    app.mount("/styles", StaticFiles(directory=str(FRONTEND_DIR / "styles")), name="styles")
    app.mount("/src", StaticFiles(directory=str(FRONTEND_DIR / "src")), name="src")

    @app.get("/")
    def serve_index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))
