from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any


SUPPORTED_TRUNCATION_MODES = {"drop_tail"}


@dataclass(frozen=True)
class LookupContextBudgetResult:
    rendered_lookup_context: dict[str, Any] | None
    trace: dict[str, Any]


def apply_lookup_context_budget(
    *,
    rendered_lookup_context: dict[str, Any],
    budget_policy: dict[str, Any] | None,
) -> LookupContextBudgetResult:
    policy = _valid_policy(budget_policy)
    if policy is None:
        return _closed(["missing_or_malformed_budget_policy"])

    if not isinstance(rendered_lookup_context, dict):
        return _closed(["malformed_rendered_lookup_context"])

    bounded = _copy_rendered_context(rendered_lookup_context)
    if bounded is None:
        return _closed(["malformed_rendered_lookup_context"])

    original_block_count = len(bounded["blocks"])
    dropped_blocks = _drop_tail_blocks(bounded, policy["max_blocks"])
    dropped_facts = _drop_tail_facts(
        bounded,
        max_facts_per_block=policy["max_facts_per_block"],
    )

    while _character_count(bounded) > policy["max_total_characters"]:
        if _drop_one_tail_fact(bounded):
            dropped_facts += 1
            continue

        if _drop_one_tail_block(bounded):
            dropped_blocks += 1
            continue

        return _closed(["budget_cannot_be_satisfied"])

    if not bounded["blocks"]:
        return _closed(["budget_removed_all_blocks"])

    final_character_count = _character_count(bounded)
    return LookupContextBudgetResult(
        rendered_lookup_context=bounded,
        trace={
            "budget_applied": True,
            "truncated": (
                dropped_blocks > 0
                or dropped_facts > 0
                or len(bounded["blocks"]) < original_block_count
            ),
            "dropped_blocks": dropped_blocks,
            "dropped_facts": dropped_facts,
            "final_character_count": final_character_count,
            "skipped_reasons": [],
        },
    )


def _valid_policy(policy: dict[str, Any] | None) -> dict[str, int | str] | None:
    if not isinstance(policy, dict):
        return None

    max_blocks = policy.get("max_blocks")
    max_facts_per_block = policy.get("max_facts_per_block")
    max_total_characters = policy.get("max_total_characters")
    truncation_mode = policy.get("truncation_mode")

    if not _positive_int(max_blocks):
        return None

    if not _positive_int(max_facts_per_block):
        return None

    if not _positive_int(max_total_characters):
        return None

    if truncation_mode not in SUPPORTED_TRUNCATION_MODES:
        return None

    return {
        "max_blocks": max_blocks,
        "max_facts_per_block": max_facts_per_block,
        "max_total_characters": max_total_characters,
        "truncation_mode": truncation_mode,
    }


def _copy_rendered_context(
    rendered_lookup_context: dict[str, Any],
) -> dict[str, Any] | None:
    content_type = rendered_lookup_context.get("content_type")
    render_mode = rendered_lookup_context.get("render_mode")
    blocks = rendered_lookup_context.get("blocks")

    if not isinstance(content_type, str) or not content_type.strip():
        return None

    if not isinstance(render_mode, str) or not render_mode.strip():
        return None

    if not isinstance(blocks, list) or not blocks:
        return None

    copied = copy.deepcopy(
        {
            "content_type": content_type,
            "render_mode": render_mode,
            "blocks": blocks,
        }
    )
    return copied


def _drop_tail_blocks(
    rendered_lookup_context: dict[str, Any],
    max_blocks: int,
) -> int:
    blocks = rendered_lookup_context["blocks"]
    dropped = max(len(blocks) - max_blocks, 0)
    if dropped:
        del blocks[max_blocks:]
    return dropped


def _drop_tail_facts(
    rendered_lookup_context: dict[str, Any],
    *,
    max_facts_per_block: int,
) -> int:
    dropped = 0
    for block in rendered_lookup_context["blocks"]:
        facts = block.get("facts") if isinstance(block, dict) else None
        if not isinstance(facts, list):
            continue
        overage = max(len(facts) - max_facts_per_block, 0)
        if overage:
            del facts[max_facts_per_block:]
            dropped += overage
    return dropped


def _drop_one_tail_fact(rendered_lookup_context: dict[str, Any]) -> bool:
    for block in reversed(rendered_lookup_context["blocks"]):
        facts = block.get("facts") if isinstance(block, dict) else None
        if isinstance(facts, list) and len(facts) > 1:
            facts.pop()
            return True
    return False


def _drop_one_tail_block(rendered_lookup_context: dict[str, Any]) -> bool:
    blocks = rendered_lookup_context["blocks"]
    if len(blocks) > 1:
        blocks.pop()
        return True
    return False


def _character_count(rendered_lookup_context: dict[str, Any]) -> int:
    return len(json.dumps(rendered_lookup_context, sort_keys=True))


def _closed(skipped_reasons: list[str]) -> LookupContextBudgetResult:
    return LookupContextBudgetResult(
        rendered_lookup_context=None,
        trace={
            "budget_applied": False,
            "truncated": False,
            "dropped_blocks": 0,
            "dropped_facts": 0,
            "final_character_count": 0,
            "skipped_reasons": list(skipped_reasons),
        },
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


__all__ = [
    "LookupContextBudgetResult",
    "SUPPORTED_TRUNCATION_MODES",
    "apply_lookup_context_budget",
]
