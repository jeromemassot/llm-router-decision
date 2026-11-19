"""Unit & integration tests for virgin-session startup, plain-text synthesis, routing, and fallback."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.architect_agent import RouterArchitectAgent
from backend.router_engine import DecisionGroundedRouter
from backend.schemas import TierLevel


def test_virgin_session_synthesis_and_routing_flow() -> None:
    client = TestClient(app)

    # 1. Reset session -> completely virgin state
    r_reset = client.post("/api/session/reset")
    assert r_reset.status_code == 200
    assert r_reset.json()["has_active_spec"] is False
    assert r_reset.json()["stats"]["total_routed"] == 0
    assert client.get("/api/config").json() is None

    # 2. Routing before configuring a router returns 400
    r_before = client.post("/api/route", json={"prompt": "Hello", "force_simulation": True})
    assert r_before.status_code == 400

    # 3. Synthesize brand-new router from plain-text user input (`current_spec = None`)
    agent = RouterArchitectAgent()
    synth = agent.handle_message(
        "Evaluate multi-step reasoning depth and code architecture complexity, and anything involving security audits above 0.75 must go straight to Carbon.",
        current_spec=None,
        force_simulation=True,
    )
    assert synth.validation_passed is True
    assert synth.proposed_spec is not None
    assert len(synth.proposed_spec.topics) >= 1
    assert len(synth.proposed_spec.hard_gates) >= 1

    # 4. Activate synthesized spec & route simple vs expert tasks
    spec = synth.proposed_spec
    client.post("/api/config", json=spec.model_dump())
    assert client.get("/api/status").json()["has_active_spec"] is True

    router = DecisionGroundedRouter()
    simple_res = router.route(
        "What is the capital of Japan?",
        spec,
        force_simulation=True,
    )
    assert simple_res.final_tier in (TierLevel.SIMPLE, TierLevel.STANDARD)
    assert all(c.output_tokens == 0 for c in simple_res.decision_calls)

    expert_res = router.route(
        "Perform a security audit and threat model for multi-tenant encryption keys.",
        spec,
        force_simulation=True,
    )
    assert expert_res.final_tier == TierLevel.EXPERT
    assert expert_res.final_model_id == "gemini-4-carbon"


def test_quality_gate_fallback_and_confidence_bump() -> None:
    agent = RouterArchitectAgent()
    spec = agent.handle_message(
        "Balance analytical reasoning complexity and factual precision.",
        current_spec=None,
        force_simulation=True,
    ).proposed_spec
    assert spec is not None

    router = DecisionGroundedRouter()
    res = router.route(
        "Translate 'good morning' to Spanish.",
        spec,
        simulate_low_quality_first_attempt=True,
        force_simulation=True,
    )
    assert res.quality_gate.executed is True
    assert res.quality_gate.passed is False
    assert res.quality_gate.fallback_triggered is True
    assert len(res.generations) == 2

    # Low-confidence escalation check
    spec.confidence_threshold = 0.92
    _, _, resolution = router.resolve_from_answers(
        spec=spec,
        hard_gate_answers={},
        topic_answers={t.key: {"type": "score", "score": 0.1, "confidence": 0.60} for t in spec.topics},
    )
    assert resolution.score_tier == TierLevel.SIMPLE
    assert resolution.confidence_escalated is True
    assert resolution.resolved_tier == TierLevel.STANDARD


def test_human_readable_multi_sentence_translation() -> None:
    user_paragraph = (
        "I want to route the requests based on the level of thinking needed, and the risks of having the llm "
        "hallucinates, or create a non formal tone. If the tone is scored as not formal enough with a probability "
        "above 70%, I want the task to be sent to the next higher tier available. On the other hand, if the tasks to "
        "be completed are related to chit chat or informal conversation, I want to use the lower tier model. The "
        "chitchat detector threshold should be above 90% to make the decision to route to the lower tier model "
        "(3.5 flash lite). I want the router to target the most cost effective tier model except if the risk "
        "associated to hallucination or not enough reasoning is high."
    )
    agent = RouterArchitectAgent()
    resp = agent.handle_message(user_paragraph, current_spec=None, force_simulation=True)

    assert resp.proposed_spec is not None
    spec = resp.proposed_spec

    # 1. Clean human-readable translation steps with zero raw LaTeX
    assert len(resp.translation_steps) == 5
    for step in resp.translation_steps:
        assert "$\\rightarrow$" not in step.routing_rule
        assert "want_route_the" not in step.title.lower()

    # 2. Chit-chat rule routes DOWN to SIMPLE at >= 90%
    cc_gates = [g for g in spec.hard_gates if g.key == "chitchat_fast_track"]
    assert len(cc_gates) == 1
    assert cc_gates[0].threshold == 0.90
    assert cc_gates[0].action == "route_to_tier"
    assert cc_gates[0].min_tier == TierLevel.SIMPLE

    # 3. Two clean weighted topics: Thinking Level (50%) + Hallucination Risk (50%)
    topic_keys = {t.key for t in spec.topics}
    assert topic_keys == {"thinking_level", "hallucination_risk"}

    # 4. Non-formal tone post-answer check escalates +1 tier at >= 70%
    tone_checks = [p for p in spec.quality_gate.custom_checks if p.key == "non_formal_tone_check"]
    assert len(tone_checks) == 1
    assert tone_checks[0].threshold == 0.70

    # 5. Verify routing behavior on casual chitchat vs failed tone check
    router = DecisionGroundedRouter()
    chat_res = router.route("Hey there, how are you doing today?", spec, force_simulation=True)
    assert chat_res.final_model_id == "gemini-3.5-flash-lite"

    tone_escalated = router.route(
        "Draft a brief update on TCP vs UDP.",
        spec,
        simulate_low_quality_first_attempt=True,
        force_simulation=True,
    )
    assert tone_escalated.quality_gate.fallback_triggered is True
    assert any(c.triggered_escalation for c in tone_escalated.quality_gate.custom_check_results)
