from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from runtime.attachment_guard import (
    build_lookup_attachment_provenance,
    detect_hidden_attachment_leakage,
    validate_attachment_path,
)
from runtime.lookup.context_budgeting import apply_lookup_context_budget


@dataclass(frozen=True)
class LookupContextInjectionResult:
    messages: list[dict[str, Any]]
    fragment: dict[str, Any] | None
    trace: dict[str, Any]


def maybe_inject_lookup_context(
    messages: list[dict[str, Any]],
    *,
    rendered_lookup_context: dict[str, Any] | None,
    render_decision: dict[str, Any] | None,
    injection_policy: dict[str, Any] | None,
) -> LookupContextInjectionResult:
    policy = _valid_policy(injection_policy)
    if policy is None:
        return _closed(
            messages=messages,
            skipped_reasons=["missing_or_malformed_injection_policy"],
        )

    if not _positive_render_decision(render_decision):
        return _closed(
            messages=messages,
            skipped_reasons=["render_decision_not_allowed"],
        )

    if not isinstance(rendered_lookup_context, dict):
        return _closed(
            messages=messages,
            skipped_reasons=["missing_rendered_lookup_context"],
        )

    leakage = detect_hidden_attachment_leakage(rendered_lookup_context)
    if leakage:
        return _closed(
            messages=messages,
            skipped_reasons=["hidden_attachment_leakage_detected"],
            blocked_fields=leakage,
        )

    budget_result = apply_lookup_context_budget(
        rendered_lookup_context=rendered_lookup_context,
        budget_policy=policy["budget_policy"],
    )
    if budget_result.rendered_lookup_context is None:
        return _closed(
            messages=messages,
            skipped_reasons=budget_result.trace["skipped_reasons"],
            budget_trace=budget_result.trace,
        )

    fragment = _build_fragment(
        rendered_lookup_context=budget_result.rendered_lookup_context,
        policy=policy,
    )
    if fragment is None:
        return _closed(
            messages=messages,
            skipped_reasons=["rendered_lookup_context_not_injectable"],
            budget_trace=budget_result.trace,
        )

    attachment_validation = _validate_lookup_context_attachment(fragment)
    if attachment_validation["allowed"] is not True:
        return _closed(
            messages=messages,
            skipped_reasons=attachment_validation["skipped_reasons"],
            blocked_fields=attachment_validation["blocked_fields"],
            budget_trace=budget_result.trace,
        )

    injected_messages = list(messages)
    injected_messages.insert(
        max(len(injected_messages) - 1, 0),
        {
            "role": "system",
            "content": _fragment_content(fragment),
        },
    )

    return LookupContextInjectionResult(
        messages=injected_messages,
        fragment=fragment,
        trace={
            "injection_attempted": True,
            "injection_allowed": True,
            "injected_block_count": len(fragment["blocks"]),
            "skipped_reasons": [],
            "attachment_guard": attachment_validation,
            **_lineage_trace(fragment),
            **budget_result.trace,
        },
    )


