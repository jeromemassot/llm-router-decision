"""Multi-call Decision-Grounded LLM Routing Engine with Human-Readable Rules, Weighted Scoring & Post-Gen Escalation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.decisions_client import DecisionsGateway
from backend.schemas import (
    CandidateModel,
    DecisionCallTrace,
    HardGateEvaluation,
    LLMGenerationTrace,
    NormalizedTopicScore,
    PostCheckResult,
    QualityGateTrace,
    RouteResult,
    RouterSpec,
    RoutingResolution,
    TierLevel,
    next_tier_up,
    tier_rank,
)


def load_router_spec(path: Path) -> RouterSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    return RouterSpec.model_validate(data)


class DecisionGroundedRouter:
    """
    Executes the custom Decision-Grounded LLM Routing pipeline in clear stages:
      1. Call #1 (Input Shortcut & Guardrail Rules + Stage-1 Topics) -> `gemini-decision-1`
      2. Call #2 (Weighted Scoring Topics)                           -> `gemini-decision-1`
      3. Rule & Weighted Score Resolution                            -> selects candidate LLM
      4. Target LLM Generation                                       -> `client.interactions.create`
      5. Call #3 (Post-Answer Checks & Quality Gate)                 -> `gemini-decision-1` (+1 tier escalation)
    """

    def __init__(self, gateway: Optional[DecisionsGateway] = None) -> None:
        self.gateway = gateway or DecisionsGateway()
        self.history: List[RouteResult] = []

    @staticmethod
    def _build_gate_question_payload(gate_obj: Any) -> Dict[str, Any]:
        q: Dict[str, Any] = {
            "type": "noul",
            "instructions": gate_obj.instructions,
        }
        if gate_obj.true_description or gate_obj.false_description:
            q["criteria"] = {
                "true_description": gate_obj.true_description or "Yes, condition applies.",
                "false_description": gate_obj.false_description or "No, condition does not apply.",
            }
        return q

    @staticmethod
    def _build_topic_question_payload(topic_obj: Any) -> Dict[str, Any]:
        q: Dict[str, Any] = {
            "type": topic_obj.type,
            "instructions": topic_obj.instructions,
        }
        if topic_obj.type == "noul":
            if topic_obj.true_description or topic_obj.false_description:
                q["criteria"] = {
                    "true_description": topic_obj.true_description or "Yes.",
                    "false_description": topic_obj.false_description or "No.",
                }
        elif topic_obj.type in ("choice", "score"):
            q["criteria"] = topic_obj.criteria
        return q

    @staticmethod
    def _model_by_tier(spec: RouterSpec, tier: TierLevel) -> CandidateModel:
        exact = [m for m in spec.models if m.tier == tier]
        if exact:
            return exact[0]
        sorted_models = sorted(spec.models, key=lambda m: abs(tier_rank(m.tier) - tier_rank(tier)))
        return sorted_models[0]

    @staticmethod
    def _model_by_id(spec: RouterSpec, model_id: str) -> Optional[CandidateModel]:
        for m in spec.models:
            if m.model_id == model_id:
                return m
        return None

    @staticmethod
    def _ceiling_model(spec: RouterSpec) -> CandidateModel:
        return max(spec.models, key=lambda m: (tier_rank(m.tier), m.output_price_per_1m))

    def resolve_from_answers(
        self,
        spec: RouterSpec,
        hard_gate_answers: Dict[str, Any],
        topic_answers: Dict[str, Any],
    ) -> Tuple[List[HardGateEvaluation], List[NormalizedTopicScore], RoutingResolution]:
        """
        Normalize Decision API answers, compute weighted composite score S in [0, 1],
        and apply input shortcut/guardrail rules (`route_to_tier`, `min_tier`, `bump_one_tier`).
        """
        explanation: List[str] = []

        # 1. Topic Normalization & Weighted Composite Score
        enabled_topics = [t for t in spec.topics if t.enabled and t.weight > 0]
        total_weight = sum(t.weight for t in enabled_topics) or 1.0
        topic_scores: List[NormalizedTopicScore] = []

        for t in enabled_topics:
            ans = topic_answers.get(t.key, {})
            share = t.weight / total_weight
            probs = ans.get("probabilities")
            legend = ans.get("legend")
            conf = float(ans.get("confidence", 0.80))

            if t.type == "noul":
                raw_p = float(ans.get("noul", 0.5))
                norm = (1.0 - raw_p) if t.invert else raw_p
                raw_val: Any = round(raw_p, 4)
            elif t.type == "score":
                k_levels = len(t.criteria) if isinstance(t.criteria, list) else 2
                raw_s = float(ans.get("score", 0.0))
                norm = raw_s / max(1, k_levels - 1)
                raw_val = round(raw_s, 4)
            else:
                top_choice = str(ans.get("choice", ""))
                dist = probs or {}
                affinities = t.option_affinities or {}
                if dist and affinities:
                    norm = sum(float(p) * float(affinities.get(opt, 0.4)) for opt, p in dist.items())
                else:
                    norm = float(affinities.get(top_choice, 0.4))
                raw_val = top_choice

            norm = max(0.0, min(1.0, norm))
            contrib = share * norm
            topic_scores.append(
                NormalizedTopicScore(
                    key=t.key,
                    label=t.label,
                    instructions=t.instructions,
                    call_stage=t.call_stage,
                    type=t.type,
                    raw_value=raw_val,
                    normalized_score=round(norm, 4),
                    weight=t.weight,
                    effective_weight_share=round(share, 4),
                    weighted_contribution=round(contrib, 4),
                    confidence=round(conf, 4),
                    probabilities=probs,
                    legend=legend,
                    invert=t.invert,
                )
            )

        composite_score = round(sum(ts.weighted_contribution for ts in topic_scores), 4)
        aggregate_conf = round(
            sum(ts.effective_weight_share * ts.confidence for ts in topic_scores), 4
        )

        c = spec.tier_cutoffs
        if composite_score >= c.expert:
            score_tier = TierLevel.EXPERT
        elif composite_score >= c.complex:
            score_tier = TierLevel.COMPLEX
        elif composite_score >= c.standard:
            score_tier = TierLevel.STANDARD
        else:
            score_tier = TierLevel.SIMPLE

        explanation.append(
            f"Weighted Topic Score = {composite_score * 100:.1f}% -> base tier {score_tier.value} "
            f"(cutoffs: STANDARD >= {c.standard * 100:.0f}%, COMPLEX >= {c.complex * 100:.0f}%, EXPERT >= {c.expert * 100:.0f}%)."
        )

        resolved_tier = score_tier

        # 2. Input Shortcut & Guardrail Rules (`hard_gates`)
        gate_evals: List[HardGateEvaluation] = []
        hard_gate_min_tier: Optional[TierLevel] = None
        pinned_shortcut_tier: Optional[TierLevel] = None
        bump_count = 0
        triggered_labels: List[str] = []

        for g in spec.hard_gates:
            if not g.enabled:
                continue
            ans = hard_gate_answers.get(g.key, {})
            noul_val = float(ans.get("noul", 0.01))
            conf_val = float(ans.get("confidence", max(noul_val, 1.0 - noul_val)))
            triggered = (noul_val >= g.threshold) and (conf_val >= g.min_confidence)
            effect_desc = g.describe_action_human()

            gate_evals.append(
                HardGateEvaluation(
                    key=g.key,
                    label=g.label,
                    instructions=g.instructions,
                    noul=round(noul_val, 4),
                    confidence=round(conf_val, 4),
                    threshold=g.threshold,
                    min_confidence=g.min_confidence,
                    action=g.action,
                    min_tier=g.min_tier,
                    triggered=triggered,
                    effect_summary=effect_desc,
                )
            )
            if triggered:
                pct_str = f"{noul_val * 100:.0f}% >= {g.threshold * 100:.0f}%"
                if g.action == "route_to_tier":
                    pinned_shortcut_tier = g.min_tier
                    triggered_labels.append(f"{g.label} ({pct_str} -> {g.min_tier.value})")
                elif g.action == "bump_one_tier":
                    bump_count += 1
                    triggered_labels.append(f"{g.label} ({pct_str} -> +1 tier)")
                else:
                    if hard_gate_min_tier is None or tier_rank(g.min_tier) > tier_rank(hard_gate_min_tier):
                        hard_gate_min_tier = g.min_tier
                    triggered_labels.append(f"{g.label} ({pct_str} -> min {g.min_tier.value})")

        # Apply shortcut pin (e.g., Chit-Chat >= 90% -> Flash-Lite) first
        if pinned_shortcut_tier is not None:
            explanation.append(
                f"Input Shortcut Rule matched: routed directly to {pinned_shortcut_tier.value} tier ({'; '.join(triggered_labels)})."
            )
            resolved_tier = pinned_shortcut_tier

        # Apply +1 tier bump rules
        for _ in range(bump_count):
            prev = resolved_tier
            resolved_tier = next_tier_up(resolved_tier)
            if resolved_tier != prev:
                explanation.append(f"Input Escalation Rule bumped tier {prev.value} -> {resolved_tier.value}.")

        # Apply minimum tier safety floor (safety floor overrides downward shortcuts if both match)
        if hard_gate_min_tier is not None and tier_rank(hard_gate_min_tier) > tier_rank(resolved_tier):
            explanation.append(
                f"Guardrail Rule enforced minimum tier {resolved_tier.value} -> {hard_gate_min_tier.value}."
            )
            resolved_tier = hard_gate_min_tier

        # 3. Low-Confidence Escalation (skip if an explicit high-confidence shortcut pinned SIMPLE)
        confidence_escalated = False
        if (
            pinned_shortcut_tier is None
            and spec.escalate_on_low_confidence
            and aggregate_conf < spec.confidence_threshold
            and resolved_tier != TierLevel.EXPERT
        ):
            bumped = next_tier_up(resolved_tier)
            explanation.append(
                f"Decision confidence {aggregate_conf * 100:.0f}% < {spec.confidence_threshold * 100:.0f}% floor: escalated {resolved_tier.value} -> {bumped.value}."
            )
            resolved_tier = bumped
            confidence_escalated = True

        chosen_model = self._model_by_tier(spec, resolved_tier)
        explanation.append(
            f"Selected model: {chosen_model.display_name} ({chosen_model.model_id})."
        )

        resolution = RoutingResolution(
            composite_score=composite_score,
            aggregate_confidence=aggregate_conf,
            score_tier=score_tier,
            hard_gate_min_tier=hard_gate_min_tier,
            triggered_gates=triggered_labels,
            confidence_escalated=confidence_escalated,
            resolved_tier=resolved_tier,
            selected_model_id=chosen_model.model_id,
            selected_model_name=chosen_model.display_name,
            explanation=explanation,
        )
        return gate_evals, topic_scores, resolution

    def route(
        self,
        prompt: str,
        spec: RouterSpec,
        simulate_low_quality_first_attempt: bool = False,
        skip_generation: bool = False,
        force_simulation: bool = False,
    ) -> RouteResult:
        """Run the end-to-end Decision-Grounded routing pipeline and return full visual trace."""
        decision_calls: List[DecisionCallTrace] = []
        hard_gate_answers: Dict[str, Any] = {}
        topic_answers: Dict[str, Any] = {}

        stage1_gates = [g for g in spec.hard_gates if g.enabled]
        stage1_topics = [t for t in spec.topics if t.enabled and t.weight > 0 and t.call_stage == 1]
        stage2_topics = [t for t in spec.topics if t.enabled and t.weight > 0 and t.call_stage == 2]

        if spec.execution_mode == "staged" and stage2_topics and (stage1_gates or stage1_topics):
            q1: Dict[str, Dict[str, Any]] = {}
            for g in stage1_gates:
                q1[g.key] = self._build_gate_question_payload(g)
            for t in stage1_topics:
                q1[t.key] = self._build_topic_question_payload(t)

            resp1, tok1, cost1, lat1, mode1 = self.gateway.create_decision(
                input_payload=prompt,
                questions=q1,
                force_simulation=force_simulation,
            )
            decision_calls.append(
                DecisionCallTrace(
                    call_index=1,
                    stage_name="Call #1 · Input Shortcut & Guardrail Checks",
                    purpose="Checks binary Yes/No rules (such as chit-chat shortcuts or safety guardrails) before scoring topics.",
                    mode=mode1,
                    request_payload={"model": "gemini-decision-1", "input": prompt, "questions": q1},
                    response_payload=resp1,
                    input_tokens=tok1,
                    output_tokens=0,
                    cost_usd=cost1,
                    latency_ms=lat1,
                )
            )
            ans1 = resp1.get("answers", {})
            for g in stage1_gates:
                hard_gate_answers[g.key] = ans1.get(g.key, {})
            for t in stage1_topics:
                topic_answers[t.key] = ans1.get(t.key, {})

            q2: Dict[str, Dict[str, Any]] = {
                t.key: self._build_topic_question_payload(t) for t in stage2_topics
            }
            resp2, tok2, cost2, lat2, mode2 = self.gateway.create_decision(
                input_payload=prompt,
                questions=q2,
                force_simulation=force_simulation,
            )
            decision_calls.append(
                DecisionCallTrace(
                    call_index=2,
                    stage_name="Call #2 · Weighted Topic Scoring",
                    purpose="Evaluates each routing topic on a calibrated scale so weights can pick the most cost-effective model.",
                    mode=mode2,
                    request_payload={"model": "gemini-decision-1", "input": prompt, "questions": q2},
                    response_payload=resp2,
                    input_tokens=tok2,
                    output_tokens=0,
                    cost_usd=cost2,
                    latency_ms=lat2,
                )
            )
            ans2 = resp2.get("answers", {})
            for t in stage2_topics:
                topic_answers[t.key] = ans2.get(t.key, {})
            active_mode = mode2
        else:
            q_all: Dict[str, Dict[str, Any]] = {}
            for g in stage1_gates:
                q_all[g.key] = self._build_gate_question_payload(g)
            for t in stage1_topics + stage2_topics:
                q_all[t.key] = self._build_topic_question_payload(t)

            resp_all, tok_all, cost_all, lat_all, active_mode = self.gateway.create_decision(
                input_payload=prompt,
                questions=q_all,
                force_simulation=force_simulation,
            )
            decision_calls.append(
                DecisionCallTrace(
                    call_index=1,
                    stage_name="Call #1 · All Input Rules & Topics (Single Pass)",
                    purpose="Evaluates all input shortcut rules and weighted topics together in one Gemini Decision 1 pass.",
                    mode=active_mode,
                    request_payload={"model": "gemini-decision-1", "input": prompt, "questions": q_all},
                    response_payload=resp_all,
                    input_tokens=tok_all,
                    output_tokens=0,
                    cost_usd=cost_all,
                    latency_ms=lat_all,
                )
            )
            ans_all = resp_all.get("answers", {})
            for g in stage1_gates:
                hard_gate_answers[g.key] = ans_all.get(g.key, {})
            for t in stage1_topics + stage2_topics:
                topic_answers[t.key] = ans_all.get(t.key, {})

        gate_evals, topic_scores, resolution = self.resolve_from_answers(
            spec=spec,
            hard_gate_answers=hard_gate_answers,
            topic_answers=topic_answers,
        )

        initial_model = self._model_by_id(spec, resolution.selected_model_id) or self._model_by_tier(
            spec, resolution.resolved_tier
        )
        generations: List[LLMGenerationTrace] = []

        if skip_generation:
            total_cost = sum(dc.cost_usd for dc in decision_calls)
            total_lat = sum(dc.latency_ms for dc in decision_calls)
            ceil = self._ceiling_model(spec)
            est_in = max(8, len(prompt) // 4)
            ceil_cost = (est_in * ceil.input_price_per_1m + 350 * ceil.output_price_per_1m) / 1_000_000
            return RouteResult(
                prompt=prompt,
                mode=active_mode,
                execution_mode=spec.execution_mode,
                decision_calls=decision_calls,
                hard_gate_evaluations=gate_evals,
                topic_scores=topic_scores,
                resolution=resolution,
                generations=[],
                quality_gate=QualityGateTrace(executed=False, threshold=spec.quality_gate.threshold),
                final_model_id=initial_model.model_id,
                final_model_name=initial_model.display_name,
                final_tier=initial_model.tier,
                final_response="(Generation skipped.)",
                total_cost_usd=round(total_cost, 7),
                ceiling_equivalent_cost_usd=round(ceil_cost, 7),
                saved_vs_ceiling_usd=round(max(0.0, ceil_cost - total_cost), 7),
                savings_pct=round(max(0.0, (ceil_cost - total_cost) / ceil_cost * 100) if ceil_cost > 0 else 0.0, 1),
                total_latency_ms=round(total_lat, 1),
            )

        # --- TARGET LLM GENERATION (Attempt 1) ---
        resp_text, in_tok, out_tok, gen_cost, gen_lat, gen_mode = self.gateway.generate_target_response(
            model_id=initial_model.model_id,
            display_name=initial_model.display_name,
            tier=initial_model.tier.value,
            prompt=prompt,
            max_output_tokens=initial_model.max_output_tokens,
            input_price_per_1m=initial_model.input_price_per_1m,
            output_price_per_1m=initial_model.output_price_per_1m,
            typical_latency_ms=initial_model.typical_latency_ms,
            force_simulation=force_simulation,
            simulate_low_quality=simulate_low_quality_first_attempt,
        )
        generations.append(
            LLMGenerationTrace(
                attempt_number=1,
                tier=initial_model.tier,
                model_id=initial_model.model_id,
                display_name=initial_model.display_name,
                mode=gen_mode,
                response_text=resp_text,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=round(gen_cost, 7),
                latency_ms=gen_lat,
            )
        )

        final_model = initial_model
        final_text = resp_text

        # --- CALL #3: Post-Generation Output Checks & Quality Gate ---
        enabled_post_checks = [pc for pc in spec.quality_gate.custom_checks if pc.enabled]
        has_fallback = bool(initial_model.fallback_model_id) and (
            self._model_by_id(spec, initial_model.fallback_model_id) is not None
        )

        if (spec.quality_gate.enabled or enabled_post_checks) and has_fallback:
            qg_input = [
                {"type": "text", "text": f"User Prompt:\n{prompt}\n\n"},
                {"type": "text", "text": f"Candidate Model Response:\n{resp_text[:3000]}"},
            ]
            qg_questions: Dict[str, Dict[str, Any]] = {
                "response_quality_rubric": {
                    "type": "score",
                    "instructions": spec.quality_gate.instructions,
                    "criteria": spec.quality_gate.criteria,
                },
                "satisfies_constraints": {
                    "type": "noul",
                    "instructions": spec.quality_gate.constraint_check_instructions,
                },
            }
            for pc in enabled_post_checks:
                qg_questions[pc.key] = {
                    "type": "noul",
                    "instructions": pc.instructions,
                }

            qg_resp, qg_tok, qg_cost, qg_lat, qg_mode = self.gateway.create_decision(
                input_payload=qg_input,
                questions=qg_questions,
                force_simulation=force_simulation,
                simulate_low_quality=simulate_low_quality_first_attempt,
            )
            qg_call_idx = len(decision_calls) + 1
            qg_trace_call = DecisionCallTrace(
                call_index=qg_call_idx,
                stage_name=f"Call #{qg_call_idx} · Post-Answer Checks & Escalation Gate",
                purpose="Verifies the draft answer (tone, quality, and constraints) with 0 output tokens; escalates +1 tier if any check fails.",
                mode=qg_mode,
                request_payload={"model": "gemini-decision-1", "input": qg_input, "questions": qg_questions},
                response_payload=qg_resp,
                input_tokens=qg_tok,
                output_tokens=0,
                cost_usd=qg_cost,
                latency_ms=qg_lat,
            )
            decision_calls.append(qg_trace_call)

            qg_ans = qg_resp.get("answers", {})
            rubric_ans = qg_ans.get("response_quality_rubric", {})
            constr_ans = qg_ans.get("satisfies_constraints", {})

            k_qg = max(2, len(spec.quality_gate.criteria))
            raw_rubric = float(rubric_ans.get("score", k_qg - 1))
            norm_rubric = raw_rubric / (k_qg - 1)
            constr_noul = float(constr_ans.get("noul", 0.9))
            norm_quality = round(0.75 * norm_rubric + 0.25 * constr_noul, 4)
            qg_conf = round(float(rubric_ans.get("confidence", 0.85)), 4)

            custom_results: List[PostCheckResult] = []
            triggered_post_reasons: List[str] = []
            for pc in enabled_post_checks:
                pc_noul = float(qg_ans.get(pc.key, {}).get("noul", 0.05))
                fired = pc_noul >= pc.threshold
                custom_results.append(
                    PostCheckResult(
                        key=pc.key,
                        label=pc.label,
                        instructions=pc.instructions,
                        noul=round(pc_noul, 4),
                        threshold=pc.threshold,
                        triggered_escalation=fired,
                    )
                )
                if fired:
                    triggered_post_reasons.append(
                        f"{pc.label} scored {pc_noul * 100:.0f}% (>= {pc.threshold * 100:.0f}% limit)"
                    )

            quality_ok = (not spec.quality_gate.enabled) or (norm_quality > spec.quality_gate.threshold)
            passed = quality_ok and (len(triggered_post_reasons) == 0)

            fallback_triggered = False
            fallback_reason: Optional[str] = None
            fb_from: Optional[str] = None
            fb_to: Optional[str] = None

            if not passed and initial_model.fallback_model_id:
                fb_model = self._model_by_id(spec, initial_model.fallback_model_id)
                if fb_model is not None:
                    fallback_triggered = True
                    fb_from = initial_model.model_id
                    fb_to = fb_model.model_id
                    if triggered_post_reasons:
                        fallback_reason = "; ".join(triggered_post_reasons)
                    else:
                        fallback_reason = (
                            f"Overall quality {norm_quality * 100:.0f}% <= {spec.quality_gate.threshold * 100:.0f}% threshold"
                        )

                    fb_text, fb_in, fb_out, fb_cost, fb_lat, fb_mode = self.gateway.generate_target_response(
                        model_id=fb_model.model_id,
                        display_name=fb_model.display_name,
                        tier=fb_model.tier.value,
                        prompt=prompt,
                        max_output_tokens=fb_model.max_output_tokens,
                        input_price_per_1m=fb_model.input_price_per_1m,
                        output_price_per_1m=fb_model.output_price_per_1m,
                        typical_latency_ms=fb_model.typical_latency_ms,
                        force_simulation=force_simulation,
                        simulate_low_quality=False,
                    )
                    generations.append(
                        LLMGenerationTrace(
                            attempt_number=2,
                            tier=fb_model.tier,
                            model_id=fb_model.model_id,
                            display_name=fb_model.display_name,
                            mode=fb_mode,
                            response_text=fb_text,
                            input_tokens=fb_in,
                            output_tokens=out_tok if not fb_out else fb_out,
                            cost_usd=round(fb_cost, 7),
                            latency_ms=fb_lat,
                        )
                    )
                    final_model = fb_model
                    final_text = fb_text

            quality_gate_trace = QualityGateTrace(
                executed=True,
                passed=passed,
                normalized_quality=norm_quality,
                quality_10_scale=round(1.0 + norm_quality * 9.0, 2),
                raw_rubric_score=round(raw_rubric, 4),
                satisfies_constraints_noul=round(constr_noul, 4),
                custom_check_results=custom_results,
                confidence=qg_conf,
                threshold=spec.quality_gate.threshold,
                fallback_triggered=fallback_triggered,
                fallback_reason=fallback_reason,
                fallback_from_model=fb_from,
                fallback_to_model=fb_to,
                decision_call=qg_trace_call,
            )
        else:
            est_q = 0.94 if final_model.tier == TierLevel.EXPERT else 0.88
            quality_gate_trace = QualityGateTrace(
                executed=False,
                passed=True,
                normalized_quality=est_q,
                quality_10_scale=round(1.0 + est_q * 9.0, 2),
                threshold=spec.quality_gate.threshold,
            )

        total_cost = sum(dc.cost_usd for dc in decision_calls) + sum(g.cost_usd for g in generations)
        total_lat = sum(dc.latency_ms for dc in decision_calls) + sum(g.latency_ms for g in generations)

        ceiling = self._ceiling_model(spec)
        last_gen = generations[-1]
        ceiling_cost = (
            last_gen.input_tokens * ceiling.input_price_per_1m
            + last_gen.output_tokens * ceiling.output_price_per_1m
        ) / 1_000_000
        saved = ceiling_cost - total_cost
        savings_pct = (saved / ceiling_cost * 100.0) if ceiling_cost > 0 else 0.0

        result = RouteResult(
            prompt=prompt,
            mode=active_mode,
            execution_mode=spec.execution_mode,
            decision_calls=decision_calls,
            hard_gate_evaluations=gate_evals,
            topic_scores=topic_scores,
            resolution=resolution,
            generations=generations,
            quality_gate=quality_gate_trace,
            final_model_id=final_model.model_id,
            final_model_name=final_model.display_name,
            final_tier=final_model.tier,
            final_response=final_text,
            total_cost_usd=round(total_cost, 7),
            ceiling_equivalent_cost_usd=round(ceiling_cost, 7),
            saved_vs_ceiling_usd=round(saved, 7),
            savings_pct=round(savings_pct, 1),
            total_latency_ms=round(total_lat, 1),
        )
        self.history.append(result)
        return result

    def get_cumulative_stats(self) -> Dict[str, Any]:
        n = len(self.history)
        if n == 0:
            return {
                "total_routed": 0,
                "total_cost_usd": 0.0,
                "ceiling_equivalent_cost_usd": 0.0,
                "saved_usd": 0.0,
                "savings_pct": 0.0,
                "fallback_count": 0,
                "fallback_rate_pct": 0.0,
                "avg_latency_ms": 0.0,
                "avg_quality_10": None,
                "model_distribution": {},
                "tier_distribution": {},
            }

        tot_cost = sum(r.total_cost_usd for r in self.history)
        tot_ceil = sum(r.ceiling_equivalent_cost_usd for r in self.history)
        saved = tot_ceil - tot_cost
        fallbacks = sum(1 for r in self.history if r.quality_gate.fallback_triggered)
        q_vals = [
            r.quality_gate.quality_10_scale
            for r in self.history
            if r.quality_gate.quality_10_scale is not None
        ]
        model_dist: Dict[str, int] = {}
        tier_dist: Dict[str, int] = {}
        for r in self.history:
            model_dist[r.model_id if hasattr(r, "model_id") else r.final_model_id] = (
                model_dist.get(r.final_model_id, 0) + 1
            )
            tier_dist[r.final_tier.value] = tier_dist.get(r.final_tier.value, 0) + 1

        return {
            "total_routed": n,
            "total_cost_usd": round(tot_cost, 6),
            "ceiling_equivalent_cost_usd": round(tot_ceil, 6),
            "saved_usd": round(saved, 6),
            "savings_pct": round((saved / tot_ceil * 100.0) if tot_ceil > 0 else 0.0, 1),
            "fallback_count": fallbacks,
            "fallback_rate_pct": round(fallbacks / n * 100.0, 1),
            "avg_latency_ms": round(sum(r.total_latency_ms for r in self.history) / n, 1),
            "avg_quality_10": round(sum(q_vals) / len(q_vals), 2) if q_vals else None,
            "model_distribution": model_dist,
            "tier_distribution": tier_dist,
        }
