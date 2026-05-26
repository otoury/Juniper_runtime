from __future__ import annotations

from typing import Any


def evaluate_lookup_context_render_gate(
    *,
    lookup_context_packets: list[dict[str, Any]],
    render_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = _valid_policy(render_policy)
    if policy is None:
        return _decision(
            render_allowed=False,
            render_mode=None,
            reasons=["missing_or_malformed_render_policy"],
            packets=[],
        )

    if not lookup_context_packets:
        return _decision(
            render_allowed=False,
            render_mode=None,
            reasons=["no_lookup_context_packets"],
            packets=[],
        )

    if len(lookup_context_packets) > policy["max_packets"]:
        return _decision(
            render_allowed=False,
            render_mode=None,
            reasons=["lookup_context_packet_limit_exceeded"],
            packets=lookup_context_packets,
        )

    reasons: list[str] = []
    packet_ids: list[str] = []
    lineage_ids: list[str] = []
    render_ids: list[str] = []

    for packet in lookup_context_packets:
        if not isinstance(packet, dict):
            reasons.append("malformed_lookup_context_packet")
            continue

        context_type = packet.get("context_type")
        if context_type not in policy["allowed_context_types"]:
            reasons.append("disallowed_context_type")

        if not _optional_value_allowed(
            packet.get("lookup_type"),
            policy["allowed_lookup_types"],
        ):
            reasons.append("disallowed_lookup_type")

        if not _optional_value_allowed(
            packet.get("source_scope"),
            policy["allowed_source_scopes"],
        ):
            reasons.append("disallowed_source_scope")

        if not _optional_value_allowed(
            packet.get("entity_type"),
            policy["allowed_entity_types"],
        ):
            reasons.append("disallowed_entity_type")

        provenance = packet.get("provenance")
        if not isinstance(provenance, dict):
            reasons.append("missing_lookup_context_provenance")
            continue

        if (
            policy["require_successful_retrieval"]
            and provenance.get("retrieval_executed") is not True
        ):
            reasons.append("retrieval_not_successful")

        if (
            policy["require_successful_retrieval"]
            and provenance.get("records_returned") != 1
        ):
            reasons.append("unexpected_records_returned")

        lookup_id = provenance.get("lookup_id")
        if isinstance(lookup_id, str) and lookup_id.strip():
            packet_ids.append(lookup_id.strip())

        lineage_id = provenance.get("lookup_lineage_id")
        if isinstance(lineage_id, str) and lineage_id.strip():
            lineage_ids.append(lineage_id.strip())

        render_id = provenance.get("lookup_render_id")
        if isinstance(render_id, str) and render_id.strip():
            render_ids.append(render_id.strip())

    if reasons:
        return _decision(
            render_allowed=False,
            render_mode=None,
            reasons=sorted(set(reasons)),
            packets=lookup_context_packets,
            packet_ids=packet_ids,
            lineage_ids=lineage_ids,
            render_ids=render_ids,
        )

    return _decision(
        render_allowed=True,
        render_mode=policy["render_modes"][0],
        reasons=[],
        packets=lookup_context_packets,
        packet_ids=packet_ids,
        lineage_ids=lineage_ids,
        render_ids=render_ids,
    )


def _valid_policy(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(policy, dict) or policy.get("allowed") is not True:
        return None

    render_modes = _string_tuple(policy.get("render_modes"))
    allowed_context_types = _string_tuple(policy.get("allowed_context_types"))
    if not render_modes or not allowed_context_types:
        return None

    max_packets = policy.get("max_packets")
    if (
        not isinstance(max_packets, int)
        or isinstance(max_packets, bool)
        or max_packets < 1
    ):
        return None

    require_successful = policy.get("require_successful_retrieval")
    if not isinstance(require_successful, bool):
        return None

    return {
        "render_modes": render_modes,
        "allowed_context_types": allowed_context_types,
        "max_packets": max_packets,
        "require_successful_retrieval": require_successful,
        "allowed_lookup_types": _optional_string_tuple(
            policy.get("allowed_lookup_types")
        ),
        "allowed_source_scopes": _optional_string_tuple(
            policy.get("allowed_source_scopes")
        ),
        "allowed_entity_types": _optional_string_tuple(
            policy.get("allowed_entity_types")
        ),
    }


def _decision(
    *,
    render_allowed: bool,
    render_mode: str | None,
    reasons: list[str],
    packets: list[dict[str, Any]],
    packet_ids: list[str] | None = None,
    lineage_ids: list[str] | None = None,
    render_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "render_allowed": render_allowed,
        "render_mode": render_mode,
        "reasons": list(reasons),
        "packet_ids": packet_ids if packet_ids is not None else _packet_ids(
            packets
        ),
        "lookup_lineage_ids": (
            lineage_ids if lineage_ids is not None else _provenance_ids(
                packets,
                "lookup_lineage_id",
            )
        ),
        "lookup_render_ids": (
            render_ids if render_ids is not None else _provenance_ids(
                packets,
                "lookup_render_id",
            )
        ),
    }


def _packet_ids(packets: list[dict[str, Any]]) -> list[str]:
    return _provenance_ids(packets, "lookup_id")


def _provenance_ids(packets: list[dict[str, Any]], field: str) -> list[str]:
    ids: list[str] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue

        provenance = packet.get("provenance")
        if not isinstance(provenance, dict):
            continue

        lookup_id = provenance.get(field)
        if isinstance(lookup_id, str) and lookup_id.strip():
            ids.append(lookup_id.strip())

    return ids


def _string_tuple(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        return ()

    return tuple(item.strip() for item in value)


def _optional_string_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None

    items = _string_tuple(value)
    return items if items else ()


def _optional_value_allowed(
    value: Any,
    allowed_values: tuple[str, ...] | None,
) -> bool:
    if allowed_values is None:
        return True

    return isinstance(value, str) and value in allowed_values


__all__ = ["evaluate_lookup_context_render_gate"]
