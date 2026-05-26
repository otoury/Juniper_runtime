import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.registries.adapter_binding_registry import (  # noqa: E402
    ContextAdapterContract,
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


def test_valid_conditions_produce_one_rendered_block():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_CONTEXT_INJECTION_CAPABILITIES=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_context_composer",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]
    assert len(result.items) == 1
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["items_returned"] == 1


def test_wrong_agent_produces_no_rendered_block():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = compose_bounded_context(
            request_id="req_context_composer",
            agent="yossi",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "no_matching_injection_contract" in result.skipped_reasons


def test_wrong_capability_produces_no_rendered_block():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = compose_bounded_context(
            request_id="req_context_composer",
            agent="alexis",
            shared_capability="send_email",
            planner_mode="ACTION",
        )

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "no_matching_injection_contract" in result.skipped_reasons


def test_rollback_flag_produces_no_rendered_block():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION="1",
    ):
        result = compose_bounded_context(
            request_id="req_context_composer",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_injection_rollback_enabled" in result.skipped_reasons


def test_trace_payload_remains_content_safe():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = compose_bounded_context(
            request_id="req_context_composer",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert "BOUNDED CONTEXT" not in repr(result.trace_payload)
    assert "Bounded guest context" not in repr(
        result.trace_payload["adapter_trace"]
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


def test_declared_guest_db_adapter_fails_closed_when_enabled():
    import runtime.context_composer as composer

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
                request_id="req_context_declared_guard",
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
    assert adapter_trace["read_scope"] == "declared_local_database"
    assert adapter_trace["read_target"] == "data/guest_db.json"
    assert adapter_trace["skipped_reasons"] == [
        "context_adapter_not_implemented"
    ]


def test_declared_guest_db_guard_does_not_read_target_file():
    import runtime.context_composer as composer

    original_lookup = composer.get_context_adapter_for_source
    original_read_text = Path.read_text
    target_reads = []

    def lookup(source_contract_id):
        return declared_guest_db_contract()

    def read_text_guard(self, *args, **kwargs):
        if str(self) == "data/guest_db.json":
            target_reads.append(str(self))
            raise AssertionError("declared guest DB target must not be read")
        return original_read_text(self, *args, **kwargs)

    composer.get_context_adapter_for_source = lookup
    Path.read_text = read_text_guard

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
            JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS="1",
        ):
            result = compose_bounded_context(
                request_id="req_context_declared_no_read",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        Path.read_text = original_read_text
        composer.get_context_adapter_for_source = original_lookup

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is False
    assert target_reads == []


def test_declared_guest_db_adapter_trace_remains_content_safe():
    import runtime.context_composer as composer

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
                request_id="req_context_declared_trace_safe",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        composer.get_context_adapter_for_source = original_lookup

    assert forbidden_keys_in_payload(result.trace_payload["adapter_trace"]) == []
    assert "Bounded guest context" not in repr(
        result.trace_payload["adapter_trace"]
    )
    assert "BOUNDED CONTEXT" not in repr(result.trace_payload)


def test_context_micro_injection_behavior_remains_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_context_composer_micro",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.messages[-1]["content"] == MICRO_BLOCK
    assert result.sources == ["alexis.guest_db"]


def main():
    test_valid_conditions_produce_one_rendered_block()
    test_wrong_agent_produces_no_rendered_block()
    test_wrong_capability_produces_no_rendered_block()
    test_rollback_flag_produces_no_rendered_block()
    test_trace_payload_remains_content_safe()
    test_declared_guest_db_adapter_fails_closed_when_enabled()
    test_declared_guest_db_guard_does_not_read_target_file()
    test_declared_guest_db_adapter_trace_remains_content_safe()
    test_context_micro_injection_behavior_remains_unchanged()
    print("PASS context composer")


if __name__ == "__main__":
    main()
