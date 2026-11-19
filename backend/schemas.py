"""Pydantic schemas for Decision-Grounded LLM Router specs, human-readable translations, and traces."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

QUESTION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class TierLevel(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"
    EXPERT = "EXPERT"


TIER_ORDER: List[TierLevel] = [
    TierLevel.SIMPLE,
    TierLevel.STANDARD,
    TierLevel.COMPLEX,
    TierLevel.EXPERT,
]


def tier_rank(tier: Union[TierLevel, str]) -> int:
    t = TierLevel(tier) if isinstance(tier, str) else tier
    return TIER_ORDER.index(t)


def next_tier_up(tier: TierLevel) -> TierLevel:
    idx = tier_rank(tier)
    return TIER_ORDER[min(idx + 1, len(TIER_ORDER) - 1)]


class CandidateModel(BaseModel):
    tier: TierLevel
    model_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    input_price_per_1m: float = Field(..., ge=0.0)
    output_price_per_1m: float = Field(..., ge=0.0)
    typical_latency_ms: int = Field(default=500, ge=10)
    max_output_tokens: int = Field(default=1024, ge=64)
    strengths: str = ""
    fallback_model_id: Optional[str] = None


def default_candidate_llm_pool() -> List[CandidateModel]:
    """Short collection of candidate Gemini LLMs ordered from lowest cost to frontier ceiling."""
    return [
        CandidateModel(
            tier=TierLevel.SIMPLE,
            model_id="gemini-3.5-flash-lite",
            display_name="Gemini 3.5 Flash-Lite",
            input_price_per_1m=0.30,
            output_price_per_1m=2.50,
            typical_latency_ms=280,
            max_output_tokens=512,
            strengths="Lowest cost & fastest tier for casual chat, lookups, and simple tasks.",
            fallback_model_id="gemini-4-hydrogen",
        ),
        CandidateModel(
            tier=TierLevel.STANDARD,
            model_id="gemini-4-hydrogen",
            display_name="Gemini 4 Hydrogen",
            input_price_per_1m=1.50,
            output_price_per_1m=7.50,
            typical_latency_ms=620,
            max_output_tokens=1200,
            strengths="Balanced everyday model for standard explanations, drafting, and code.",
            fallback_model_id="gemini-4-neon",
        ),
        CandidateModel(
            tier=TierLevel.COMPLEX,
            model_id="gemini-4-neon",
            display_name="Gemini 4 Neon",
            input_price_per_1m=3.00,
            output_price_per_1m=15.00,
            typical_latency_ms=1350,
            max_output_tokens=2400,
            strengths="High-reasoning tier for multi-step analysis and high-accuracy tasks.",
            fallback_model_id="gemini-4-carbon",
        ),
        CandidateModel(
            tier=TierLevel.EXPERT,
            model_id="gemini-4-carbon",
            display_name="Gemini 4 Carbon",
            input_price_per_1m=4.00,
            output_price_per_1m=20.00,
            typical_latency_ms=2400,
            max_output_tokens=4096,
            strengths="Frontier reasoning ceiling for highest-risk and deepest-thinking tasks.",
            fallback_model_id=None,
        ),
    ]


class HardGateQuestion(BaseModel):
    """Pre-routing binary (`noul`) IF/THEN rule evaluated on the user's input prompt."""

    key: str
    label: str
    user_intent: str = ""
    instructions: str = Field(..., min_length=8)
    true_description: Optional[str] = None
    false_description: Optional[str] = None
    threshold: float = Field(default=0.75, ge=0.01, le=0.99)
    min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    action: Literal["min_tier", "route_to_tier", "bump_one_tier"] = "min_tier"
    min_tier: TierLevel = TierLevel.COMPLEX
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_key_and_bounds(self) -> "HardGateQuestion":
        if not QUESTION_KEY_RE.match(self.key):
            raise ValueError(
                f"Invalid question key '{self.key}': must match ^[A-Za-z0-9_-]{{1,64}}$"
            )
        return self

    def describe_action_human(self) -> str:
        pct = int(round(self.threshold * 100))
        if self.action == "route_to_tier":
            return f"IF Yes >= {pct}% -> Route directly to {self.min_tier.value} tier"
        if self.action == "bump_one_tier":
            return f"IF Yes >= {pct}% -> Escalate +1 higher tier"
        return f"IF Yes >= {pct}% -> Use at least {self.min_tier.value} tier"


