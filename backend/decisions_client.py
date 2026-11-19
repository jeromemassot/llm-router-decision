"""Google GenAI Decisions API (gemini-decision-1) & Interactions API client with calibrated simulation."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DECISION_MODEL_ID = "gemini-decision-1"
DECISION_INPUT_PRICE_PER_1M = 0.10  # $0.10 / 1M input tokens, $0.00 output tokens

_RUNTIME_API_KEY: Optional[str] = None


def set_runtime_api_key(api_key: Optional[str]) -> None:
    """Set or clear an in-memory GEMINI_API_KEY for the active local session."""
    global _RUNTIME_API_KEY
    cleaned = (api_key or "").strip()
    _RUNTIME_API_KEY = cleaned if cleaned else None


def get_active_api_key() -> Optional[str]:
    """Return active GEMINI_API_KEY from runtime session or environment."""
    if _RUNTIME_API_KEY:
        return _RUNTIME_API_KEY
    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return env_key.strip() if env_key and env_key.strip() else None


def has_live_api_key() -> bool:
    return get_active_api_key() is not None


def mask_api_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _approx_tokens(payload: Any) -> int:
    text = payload if isinstance(payload, str) else str(payload)
    return max(4, len(text) // 4)


def _clamp_noul(p: float) -> float:
    return round(min(0.99, max(0.01, p)), 4)


def _normalize_dist(raw: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(1e-6, v) for v in raw.values())
    norm = {k: round(max(1e-6, v) / total, 4) for k, v in raw.items()}
    # Adjust largest key so sum is 1.0000
    if norm:
        top_k = max(norm, key=lambda k: norm[k])
        diff = round(1.0 - sum(norm.values()), 4)
        norm[top_k] = round(max(0.0, min(1.0, norm[top_k] + diff)), 4)
    return norm


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "does", "what",
    "which", "when", "where", "how", "are", "is", "in", "to", "of", "or", "an",
    "be", "as", "on", "by", "at", "it", "user", "request", "prompt", "message",
    "task", "input", "model", "response", "candidate", "question", "level",
    "any", "all", "can", "would", "should", "about", "such", "than", "more",
}


def _extract_meaningful_tokens(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9_-]{3,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]


class DecisionsGateway:
    """Unified gateway for `gemini-decision-1` and routed Gemini target models."""

    # Curated semantic feature detectors for realistic offline simulation
    _EXPERT_SIGNALS = [
        "security audit", "threat model", "gdpr", "hipaa", "soc2", "pci-dss", "pci",
        "pii", "cryptograph", "kms", "consensus", "paxos", "raft", "split-brain",
        "event sourcing", "ledger", "novel", "mathematical", "reinforcement learning",
        "contextual bandit", "proof", "formal", "compliance", "zero-trust", "audit-log",
        "audit log", "multi-region", "byzantine",
    ]
    _COMPLEX_SIGNALS = [
        "implement", "design a", "design an", "distributed", "rate-limit", "rate limit",
        "token bucket", "lru", "thread-safe", "concurrency", "lock", "deadlock",
        "migration", "zero-downtime", "partition", "sharding", "postgres", "sql",
        "refactor", "debug", "exponential backoff", "architecture", "schema",
        "redis", "kubernetes", "terraform", "microservice", "rollback", "idempoten",
    ]
    _STANDARD_SIGNALS = [
        "explain", "summarize", "difference between", "differences between",
        "pros and cons", "compare", "how does", "how do", "acid", "tcp", "udp",
        "garbage collect", "docker", "solid", "typescript", "tls", "ssl", "dns",
        "overview", "example",
    ]
    _SIMPLE_SIGNALS = [
        "capital of", "translate", "stand for", "who wrote", "how many days",
        "leap year", "currency", "15% of", "what is 15%", "meaning of", "hello",
        "thank you", "good evening",
    ]

    def _get_genai_client(self) -> genai.Client:
        api_key = get_active_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        return genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

    def create_decision(
        self,
        input_payload: Union[str, List[Dict[str, Any]]],
        questions: Dict[str, Dict[str, Any]],
        force_simulation: bool = False,
        simulate_low_quality: bool = False,
    ) -> Tuple[Dict[str, Any], int, float, float, Literal["live", "simulation"]]:
        """
        Evaluate a map of typed questions (`noul`, `choice`, `score`) against shared input.

        Returns:
            (response_dict, input_tokens, cost_usd, latency_ms, mode)
        """
        use_live = has_live_api_key() and not force_simulation
        t0 = time.perf_counter()

        if use_live:
            client = self._get_genai_client()
            result = client.decisions.create(
                model=DECISION_MODEL_ID,
                input=input_payload,
                questions=questions,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            dumped = (
                result.model_dump(exclude_none=True)
                if hasattr(result, "model_dump")
                else dict(result)
            )
            usage = dumped.get("usage", {}) or {}
            in_tok = int(
                usage.get("total_input_tokens")
                or usage.get("total_tokens")
                or _approx_tokens({"input": input_payload, "questions": questions})
            )
            cost_usd = (in_tok * DECISION_INPUT_PRICE_PER_1M) / 1_000_000
            normalized_answers = self._normalize_live_answers(dumped.get("answers", {}), questions)
            response_payload = {
                "answers": normalized_answers,
                "usage": {
                    "total_input_tokens": in_tok,
                    "total_output_tokens": 0,
                    "total_tokens": in_tok,
                },
            }
            return response_payload, in_tok, cost_usd, latency_ms, "live"

        # Calibrated Simulation Mode
        sim_answers = self._simulate_decisions(
            input_payload=input_payload,
            questions=questions,
            simulate_low_quality=simulate_low_quality,
        )
        # Realistic 165-220ms tree-prefill latency visual representation (without blocking tests)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        pseudo_jitter = (int(hashlib.md5(str(questions.keys()).encode()).hexdigest()[:4], 16) % 55)
        latency_ms = round(max(elapsed_ms, 155.0 + pseudo_jitter), 1)
        in_tok = _approx_tokens({"input": input_payload, "questions": questions})
        cost_usd = (in_tok * DECISION_INPUT_PRICE_PER_1M) / 1_000_000
        response_payload = {
            "answers": sim_answers,
            "usage": {
                "total_input_tokens": in_tok,
                "total_output_tokens": 0,
                "total_tokens": in_tok,
            },
        }
        return response_payload, in_tok, cost_usd, latency_ms, "simulation"

    @staticmethod
    def _normalize_live_answers(
        raw_answers: Dict[str, Any],
        questions: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Ensure uniform field presence across SDK versions."""
        out: Dict[str, Any] = {}
        for key, q in questions.items():
            ans = raw_answers.get(key, {})
            if hasattr(ans, "model_dump"):
                ans = ans.model_dump(exclude_none=True)
            q_type = q["type"]
            if q_type == "noul":
                noul_val = _clamp_noul(float(ans.get("noul", 0.5)))
                conf = round(float(ans.get("confidence", max(noul_val, 1.0 - noul_val))), 4)
                out[key] = {"type": "noul", "noul": noul_val, "confidence": conf}
            elif q_type == "choice":
                probs = {k: float(v) for k, v in (ans.get("probabilities") or {}).items()}
                probs = _normalize_dist(probs) if probs else {}
                top_choice = ans.get("choice") or (max(probs, key=probs.get) if probs else "")
                conf = round(float(ans.get("confidence", probs.get(top_choice, 0.5))), 4)
                out[key] = {
                    "type": "choice",
                    "choice": top_choice,
                    "probabilities": probs,
                    "confidence": conf,
                }
            elif q_type == "score":
                criteria_list = list(q.get("criteria") or [])
                legend = ans.get("legend") or {str(i): c for i, c in enumerate(criteria_list)}
                probs = {str(k): float(v) for k, v in (ans.get("probabilities") or {}).items()}
                probs = _normalize_dist(probs) if probs else {}
                score_val = float(
                    ans.get(
                        "score",
                        sum(int(k) * v for k, v in probs.items()) if probs else 0.0,
                    )
                )
                conf = round(
                    float(ans.get("confidence", max(probs.values()) if probs else 0.5)), 4
                )
                out[key] = {
                    "type": "score",
                    "score": round(score_val, 4),
                    "legend": legend,
                    "probabilities": probs,
                    "confidence": conf,
                }
        return out

    def _simulate_decisions(
        self,
        input_payload: Union[str, List[Dict[str, Any]]],
        questions: Dict[str, Dict[str, Any]],
        simulate_low_quality: bool = False,
    ) -> Dict[str, Any]:
        """Deterministic calibrated simulator honoring `gemini-decision-1` semantics."""
        if isinstance(input_payload, list):
            full_text = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in input_payload
            )
        else:
            full_text = str(input_payload)

        tl = full_text.lower()
        prompt_tokens = set(_extract_meaningful_tokens(full_text))
        complexity_idx = self._analyze_prompt_complexity_index(full_text)
        is_quality_gate_input = "candidate model response:" in tl or "candidate response:" in tl

        answers: Dict[str, Any] = {}
        for key, q in questions.items():
            q_type = q["type"]
            instr = str(q.get("instructions", ""))
            instr_l = instr.lower()
            criteria = q.get("criteria")

            if q_type == "noul":
                p_yes = self._simulate_noul(
                    key=key,
                    instr=instr_l,
                    criteria=criteria if isinstance(criteria, dict) else {},
                    tl=tl,
                    prompt_tokens=prompt_tokens,
                    complexity_idx=complexity_idx,
                    is_quality_gate=is_quality_gate_input,
                    simulate_low_quality=simulate_low_quality,
                )
                noul_val = _clamp_noul(p_yes)
                conf = round(max(noul_val, 1.0 - noul_val), 4)
                answers[key] = {
                    "type": "noul",
                    "noul": noul_val,
                    "confidence": conf,
                }

            elif q_type == "choice":
                # Sort option keys alphabetically in UTF-8 byte order (matching real API!)
                opt_map: Dict[str, str] = dict(sorted((criteria or {}).items(), key=lambda kv: kv[0].encode("utf-8")))
                probs = self._simulate_choice(
                    opt_map=opt_map,
                    tl=tl,
                    prompt_tokens=prompt_tokens,
                    complexity_idx=complexity_idx,
                )
                # Break ties alphabetically
                winning = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0].encode("utf-8")))[0][0]
                answers[key] = {
                    "type": "choice",
                    "choice": winning,
                    "probabilities": probs,
                    "confidence": round(probs[winning], 4),
                }

            elif q_type == "score":
                levels: List[str] = list(criteria or [])
                probs, expected, legend = self._simulate_score(
                    key=key,
                    instr=instr_l,
                    levels=levels,
                    tl=tl,
                    prompt_tokens=prompt_tokens,
                    complexity_idx=complexity_idx,
                    is_quality_gate=is_quality_gate_input,
                    simulate_low_quality=simulate_low_quality,
                )
                answers[key] = {
                    "type": "score",
                    "score": expected,
                    "legend": legend,
                    "probabilities": probs,
                    "confidence": round(max(probs.values()), 4),
                }

        return answers

    def _analyze_prompt_complexity_index(self, text: str) -> float:
        tl = text.lower()
        expert_hits = sum(1 for s in self._EXPERT_SIGNALS if s in tl)
        complex_hits = sum(1 for s in self._COMPLEX_SIGNALS if s in tl)
        std_hits = sum(1 for s in self._STANDARD_SIGNALS if s in tl)
        simple_hits = sum(1 for s in self._SIMPLE_SIGNALS if s in tl)

        words = len(text.split())
        has_code = "```" in text or "def " in tl or "select " in tl or "create table" in tl

        raw = 0.22
        raw += min(expert_hits * 0.26, 0.65)
        raw += min(complex_hits * 0.16, 0.44)
        raw += min(std_hits * 0.07, 0.18)
        raw -= min(simple_hits * 0.20, 0.28)
        if words < 14 and expert_hits == 0 and complex_hits == 0:
            raw -= 0.10
        elif words > 35:
            raw += 0.08
        if words > 65:
            raw += 0.07
        if has_code:
            raw += 0.14

        return max(0.03, min(0.96, raw))

    def _simulate_noul(
        self,
        key: str,
        instr: str,
        criteria: Dict[str, str],
        tl: str,
        prompt_tokens: set[str],
        complexity_idx: float,
        is_quality_gate: bool,
        simulate_low_quality: bool,
    ) -> float:
        if is_quality_gate:
            # Custom post-generation negative-condition checks (e.g. "Is the tone informal / not formal enough?")
            is_risk_check = any(
                w in instr
                for w in ("informal", "not formal", "casual", "insufficient", "violation", "hallucinat", "unsafe", "error")
            )
            if is_risk_check:
                return 0.84 if (simulate_low_quality or "[low_quality_draft]" in tl) else 0.12
            if simulate_low_quality or "[low_quality_draft]" in tl:
                return 0.28
            return 0.93

        # Casual chit-chat / small talk detection in simulation mode
        if any(w in instr for w in ("chit-chat", "chitchat", "chit chat", "small talk", "casual", "greeting")):
            chitchat_hits = sum(
                1 for k in ("hi", "hello", "hey", "how are you", "good morning", "good evening", "what's up", "thanks", "thank you", "weather", "joke")
                if re.search(rf"\b{re.escape(k)}\b", tl)
            )
            if chitchat_hits >= 1 and len(tl.split()) <= 16:
                return 0.95
            return max(0.02, 0.18 - complexity_idx * 0.20)

        # Formal tone / style sensitivity detection in simulation mode
        if any(w in instr for w in ("formal", "professional", "tone", "executive", "polite")):
            formal_hits = sum(
                1 for k in ("executive", "board", "legal", "contract", "client", "formal", "memo", "official", "compliance", "regulator", "dear ")
                if k in tl
            )
            if formal_hits >= 1:
                return min(0.95, 0.55 + formal_hits * 0.22)
            return max(0.06, complexity_idx * 0.45)

        true_desc = str(criteria.get("true_description", ""))
        false_desc = str(criteria.get("false_description", ""))
        pos_tokens = set(_extract_meaningful_tokens(instr + " " + true_desc))
        neg_tokens = set(_extract_meaningful_tokens(false_desc))

        pos_overlap = len(prompt_tokens & pos_tokens)
        neg_overlap = len(prompt_tokens & neg_tokens)

        # Specialized high-precision calibration for common routing concepts
        if any(w in instr for w in ("security", "compliance", "gdpr", "hipaa", "soc2", "threat", "audit")):
            sec_hits = sum(
                1 for k in ("security", "audit", "threat", "gdpr", "hipaa", "soc2", "pci", "kms", "compliance", "vulnerability", "injection")
                if k in tl
            )
            return min(0.97, 0.04 + sec_hits * 0.34 + pos_overlap * 0.05)

        if any(w in instr for w in ("pii", "pci", "personally identifiable", "card", "encryption")):
            pii_hits = sum(
                1 for k in ("pii", "pci", "ssn", "card", "healthcare", "hipaa", "gdpr", "token", "secret", "kms", "auth")
                if k in tl
            )
            return min(0.97, 0.05 + pii_hits * 0.32)

        if any(w in instr for w in ("schema", "migration", "zero-downtime", "database", "ddl", "consensus", "failover")):
            db_hits = sum(
                1 for k in ("migration", "zero-downtime", "schema", "postgres", "partition", "sharding", "rollback", "consensus", "ledger", "multi-region")
                if k in tl
            )
            return min(0.96, 0.05 + db_hits * 0.33)

        if any(w in instr for w in ("simple", "single", "factual", "definition", "lookup", "translation")):
            return max(0.03, min(0.96, 1.0 - complexity_idx * 1.15))

        if any(w in instr for w in ("error", "hallucination", "stakes", "financial loss", "production failure", "harm")):
            return max(0.05, min(0.95, complexity_idx * 0.92 + pos_overlap * 0.04))

        # General dynamic keyword + semantic alignment for custom user-added noul checks!
        base = 0.08 + pos_overlap * 0.24 - neg_overlap * 0.12
        if pos_overlap == 0:
            # Check substring matches for domain nouns in instructions
            for tok in pos_tokens:
                if len(tok) >= 4 and tok in tl:
                    base += 0.26
        return max(0.02, min(0.96, base))

    def _simulate_choice(
        self,
        opt_map: Dict[str, str],
        tl: str,
        prompt_tokens: set[str],
        complexity_idx: float,
    ) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        n_opts = max(2, len(opt_map))
        for idx, (opt_key, desc) in enumerate(opt_map.items()):
            combined = f"{opt_key.replace('_', ' ')} {desc}".lower()
            opt_tokens = set(_extract_meaningful_tokens(combined))
            overlap = len(prompt_tokens & opt_tokens)

            # Estimate canonical complexity center of this option
            if any(k in combined for k in ("lookup", "faq", "glossary", "quick", "translation", "factual")):
                center = 0.10
            elif any(k in combined for k in ("explain", "summary", "guided", "productivity", "comparison")):
                center = 0.35
            elif any(k in combined for k in ("software", "code", "technical", "payment", "implement", "engineer")):
                center = 0.68
            elif any(k in combined for k in ("research", "audit", "risk", "deep", "strategy", "novel")):
                center = 0.90
            elif opt_key == "other":
                center = 0.45
            else:
                center = (idx + 0.5) / n_opts

            dist_affinity = math.exp(-((complexity_idx - center) ** 2) / 0.065)
            if opt_key == "other":
                dist_affinity *= 0.25  # catch-all activates primarily when nothing else fits
            scores[opt_key] = dist_affinity * (1.0 + overlap * 0.55)

        return _normalize_dist(scores)

    def _simulate_score(
        self,
        key: str,
        instr: str,
        levels: List[str],
        tl: str,
        prompt_tokens: set[str],
        complexity_idx: float,
        is_quality_gate: bool,
        simulate_low_quality: bool,
    ) -> Tuple[Dict[str, float], float, Dict[str, str]]:
        k = len(levels)
        legend = {str(i): desc for i, desc in enumerate(levels)}

        if is_quality_gate:
            target_norm = 0.34 if (simulate_low_quality or "[low_quality_draft]" in tl) else 0.86
        elif any(w in instr for w in ("code", "software", "implementation", "distributed", "system")):
            has_code_intent = any(
                w in tl for w in ("python", "implement", "function", "code", "api", "redis", "postgres", "sql", "schema", "cache", "server", "architecture", "ledger")
            )
            target_norm = complexity_idx * (1.05 if has_code_intent else 0.35)
        else:
            # Blend overall complexity with overlap on upper rubric descriptions
            high_tokens = set(_extract_meaningful_tokens(" ".join(levels[k // 2 :])))
            overlap_boost = min(0.22, len(prompt_tokens & high_tokens) * 0.06)
            target_norm = min(0.97, complexity_idx * 0.95 + overlap_boost)

        target_level = max(0.0, min(float(k - 1), target_norm * (k - 1)))
        raw_probs: Dict[str, float] = {}
        for i in range(k):
            raw_probs[str(i)] = math.exp(-((i - target_level) ** 2) / 0.38)

        probs = _normalize_dist(raw_probs)
        expected = round(sum(int(lvl) * p for lvl, p in probs.items()), 4)
        return probs, expected, legend

    def generate_target_response(
        self,
        model_id: str,
        display_name: str,
        tier: str,
        prompt: str,
        max_output_tokens: int,
        input_price_per_1m: float,
        output_price_per_1m: float,
        typical_latency_ms: int,
        force_simulation: bool = False,
        simulate_low_quality: bool = False,
    ) -> Tuple[str, int, int, float, float, Literal["live", "simulation"]]:
        """
        Call the selected target Gemini LLM via `client.interactions.create` (or simulate).

        Returns:
            (response_text, input_tokens, output_tokens, cost_usd, latency_ms, mode)
        """
        use_live = has_live_api_key() and not force_simulation
        t0 = time.perf_counter()

        if use_live:
            client = self._get_genai_client()
            try:
                interaction = client.interactions.create(
                    model=model_id,
                    input=prompt,
                )
                text = getattr(interaction, "output_text", None) or str(interaction)
                usage = getattr(interaction, "usage", None)
                in_tok = int(getattr(usage, "input_tokens", 0) or _approx_tokens(prompt))
                out_tok = int(getattr(usage, "output_tokens", 0) or _approx_tokens(text))
            except Exception:
                # Graceful fallback to models.generate_content if model alias uses legacy endpoint
                resp = client.models.generate_content(model=model_id, contents=prompt)
                text = resp.text or ""
                um = getattr(resp, "usage_metadata", None)
                in_tok = int(getattr(um, "prompt_token_count", 0) or _approx_tokens(prompt))
                out_tok = int(getattr(um, "candidates_token_count", 0) or _approx_tokens(text))

            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            cost_usd = (in_tok * input_price_per_1m + out_tok * output_price_per_1m) / 1_000_000
            return text, in_tok, out_tok, cost_usd, latency_ms, "live"

        # Simulation generation with realistic token counts per complexity tier
        in_tok = _approx_tokens(prompt)
        out_tok_map = {"SIMPLE": 95, "STANDARD": 310, "COMPLEX": 640, "EXPERT": 1050}
        out_tok = min(max_output_tokens, out_tok_map.get(tier, 320))
        cost_usd = (in_tok * input_price_per_1m + out_tok * output_price_per_1m) / 1_000_000

        if simulate_low_quality:
            text = (
                f"[LOW_QUALITY_DRAFT from {display_name} ({model_id})]\n"
                f"Brief incomplete outline for: \"{prompt[:90]}...\" — key edge cases and "
                f"constraints omitted, triggering Decision API post-generation quality gate escalation."
            )
        else:
            text = (
                f"[{display_name} · `{model_id}` ({tier} Tier)]\n\n"
                f"Routed via Decision-Grounded weighted calibration (`gemini-decision-1`, 0 decision output tokens).\n"
                f"- **Task Summary**: Addressed `{prompt[:110]}{'...' if len(prompt) > 110 else ''}`\n"
                f"- **Execution Profile**: Selected `{model_id}` matching required reasoning depth, domain affinity, "
                f"and threshold guardrails (~{out_tok} output tokens budgeted)."
            )

        return text, in_tok, out_tok, cost_usd, float(typical_latency_ms), "simulation"
