import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.lifecycle import (  # noqa: E402
    LOOKUP_LIFECYCLE_STATES,
    aggregate_lookup_execution_status,
    is_lookup_aggregate_state,
    is_lookup_lifecycle_state,
    lookup_status_counts,
    normalize_lookup_status,
    normalize_lookup_trace_status,
)


def test_all_lookup_lifecycle_states_validate():
    expected = {
        "success",
        "failed",
        "skipped",
        "unauthorized",
        "no_match",
        "duplicate_match",
        "timeout",
        "cancelled",
        "partial_success",
    }

    assert LOOKUP_LIFECYCLE_STATES == expected
    assert all(is_lookup_lifecycle_state(state) for state in expected)
    assert is_lookup_aggregate_state("not_attempted") is True
    assert is_lookup_aggregate_state("request_not_created") is True
    assert is_lookup_aggregate_state("not_executed") is True


def test_unknown_lifecycle_state_fails_closed():
    assert is_lookup_lifecycle_state("semantic_search") is False
    assert is_lookup_aggregate_state("semantic_search") is False
    assert normalize_lookup_trace_status(
        {
            "lookup_status": "semantic_search",
            "retrieval_executed": True,
            "records_returned": 0,
            "skipped_reasons": ["unexpected_executor_output"],
        }
    ) == "failed"


def test_lookup_status_normalization():
    assert normalize_lookup_status(
        retrieval_executed=True,
        records_returned=1,
        skipped_reasons=[],
    ) == "success"
    assert normalize_lookup_status(
        retrieval_executed=True,
        records_returned=0,
        skipped_reasons=["no_exact_match"],
    ) == "no_match"
    assert normalize_lookup_status(
        retrieval_executed=True,
        records_returned=0,
        skipped_reasons=["multiple_exact_matches"],
    ) == "duplicate_match"
    assert normalize_lookup_status(
        retrieval_executed=False,
        records_returned=0,
        skipped_reasons=["lookup_executor_unavailable"],
    ) == "unauthorized"
    assert normalize_lookup_status(
        retrieval_executed=False,
        records_returned=0,
        skipped_reasons=["lookup_capability_resolution_failed"],
    ) == "skipped"
    assert normalize_lookup_status(
        retrieval_executed=True,
        records_returned=0,
        skipped_reasons=["malformed_lookup_payload"],
    ) == "failed"
    assert normalize_lookup_status(
        retrieval_executed=False,
        records_returned=0,
        skipped_reasons=["lookup_execution_timeout"],
    ) == "timeout"
    assert normalize_lookup_status(
        retrieval_executed=False,
        records_returned=0,
        skipped_reasons=["lookup_execution_cancelled"],
    ) == "cancelled"


def test_partial_success_aggregation_is_deterministic():
    traces = [
        {
            "lookup_status": "success",
            "retrieval_executed": True,
            "records_returned": 1,
            "skipped_reasons": [],
        },
        {
            "lookup_status": "no_match",
            "retrieval_executed": True,
            "records_returned": 0,
            "skipped_reasons": ["no_exact_match"],
        },
        {
            "lookup_status": "success",
            "retrieval_executed": True,
            "records_returned": 1,
            "skipped_reasons": [],
        },
    ]
    counts = lookup_status_counts(traces)

    assert counts == {"success": 2, "no_match": 1}
    assert aggregate_lookup_execution_status(
        attempted=True,
        request_created=True,
        execution_traces=traces,
        status_counts=counts,
    ) == "partial_success"


def test_unknown_trace_state_counts_as_failed():
    traces = [
        {
            "lookup_status": "new_unreviewed_state",
            "retrieval_executed": True,
            "records_returned": 0,
            "skipped_reasons": ["unexpected_executor_output"],
        }
    ]
    counts = lookup_status_counts(traces)

    assert counts == {"failed": 1}
    assert aggregate_lookup_execution_status(
        attempted=True,
        request_created=True,
        execution_traces=traces,
        status_counts=counts,
    ) == "failed"


def test_timeout_and_cancelled_aggregation_is_deterministic():
    timeout_traces = [
        {
            "lookup_status": "timeout",
            "retrieval_executed": False,
            "records_returned": 0,
            "skipped_reasons": ["lookup_execution_timeout"],
        }
    ]
    cancelled_traces = [
        {
            "lookup_status": "cancelled",
            "retrieval_executed": False,
            "records_returned": 0,
            "skipped_reasons": ["lookup_execution_cancelled"],
        }
    ]

    timeout_counts = lookup_status_counts(timeout_traces)
    cancelled_counts = lookup_status_counts(cancelled_traces)

    assert timeout_counts == {"timeout": 1}
    assert cancelled_counts == {"cancelled": 1}
    assert aggregate_lookup_execution_status(
        attempted=True,
        request_created=True,
        execution_traces=timeout_traces,
        status_counts=timeout_counts,
    ) == "timeout"
    assert aggregate_lookup_execution_status(
        attempted=True,
        request_created=True,
        execution_traces=cancelled_traces,
        status_counts=cancelled_counts,
    ) == "cancelled"


def main():
    test_all_lookup_lifecycle_states_validate()
    test_unknown_lifecycle_state_fails_closed()
    test_lookup_status_normalization()
    test_partial_success_aggregation_is_deterministic()
    test_unknown_trace_state_counts_as_failed()
    test_timeout_and_cancelled_aggregation_is_deterministic()
    print("PASS lookup lifecycle")


if __name__ == "__main__":
    main()
