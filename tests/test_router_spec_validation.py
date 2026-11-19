"""Unit tests for Decisions API schema constraints & virgin-session RouterSpec validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas import (
    HardGateQuestion,
    RouterSpec,
    TierCutoffs,
    TopicQuestion,
    default_candidate_llm_pool,
)


def test_default_candidate_llm_pool_and_minimal_spec_validate() -> None:
    pool = default_candidate_llm_pool()
    assert len(pool) == 4
    spec = RouterSpec(
        name="User Built Router",
        models=pool,
        topics=[
            TopicQuestion(
                key="reasoning_complexity",
                label="Reasoning Complexity",
                type="score",
                weight=1.0,
                instructions="How much reasoning complexity does this request require?",
                criteria=["Low", "Medium", "High"],
            )
        ],
    )
    assert spec.tier_cutoffs.standard < spec.tier_cutoffs.complex < spec.tier_cutoffs.expert


def test_rejects_none_of_the_above_in_choice_topic() -> None:
    with pytest.raises(ValidationError, match="none_of_the_above"):
        TopicQuestion(
            key="bad_choice",
            label="Bad Choice",
            type="choice",
            weight=0.5,
            instructions="Which category fits this input?",
            criteria={
                "billing": "Billing questions.",
                "none_of_the_above": "Catch-all key discouraged by Decisions API docs.",
            },
        )


def test_rejects_out_of_range_noul_threshold() -> None:
    with pytest.raises(ValidationError):
        HardGateQuestion(
            key="impossible_gate",
            label="Impossible Gate",
            instructions="Does this prompt contain sensitive data?",
            threshold=0.995,
        )


def test_rejects_non_monotonic_cutoffs() -> None:
    with pytest.raises(ValidationError, match="Tier cutoffs"):
        TierCutoffs(standard=0.60, complex=0.50, expert=0.80)
