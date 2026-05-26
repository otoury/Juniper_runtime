import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_adapter_factory as adapter_factory  # noqa: E402
import runtime.context_composer as composer  # noqa: E402
from agents.alexis.adapters.guest_db.readonly_adapter import (  # noqa: E402
    AlexisGuestDbReadonlyAdapter,
    CANONICAL_GUESTS_CSV_PATH,
)
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.lookup.types import BoundedLookupRequest  # noqa: E402
from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
)
from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    list_context_injection_contracts,
)
from tools.test_context_trace_payload import (  # noqa: E402
    forbidden_keys_in_payload,
)


KNOWN_GUEST_ID = "dr_saju_matthew"
KNOWN_GUEST_SUMMARY = (
    "Guest: Dr. Saju Matthew\n"
    "Title: Family Practice Physician\n"
    "Booking notes: ⭐ BOOK MONTHLY — one of our favorites"
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


def injection_contract():
    return list_context_injection_contracts(ROOT)[0]


def readonly_adapter_contract(**overrides):
    data = {
        "adapter_id": "guest_db_readonly",
        "source_contract_id": "alexis_guest_db",
        "enabled": True,
        "adapter_type": "structured_database",
        "execution_mode": "read_only_fixed_id",
        "external_reads_allowed": True,
        "read_scope": "declared_local_database",
        "read_target": str(CANONICAL_GUESTS_CSV_PATH),
        "max_records": 1,
        "writes_allowed": False,
        "raw_data": {},
        "lookup_request": BoundedLookupRequest(
            lookup_id="lookup-known",
            source_contract_id="alexis_guest_db",
            lookup_mode="fixed_id",
            query=None,
            lookup_key="entity_id",
            lookup_value=KNOWN_GUEST_ID,
            max_records=1,
        ),
    }
    data.update(overrides)
    return ContextAdapterContract(**data)


def run_with_adapter_contract(
    adapter_contract,
    *,
    external_reads_enabled,
):
    original_lookup = composer.get_context_adapter_for_source

    def lookup(source_contract_id):
        return adapter_contract

    composer.get_context_adapter_for_source = lookup

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
            JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=(
                "1" if external_reads_enabled else None
            ),
        ):
            return compose_bounded_context(
                request_id="req_guest_db_readonly",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup


def test_disabled_registry_mapping_does_not_affect_current_behavior():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS="1",
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_readonly_default",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]
    assert (
        result.trace_payload["adapter_trace"]["adapter_id"]
        == "synthetic_guest_context"
    )


def test_fixed_id_lookup_with_env_and_test_enabled_mapping_returns_one_item():
    result = run_with_adapter_contract(
        readonly_adapter_contract(),
        external_reads_enabled=True,
    )

    assert result.injection_performed is True
    assert len(result.items) == 1
    assert result.items[0].id == f"guest_db_readonly:{KNOWN_GUEST_ID}"
    assert result.items[0].content == KNOWN_GUEST_SUMMARY
    assert KNOWN_GUEST_SUMMARY in result.rendered_blocks[0]
    assert (
        result.trace_payload["adapter_trace"]["adapter_id"]
        == "guest_db_readonly"
    )
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["items_returned"] == 1


def test_adapter_trace_includes_lookup_trace_when_invoked():
    result = run_with_adapter_contract(
        readonly_adapter_contract(),
        external_reads_enabled=True,
    )

    lookup_trace = result.trace_payload["adapter_trace"]["lookup_trace"]
    assert lookup_trace == {
        "lookup_id": "lookup-known",
        "source_contract_id": "alexis_guest_db",
        "lookup_mode": "fixed_id",
        "lookup_key": "entity_id",
        "max_records": 1,
        "retrieval_executed": True,
        "records_returned": 1,
        "skipped_reasons": [],
    }


def test_lookup_trace_excludes_value_query_and_record_contents():
    result = run_with_adapter_contract(
        readonly_adapter_contract(
            lookup_request=BoundedLookupRequest(
                lookup_id="lookup-sensitive",
                source_contract_id="alexis_guest_db",
                lookup_mode="fixed_id",
                query="sensitive query text",
                lookup_key="entity_id",
                lookup_value=KNOWN_GUEST_ID,
                max_records=1,
            )
        ),
        external_reads_enabled=True,
    )

    adapter_trace = result.trace_payload["adapter_trace"]
    lookup_trace = adapter_trace["lookup_trace"]
    rendered_trace = repr(adapter_trace)

    assert "lookup_value" not in lookup_trace
    assert "query" not in lookup_trace
    assert KNOWN_GUEST_ID not in rendered_trace
    assert "sensitive query text" not in rendered_trace
    assert "Dr. Saju Matthew" not in rendered_trace
    assert KNOWN_GUEST_SUMMARY not in rendered_trace


def test_readonly_adapter_uses_request_lookup_fields():
    adapter = AlexisGuestDbReadonlyAdapter(
        injection_contract(),
        readonly_adapter_contract(
            lookup_request=BoundedLookupRequest(
                lookup_id="lookup-request-fields",
                source_contract_id="alexis_guest_db",
                lookup_mode="fixed_id",
                query="ignored user text",
                lookup_key="entity_id",
                lookup_value=KNOWN_GUEST_ID,
                max_records=1,
            )
        ),
    )

    items = adapter.retrieve(
        request_id="req_ignored",
        agent="alexis",
        shared_capability="draft_email",
    )

    assert len(items) == 1
    assert items[0].id == f"guest_db_readonly:{KNOWN_GUEST_ID}"


def test_missing_env_flag_prevents_file_read_and_invocation():
    original_factory = (
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly"
        ]
    )
    calls = {"factory": 0, "retrieve": 0}

    class CountingAdapter:
        def __init__(self, contract, adapter_contract):
            calls["factory"] += 1

        def retrieve(self, **kwargs):
            calls["retrieve"] += 1
            raise AssertionError("adapter should not be invoked")

    adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
        "guest_db_readonly"
    ] = lambda contract, adapter_contract: CountingAdapter(
        contract,
        adapter_contract,
    )

    try:
        result = run_with_adapter_contract(
            readonly_adapter_contract(),
            external_reads_enabled=False,
        )
    finally:
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly"
        ] = original_factory

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.skipped_reasons == ["external_context_reads_disabled"]
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is False
    assert "lookup_trace" not in result.trace_payload["adapter_trace"]
    assert calls == {"factory": 0, "retrieve": 0}


