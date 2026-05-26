import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_composer as composer  # noqa: E402
import runtime.context_adapter_factory as adapter_factory  # noqa: E402
from runtime.context_adapter_output import validate_adapter_output  # noqa: E402
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.context_types import (  # noqa: E402
    ResolvedContextItem,
    ResolvedContextProvenance,
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


def valid_item(**overrides):
    data = {
        "id": "ctx_1",
        "source_contract_id": "alexis_guest_db",
        "content": "bounded context",
        "content_type": "synthetic_notice",
        "provenance": ResolvedContextProvenance(
            source_contract_id="alexis_guest_db",
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        ),
        "estimated_tokens": 2,
        "trust_level": "system_declared",
        "rendering_policy": "bounded_context_block",
        "metadata": {},
    }
    data.update(overrides)
    return ResolvedContextItem(**data)


def run_with_fake_adapter(adapter_cls):
    original_factory = (
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "synthetic_guest_context"
        ]
    )
    adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
        "synthetic_guest_context"
    ] = lambda contract, adapter_contract: adapter_cls(contract)

    try:
        with Env(
            JUNIPER_ENABLE_CONTEXT_INJECTION="1",
            JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        ):
            return compose_bounded_context(
                request_id="req_adapter_output",
                agent="alexis",
                shared_capability="draft_email",
                planner_mode="NEW_REQUEST",
            )
    finally:
        adapter_factory.APPROVED_CONTEXT_ADAPTER_FACTORIES[
            "synthetic_guest_context"
        ] = original_factory


def test_valid_context_item_list_passes():
    item = valid_item()

    assert validate_adapter_output([item]) == [item]


def test_non_list_adapter_return_fails_closed():
    assert validate_adapter_output({"id": "ctx_1"}) == []


def test_non_context_item_is_dropped():
    item = valid_item()

    assert validate_adapter_output([{"id": "ctx_1"}, item]) == [item]


def test_invalid_context_item_is_dropped():
    item = valid_item(content="")

    assert validate_adapter_output([item]) == []


def test_composer_handles_non_list_adapter_output_without_rendering():
    class BadAdapter:
        def __init__(self, contract):
            self.contract = contract

        def retrieve(self, **kwargs):
            return {"content": "must not render"}

    result = run_with_fake_adapter(BadAdapter)

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_adapter_no_item" in result.skipped_reasons
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["raw_items_returned"] == 0
    assert result.trace_payload["adapter_trace"]["valid_items_returned"] == 0


def test_composer_drops_invalid_adapter_entry_without_rendering():
    class MixedAdapter:
        def __init__(self, contract):
            self.contract = contract

        def retrieve(self, **kwargs):
            return [
                "not-context",
                valid_item(content=""),
            ]

    result = run_with_fake_adapter(MixedAdapter)

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_adapter_no_item" in result.skipped_reasons
    assert result.trace_payload["adapter_trace"]["raw_items_returned"] == 2
    assert result.trace_payload["adapter_trace"]["valid_items_returned"] == 0


def test_adapter_telemetry_remains_content_safe():
    class BadAdapter:
        def __init__(self, contract):
            self.contract = contract

        def retrieve(self, **kwargs):
            return [
                {
                    "content": "must not be logged",
                }
            ]

    result = run_with_fake_adapter(BadAdapter)

    assert forbidden_keys_in_payload(result.trace_payload["adapter_trace"]) == []
    assert "must not be logged" not in repr(result.trace_payload)


def test_composer_isolates_adapter_exception_without_rendering():
    class ExplodingAdapter:
        def __init__(self, contract):
            self.contract = contract

        def retrieve(self, **kwargs):
            raise RuntimeError("raw guest row should not be logged")

    result = run_with_fake_adapter(ExplodingAdapter)

    assert result.injection_performed is False
    assert result.rendered_blocks == []
    assert "context_adapter_exception" in result.skipped_reasons
    assert result.trace_payload["adapter_trace"]["adapter_invoked"] is True
    assert result.trace_payload["adapter_trace"]["items_returned"] == 0
    assert result.trace_payload["adapter_trace"]["raw_items_returned"] == 0
    assert result.trace_payload["adapter_trace"]["valid_items_returned"] == 0
    assert result.trace_payload["adapter_trace"]["exception_type"] == "RuntimeError"


def test_adapter_exception_trace_does_not_include_message():
    class ExplodingAdapter:
        def __init__(self, contract):
            self.contract = contract

        def retrieve(self, **kwargs):
            raise ValueError("sensitive retrieved text")

    result = run_with_fake_adapter(ExplodingAdapter)
    adapter_trace = result.trace_payload["adapter_trace"]

    assert "exception_message" not in adapter_trace
    assert "sensitive retrieved text" not in repr(result.trace_payload)
    assert forbidden_keys_in_payload(adapter_trace) == []


def test_normal_synthetic_injection_behavior_remains_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_output_normal",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]
    assert result.trace_payload["adapter_trace"]["items_returned"] == 1
    assert result.trace_payload["adapter_trace"]["raw_items_returned"] == 1
    assert result.trace_payload["adapter_trace"]["valid_items_returned"] == 1


def main():
    test_valid_context_item_list_passes()
    test_non_list_adapter_return_fails_closed()
    test_non_context_item_is_dropped()
    test_invalid_context_item_is_dropped()
    test_composer_handles_non_list_adapter_output_without_rendering()
    test_composer_drops_invalid_adapter_entry_without_rendering()
    test_adapter_telemetry_remains_content_safe()
    test_composer_isolates_adapter_exception_without_rendering()
    test_adapter_exception_trace_does_not_include_message()
    test_normal_synthetic_injection_behavior_remains_unchanged()
    print("PASS context adapter output")


if __name__ == "__main__":
    main()
