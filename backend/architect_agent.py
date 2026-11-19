"""Skill-Driven Router Architect Agent: translates plain-text user priorities into a clear,
human-readable 3-part Decision-Grounded LLM Router (`Input Rules` -> `Weighted Topics` -> `Output Checks`)."""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from google import genai
from google.genai import types as genai_types

from backend.decisions_client import DecisionsGateway, get_active_api_key, has_live_api_key
from backend.schemas import (
    ArchitectChatResponse,
    FeedbackEntry,
    HardGateQuestion,
    PostGenCheck,
    QualityGateSpec,
    RouteResult,
    RouterSpec,
    SpecChangeItem,
    TierCutoffs,
    TierLevel,
    TopicQuestion,
    TranslationStep,
    default_candidate_llm_pool,
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = WORKSPACE_ROOT / ".agents" / "skills"


def load_installed_skills() -> List[Dict[str, str]]:
    """Discover and parse workspace skills under `.agents/skills/*/SKILL.md`."""
    skills: List[Dict[str, str]] = []
    if not SKILLS_DIR.exists():
        return skills

    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        raw = skill_md.read_text(encoding="utf-8")
        name = skill_md.parent.name
        desc = ""
        body = raw
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
        if m:
            fm, body = m.group(1), m.group(2)
            nm = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
            if nm:
                name = nm.group(1).strip()
            dm = re.search(r"description:\s*>?-?\s*\n((?:\s+.*\n?)+)", fm)
            if dm:
                desc = " ".join(line.strip() for line in dm.group(1).splitlines()).strip()
            else:
                dm2 = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
                if dm2:
                    desc = dm2.group(1).strip().strip('"')

        skills.append(
            {
                "name": name,
                "description": desc,
                "path": str(skill_md.relative_to(WORKSPACE_ROOT)),
                "content": body.strip(),
            }
        )
    return skills


def _model_label_for_tier(spec: RouterSpec, tier: TierLevel) -> str:
    for m in spec.models:
        if m.tier == tier:
            return f"{m.display_name} ({m.model_id})"
    return tier.value


def build_human_translation_steps(spec: RouterSpec) -> List[TranslationStep]:
    """
    Build a crystal-clear, jargon-free explanation of how the RouterSpec works
    so any human immediately understands every Decision API call and threshold.
    """
    steps: List[TranslationStep] = []

    # 1. Pre-Routing Input Rules (`hard_gates`)
    for g in spec.hard_gates:
        if not g.enabled:
            continue
        pct = int(round(g.threshold * 100))
        if g.action == "route_to_tier":
            rule_txt = f"IF Yes probability >= {pct}%  ->  Route directly to {_model_label_for_tier(spec, g.min_tier)}"
        elif g.action == "bump_one_tier":
            rule_txt = f"IF Yes probability >= {pct}%  ->  Send task to the next higher model tier (+1 tier)"
        else:
            rule_txt = f"IF Yes probability >= {pct}%  ->  Require at least {_model_label_for_tier(spec, g.min_tier)}"

        steps.append(
            TranslationStep(
                phase="1. Input Shortcut / Guardrail Rule",
                title=g.label,
                from_your_text=g.user_intent or f"Check '{g.label}' with a {pct}% probability threshold.",
                decision_api_check="Gemini Decision 1 · Yes/No Probability (0% – 100%)",
                api_question=g.instructions,
                routing_rule=rule_txt,
            )
        )

    # 2. Weighted Scoring Topics (`topics`)
    enabled_topics = [t for t in spec.topics if t.enabled and t.weight > 0]
    total_w = sum(t.weight for t in enabled_topics) or 1.0
    for t in enabled_topics:
        share_pct = int(round((t.weight / total_w) * 100))
        if t.type == "score" and isinstance(t.criteria, list):
            scale_preview = " | ".join(f"{i}: {lvl}" for i, lvl in enumerate(t.criteria))
            check_label = f"Gemini Decision 1 · {len(t.criteria)}-Level Scale (0 to {len(t.criteria) - 1})"
            q_detail = f"{t.instructions}\nScale: {scale_preview}"
        elif t.type == "choice" and isinstance(t.criteria, dict):
            opts = ", ".join(t.criteria.keys())
            check_label = f"Gemini Decision 1 · Single-Select Category ({opts})"
            q_detail = t.instructions
        else:
            check_label = "Gemini Decision 1 · Yes/No Probability (0% – 100%)"
            q_detail = t.instructions

        steps.append(
            TranslationStep(
                phase="2. Weighted Scoring Topic",
                title=f"{t.label} ({share_pct}% of score)",
                from_your_text=t.user_intent or f"Evaluate {t.label.lower()} when choosing a model tier.",
                decision_api_check=check_label,
                api_question=q_detail,
                routing_rule=f"Contributes {share_pct}% to the Combined Complexity/Risk Score (0% – 100%).",
            )
        )

    # 3. Tier Mapping Cutoffs
    c = spec.tier_cutoffs
    s_pct = int(round(c.standard * 100))
    c_pct = int(round(c.complex * 100))
    e_pct = int(round(c.expert * 100))
    m_simple = _model_label_for_tier(spec, TierLevel.SIMPLE)
    m_std = _model_label_for_tier(spec, TierLevel.STANDARD)
    m_cplx = _model_label_for_tier(spec, TierLevel.COMPLEX)
    m_exp = _model_label_for_tier(spec, TierLevel.EXPERT)

    steps.append(
        TranslationStep(
            phase="3. Score-to-Model Tier Mapping",
            title="Combined Score -> Model Selection",
            from_your_text="Balance cost-effectiveness against reasoning & risk scores.",
            decision_api_check="Weighted Average of Topic Scores (0% – 100%)",
            api_question="Combines all weighted topic scores above when no Input Shortcut Rule has locked a model.",
            routing_rule=(
                f"0%–{s_pct - 1}% -> {m_simple}  |  "
                f"{s_pct}%–{c_pct - 1}% -> {m_std}  |  "
                f"{c_pct}%–{e_pct - 1}% -> {m_cplx}  |  "
                f"{e_pct}%–100% -> {m_exp}"
            ),
        )
    )

    # 4. Post-Answer Output Checks (`quality_gate.custom_checks`)
    for pc in spec.quality_gate.custom_checks:
        if not pc.enabled:
            continue
        pc_pct = int(round(pc.threshold * 100))
        steps.append(
            TranslationStep(
                phase="4. Post-Answer Check & Auto-Escalation",
                title=pc.label,
                from_your_text=pc.user_intent or f"Escalate to next higher tier if '{pc.label}' exceeds {pc_pct}%.",
                decision_api_check="Gemini Decision 1 · Yes/No Check on Draft Answer (0% – 100%)",
                api_question=pc.instructions,
                routing_rule=f"IF Yes probability >= {pc_pct}% on the draft answer  ->  Re-run task on the next higher model tier (+1 tier).",
            )
        )

    return steps


def compute_spec_diff(old_spec: Optional[RouterSpec], new_spec: RouterSpec) -> List[SpecChangeItem]:
    """Produce human-friendly summary rows comparing old vs new spec."""
    changes: List[SpecChangeItem] = []
    if old_spec is None:
        for step in build_human_translation_steps(new_spec):
            changes.append(
                SpecChangeItem(
                    category=step.phase,
                    target=step.title,
                    before="Not set",
                    after=step.routing_rule,
                    rationale=step.api_question,
                )
            )
        return changes

    # Concise diff for iterative updates
    for step in build_human_translation_steps(new_spec):
        changes.append(
            SpecChangeItem(
                category=step.phase,
                target=step.title,
                before="Updated",
                after=step.routing_rule,
                rationale=step.api_question,
            )
        )
    return changes


# ---------------------------------------------------------------------------
# Clean Semantic Concept & Sentence Parser (Offline / Fallback Engine)
# ---------------------------------------------------------------------------

def _extract_threshold(sentence: str, default: float = 0.75) -> float:
    m_pct = re.search(r"(\d{1,2})\s*%", sentence)
    if m_pct:
        return min(0.98, max(0.05, int(m_pct.group(1)) / 100.0))
    m_dec = re.search(r"\b(0\.\d{1,2})\b", sentence)
    if m_dec:
        return min(0.98, max(0.05, float(m_dec.group(1))))
    return default


def _clean_concept_phrase(raw: str) -> str:
    """Strip conversational filler so arbitrary user concepts get crisp human titles."""
    s = raw.strip(" .,:;?!-")
    filler_patterns = [
        r"^on the other hand[,\s]*",
        r"^also[,\s]*",
        r"^additionally[,\s]*",
        r"^i\s+(?:also\s+)?(?:want|would like|need)\s+(?:the\s+router\s+)?(?:to\s+)?(?:route\s+(?:the\s+)?(?:requests|tasks|prompts)\s+)?(?:based\s+on\s+)?",
        r"^route\s+(?:the\s+)?(?:requests|tasks|prompts)\s+based\s+on\s+",
        r"^evaluate\s+(?:whether|how|the)\s+",
        r"^(?:the\s+)?(?:level|amount|degree)\s+of\s+",
        r"^(?:the\s+)?risks?\s+(?:of\s+(?:having\s+(?:the\s+)?(?:llm|model)\s+)?|associated\s+(?:to|with)\s+)",
        r"^if\s+(?:the\s+)?(?:tasks?|requests?|prompts?)\s+(?:to\s+be\s+completed\s+)?(?:are|is)\s+(?:related\s+to\s+)?",
        r"^(?:or\s+|and\s+)+",
    ]
    for pat in filler_patterns:
        s = re.sub(pat, "", s, flags=re.IGNORECASE).strip(" .,:;-")
    s = re.sub(r"\s+is\s+(?:high|low|needed|required)$", "", s, flags=re.IGNORECASE).strip()
    return s


class RouterArchitectAgent:
    """
    Translates plain-text user descriptions into a simple, transparent 3-stage router
    and explains every step in plain English.
    """

    def __init__(self, gateway: Optional[DecisionsGateway] = None) -> None:
        self.gateway = gateway or DecisionsGateway()
        self.skills = load_installed_skills()

    def _triage_user_intent(self, message: str) -> Literal["discovery_interview", "feedback_translation", "question_answering"]:
        ml = message.lower().strip()
        words = ml.split()
        if len(words) <= 3 and any(g in ml for g in ("hi", "hello", "hey", "start", "begin", "help")):
            return "discovery_interview"
        if any(p in ml for p in ("interview me", "ask me questions", "what do you need", "how do we start")):
            return "discovery_interview"
        if ml.endswith("?") and ml.startswith(("how does", "what is", "explain how", "why did")):
            return "question_answering"
        return "feedback_translation"

    def handle_message(
        self,
        message: str,
        current_spec: Optional[RouterSpec],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        last_route_result: Optional[RouteResult] = None,
        force_simulation: bool = False,
    ) -> ArchitectChatResponse:
        use_live = has_live_api_key() and not force_simulation
        intent = self._triage_user_intent(message)

        if intent == "discovery_interview":
            return self._handle_discovery(current_spec, mode="live" if use_live else "simulation")
        if intent == "question_answering":
            return self._handle_qa(current_spec, mode="live" if use_live else "simulation")

        if use_live:
            live_resp = self._try_live_llm_translation(
                message=message,
                current_spec=current_spec,
                conversation_history=conversation_history or [],
                last_route_result=last_route_result,
            )
            if live_resp is not None:
                return live_resp

        return self._semantic_translate_feedback(
            message=message,
            current_spec=current_spec,
            mode="live" if use_live else "simulation",
        )

    def _try_live_llm_translation(
        self,
        message: str,
        current_spec: Optional[RouterSpec],
        conversation_history: List[Dict[str, str]],
        last_route_result: Optional[RouteResult],
    ) -> Optional[ArchitectChatResponse]:
        """Try Gemini models in fallback order with strict JSON output to translate plain text."""
        api_key = get_active_api_key()
        if not api_key:
            return None
        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

        default_models_json = json.dumps(
            [m.model_dump() for m in default_candidate_llm_pool()], indent=2
        )
        spec_ctx = (
            f"Existing RouterSpec to refine:\n{current_spec.model_dump_json(indent=2)}"
            if current_spec is not None
            else f"No existing RouterSpec (create a fresh one using these 4 candidate models):\n{default_models_json}"
        )

        prompt = f"""You translate a user's plain-text LLM routing requirements into a clean, minimal, human-understandable `RouterSpec` for Google's Gemini Decision 1 API (`gemini-decision-1`).

CRITICAL DESIGN PRINCIPLES:
1. Keep the router SIMPLE and FAITHFUL to what the user actually asked for (typically 1–3 weighted `topics`, plus `hard_gates` or `quality_gate.custom_checks` ONLY for explicit threshold rules the user asked for). NEVER invent bloated or cryptic rules, and NEVER copy sentence fragments like "I want to route..." as labels!
2. Map each type of user requirement cleanly:
   - Input shortcut to a cheaper/lower model (e.g. "if chitchat > 90%, route to 3.5 flash lite"):
     Add to `hard_gates` with `"action": "route_to_tier"`, `"min_tier": "SIMPLE"`, `"threshold": 0.90`, positive Yes/No `instructions`, and clear `user_intent`.
   - Input rule escalating to next tier or minimum tier on prompt condition:
     Add to `hard_gates` with `"action": "bump_one_tier"` or `"action": "min_tier"`, `"min_tier": "COMPLEX"` or `"EXPERT"`.
   - Output / tone / style escalation rule (e.g. "if tone is not formal enough > 70%, send to next higher tier"):
     Add to `quality_gate.custom_checks` with `"threshold": 0.70`, positive `instructions` asking whether the candidate response exhibits the bad condition (e.g. "Is the tone of the candidate model response informal, casual, or not formal enough?"), and clear `user_intent`.
   - Continuous routing criteria (e.g. "level of thinking needed", "risk of hallucination"):
     Add to `topics` with `"type": "score"`, 4 short crystal-clear `criteria` strings ordered from 0 (lowest) to 3 (highest), clean human `label` (e.g. "Level of Thinking Needed", "Hallucination Risk"), and `user_intent`.
   - Cost vs risk appetite (e.g. "target most cost-effective model except if risk is high"):
     Set higher `tier_cutoffs` like `{{"standard": 0.35, "complex": 0.62, "expert": 0.84}}` so lower-cost models handle most requests unless scores are high.
3. Every `key` must match `^[a-z0-9_]{{2,48}}$`. Never use raw LaTeX in text.

Return JSON with exact keys:
{{
  "summary_headline": "One plain-English sentence summarizing how the router works.",
  "proposed_spec": {{ ... valid RouterSpec JSON ... }}
}}

{spec_ctx}

USER PLAIN-TEXT REQUEST:
{message}
"""
        for model_name in ("gemini-4-hydrogen", "gemini-2.5-flash", "gemini-3.5-flash-lite"):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                raw_text = (resp.text or "").strip()
                parsed = json.loads(raw_text)
                proposed = RouterSpec.model_validate(parsed["proposed_spec"])
                summary_headline = str(
                    parsed.get("summary_headline")
                    or "Translated your plain-text rules into a custom Gemini Decision 1 router."
                )
                now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                proposed.feedback_history.append(
                    FeedbackEntry(
                        timestamp=now_iso,
                        user_feedback=message,
                        summary=summary_headline[:180],
                        skills_used=["topic-threshold-discovery", "feedback-to-decisions-translator"],
                    )
                )
                steps = build_human_translation_steps(proposed)
                diffs = compute_spec_diff(current_spec, proposed)
                return ArchitectChatResponse(
                    reply_markdown=f"### How Your Rules Were Translated\n\n{summary_headline}",
                    summary_headline=summary_headline,
                    translation_steps=steps,
                    active_skills=["topic-threshold-discovery", "feedback-to-decisions-translator"],
                    intent_detected="feedback_translation",
                    proposed_spec=proposed,
                    changes=diffs,
                    validation_passed=True,
                    mode="live",
                )
            except Exception:
                continue
        return None

    def _handle_discovery(
        self,
        current_spec: Optional[RouterSpec],
        mode: Literal["live", "simulation"],
    ) -> ArchitectChatResponse:
        if current_spec is None:
            reply = (
                "### Tell Me How You Want to Route Prompts\n\n"
                "Describe your routing rules in plain English—for example:\n"
                "- **Topics to score** *(e.g., level of reasoning required, hallucination risk, code complexity, medical/legal sensitivity)*.\n"
                "- **Shortcut or escalation thresholds** *(e.g., \"If chit-chat > 90%, send to Flash-Lite\" or \"If tone is not formal enough > 70%, escalate to the next higher tier\")*.\n"
                "- **Cost vs. quality goal** *(e.g., \"Prefer the most cost-effective model unless risk is high\")*."
            )
        else:
            reply = (
                f"### Refining **{current_spec.name}**\n\n"
                "Tell me in plain English any rule, topic weight, or probability threshold you want to add, remove, or change."
            )
        return ArchitectChatResponse(
            reply_markdown=reply,
            active_skills=["topic-threshold-discovery"],
            intent_detected="discovery_interview",
            proposed_spec=None,
            changes=[],
            validation_passed=True,
            mode=mode,
        )

    def _handle_qa(
        self,
        current_spec: Optional[RouterSpec],
        mode: Literal["live", "simulation"],
    ) -> ArchitectChatResponse:
        reply = (
            "### How Translation to `gemini-decision-1` Works\n\n"
            "1. **Input Shortcut & Guardrail Rules (`Yes/No` checks)**: Binary questions with a `%` threshold that either fast-track simple prompts to a cheap model or force high-risk prompts to a stronger tier.\n"
            "2. **Weighted Scoring Topics (`0–3` scales)**: Continuous topics (like reasoning depth or hallucination risk) combined into a `0%–100%` score to pick among the 4 candidate LLMs.\n"
            "3. **Post-Answer Checks**: Optional `Yes/No` checks on the generated draft (like tone formality) that re-run the prompt on the next higher tier (`+1 tier`) if triggered."
        )
        return ArchitectChatResponse(
            reply_markdown=reply,
            active_skills=["decision-weighted-routing"],
            intent_detected="question_answering",
            proposed_spec=None,
            changes=[],
            validation_passed=True,
            mode=mode,
        )

    def _semantic_translate_feedback(
        self,
        message: str,
        current_spec: Optional[RouterSpec],
        mode: Literal["live", "simulation"],
    ) -> ArchitectChatResponse:
        """
        Clean sentence-level semantic parser that turns multi-sentence plain English into
        understandable Input Rules, Weighted Topics, Cutoffs, and Output Escalation Checks.
        """
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", message.strip())
            if s.strip()
        ]
        full_lower = message.lower()

        if current_spec is not None:
            new_spec = RouterSpec.model_validate(copy.deepcopy(current_spec.model_dump()))
            hard_gates = list(new_spec.hard_gates)
            topics = list(new_spec.topics)
            post_checks = list(new_spec.quality_gate.custom_checks)
            cutoffs = copy.deepcopy(new_spec.tier_cutoffs)
        else:
            hard_gates = []
            topics = []
            post_checks = []
            cutoffs = TierCutoffs(standard=0.30, complex=0.58, expert=0.82)

        existing_keys = (
            {g.key for g in hard_gates}
            | {t.key for t in topics}
            | {p.key for p in post_checks}
        )
        handled_concepts: set[str] = set()

        # Pass 1: Merge paired context across sentences (e.g. Sentence 3 mentions chitchat -> lower tier, Sentence 4 gives 90% threshold!)
        # First scan for explicit conditional / threshold rules!
        chitchat_sentences = [
            s for s in sentences
            if any(w in s.lower() for w in ("chit chat", "chitchat", "chit-chat", "informal conversation", "small talk", "casual chat"))
        ]
        if chitchat_sentences:
            combined_cc = " ".join(chitchat_sentences)
            cc_thresh = _extract_threshold(combined_cc, default=0.85)
            # Determine target tier (user usually wants lowest tier / flash lite for chitchat!)
            cc_tier = TierLevel.SIMPLE
            if "hydrogen" in combined_cc.lower() or "standard" in combined_cc.lower():
                cc_tier = TierLevel.STANDARD

            hard_gates = [g for g in hard_gates if g.key != "chitchat_fast_track"]
            hard_gates.append(
                HardGateQuestion(
                    key="chitchat_fast_track",
                    label="Chit-Chat & Casual Conversation Detector",
                    user_intent=combined_cc,
                    instructions="Is this user message casual chit-chat, small talk, or informal conversation rather than a substantive task?",
                    true_description="Greetings, small talk, casual banter, or simple conversational remarks.",
                    false_description="Questions requiring factual accuracy, analysis, coding, or professional drafting.",
                    threshold=cc_thresh,
                    min_confidence=0.55,
                    action="route_to_tier",
                    min_tier=cc_tier,
                    enabled=True,
                )
            )
            existing_keys.add("chitchat_fast_track")
            handled_concepts.add("chitchat")

        tone_sentences = [
            s for s in sentences
            if s not in chitchat_sentences
            and re.search(r"\b(tone|formal|non-formal|polite|professional style)\b", s.lower())
            and any(w in s.lower() for w in ("if ", "above", "%", "next higher", "higher tier", "escalate"))
        ]
        if tone_sentences:
            combined_tone = " ".join(tone_sentences)
            tone_thresh = _extract_threshold(combined_tone, default=0.70)
            post_checks = [p for p in post_checks if p.key != "non_formal_tone_check"]
            post_checks.append(
                PostGenCheck(
                    key="non_formal_tone_check",
                    label="Non-Formal Tone Escalation Check",
                    user_intent=combined_tone,
                    instructions="Is the tone of the candidate model response informal, casual, or not formal enough for a professional reply?",
                    threshold=tone_thresh,
                    enabled=True,
                )
            )
            existing_keys.add("non_formal_tone_check")
            handled_concepts.add("tone")

        # General conditional rules in other sentences ("If <X> above <Y%> ... route to <tier>")
        for sent in sentences:
            sl = sent.lower()
            if sent in chitchat_sentences or sent in tone_sentences:
                continue
            if "except if" in sl or "unless " in sl:
                continue
            has_cond = ("if " in sl or "when " in sl or "above " in sl or "over " in sl or ">=" in sl or "%" in sl)
            has_route_verb = any(
                v in sl for v in ("route", "send", "sent", "use ", "escalate", "higher tier", "lower tier", "carbon", "neon", "flash")
            )
            if has_cond and has_route_verb:
                thresh = _extract_threshold(sent, default=0.75)
                # Extract subject before "with a probability" / "above" / "i want"
                subj_part = re.split(
                    r"(?:with a probability|is above|should be above|above|>=|,?\s*i want|,?\s*send|,?\s*route|,?\s*use\b)",
                    sent,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                concept = _clean_concept_phrase(subj_part)
                if len(concept) < 3:
                    concept = "High-Risk Condition"
                title = concept[:48].title()
                key = re.sub(r"[^a-z0-9]+", "_", concept.lower()).strip("_")[:40] or "custom_rule"
                if key in existing_keys:
                    key = f"{key}_{len(existing_keys) + 1}"

                if any(w in sl for w in ("lower tier", "lowest tier", "flash", "cheapest", "simple")):
                    act: Literal["min_tier", "route_to_tier", "bump_one_tier"] = "route_to_tier"
                    t_tier = TierLevel.SIMPLE
                elif any(w in sl for w in ("next higher", "next tier", "+1")):
                    act = "bump_one_tier"
                    t_tier = TierLevel.COMPLEX
                elif any(w in sl for w in ("carbon", "expert", "top tier", "highest tier", "strongest")):
                    act = "min_tier"
                    t_tier = TierLevel.EXPERT
                else:
                    act = "min_tier"
                    t_tier = TierLevel.COMPLEX

                hard_gates.append(
                    HardGateQuestion(
                        key=key,
                        label=f"{title} Rule",
                        user_intent=sent,
                        instructions=f"Does this request involve {concept.lower()}?",
                        threshold=thresh,
                        action=act,
                        min_tier=t_tier,
                        enabled=True,
                    )
                )
                existing_keys.add(key)

        # Pass 2: Extract clear Weighted Scoring Topics!
        if any(w in full_lower for w in ("thinking", "reasoning", "logic", "analytical", "complexity")) and "thinking_level" not in existing_keys:
            topics.append(
                TopicQuestion(
                    key="thinking_level",
                    label="Level of Thinking Needed",
                    user_intent="Route requests based on the level of thinking / reasoning needed.",
                    call_stage=2,
                    type="score",
                    weight=0.50,
                    instructions="How much multi-step logical thinking and reasoning is required to answer this request accurately?",
                    criteria=[
                        "Minimal thinking: direct fact, greeting, or simple formatting.",
                        "Moderate thinking: clear explanation, summary, or straightforward task.",
                        "High thinking: multi-step analysis, trade-offs, or complex problem solving.",
                        "Deep reasoning: hard edge cases, formal logic, or frontier synthesis.",
                    ],
                    enabled=True,
                )
            )
            existing_keys.add("thinking_level")
            handled_concepts.add("thinking")

        if any(w in full_lower for w in ("hallucinat", "factual", "fabricat", "grounding", "truth", "accuracy")) and "hallucination_risk" not in existing_keys:
            topics.append(
                TopicQuestion(
                    key="hallucination_risk",
                    label="Hallucination & Factual Error Risk",
                    user_intent="Account for the risk of the LLM hallucinating or making factual errors.",
                    call_stage=2,
                    type="score",
                    weight=0.50,
                    instructions="How high is the risk that a smaller LLM will hallucinate facts, invent details, or give an inaccurate answer to this prompt?",
                    criteria=[
                        "Very low risk: open-ended chat, opinion, or user-supplied text transformation.",
                        "Moderate risk: widely known concepts with low ambiguity.",
                        "High risk: specific technical, historical, legal, or numerical claims.",
                        "Severe risk: niche facts, strict precision required, or high consequence of error.",
                    ],
                    enabled=True,
                )
            )
            existing_keys.add("hallucination_risk")
            handled_concepts.add("hallucination")

        if any(w in full_lower for w in ("code", "coding", "programming", "software", "sql", "debug", "architecture")) and "code_complexity" not in existing_keys:
            topics.append(
                TopicQuestion(
                    key="code_complexity",
                    label="Code & Engineering Complexity",
                    user_intent="Evaluate software coding or architectural complexity.",
                    call_stage=2,
                    type="score",
                    weight=0.50,
                    instructions="What level of coding, debugging, or system architecture complexity does this request require?",
                    criteria=[
                        "No coding or trivial syntax.",
                        "Single self-contained function or simple script.",
                        "Multi-component engineering, concurrency, or tricky debugging.",
                        "Complex distributed architecture, security-critical code, or deep optimization.",
                    ],
                    enabled=True,
                )
            )
            existing_keys.add("code_complexity")
            handled_concepts.add("code")

        if ("tone" in full_lower or "formal" in full_lower) and "tone" not in handled_concepts and "formality_requirement" not in existing_keys:
            topics.append(
                TopicQuestion(
                    key="formality_requirement",
                    label="Formal Tone Requirement",
                    user_intent="Evaluate how strictly the request requires a polished, formal tone.",
                    call_stage=2,
                    type="score",
                    weight=0.35,
                    instructions="How strictly does this request require a formal, executive, or carefully nuanced professional tone?",
                    criteria=[
                        "Casual tone is fine.",
                        "Standard neutral helpful tone.",
                        "Polished professional business tone required.",
                        "Strict executive, legal, or diplomatic formality required.",
                    ],
                    enabled=True,
                )
            )
            existing_keys.add("formality_requirement")

        # Fallback if the user named a completely custom domain (e.g. "medical urgency" or "creative writing flair")
        if not topics:
            first_clean = _clean_concept_phrase(sentences[0]) if sentences else "Task Complexity"
            if len(first_clean) < 3 or len(first_clean) > 55:
                first_clean = "Overall Task Complexity"
            title = first_clean.title()
            key = re.sub(r"[^a-z0-9]+", "_", first_clean.lower()).strip("_")[:40] or "task_complexity"
            topics.append(
                TopicQuestion(
                    key=key,
                    label=title,
                    user_intent=sentences[0] if sentences else message,
                    call_stage=2,
                    type="score",
                    weight=1.0,
                    instructions=f"What level of capability is required regarding {first_clean.lower()}?",
                    criteria=[
                        f"Minimal ({first_clean.lower()} is trivial).",
                        f"Moderate standard requirement.",
                        f"High multi-step requirement.",
                        f"Maximum frontier capability required.",
                    ],
                    enabled=True,
                )
            )

        # Normalize topic weights so shares add cleanly (e.g., 0.50 + 0.50 = 1.00)
        enabled_t = [t for t in topics if t.enabled]
        if enabled_t and current_spec is None:
            even_w = round(1.0 / len(enabled_t), 2)
            for t in enabled_t:
                t.weight = even_w

        # Pass 3: Cost vs Risk Cutoffs
        wants_cost_effective = any(
            k in full_lower
            for k in ("cost effective", "cost-effective", "cheapest", "save cost", "low cost", "economy", "budget")
        )
        wants_strict_quality = any(
            k in full_lower
            for k in ("highest quality", "maximum accuracy", "strictly", "conservative")
        ) and not wants_cost_effective

        if wants_cost_effective:
            cutoffs = TierCutoffs(standard=0.35, complex=0.62, expert=0.84)
            strategy_phrase = "Targets the most cost-effective model by default, escalating only when topic risk scores are high"
        elif wants_strict_quality:
            cutoffs = TierCutoffs(standard=0.20, complex=0.48, expert=0.74)
            strategy_phrase = "Prioritizes higher-tier models earlier to minimize quality risk"
        else:
            strategy_phrase = "Balances cost and model capability across your topics"

        qg_spec = QualityGateSpec(
            enabled=True,
            threshold=0.70,
            custom_checks=post_checks,
        )

        final_spec = RouterSpec(
            id="user_custom_router",
            name="Custom Decision-Grounded Router",
            description=strategy_phrase,
            execution_mode=current_spec.execution_mode if current_spec else "staged",
            models=current_spec.models if current_spec else default_candidate_llm_pool(),
            hard_gates=hard_gates,
            topics=topics,
            tier_cutoffs=cutoffs,
            confidence_threshold=current_spec.confidence_threshold if current_spec else 0.68,
            quality_gate=qg_spec,
            feedback_history=(list(current_spec.feedback_history) if current_spec else []),
        )

        # Build crisp one-sentence summary headline
        parts_summary = []
        if hard_gates:
            parts_summary.append(f"{len(hard_gates)} input shortcut/guardrail rule(s)")
        parts_summary.append(
            f"{len(enabled_t)} weighted topic(s) ({', '.join(t.label for t in enabled_t)})"
        )
        if post_checks:
            parts_summary.append(f"{len(post_checks)} post-answer escalation check(s)")
        headline = f"{strategy_phrase} — using " + ", ".join(parts_summary) + "."

        now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        final_spec.feedback_history.append(
            FeedbackEntry(
                timestamp=now_iso,
                user_feedback=message,
                summary=headline[:180],
                skills_used=["topic-threshold-discovery", "feedback-to-decisions-translator"],
            )
        )

        steps = build_human_translation_steps(final_spec)
        diffs = compute_spec_diff(current_spec, final_spec)

        return ArchitectChatResponse(
            reply_markdown=f"### How Your Rules Were Translated\n\n{headline}",
            summary_headline=headline,
            translation_steps=steps,
            active_skills=["topic-threshold-discovery", "feedback-to-decisions-translator"],
            intent_detected="feedback_translation",
            proposed_spec=final_spec,
            changes=diffs,
            validation_passed=True,
            mode=mode,
        )
