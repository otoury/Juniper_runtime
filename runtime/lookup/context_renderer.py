from __future__ import annotations

from typing import Any


SUPPORTED_RENDER_MODES = {"structured_fact_block"}


def render_lookup_context_blocks(
    *,
    lookup_context_packets: list[dict[str, Any]],
    render_decision: dict[str, Any] | None,
    render_policy: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not _render_allowed(render_decision):
        return None

    render_mode = render_decision.get("render_mode")
    if render_mode not in SUPPORTED_RENDER_MODES:
        return None

    policy = _valid_policy(render_policy, render_mode=render_mode)
    if policy is None:
        return None

    packet_ids = render_decision.get("packet_ids")
    if not isinstance(packet_ids, list):
        return None

    blocks: list[dict[str, Any]] = []
    for packet in lookup_context_packets:
        block = _render_packet(
            packet=packet,
            packet_ids=packet_ids,
            field_order=policy["field_order"],
            field_labels=policy["field_labels"],
        )
        if block is not None:
            blocks.append(block)

    if not blocks:
        return None

    return {
        "render_mode": render_mode,
        "content_type": "lookup_context_block",
        "blocks": blocks,
    }


def _render_allowed(render_decision: dict[str, Any] | None) -> bool:
    return (
        isinstance(render_decision, dict)
        and render_decision.get("render_allowed") is True
    )


def _valid_policy(
    policy: dict[str, Any] | None,
    *,
    render_mode: str,
) -> dict[str, Any] | None:
    if not isinstance(policy, dict) or policy.get("allowed") is not True:
        return None

    if render_mode not in policy.get("render_modes", []):
        return None

    field_order = _string_tuple(policy.get("field_order"))
    field_labels = policy.get("field_labels", {})
    if not field_order or not isinstance(field_labels, dict):
        return None

    labels: dict[str, str] = {}
    for field in field_order:
        label = field_labels.get(field, field)
        if not isinstance(label, str) or not label.strip():
            return None
        labels[field] = label.strip()

    return {
        "field_order": field_order,
        "field_labels": labels,
    }


def _render_packet(
    *,
    packet: dict[str, Any],
    packet_ids: list[Any],
    field_order: tuple[str, ...],
    field_labels: dict[str, str],
) -> dict[str, Any] | None:
    if not isinstance(packet, dict):
        return None

    fields = packet.get("fields")
    provenance = packet.get("provenance")
    if not isinstance(fields, dict) or not isinstance(provenance, dict):
        return None

    lookup_id = provenance.get("lookup_id")
    if lookup_id not in packet_ids:
        return None

    facts: list[dict[str, Any]] = []
    for field in field_order:
        if field not in fields:
            continue

        value = _safe_value(fields[field])
        if value is None:
            return None

        facts.append(
            {
                "label": field_labels[field],
                "field": field,
                "value": value,
            }
        )

    if not facts:
        return None

    return {
        "title": _block_title(packet),
        "facts": facts,
        "provenance": _safe_provenance(provenance),
    }


def _block_title(packet: dict[str, Any]) -> str:
    if packet.get("lookup_type") == "bounded_entity_search":
        return "Bounded entity search result"

    return "Retrieved entity context"


def _safe_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "lookup_id": _optional_string(provenance.get("lookup_id")),
        "retrieval_executed": provenance.get("retrieval_executed") is True,
        "records_returned": (
            provenance.get("records_returned")
            if provenance.get("records_returned") == 1
            else 0
        ),
    }
    result_index = provenance.get("result_index")
    result_count = provenance.get("result_count")
    if isinstance(result_index, int) and not isinstance(result_index, bool):
        safe["result_index"] = result_index
    if isinstance(result_count, int) and not isinstance(result_count, bool):
        safe["result_count"] = result_count

    for key in (
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_execution_id",
        "lookup_packet_id",
        "lookup_render_id",
        "lookup_injection_id",
    ):
        value = _optional_string(provenance.get(key))
        if value is not None:
            safe[key] = value

    return safe


def _safe_value(value: Any) -> str | list[str] | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None

    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        cleaned_items = [item.strip() for item in value if item.strip()]
        return cleaned_items if cleaned_items else None

    return None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        return ()

    return tuple(item.strip() for item in value)


__all__ = [
    "SUPPORTED_RENDER_MODES",
    "render_lookup_context_blocks",
]
