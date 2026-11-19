#!/usr/bin/env python3
"""Validate a RouterSpec JSON file against Gemini Decision 1 (`gemini-decision-1`) rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from backend.schemas import RouterSpec  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Decision-Grounded RouterSpec JSON file.")
    parser.add_argument("config", type=Path, help="Path to router JSON spec.")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"ERROR: File not found: {args.config}", file=sys.stderr)
        return 1

    try:
        raw = json.loads(args.config.read_text(encoding="utf-8"))
        spec = RouterSpec.model_validate(raw)
    except Exception as exc:
        print(f"VALIDATION FAILED for {args.config}:\n{exc}", file=sys.stderr)
        return 1

    enabled_topics = [t for t in spec.topics if t.enabled and t.weight > 0]
    enabled_gates = [g for g in spec.hard_gates if g.enabled]
    print(
        f"OK: '{spec.name}' ({spec.id}) is valid — "
        f"{len(spec.models)} candidate LLMs, {len(enabled_gates)} hard gate(s), "
        f"{len(enabled_topics)} weighted topic(s), cutoffs="
        f"[{spec.tier_cutoffs.standard:.2f}, {spec.tier_cutoffs.complex:.2f}, {spec.tier_cutoffs.expert:.2f}]."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
