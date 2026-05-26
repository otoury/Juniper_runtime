from __future__ import annotations

from typing import Any

from runtime.lookup.lifecycle import (
    aggregate_lookup_execution_status,
    lookup_status_counts,
)
from runtime.governance.operation_visibility import (
    build_retrieval_governance_visibility,
)
from runtime.retrieval.terminology import bounded_lookup_retrieval_metadata


def build_lookup_pipeline_summary(
    *,
    planning,
    injection_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lookup_requests = _list_attr(planning, "lookup_requests")
    request_traces = _list_attr(planning, "lookup_request_traces")
    execution_traces = _list_attr(planning, "lookup_execution_traces")
    packets = _list_attr(planning, "lookup_context_packets")
    render_decision = getattr(
        planning,
        "lookup_context_render_decision",
        None,
    )

    attempted = bool(lookup_requests or request_traces or execution_traces)
    request_created = any(
        trace.get("request_created") is True
        for trace in request_traces
        if isinstance(trace, dict)
    ) or bool(lookup_requests)

    execution_trace = _first_dict(execution_traces)
    records_returned = _total_records_returned(execution_traces)
    status_counts = lookup_status_counts(execution_traces)
    successful_lookup_count = status_counts.get("success", 0)
    failed_lookup_count = sum(
        count
        for status, count in status_counts.items()
        if status != "success"
    )
    skipped_reasons = _skipped_reasons(
        request_traces=request_traces,
        execution_traces=execution_traces,
        render_decision=render_decision,
        injection_trace=injection_trace,
    )
    lineage = _lineage_summary(
        lookup_requests=lookup_requests,
        request_traces=request_traces,
        execution_traces=execution_traces,
        packets=packets,
        render_decision=render_decision,
        injection_trace=injection_trace,
    )
    governance_state = _governance_state(
        request_traces=request_traces,
        execution_traces=execution_traces,
    )
    render_allowed = (
        render_decision.get("render_allowed") is True
        if isinstance(render_decision, dict)
        else False
    )
    render_mode = (
        render_decision.get("render_mode")
        if isinstance(render_decision, dict)
        and isinstance(render_decision.get("render_mode"), str)
        else None
    )
    injection_allowed = (
        injection_trace.get("injection_allowed") is True
        if isinstance(injection_trace, dict)
        else None
    )
    injected_block_count = (
        injection_trace.get("injected_block_count")
        if isinstance(injection_trace, dict)
        and _non_bool_int(injection_trace.get("injected_block_count"))
        else 0
    )

    summary = {
        "lookup_pipeline": {
            "attempted": attempted,
            **bounded_lookup_retrieval_metadata(
                retrieval_types=_lookup_types(
                    lookup_requests=lookup_requests,
                    request_traces=request_traces,
                    execution_traces=execution_traces,
                ),
            ),
            **lineage,
            "request_created": request_created,
            "governance_state": governance_state,
            "execution_status": aggregate_lookup_execution_status(
                attempted=attempted,
                request_created=request_created,
                execution_traces=execution_traces,
                status_counts=status_counts,
            ),
            "lookup_status_counts": status_counts,
            "successful_lookup_count": successful_lookup_count,
            "failed_lookup_count": failed_lookup_count,
            "records_returned": records_returned,
            "context_materialized": bool(packets),
            "render_allowed": render_allowed,
            "render_mode": render_mode,
            "injection_allowed": injection_allowed,
            "injected_block_count": injected_block_count,
            "skipped_reasons": skipped_reasons,
            "governance_visibility": build_retrieval_governance_visibility(
                governance_state=governance_state,
                execution_allowed=successful_lookup_count > 0,
                retrieval_executed=any(
                    trace.get("retrieval_executed") is True
                    for trace in execution_traces
                    if isinstance(trace, dict)
                ),
                lookup_type=_first_string(
                    [
                        *_dicts(lookup_requests),
                        *_dicts(request_traces),
                        *_dicts(execution_traces),
                    ],
                    "lookup_type",
                ),
                source_scope=_first_string(
                    [
                        *_dicts(lookup_requests),
                        *_dicts(request_traces),
                        *_dicts(execution_traces),
                    ],
                    "source_scope",
                ),
                lookup_lineage_id=lineage.get("lineage_root"),
                lookup_request_id=lineage.get("lookup_request_id"),
                lookup_execution_id=lineage.get("lookup_execution_id"),
                records_returned=records_returned,
                render_allowed=render_allowed,
                injection_allowed=injection_allowed,
                skipped_reasons=skipped_reasons,
            ),
        }
    }
    return summary


def _lookup_types(
    *,
    lookup_requests: list[Any],
    request_traces: list[Any],
    execution_traces: list[Any],
) -> list[str]:
    return _all_strings(
        [
            *_dicts(lookup_requests),
            *_dicts(request_traces),
            *_dicts(execution_traces),
        ],
        "lookup_type",
    )


def _lineage_summary(
    *,
    lookup_requests: list[Any],
    request_traces: list[Any],
    execution_traces: list[Any],
    packets: list[Any],
    render_decision: Any,
    injection_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    values = [
        *_dicts(lookup_requests),
        *_dicts(request_traces),
        *_dicts(execution_traces),
        *[
            packet.get("provenance")
            for packet in packets
            if isinstance(packet, dict)
            and isinstance(packet.get("provenance"), dict)
        ],
    ]

    if isinstance(render_decision, dict):
        values.append(render_decision)
    if isinstance(injection_trace, dict):
        values.append(injection_trace)

    lineage_roots = _all_strings(values, "lookup_lineage_id")
    return {
        "lineage_root": _first_string(values, "lookup_lineage_id"),
        "lineage_roots": lineage_roots,
        "lookup_request_id": _first_string(values, "lookup_request_id"),
        "lookup_execution_id": _first_string(values, "lookup_execution_id"),
        "lookup_packet_id": _first_string(values, "lookup_packet_id"),
        "lookup_render_id": _first_stage_value(
            values,
            scalar_field="lookup_render_id",
            list_field="lookup_render_ids",
        ),
        "lookup_injection_id": _first_string(values, "lookup_injection_id"),
    }


def _skipped_reasons(
    *,
    request_traces: list[Any],
    execution_traces: list[Any],
    render_decision: Any,
    injection_trace: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    for trace in [*request_traces, *execution_traces]:
        if isinstance(trace, dict):
            reasons.extend(_string_list(trace.get("skipped_reasons")))

    if isinstance(render_decision, dict):
        reasons.extend(_string_list(render_decision.get("reasons")))

    if isinstance(injection_trace, dict):
        reasons.extend(_string_list(injection_trace.get("skipped_reasons")))

    return sorted(set(reasons))


def _governance_state(
    *,
    request_traces: list[Any],
    execution_traces: list[Any],
) -> str | None:
    for trace in [*request_traces, *execution_traces]:
        if not isinstance(trace, dict):
            continue

        state = trace.get("governance_state")
        if isinstance(state, str) and state.strip():
            return state.strip()

    return None


def _total_records_returned(execution_traces: list[Any]) -> int:
    total = 0
    for trace in execution_traces:
        if not isinstance(trace, dict):
            continue
        value = trace.get("records_returned")
        if _non_bool_int(value) and value >= 0:
            total += value
    return total


def _list_attr(value: Any, name: str) -> list[Any]:
    attr = getattr(value, name, [])
    return list(attr) if isinstance(attr, list) else []


def _first_dict(values: list[Any]) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _dicts(values: list[Any]) -> list[dict[str, Any]]:
    return [value for value in values if isinstance(value, dict)]


def _first_string(values: list[Any], field: str) -> str | None:
    for value in values:
        if not isinstance(value, dict):
            continue

        item = value.get(field)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _all_strings(values: list[Any], field: str) -> list[str]:
    found: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue

        item = value.get(field)
        if isinstance(item, str) and item.strip() and item.strip() not in found:
            found.append(item.strip())
    return found


def _first_stage_value(
    values: list[Any],
    *,
    scalar_field: str,
    list_field: str,
) -> str | None:
    scalar = _first_string(values, scalar_field)
    if scalar is not None:
        return scalar

    for value in values:
        if not isinstance(value, dict):
            continue

        items = value.get(list_field)
        if (
            isinstance(items, list)
            and items
            and isinstance(items[0], str)
            and items[0].strip()
        ):
            return items[0].strip()
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _non_bool_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = ["build_lookup_pipeline_summary"]