def test_unknown_guest_id_returns_no_item():
    adapter = AlexisGuestDbReadonlyAdapter(
        injection_contract(),
        readonly_adapter_contract(),
    )
    lookup_result = adapter.lookup(
        BoundedLookupRequest(
            lookup_id="lookup-unknown",
            source_contract_id="alexis_guest_db",
            lookup_mode="fixed_id",
            query="missing_guest_id",
            lookup_key="entity_id",
            lookup_value="missing_guest_id",
            max_records=1,
        )
    )

    assert lookup_result.retrieval_executed is True
    assert lookup_result.records == []
    assert lookup_result.skipped_reasons == ["guest_id_not_found"]


def test_max_records_remains_one():
    contract = readonly_adapter_contract()
    adapter = AlexisGuestDbReadonlyAdapter(injection_contract(), contract)
    lookup_result = adapter.lookup(
        BoundedLookupRequest(
            lookup_id="lookup-known",
            source_contract_id="alexis_guest_db",
            lookup_mode="fixed_id",
            query=None,
            lookup_key="entity_id",
            lookup_value=KNOWN_GUEST_ID,
            max_records=1,
        )
    )

    assert contract.max_records == 1
    assert len(lookup_result.records) == 1


def test_telemetry_remains_content_safe():
    result = run_with_adapter_contract(
        readonly_adapter_contract(),
        external_reads_enabled=True,
    )

    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert KNOWN_GUEST_SUMMARY not in repr(result.trace_payload)
    assert "Dr. Saju Matthew" not in repr(result.trace_payload)


def test_skipped_lookup_path_remains_content_safe():
    result = run_with_adapter_contract(
        readonly_adapter_contract(
            lookup_request=BoundedLookupRequest(
                lookup_id="lookup-missing",
                source_contract_id="alexis_guest_db",
                lookup_mode="fixed_id",
                query="sensitive missing query",
                lookup_key="entity_id",
                lookup_value="missing_guest_id",
                max_records=1,
            )
        ),
        external_reads_enabled=True,
    )

    adapter_trace = result.trace_payload["adapter_trace"]
    lookup_trace = adapter_trace["lookup_trace"]
    rendered_trace = repr(adapter_trace)

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.skipped_reasons == ["context_adapter_no_item"]
    assert lookup_trace["retrieval_executed"] is True
    assert lookup_trace["records_returned"] == 0
    assert lookup_trace["skipped_reasons"] == ["guest_id_not_found"]
    assert "lookup_value" not in lookup_trace
    assert "query" not in lookup_trace
    assert "missing_guest_id" not in rendered_trace
    assert "sensitive missing query" not in rendered_trace


def test_synthetic_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS="1",
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_readonly_synthetic",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]
    assert "lookup_trace" not in result.trace_payload["adapter_trace"]


def test_fixture_behavior_unchanged():
    fixture_contract = ContextAdapterContract(
        adapter_id="guest_db_readonly_fixture",
        source_contract_id="alexis_guest_db",
        enabled=True,
        adapter_type="structured_database",
        execution_mode="read_only_fixture",
        external_reads_allowed=True,
        read_scope="local_fixture_file",
        read_target="tools/fixtures/guest_db_readonly_fixture.json",
        max_records=1,
        writes_allowed=False,
        raw_data={},
        lookup_request=None,
    )
    result = run_with_adapter_contract(
        fixture_contract,
        external_reads_enabled=True,
    )

    assert result.injection_performed is True
    assert len(result.items) == 1
    assert (
        result.trace_payload["adapter_trace"]["adapter_id"]
        == "guest_db_readonly_fixture"
    )
    assert "lookup_trace" not in result.trace_payload["adapter_trace"]


def main():
    test_disabled_registry_mapping_does_not_affect_current_behavior()
    test_fixed_id_lookup_with_env_and_test_enabled_mapping_returns_one_item()
    test_adapter_trace_includes_lookup_trace_when_invoked()
    test_lookup_trace_excludes_value_query_and_record_contents()
    test_readonly_adapter_uses_request_lookup_fields()
    test_missing_env_flag_prevents_file_read_and_invocation()
    test_unknown_guest_id_returns_no_item()
    test_max_records_remains_one()
    test_telemetry_remains_content_safe()
    test_skipped_lookup_path_remains_content_safe()
    test_synthetic_behavior_unchanged()
    test_fixture_behavior_unchanged()
    print("PASS guest db readonly adapter")


if __name__ == "__main__":
    main()
