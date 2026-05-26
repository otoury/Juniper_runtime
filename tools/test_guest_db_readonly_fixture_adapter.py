import os
import sys
import tempfile
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_composer as composer  # noqa: E402
import runtime.context_adapter_factory as adapter_factory  # noqa: E402
from agents.alexis.adapters.guest_db.fixture_adapter import (  # noqa: E402
    GuestDbReadonlyFixtureAdapter,
    MAX_SUMMARY_CHARS,
)
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.context_types import (  # noqa: E402
    validate_context_item_source_contract,
    validate_resolved_context_item,
)
from agents.alexis.adapters.guest_db.record_renderer import (  # noqa: E402
    render_guest_record_summary,
)
from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
)
from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    list_context_injection_contracts,
)
from tools.test_context_trace_payload import (  # noqa: E402
    forbidden_keys_in_payload,
)


FIXTURE_RECORD = {
    "guest_id": "fixture_guest_1",
    "display_name": "Jane Doe",
    "title": "Former State Department official",
    "expertise": "Middle East policy",
    "booking_notes": "Good on live hits",
    "source_updated_at": "2026-05-17T00:00:00Z",
}
FIXTURE_SUMMARY = render_guest_record_summary(FIXTURE_RECORD)


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


def temp_fixture(payload: object, *, raw_json: str | None = None) -> Path:
    path = Path(tempfile.mkdtemp()) / "guest_fixture.json"
    if raw_json is None:
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(raw_json, encoding="utf-8")
    return path


def fixture_adapter_contract(**overrides):
    data = {
        "adapter_id": "guest_db_readonly_fixture",
        "source_contract_id": "alexis_guest_db",
        "enabled": True,
        "adapter_type": "structured_database",
        "execution_mode": "read_only_fixture",
        "external_reads_allowed": True,
        "read_scope": "local_fixture_file",
        "read_target": "tools/fixtures/guest_db_readonly_fixture.json",
        "max_records": 1,
        "writes_allowed": False,
        "raw_data": {},
    }
    data.update(overrides)
    return ContextAdapterContract(**data)


def run_with_adapter_contract(
    adapter_contract: ContextAdapterContract,
    *,
    external_reads_enabled: bool,
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
                request_id="req_guest_db_fixture",
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
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_default",
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


def test_external_read_adapter_not_invoked_without_env_flag():
    result = run_with_adapter_contract(
        fixture_adapter_contract(),
        external_reads_enabled=False,
    )

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.skipped_reasons == ["external_context_reads_disabled"]
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is False


def test_no_file_read_occurs_when_external_env_flag_disabled():
    original_factory = (
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly_fixture"
        ]
    )
    calls = {"init": 0, "retrieve": 0}

    class CountingAdapter:
        def __init__(self, contract):
            calls["init"] += 1

        def retrieve(self, **kwargs):
            calls["retrieve"] += 1
            raise AssertionError("adapter should not be invoked")

    adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
        "guest_db_readonly_fixture"
    ] = lambda contract, adapter_contract: CountingAdapter(contract)

    try:
        result = run_with_adapter_contract(
            fixture_adapter_contract(),
            external_reads_enabled=False,
        )
    finally:
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly_fixture"
        ] = original_factory

    assert result.injection_performed is False
    assert calls == {"init": 0, "retrieve": 0}


def test_adapter_reads_fixture_and_returns_one_valid_item():
    adapter = GuestDbReadonlyFixtureAdapter(injection_contract())
    items = adapter.retrieve(
        request_id="req_guest_db_direct",
        agent="alexis",
        shared_capability="draft_email",
    )

    assert len(items) == 1
    item = items[0]
    assert item.source_contract_id == "alexis_guest_db"
    assert item.content_type == "database_summary"
    assert item.provenance.retrieval_executed is True
    assert item.provenance.attribution == "guest_db_record"
    assert item.trust_level == "retrieved_unverified"
    assert item.rendering_policy == "bounded_context_block"
    assert item.content == FIXTURE_SUMMARY
    assert validate_resolved_context_item(item) == []
    assert validate_context_item_source_contract(
        item,
        require_declared_source=True,
        root=ROOT,
    ) == []


def test_invalid_json_fixture_returns_no_items():
    path = temp_fixture({}, raw_json="{")
    adapter = GuestDbReadonlyFixtureAdapter(
        injection_contract(),
        fixture_path=path,
    )

    assert adapter.retrieve(
        request_id="req_guest_db_invalid_json",
        agent="alexis",
        shared_capability="draft_email",
    ) == []


def test_non_object_fixture_returns_no_items():
    path = temp_fixture([
        {
            "guest_id": "fixture_guest_1",
            "display_name": "Jane Doe",
        }
    ])
    adapter = GuestDbReadonlyFixtureAdapter(
        injection_contract(),
        fixture_path=path,
    )

    assert adapter.retrieve(
        request_id="req_guest_db_non_object",
        agent="alexis",
        shared_capability="draft_email",
    ) == []


def test_missing_fixture_guest_id_returns_no_items():
    path = temp_fixture({
        "display_name": "Jane Doe",
    })
    adapter = GuestDbReadonlyFixtureAdapter(
        injection_contract(),
        fixture_path=path,
    )

    assert adapter.retrieve(
        request_id="req_guest_db_missing_id",
        agent="alexis",
        shared_capability="draft_email",
    ) == []