class TopicQuestion(BaseModel):
    """Weighted scoring topic (`score`, `noul`, or `choice`) evaluated on the user's input prompt."""

    key: str
    label: str
    user_intent: str = ""
    call_stage: Literal[1, 2] = 2
    type: Literal["noul", "choice", "score"]
    weight: float = Field(default=0.50, ge=0.0, le=5.0)
    instructions: str = Field(..., min_length=8)
    invert: bool = False
    true_description: Optional[str] = None
    false_description: Optional[str] = None
    criteria: Optional[Union[Dict[str, str], List[str]]] = None
    option_affinities: Optional[Dict[str, float]] = None
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_decisions_api_rules(self) -> "TopicQuestion":
        if not QUESTION_KEY_RE.match(self.key):
            raise ValueError(
                f"Invalid topic key '{self.key}': must match ^[A-Za-z0-9_-]{{1,64}}$"
            )
        if self.type == "choice":
            if not isinstance(self.criteria, dict) or not (2 <= len(self.criteria) <= 255):
                raise ValueError(
                    f"Choice topic '{self.key}' requires criteria dict with 2..255 options."
                )
            for opt_key in self.criteria:
                if not (1 <= len(opt_key) <= 128) or opt_key != opt_key.strip():
                    raise ValueError(
                        f"Invalid option key '{opt_key}' in choice topic '{self.key}'."
                    )
                if opt_key.lower() == "none_of_the_above":
                    raise ValueError(
                        f"Avoid 'none_of_the_above' in '{self.key}' (Decisions API sorts option keys alphabetically); use 'other' instead."
                    )
            if self.option_affinities:
                for k, v in self.option_affinities.items():
                    if not (0.0 <= v <= 1.0):
                        raise ValueError(
                            f"Option affinity for '{k}' in '{self.key}' must be in [0, 1]."
                        )
        elif self.type == "score":
            if not isinstance(self.criteria, list) or not (2 <= len(self.criteria) <= 255):
                raise ValueError(
                    f"Score topic '{self.key}' requires criteria list with 2..255 ordered levels."
                )
            if any(not isinstance(item, str) or not item.strip() for item in self.criteria):
                raise ValueError(
                    f"Score topic '{self.key}' has empty rubric level description."
                )
        return self


class TierCutoffs(BaseModel):
    standard: float = Field(default=0.30, gt=0.01, lt=0.95)
    complex: float = Field(default=0.60, gt=0.03, lt=0.97)
    expert: float = Field(default=0.82, gt=0.05, lt=0.99)

    @model_validator(mode="after")
    def _validate_monotonic(self) -> "TierCutoffs":
        if not (self.standard < self.complex < self.expert):
            raise ValueError(
                f"Tier cutoffs must satisfy standard ({self.standard}) < complex ({self.complex}) < expert ({self.expert})."
            )
        return self


class PostGenCheck(BaseModel):
    """Custom binary (`noul`) check evaluated by `gemini-decision-1` on the generated draft response."""

    key: str
    label: str
    user_intent: str = ""
    instructions: str = Field(..., min_length=8)
    threshold: float = Field(default=0.70, ge=0.05, le=0.99)
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_key(self) -> "PostGenCheck":
        if not QUESTION_KEY_RE.match(self.key):
            raise ValueError(f"Invalid post-check key '{self.key}'.")
        return self


class QualityGateSpec(BaseModel):
    enabled: bool = True
    threshold: float = Field(default=0.70, ge=0.05, le=0.98)
    instructions: str = Field(
        default="How accurate, complete, and well-reasoned is the candidate response relative to the user prompt?"
    )
    criteria: List[str] = Field(
        default_factory=lambda: [
            "Incorrect, off-topic, or refuses without cause.",
            "Partially answers the prompt but misses important details or constraints.",
            "Accurate, clear response meeting core requirements.",
            "Thorough, accurate, high-quality response.",
        ]
    )
    constraint_check_instructions: str = Field(
        default="Does the candidate response satisfy all explicit instructions in the user prompt?"
    )
    custom_checks: List[PostGenCheck] = Field(default_factory=list)


class FeedbackEntry(BaseModel):
    timestamp: str
    user_feedback: str
    summary: str
    skills_used: List[str] = Field(default_factory=list)


