import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.lookup.telemetry import (  # noqa: E402
    build_bounded_lookup_trace,
)
from runtime.lookup.types import (  # noqa: E402
    BoundedLookupRequest,
    BoundedLookupResult,
)
from tools.test_context_trace_payload import (  # noqa: E402
    forbidden_keys_in_payload,
)


class Env:
    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def request(**overrides):
    data = {
        "lookup_id": "lookup-001",
        "source_contract_id": "alexis_guest_db",
        "lookup_mode": "fixed_id",
        "query": "Jane Doe user text",
        "lookup_key": "entity_id",
        "lookup_value": "entity-001",
        "max_records": 1,
    }
    data.update(overrides)
    return BoundedLookupRequest(**data)


def result(**overrides):
    data = {
        "lookup_id": "lookup-001",
        "source_contract_id": "alexis_guest_db",
        "records": [
            {
                "record_id": "entity-001",
                "display_name": "Jane Doe",
                "private_notes": "Private summary text",
            },
        ],
        "retrieval_executed": True,
        "skipped_reasons": [],
    }
    data.update(overrides)
    return BoundedLookupResult(**data)


def test_request_result_trace_includes_ids_counts_flags():
    trace = build_bounded_lookup_trace(
        request=request(),
        result=result(),
    )

    assert trace == {
        "lookup_id": "lookup-001",
        "source_contract_id": "alexis_guest_db",
        "lookup_mode": "fixed_id",
        "lookup_key": "entity_id",
        "max_records": 1,
        "retrieval_executed": True,
        "records_returned": 1,
        "skipped_reasons": [],
    }


def test_retrieval_executed_false_trace_works():
    trace = build_bounded_lookup_trace(
        request=request(),
        result=result(
            records=[],
            retrieval_executed=False,
            skipped_reasons=["not_implemented"],
        ),
    )

    assert trace["retrieval_executed"] is False
    assert trace["records_returned"] == 0
    assert trace["skipped_reasons"] == ["not_implemented"]


def test_none_request_result_works_fail_closed():
    trace = build_bounded_lookup_trace(request=None, result=None)

    assert trace == {
        "lookup_id": None,
        "source_contract_id": None,
        "lookup_mode": None,
        "lookup_key": None,
        "max_records": None,
        "retrieval_executed": False,
        "records_returned": 0,
        "skipped_reasons": [],
    }


def test_query_is_not_included():
    trace = build_bounded_lookup_trace(
        request=request(query="sensitive query text"),
        result=result(),
    )

    assert "query" not in trace
    assert "sensitive query text" not in repr(trace)


def test_lookup_key_included_but_lookup_value_not_included():
    trace = build_bounded_lookup_trace(
        request=request(lookup_value="sensitive-entity-id"),
        result=result(),
    )

    assert trace["lookup_key"] == "entity_id"
    assert "lookup_value" not in trace
    assert "sensitive-entity-id" not in repr(trace)


def test_record_contents_are_not_included():
    trace = build_bounded_lookup_trace(
        request=request(),
        result=result(),
    )

    assert "records" not in trace
    assert "Jane Doe" not in repr(trace)
    assert "Private summary text" not in repr(trace)
    assert forbidden_keys_in_payload(trace) == []


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        composer_result = compose_bounded_context(
            request_id="req_lookup_telemetry",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert composer_result.injection_performed is True
    assert composer_result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_request_result_trace_includes_ids_counts_flags()
    test_retrieval_executed_false_trace_works()
    test_none_request_result_works_fail_closed()
    test_query_is_not_included()
    test_lookup_key_included_but_lookup_value_not_included()
    test_record_contents_are_not_included()
    test_context_composer_behavior_unchanged()
    print("PASS bounded lookup telemetry")


if __name__ == "__main__":
    main()
