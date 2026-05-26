from __future__ import annotations

from typing import Any, Iterable


def materialize_lookup_context_packets(
    *,
    lookup_results: Iterable[dict[str, Any]],
    materialization_policy: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    policy = _valid_policy(materialization_policy)
    if policy is None:
        return []

    packets: list[dict[str, Any]] = []
    for result in lookup_results:
        result_packets = materialize_lookup_context_packets_for_result(
            lookup_result=result,
            materialization_policy=policy,
        )
        packets.extend(result_packets)

    return packets


def materialize_lookup_context_packet(
    *,
    lookup_result: dict[str, Any],
    materialization_policy: dict[str, Any],
) -> dict[str, Any] | None:
    packets = materialize_lookup_context_packets_for_result(
        lookup_result=lookup_result,
        materialization_policy=materialization_policy,
    )
    if len(packets) != 1:
        return None

    return packets[0]


def materialize_lookup_context_packets_for_result(
    *,
    lookup_result: dict[str, Any],
    materialization_policy: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = _valid_policy(materialization_policy)
    if policy is None:
        return []

    if lookup_result.get("retrieval_executed") is not True:
        return []

    payloads = lookup_result.get("payloads")
    records_returned = lookup_result.get("records_returned")
    if (
        not isinstance(payloads, list)
        or not isinstance(records_returned, int)
        or isinstance(records_returned, bool)
        or records_returned < 1
        or len(payloads) != records_returned
    ):
        return []

    packets: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads, start=1):
        if not isinstance(payload, dict):
            return []

        fields = _allowlisted_fields(
            payload=payload,
            allowed_fields=policy["allowed_fields"],
            max_fields=policy["max_fields"],
        )
        if fields is None or not fields:
            return []

        packets.append(
            {
                "context_type": policy["context_type"],
                "lookup_type": _optional_string(
                    lookup_result.get("lookup_type")
                ),
                "entity_type": _optional_string(
                    lookup_result.get("entity_type")
                ),
                "source_scope": _optional_string(
                    lookup_result.get("source_scope")
                ),
                "fields": fields,
                "provenance": _provenance(
                    lookup_result,
                    result_index=index,
                    result_count=records_returned,
                ),
            }
        )

    return packets


def _provenance(
    lookup_result: dict[str, Any],
    *,
    result_index: int,
    result_count: int,
) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "lookup_id": _optional_string(lookup_result.get("lookup_id")),
        "retrieval_executed": True,
        "records_returned": 1,
        "skipped_reasons": [],
    }
    if result_count > 1:
        provenance["result_index"] = result_index
        provenance["result_count"] = result_count

    for key in (
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_execution_id",
        "lookup_packet_id",
        "lookup_render_id",
        "lookup_injection_id",
    ):
        value = _optional_string(lookup_result.get(key))
        if value is not None:
            provenance[key] = value

    return provenance


def _valid_policy(
    policy: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return None

    context_type = policy.get("context_type")
    if not isinstance(context_type, str) or not context_type.strip():
        return None

    allowed_fields = policy.get("allowed_fields")
    if (
        not isinstance(allowed_fields, (list, tuple))
        or not allowed_fields
        or any(
            not isinstance(field, str) or not field.strip()
            for field in allowed_fields
        )
    ):
        return None

    max_fields = policy.get("max_fields", len(allowed_fields))
    if (
        not isinstance(max_fields, int)
        or isinstance(max_fields, bool)
        or max_fields < 1
        or max_fields > len(allowed_fields)
    ):
        return None

    return {
        "enabled": True,
        "context_type": context_type.strip(),
        "allowed_fields": tuple(field.strip() for field in allowed_fields),
        "max_fields": max_fields,
    }


def _allowlisted_fields(
    *,
    payload: dict[str, Any],
    allowed_fields: tuple[str, ...],
    max_fields: int,
) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}

    for field in allowed_fields:
        if len(fields) >= max_fields:
            break

        if field not in payload:
            continue

        value = _safe_value(payload[field])
        if value is None:
            return None

        fields[field] = value

    return fields


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


__all__ = [
    "materialize_lookup_context_packet",
    "materialize_lookup_context_packets",
    "materialize_lookup_context_packets_for_result",
]