class RouterSpec(BaseModel):
    id: str = "custom_router"
    name: str = "Custom Decision-Grounded Router"
    description: str = ""
    execution_mode: Literal["staged", "batched"] = "staged"
    models: List[CandidateModel] = Field(default_factory=default_candidate_llm_pool)
    hard_gates: List[HardGateQuestion] = Field(default_factory=list)
    topics: List[TopicQuestion]
    tier_cutoffs: TierCutoffs = Field(default_factory=TierCutoffs)
    confidence_threshold: float = Field(default=0.68, ge=0.05, le=0.99)
    escalate_on_low_confidence: bool = True
    quality_gate: QualityGateSpec = Field(default_factory=QualityGateSpec)
    feedback_history: List[FeedbackEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_keys_and_models(self) -> "RouterSpec":
        seen_keys: set[str] = set()
        for g in self.hard_gates:
            if g.key in seen_keys:
                raise ValueError(f"Duplicate question key '{g.key}' across router spec.")
            seen_keys.add(g.key)
        for t in self.topics:
            if t.key in seen_keys:
                raise ValueError(f"Duplicate question key '{t.key}' across router spec.")
            seen_keys.add(t.key)
        if not any(t.enabled and t.weight > 0 for t in self.topics):
            raise ValueError("RouterSpec must have at least one enabled topic with weight > 0.")
        tiers_present = {m.tier for m in self.models}
        if len(tiers_present) < 2:
            raise ValueError("RouterSpec must configure at least 2 distinct LLM tiers.")
        return self


# ---------------------------------------------------------------------------
# Trace & Execution Models
# ---------------------------------------------------------------------------

class DecisionCallTrace(BaseModel):
    call_index: int
    stage_name: str
    purpose: str
    model: str = "gemini-decision-1"
    mode: Literal["live", "simulation"]
    request_payload: Dict[str, Any]
    response_payload: Dict[str, Any]
    input_tokens: int
    output_tokens: int = 0
    cost_usd: float
    latency_ms: float


class HardGateEvaluation(BaseModel):
    key: str
    label: str
    instructions: str = ""
    noul: float
    confidence: float
    threshold: float
    min_confidence: float
    action: Literal["min_tier", "route_to_tier", "bump_one_tier"] = "min_tier"
    min_tier: TierLevel
    triggered: bool
    effect_summary: str = ""


class NormalizedTopicScore(BaseModel):
    key: str
    label: str
    instructions: str = ""
    call_stage: int
    type: Literal["noul", "choice", "score"]
    raw_value: Union[float, str]
    normalized_score: float
    weight: float
    effective_weight_share: float
    weighted_contribution: float
    confidence: float
    probabilities: Optional[Dict[str, float]] = None
    legend: Optional[Dict[str, str]] = None
    invert: bool = False


class RoutingResolution(BaseModel):
    composite_score: float
    aggregate_confidence: float
    score_tier: TierLevel
    hard_gate_min_tier: Optional[TierLevel] = None
    triggered_gates: List[str] = Field(default_factory=list)
    confidence_escalated: bool = False
    resolved_tier: TierLevel
    selected_model_id: str
    selected_model_name: str
    explanation: List[str]


class LLMGenerationTrace(BaseModel):
    attempt_number: int
    tier: TierLevel
    model_id: str
    display_name: str
    mode: Literal["live", "simulation"]
    response_text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class PostCheckResult(BaseModel):
    key: str
    label: str
    instructions: str
    noul: float
    threshold: float
    triggered_escalation: bool


class QualityGateTrace(BaseModel):
    executed: bool
    passed: Optional[bool] = None
    normalized_quality: Optional[float] = None
    quality_10_scale: Optional[float] = None
    raw_rubric_score: Optional[float] = None
    satisfies_constraints_noul: Optional[float] = None
    custom_check_results: List[PostCheckResult] = Field(default_factory=list)
    confidence: Optional[float] = None
    threshold: float
    fallback_triggered: bool = False
    fallback_reason: Optional[str] = None
    fallback_from_model: Optional[str] = None
    fallback_to_model: Optional[str] = None
    decision_call: Optional[DecisionCallTrace] = None


class RouteResult(BaseModel):
    prompt: str
    mode: Literal["live", "simulation"]
    execution_mode: Literal["staged", "batched"]
    decision_calls: List[DecisionCallTrace]
    hard_gate_evaluations: List[HardGateEvaluation]
    topic_scores: List[NormalizedTopicScore]
    resolution: RoutingResolution
    generations: List[LLMGenerationTrace]
    quality_gate: QualityGateTrace
    final_model_id: str
    final_model_name: str
    final_tier: TierLevel
    final_response: str
    total_cost_usd: float
    ceiling_equivalent_cost_usd: float
    saved_vs_ceiling_usd: float
    savings_pct: float
    total_latency_ms: float


# ---------------------------------------------------------------------------
# Human-Readable Translation Models
# ---------------------------------------------------------------------------

class TranslationStep(BaseModel):
    """Clear, jargon-free explanation of one translated piece of the user's router."""

    phase: Literal[
        "1. Input Shortcut / Guardrail Rule",
        "2. Weighted Scoring Topic",
        "3. Score-to-Model Tier Mapping",
        "4. Post-Answer Check & Auto-Escalation",
    ]
    title: str
    from_your_text: str
    decision_api_check: str
    api_question: str
    routing_rule: str


class RouteRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    router_spec: Optional[RouterSpec] = None
    simulate_low_quality_first_attempt: bool = False
    skip_generation: bool = False
    force_simulation: bool = False


class RecomputeRequest(BaseModel):
    router_spec: RouterSpec
    hard_gate_answers: Dict[str, Any]
    topic_answers: Dict[str, Any]


class ArchitectChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    current_spec: Optional[RouterSpec] = None
    last_route_result: Optional[RouteResult] = None
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    force_simulation: bool = False


class SpecChangeItem(BaseModel):
    category: str
    target: str
    before: str
    after: str
    rationale: str


class ArchitectChatResponse(BaseModel):
    reply_markdown: str
    summary_headline: str = ""
    translation_steps: List[TranslationStep] = Field(default_factory=list)
    active_skills: List[str]
    intent_detected: Literal["discovery_interview", "feedback_translation", "question_answering"]
    proposed_spec: Optional[RouterSpec] = None
    changes: List[SpecChangeItem] = Field(default_factory=list)
    validation_passed: bool = True
    mode: Literal["live", "simulation"]
