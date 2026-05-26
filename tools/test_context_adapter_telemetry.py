import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_composer as composer  # noqa: E402
from runtime.context_adapter_telemetry import (  # noqa: E402
    build_context_adapter_trace,
)
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
)
from tools.test_context_trace_payload import (  # noqa: E402
    forbidden_keys_in_payload,
)


REQUIRED_FIELDS = {
    "source_contract_id",
    "adapter_id",
    "adapter_type",
    "execution_mode",
    "adapter_invoked",
    "items_returned",
    "raw_items_returned",
    "valid_items_returned",
    "skipped_reasons",
    "exception_type",
    "external_reads_allowed",
    "read_scope",
    "read_target",
    "max_records",
    "writes_allowed",
}


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


def disabled_contract():
    return ContextAdapterContract(
        adapter_id="synthetic_guest_context",
        source_contract_id="alexis_guest_db",
        enabled=False,
        adapter_type="synthetic",
        execution_mode="synthetic_only",
        external_reads_allowed=False,
        read_scope=None,
        read_target=None,
        max_records=None,
        writes_allowed=None,
        raw_data={},
    )


def external_read_contract():
    return ContextAdapterContract(
        adapter_id="synthetic_guest_context",
        source_contract_id="alexis_guest_db",
        enabled=True,
        adapter_type="synthetic",
        execution_mode="synthetic_only",
        external_reads_allowed=True,
        read_scope="local_fixture_file",
        read_target="tools/fixtures/guest_db_readonly_fixture.json",
        max_records=1,
        writes_allowed=False,
        raw_data={},
    )


def declared_guest_db_contract():
    return ContextAdapterContract(
        adapter_id="guest_db_readonly",
        source_contract_id="alexis_guest_db",
        enabled=True,
        adapter_type="structured_database",
        execution_mode="read_only_declared",
        external_reads_allowed=True,
        read_scope="declared_local_database",
        read_target="data/guest_db.json",
        max_records=1,
        writes_allowed=False,
        raw_data={},
    )


def test_adapter_trace_includes_required_fields():
    trace = build_context_adapter_trace(
        source_contract_id="alexis_guest_db",
        adapter_id="synthetic_guest_context",
        adapter_type="synthetic",
        execution_mode="synthetic_only",
        adapter_invoked=True,
        items_returned=1,
        skipped_reasons=[],
    )

    assert REQUIRED_FIELDS <= set(trace)


def test_adapter_trace_can_include_content_safe_lookup_trace():
    trace = build_context_adapter_trace(
        source_contract_id="alexis_guest_db",
        adapter_id="guest_db_readonly",
        adapter_type="structured_database",
        execution_mode="read_only_fixed_id",
        adapter_invoked=True,
        items_returned=1,
        skipped_reasons=[],
        lookup_trace={
            "lookup_id": "lookup-known",
            "source_contract_id": "alexis_guest_db",
            "lookup_mode": "fixed_id",
            "lookup_key": "entity_id",
            "max_records": 1,
            "retrieval_executed": True,
            "records_returned": 1,
            "skipped_reasons": [],
        },
    )

    assert trace["lookup_trace"]["lookup_key"] == "entity_id"
    assert "lookup_value" not in repr(trace)
    assert "query" not in repr(trace)


def test_invoked_adapter_reports_item_count():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_trace",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    adapter_trace = result.trace_payload["adapter_trace"]
    assert adapter_trace["adapter_invoked"] is True
    assert adapter_trace["items_returned"] == 1
    assert adapter_trace["raw_items_returned"] == 1
    assert adapter_trace["valid_items_returned"] == 1
    assert adapter_trace["adapter_id"] == "synthetic_guest_context"
    assert adapter_trace["external_reads_allowed"] is False
    assert adapter_trace["read_scope"] is None
    assert adapter_trace["read_target"] is None
    assert adapter_trace["max_records"] is None
    assert adapter_trace["writes_allowed"] is None


