from __future__ import annotations

from typing import Any, Iterable


LOOKUP_STATE_SUCCESS = "success"
LOOKUP_STATE_FAILED = "failed"
LOOKUP_STATE_SKIPPED = "skipped"
LOOKUP_STATE_UNAUTHORIZED = "unauthorized"
LOOKUP_STATE_NO_MATCH = "no_match"
LOOKUP_STATE_DUPLICATE_MATCH = "duplicate_match"
LOOKUP_STATE_TIMEOUT = "timeout"
LOOKUP_STATE_CANCELLED = "cancelled"
LOOKUP_STATE_PARTIAL_SUCCESS = "partial_success"

LOOKUP_TERMINAL_STATES = frozenset(
    {
        LOOKUP_STATE_SUCCESS,
        LOOKUP_STATE_FAILED,
        LOOKUP_STATE_SKIPPED,
        LOOKUP_STATE_UNAUTHORIZED,
        LOOKUP_STATE_NO_MATCH,
        LOOKUP_STATE_DUPLICATE_MATCH,
        LOOKUP_STATE_TIMEOUT,
        LOOKUP_STATE_CANCELLED,
    }
)

LOOKUP_AGGREGATE_STATES = frozenset(
    {
        LOOKUP_STATE_SUCCESS,
        LOOKUP_STATE_FAILED,
        LOOKUP_STATE_SKIPPED,
        LOOKUP_STATE_UNAUTHORIZED,
        LOOKUP_STATE_NO_MATCH,
        LOOKUP_STATE_DUPLICATE_MATCH,
        LOOKUP_STATE_TIMEOUT,
        LOOKUP_STATE_CANCELLED,
        LOOKUP_STATE_PARTIAL_SUCCESS,
        "not_attempted",
        "request_not_created",
        "not_executed",
    }
)

LOOKUP_LIFECYCLE_STATES = frozenset(
    {*LOOKUP_TERMINAL_STATES, LOOKUP_STATE_PARTIAL_SUCCESS}
)

UNAUTHORIZED_REASONS = frozenset(
    {
        "lookup_executor_unavailable",
        "unauthorized_source_scope",
        "source_scope_not_supported_by_capability",
        "lookup_type_not_supported_by_capability",
    }
)

TIMEOUT_REASONS = frozenset({"lookup_execution_timeout"})
CANCELLED_REASONS = frozenset({"lookup_execution_cancelled"})


def is_lookup_lifecycle_state(state: Any) -> bool:
    return isinstance(state, str) and state in LOOKUP_LIFECYCLE_STATES


def is_lookup_aggregate_state(state: Any) -> bool:
    return isinstance(state, str) and state in LOOKUP_AGGREGATE_STATES


def normalize_lookup_status(
    *,
    retrieval_executed: bool,
    records_returned: int,
    skipped_reasons: Iterable[str],
) -> str:
    reasons = {reason for reason in skipped_reasons if isinstance(reason, str)}

    if (
        retrieval_executed is True
        and records_returned == 1
        and not reasons
    ):
        return LOOKUP_STATE_SUCCESS

    if reasons & TIMEOUT_REASONS:
        return LOOKUP_STATE_TIMEOUT

    if reasons & CANCELLED_REASONS:
        return LOOKUP_STATE_CANCELLED

    if reasons & UNAUTHORIZED_REASONS:
        return LOOKUP_STATE_UNAUTHORIZED

    if "multiple_exact_matches" in reasons:
        return LOOKUP_STATE_DUPLICATE_MATCH

    if "no_exact_match" in reasons:
        return LOOKUP_STATE_NO_MATCH

    if retrieval_executed is False:
        return LOOKUP_STATE_SKIPPED

    return LOOKUP_STATE_FAILED


def normalize_lookup_trace_status(trace: dict[str, Any]) -> str:
    declared = trace.get("lookup_status")
    if is_lookup_lifecycle_state(declared) and declared != (
        LOOKUP_STATE_PARTIAL_SUCCESS
    ):
        return declared

    return normalize_lookup_status(
        retrieval_executed=trace.get("retrieval_executed") is True,
        records_returned=(
            trace.get("records_returned")
            if _non_bool_int(trace.get("records_returned"))
            else 0
        ),
        skipped_reasons=_string_list(trace.get("skipped_reasons")),
    )


def lookup_status_counts(execution_traces: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trace in execution_traces:
        if not isinstance(trace, dict):
            continue

        status = normalize_lookup_trace_status(trace)
        if not is_lookup_lifecycle_state(status):
            status = LOOKUP_STATE_FAILED

        counts[status] = counts.get(status, 0) + 1

    return counts


def aggregate_lookup_execution_status(
    *,
    attempted: bool,
    request_created: bool,
    execution_traces: Iterable[Any],
    status_counts: dict[str, int],
) -> str:
    if not attempted:
        return "not_attempted"

    if not request_created:
        return "request_not_created"

    safe_traces = [trace for trace in execution_traces if isinstance(trace, dict)]
    if not safe_traces:
        return "not_executed"

    trace_count = len(safe_traces)
    success_count = status_counts.get(LOOKUP_STATE_SUCCESS, 0)
    if success_count == trace_count:
        return LOOKUP_STATE_SUCCESS

    if success_count > 0:
        return LOOKUP_STATE_PARTIAL_SUCCESS

    if status_counts.get(LOOKUP_STATE_UNAUTHORIZED, 0) == trace_count:
        return LOOKUP_STATE_UNAUTHORIZED

    if status_counts.get(LOOKUP_STATE_DUPLICATE_MATCH, 0) == trace_count:
        return LOOKUP_STATE_DUPLICATE_MATCH

    if status_counts.get(LOOKUP_STATE_NO_MATCH, 0) == trace_count:
        return LOOKUP_STATE_FAILED

    if status_counts.get(LOOKUP_STATE_TIMEOUT, 0) == trace_count:
        return LOOKUP_STATE_TIMEOUT

    if status_counts.get(LOOKUP_STATE_CANCELLED, 0) == trace_count:
        return LOOKUP_STATE_CANCELLED

    if not any(trace.get("retrieval_executed") is True for trace in safe_traces):
        return LOOKUP_STATE_SKIPPED

    return LOOKUP_STATE_FAILED


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _non_bool_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "LOOKUP_AGGREGATE_STATES",
    "LOOKUP_LIFECYCLE_STATES",
    "LOOKUP_TERMINAL_STATES",
    "aggregate_lookup_execution_status",
    "is_lookup_aggregate_state",
    "is_lookup_lifecycle_state",
    "lookup_status_counts",
    "normalize_lookup_status",
    "normalize_lookup_trace_status",
]