def _valid_policy(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(policy, dict) or policy.get("allowed") is not True:
        return None

    allowed_content_types = _string_tuple(policy.get("allowed_content_types"))
    allowed_render_modes = _string_tuple(policy.get("allowed_render_modes"))
    max_blocks = policy.get("max_blocks")
    max_facts_per_block = policy.get("max_facts_per_block")
    max_total_characters = policy.get("max_total_characters")
    truncation_mode = policy.get("truncation_mode")

    if not allowed_content_types or not allowed_render_modes:
        return None

    if (
        not isinstance(max_blocks, int)
        or isinstance(max_blocks, bool)
        or max_blocks < 1
    ):
        return None

    if (
        not isinstance(max_facts_per_block, int)
        or isinstance(max_facts_per_block, bool)
        or max_facts_per_block < 1
    ):
        return None

    if (
        not isinstance(max_total_characters, int)
        or isinstance(max_total_characters, bool)
        or max_total_characters < 1
    ):
        return None

    if truncation_mode != "drop_tail":
        return None

    if policy.get("require_render_decision") is not True:
        return None

    if policy.get("require_rendered_context") is not True:
        return None

    return {
        "allowed_content_types": allowed_content_types,
        "allowed_render_modes": allowed_render_modes,
        "max_blocks": max_blocks,
        "budget_policy": {
            "max_blocks": max_blocks,
            "max_facts_per_block": max_facts_per_block,
            "max_total_characters": max_total_characters,
            "truncation_mode": truncation_mode,
        },
    }


def _positive_render_decision(
    render_decision: dict[str, Any] | None,
) -> bool:
    return (
        isinstance(render_decision, dict)
        and render_decision.get("render_allowed") is True
    )


def _build_fragment(
    *,
    rendered_lookup_context: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any] | None:
    content_type = rendered_lookup_context.get("content_type")
    render_mode = rendered_lookup_context.get("render_mode")
    blocks = rendered_lookup_context.get("blocks")

    if content_type not in policy["allowed_content_types"]:
        return None

    if render_mode not in policy["allowed_render_modes"]:
        return None

    if (
        not isinstance(blocks, list)
        or not blocks
        or len(blocks) > policy["max_blocks"]
    ):
        return None

    safe_blocks = [_safe_block(block) for block in blocks]
    if any(block is None for block in safe_blocks):
        return None

    attachment_provenance = build_lookup_attachment_provenance(
        block_count=len(safe_blocks),
        first_block_provenance=safe_blocks[0].get("provenance"),
    )

    return {
        "content_type": content_type,
        "render_mode": render_mode,
        "blocks": safe_blocks,
        "attachment_provenance": attachment_provenance,
    }


def _validate_lookup_context_attachment(
    fragment: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_attachment_path(
        payload=fragment,
        source_substrate="retrieval",
        target="lookup_context_block",
        attachment_type="lookup_context_block",
        provenance=fragment.get("attachment_provenance"),
        attachment_path="lookup_context_injection",
    )
    return validation.to_record()


def _safe_block(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None

    title = block.get("title")
    facts = block.get("facts")
    provenance = block.get("provenance")

    if not isinstance(title, str) or not title.strip():
        return None

    if not isinstance(facts, list) or not facts:
        return None

    safe_facts = [_safe_fact(fact) for fact in facts]
    if any(fact is None for fact in safe_facts):
        return None

    if not isinstance(provenance, dict):
        return None

    lookup_id = provenance.get("lookup_id")
    if not isinstance(lookup_id, str) or not lookup_id.strip():
        return None

    return {
        "title": title.strip(),
        "facts": safe_facts,
        "provenance": {
            "lookup_id": lookup_id.strip(),
            **_safe_lineage_provenance(provenance),
            "retrieval_executed": (
                provenance.get("retrieval_executed") is True
            ),
            "records_returned": (
                provenance.get("records_returned")
                if provenance.get("records_returned") == 1
                else 0
            ),
            **_safe_result_provenance(provenance),
        },
    }


def _safe_fact(fact: Any) -> dict[str, Any] | None:
    if not isinstance(fact, dict):
        return None

    label = fact.get("label")
    field = fact.get("field")
    value = _safe_value(fact.get("value"))

    if not isinstance(label, str) or not label.strip():
        return None

    if not isinstance(field, str) or not field.strip():
        return None

    if value is None:
        return None

    return {
        "label": label.strip(),
        "field": field.strip(),
        "value": value,
    }


def _safe_lineage_provenance(
    provenance: dict[str, Any],
) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key in (
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_execution_id",
        "lookup_packet_id",
        "lookup_render_id",
        "lookup_injection_id",
    ):
        value = provenance.get(key)
        if isinstance(value, str) and value.strip():
            safe[key] = value.strip()
    return safe


def _safe_result_provenance(
    provenance: dict[str, Any],
) -> dict[str, int]:
    safe: dict[str, int] = {}
    for key in ("result_index", "result_count"):
        value = provenance.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            safe[key] = value
    return safe


def _lineage_trace(fragment: dict[str, Any]) -> dict[str, Any]:
    blocks = fragment.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return {}

    first_block = blocks[0]
    if not isinstance(first_block, dict):
        return {}

    provenance = first_block.get("provenance")
    if not isinstance(provenance, dict):
        return {}

    return _safe_lineage_provenance(provenance)


def _safe_value(value: Any) -> str | list[str] | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None

    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        cleaned_items = [item.strip() for item in value if item.strip()]
        return cleaned_items if cleaned_items else None

    return None


def _fragment_content(fragment: dict[str, Any]) -> str:
    return (
        "LOOKUP_CONTEXT_BLOCK\n"
        + json.dumps(fragment, sort_keys=True)
        + "\nEND_LOOKUP_CONTEXT_BLOCK"
    )


def _closed(
    *,
    messages: list[dict[str, Any]],
    skipped_reasons: list[str],
    budget_trace: dict[str, Any] | None = None,
    blocked_fields: list[str] | None = None,
) -> LookupContextInjectionResult:
    trace = {
        "injection_attempted": True,
        "injection_allowed": False,
        "injected_block_count": 0,
        "skipped_reasons": list(skipped_reasons),
    }
    if blocked_fields:
        trace["blocked_fields"] = list(blocked_fields)
    if budget_trace is not None:
        for key, value in budget_trace.items():
            if key == "skipped_reasons":
                continue
            trace[key] = value

    return LookupContextInjectionResult(
        messages=list(messages),
        fragment=None,
        trace=trace,
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        return ()

    return tuple(item.strip() for item in value)


__all__ = [
    "LookupContextInjectionResult",
    "maybe_inject_lookup_context",
]
