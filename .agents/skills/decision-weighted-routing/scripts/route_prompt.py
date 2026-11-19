#!/usr/bin/env python3
"""CLI helper for the `decision-weighted-routing` skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from backend.router_engine import DecisionGroundedRouter, load_router_spec  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Route a prompt through the Decision-Grounded LLM Router.")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to user-created RouterSpec JSON file.",
    )
    parser.add_argument("--prompt", type=str, required=True, help="Task prompt to route.")
    parser.add_argument("--simulate", action="store_true", help="Force offline calibrated simulation.")
    parser.add_argument("--json", action="store_true", help="Print full JSON trace.")
    args = parser.parse_args()

    spec = load_router_spec(args.config)
    router = DecisionGroundedRouter()
    res = router.route(args.prompt, spec, force_simulation=args.simulate)

    if args.json:
        print(res.model_dump_json(indent=2))
        return 0

    print(f"=== Decision-Grounded LLM Router ({res.mode.upper()} MODE) ===")
    print(f"Spec:            {spec.name} ({res.execution_mode})")
    print(f"Decision Calls:  {len(res.decision_calls)} call(s) to gemini-decision-1 (0 output tokens)")
    for t in res.topic_scores:
        print(
            f"  - [{t.type:<6}] {t.label:<34} raw={str(t.raw_value):<18} "
            f"norm={t.normalized_score:.2f}  w_share={t.effective_weight_share:.0%}  contrib={t.weighted_contribution:.3f}"
        )
    print(f"Composite Score: S = {res.resolution.composite_score:.3f} (conf={res.resolution.aggregate_confidence:.2f})")
    if res.resolution.triggered_gates:
        print(f"Hard Gates:      {'; '.join(res.resolution.triggered_gates)}")
    print(f"Selected Model:  {res.final_model_id} ({res.final_tier.value})")
    print(
        f"Cost & Savings:  ${res.total_cost_usd:.6f} "
        f"(saved {res.savings_pct:.1f}% vs Always-Carbon ${res.ceiling_equivalent_cost_usd:.6f})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