def test_missing_fixture_display_name_returns_no_items():
    path = temp_fixture({
        "guest_id": "fixture_guest_1",
    })
    adapter = GuestDbReadonlyFixtureAdapter(
        injection_contract(),
        fixture_path=path,
    )

    assert adapter.retrieve(
        request_id="req_guest_db_missing_summary",
        agent="alexis",
        shared_capability="draft_email",
    ) == []


def test_oversized_fixture_summary_returns_no_items():
    oversized_summary = "x" * (MAX_SUMMARY_CHARS + 1)
    payload = dict(FIXTURE_RECORD)
    payload["booking_notes"] = oversized_summary
    path = temp_fixture(payload)
    adapter = GuestDbReadonlyFixtureAdapter(
        injection_contract(),
        fixture_path=path,
    )

    assert adapter.retrieve(
        request_id="req_guest_db_oversized_summary",
        agent="alexis",
        shared_capability="draft_email",
    ) == []


def test_composer_reads_fixture_with_enabled_mapping_and_env_flag():
    result = run_with_adapter_contract(
        fixture_adapter_contract(),
        external_reads_enabled=True,
    )

    assert result.injection_performed is True
    assert len(result.items) == 1
    assert len(result.rendered_blocks) == 1
    assert FIXTURE_SUMMARY in result.rendered_blocks[0]
    assert result.items[0].content == FIXTURE_SUMMARY
    assert result.items[0].provenance.retrieval_executed is True
    assert (
        result.trace_payload["adapter_trace"]["adapter_id"]
        == "guest_db_readonly_fixture"
    )
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["items_returned"] == 1
    assert result.trace_payload["adapter_trace"]["external_reads_allowed"] is True
    assert (
        result.trace_payload["adapter_trace"]["read_scope"]
        == "local_fixture_file"
    )
    assert (
        result.trace_payload["adapter_trace"]["read_target"]
        == "tools/fixtures/guest_db_readonly_fixture.json"
    )
    assert result.trace_payload["adapter_trace"]["max_records"] == 1
    assert result.trace_payload["adapter_trace"]["writes_allowed"] is False


def test_fixture_adapter_telemetry_remains_content_safe():
    result = run_with_adapter_contract(
        fixture_adapter_contract(),
        external_reads_enabled=True,
    )

    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert FIXTURE_SUMMARY not in repr(result.trace_payload)
    assert "BOUNDED CONTEXT" not in repr(result.trace_payload)


def test_invalid_fixture_composer_failure_is_content_safe():
    bad_summary = "This raw invalid fixture summary must not appear."
    path = temp_fixture({
        "guest_id": "fixture_guest_1",
        "display_name": bad_summary,
        "booking_notes": ["invalid"],
    })
    original_factory = (
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly_fixture"
        ]
    )

    class InvalidFixtureAdapter(GuestDbReadonlyFixtureAdapter):
        def __init__(self, contract):
            super().__init__(contract, fixture_path=path)

    adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
        "guest_db_readonly_fixture"
    ] = lambda contract, adapter_contract: InvalidFixtureAdapter(contract)

    try:
        result = run_with_adapter_contract(
            fixture_adapter_contract(),
            external_reads_enabled=True,
        )
    finally:
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly_fixture"
        ] = original_factory

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["items_returned"] == 0
    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert bad_summary not in repr(result.trace_payload)


def test_oversized_fixture_composer_failure_is_content_safe():
    oversized_summary = "oversized-fixture-summary-" * 40
    payload = dict(FIXTURE_RECORD)
    payload["booking_notes"] = oversized_summary
    path = temp_fixture(payload)
    original_factory = (
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly_fixture"
        ]
    )

    class OversizedFixtureAdapter(GuestDbReadonlyFixtureAdapter):
        def __init__(self, contract):
            super().__init__(contract, fixture_path=path)

    adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
        "guest_db_readonly_fixture"
    ] = lambda contract, adapter_contract: OversizedFixtureAdapter(contract)

    try:
        result = run_with_adapter_contract(
            fixture_adapter_contract(),
            external_reads_enabled=True,
        )
    finally:
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "guest_db_readonly_fixture"
        ] = original_factory

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["items_returned"] == 0
    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert oversized_summary not in repr(result.trace_payload)


def test_current_synthetic_adapter_behavior_remains_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS="1",
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_synthetic",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_disabled_registry_mapping_does_not_affect_current_behavior()
    test_external_read_adapter_not_invoked_without_env_flag()
    test_no_file_read_occurs_when_external_env_flag_disabled()
    test_adapter_reads_fixture_and_returns_one_valid_item()
    test_invalid_json_fixture_returns_no_items()
    test_non_object_fixture_returns_no_items()
    test_missing_fixture_guest_id_returns_no_items()
    test_missing_fixture_display_name_returns_no_items()
    test_oversized_fixture_summary_returns_no_items()
    test_composer_reads_fixture_with_enabled_mapping_and_env_flag()
    test_fixture_adapter_telemetry_remains_content_safe()
    test_invalid_fixture_composer_failure_is_content_safe()
    test_oversized_fixture_composer_failure_is_content_safe()
    test_current_synthetic_adapter_behavior_remains_unchanged()
    print("PASS guest db readonly fixture adapter")


if __name__ == "__main__":
    main()
