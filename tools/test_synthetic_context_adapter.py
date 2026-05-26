import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.adapters.synthetic_guest_context_adapter import (  # noqa: E402
    SyntheticGuestContextAdapter,
)
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.context_types import (  # noqa: E402
    validate_context_item_source_contract,
    validate_resolved_context_item,
)
from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    list_context_injection_contracts,
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


def contract():
    return list_context_injection_contracts(ROOT)[0]


def adapter_item():
    adapter = SyntheticGuestContextAdapter(contract())
    items = adapter.retrieve(
        request_id="req_adapter",
        agent="alexis",
        shared_capability="draft_email",
    )
    assert len(items) == 1
    return items[0]


def test_adapter_returns_valid_resolved_context_item():
    item = adapter_item()

    assert item.id == "req_adapter:alexis_guest_context_notice"
    assert item.source_contract_id == "alexis_guest_db"
    assert item.content == MICRO_BLOCK
    assert item.content_type == "synthetic_notice"


def test_adapter_output_passes_existing_validators():
    item = adapter_item()

    assert validate_resolved_context_item(item) == []
    assert validate_context_item_source_contract(
        item,
        require_declared_source=True,
        root=ROOT,
    ) == []


def test_no_retrieval_execution_occurs():
    item = adapter_item()

    assert item.provenance.retrieval_executed is False
    assert item.provenance.attribution == "synthetic_system_notice"


def test_compose_bounded_context_still_renders_same_block():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_compose",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def test_rollback_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION="1",
    ):
        result = compose_bounded_context(
            request_id="req_adapter_rollback",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_injection_rollback_enabled" in result.skipped_reasons


def test_telemetry_remains_content_safe():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_telemetry",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert forbidden_keys_in_payload(result.trace_payload) == []
    assert "BOUNDED CONTEXT" not in repr(result.trace_payload)


def test_synthetic_injection_behavior_remains_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_adapter_micro",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.messages[-1]["content"] == MICRO_BLOCK
    assert result.sources == ["alexis.guest_db"]


def main():
    test_adapter_returns_valid_resolved_context_item()
    test_adapter_output_passes_existing_validators()
    test_no_retrieval_execution_occurs()
    test_compose_bounded_context_still_renders_same_block()
    test_rollback_behavior_unchanged()
    test_telemetry_remains_content_safe()
    test_synthetic_injection_behavior_remains_unchanged()
    print("PASS synthetic context adapter")


if __name__ == "__main__":
    main()
