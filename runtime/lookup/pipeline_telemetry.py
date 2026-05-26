from __future__ import annotations

from typing import Any


def emit_lookup_pipeline_trace_events(
    *,
    report_event,
    source_bot: str,
    request_id: str,
    user_id: str,
    agent_name: str,
    planning,
) -> None:
    for trace in getattr(planning, "lookup_request_traces", []):
        _emit(
            report_event=report_event,
            source_bot=source_bot,
            request_id=request_id,
            event_type="lookup_request_trace",
            user_id=user_id,
            agent_name=agent_name,
            payload=_safe_trace_dict(trace),
        )

    for trace in getattr(planning, "lookup_execution_traces", []):
        _emit(
            report_event=report_event,
            source_bot=source_bot,
            request_id=request_id,
            event_type="lookup_execution_trace",
            user_id=user_id,
            agent_name=agent_name,
            payload=_safe_trace_dict(trace),
        )

    packets = getattr(planning, "lookup_context_packets", [])
    if packets:
        _emit(
            report_event=report_event,
            source_bot=source_bot,
            request_id=request_id,
            event_type="lookup_context_materialized",
            user_id=user_id,
            agent_name=agent_name,
            payload=_materialized_payload(packets),
        )

    render_decision = getattr(planning, "lookup_context_render_decision", None)
    if render_decision is not None:
        _emit(
            report_event=report_event,
            source_bot=source_bot,
            request_id=request_id,
            event_type="lookup_context_render_decision",
            user_id=user_id,
            agent_name=agent_name,
            payload=_safe_trace_dict(render_decision),
        )


def emit_lookup_context_injection_trace(
    *,
    report_event,
    source_bot: str,
    request_id: str,
    user_id: str,
    agent_name: str,
    trace: dict[str, Any],
) -> None:
    _emit(
        report_event=report_event,
        source_bot=source_bot,
        request_id=request_id,
        event_type="lookup_context_injection_trace",
        user_id=user_id,
        agent_name=agent_name,
        payload=_safe_trace_dict(trace),
    )


def _emit(
    *,
    report_event,
    source_bot: str,
    request_id: str,
    event_type: str,
    user_id: str,
    agent_name: str,
    payload: dict[str, Any],
) -> None:
    report_event(
        source_bot,
        event_type,
        {
            "user_id": user_id,
            "agent": agent_name,
            **payload,
        },
        request_id=request_id,
    )


def _materialized_payload(packets: list[Any]) -> dict[str, Any]:
    safe_packets = [packet for packet in packets if isinstance(packet, dict)]
    return {
        "packet_count": len(safe_packets),
        "context_types": [
            packet.get("context_type")
            for packet in safe_packets
            if isinstance(packet.get("context_type"), str)
        ],
        "packet_ids": [
            packet["provenance"]["lookup_id"]
            for packet in safe_packets
            if isinstance(packet.get("provenance"), dict)
            and isinstance(packet["provenance"].get("lookup_id"), str)
        ],
        "lookup_lineage_ids": _provenance_values(
            safe_packets,
            "lookup_lineage_id",
        ),
        "lookup_packet_ids": _provenance_values(
            safe_packets,
            "lookup_packet_id",
        ),
    }


def _provenance_values(
    packets: list[dict[str, Any]],
    field: str,
) -> list[str]:
    return [
        packet["provenance"][field]
        for packet in packets
        if isinstance(packet.get("provenance"), dict)
        and isinstance(packet["provenance"].get(field), str)
    ]


def _safe_trace_dict(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}

    safe: dict[str, Any] = {}
    for key, value in trace.items():
        if key in _FORBIDDEN_TELEMETRY_KEYS:
            continue

        safe_value = _safe_value(value)
        if safe_value is not None:
            safe[key] = safe_value

    return safe


def _safe_value(value: Any) -> str | int | bool | None | list[str]:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value

    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)

    return None


_FORBIDDEN_TELEMETRY_KEYS = {
    "fields",
    "payloads",
    "blocks",
    "lookup_results",
    "lookup_context_packets",
    "rendered_lookup_context",
    "raw_database_path",
    "raw_lookup_results",
    "raw_rows",
}


__all__ = [
    "emit_lookup_context_injection_trace",
    "emit_lookup_pipeline_trace_events",
]