def test_missing_adapter_mapping_reports_not_invoked():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return None

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        ):
            result = compose_bounded_context(
                request_id="req_adapter_missing_trace",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    adapter_trace = result.trace_payload["adapter_trace"]
    assert adapter_trace["adapter_invoked"] is False
    assert adapter_trace["items_returned"] == 0
    assert adapter_trace["adapter_id"] is None
    assert adapter_trace["skipped_reasons"] == [
        "context_adapter_mapping_unavailable"
    ]


def test_disabled_adapter_mapping_reports_not_invoked():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return disabled_contract()

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        ):
            result = compose_bounded_context(
                request_id="req_adapter_disabled_trace",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    adapter_trace = result.trace_payload["adapter_trace"]
    assert adapter_trace["adapter_invoked"] is False
    assert adapter_trace["items_returned"] == 0
    assert adapter_trace["adapter_id"] == "synthetic_guest_context"
    assert adapter_trace["skipped_reasons"] == [
        "context_adapter_mapping_unavailable"
    ]


def test_adapter_trace_is_content_safe():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_trace_safe",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert forbidden_keys_in_payload(result.trace_payload["adapter_trace"]) == []
    assert "Bounded guest context" not in repr(
        result.trace_payload["adapter_trace"]
    )


def test_external_read_adapter_not_invoked_without_flag():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return external_read_contract()

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
            JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
        ):
            result = compose_bounded_context(
                request_id="req_external_disabled",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    adapter_trace = result.trace_payload["adapter_trace"]
    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.skipped_reasons == ["external_context_reads_disabled"]
    assert adapter_trace["adapter_invoked"] is False
    assert adapter_trace["external_reads_allowed"] is True
    assert adapter_trace["read_scope"] == "local_fixture_file"
    assert (
        adapter_trace["read_target"]
        == "tools/fixtures/guest_db_readonly_fixture.json"
    )
    assert adapter_trace["max_records"] == 1
    assert adapter_trace["writes_allowed"] is False
    assert adapter_trace["skipped_reasons"] == [
        "external_context_reads_disabled"
    ]


def test_external_read_adapter_passes_guard_with_flag():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return external_read_contract()

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
            JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS="1",
        ):
            result = compose_bounded_context(
                request_id="req_external_enabled",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    assert result.injection_performed is True
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["external_reads_allowed"] is True
    assert (
        result.trace_payload["adapter_trace"]["read_target"]
        == "tools/fixtures/guest_db_readonly_fixture.json"
    )


def test_declared_guest_db_adapter_reports_not_implemented():
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return declared_guest_db_contract()

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
            JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS="1",
        ):
            result = compose_bounded_context(
                request_id="req_declared_guest_db_trace",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    adapter_trace = result.trace_payload["adapter_trace"]
    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.skipped_reasons == ["context_adapter_not_implemented"]
    assert adapter_trace["adapter_id"] == "guest_db_readonly"
    assert adapter_trace["execution_mode"] == "read_only_declared"
    assert adapter_trace["adapter_invoked"] is False
    assert adapter_trace["items_returned"] == 0
    assert adapter_trace["external_reads_allowed"] is True
    assert adapter_trace["read_scope"] == "declared_local_database"
    assert adapter_trace["read_target"] == "data/guest_db.json"
    assert adapter_trace["max_records"] == 1
    assert adapter_trace["writes_allowed"] is False
    assert adapter_trace["skipped_reasons"] == [
        "context_adapter_not_implemented"
    ]
    assert forbidden_keys_in_payload(adapter_trace) == []


def main():
    test_adapter_trace_includes_required_fields()
    test_adapter_trace_can_include_content_safe_lookup_trace()
    test_invoked_adapter_reports_item_count()
    test_missing_adapter_mapping_reports_not_invoked()
    test_disabled_adapter_mapping_reports_not_invoked()
    test_adapter_trace_is_content_safe()
    test_external_read_adapter_not_invoked_without_flag()
    test_external_read_adapter_passes_guard_with_flag()
    test_declared_guest_db_adapter_reports_not_implemented()
    print("PASS context adapter telemetry")


if __name__ == "__main__":
    main()
