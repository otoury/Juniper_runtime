import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.context_composer as composer  # noqa: E402
from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.registries.context_injection_binding_registry import (  # noqa: E402
    ContextInjectionContract,
    ContextInjectionRegistryError,
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


def reporter(events):
    def report_event(source_bot, event_type, payload, request_id=None):
        events.append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    return report_event


def base_messages():
    return [{"role": "user", "content": "draft outreach"}]


def registry_contract(*, enabled=True):
    return ContextInjectionContract(
        id="alexis_guest_context_notice",
        enabled=enabled,
        agent_scope=["alexis"],
        shared_capability_scope=["draft_email"],
        source_contract_id="alexis_guest_db",
        operation_scope=["NEW_REQUEST"],
        injection_mode="synthetic",
        content="[Bounded guest context: guest_db is available for booking context.]",
        source_name="alexis.guest_db",
        source_type="agent_resource",
        max_items=1,
        max_tokens=80,
        requires_provenance_validation=True,
        rollback_env_flag="JUNIPER_DISABLE_CONTEXT_INJECTION",
        telemetry_label="guest_context_notice",
        raw_data={},
    )


def apply(
    *,
    shared_capability="draft_email",
    operation="NEW_REQUEST",
    agent_name="alexis",
    events=None,
):
    return maybe_apply_micro_context_injection(
        base_messages(),
        request_id="req_micro_context",
        agent_name=agent_name,
        shared_capability=shared_capability,
        operation=operation,
        report_event=reporter(events if events is not None else []),
        source_bot="alexis",
    )


def test_default_disabled_no_message_mutation():
    events = []

    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION=None,
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_CONTEXT_INJECTION_CAPABILITIES=None,
    ):
        messages = base_messages()
        result = maybe_apply_micro_context_injection(
            messages,
            request_id="req_disabled",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
            report_event=reporter(events),
            source_bot="alexis",
        )

    assert result.messages == messages
    assert result.messages is messages
    assert result.injection_performed is False
    assert events[0]["payload"]["injection_performed"] is False
    assert "context_injection_disabled" in events[0]["payload"]["skipped_reasons"]


def test_hard_rollback_disables_injection():
    events = []

    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION="1",
    ):
        result = apply(events=events)

    assert result.injection_performed is False
    assert result.messages == base_messages()
    assert events[0]["payload"]["rollback_enabled"] is True
    assert "context_injection_rollback_enabled" in events[0]["payload"]["skipped_reasons"]


def test_enabled_draft_email_injects_exactly_one_bounded_block():
    events = []

    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_CONTEXT_INJECTION_CAPABILITIES=None,
    ):
        result = apply(events=events)

    assert result.injection_performed is True
    assert len(result.messages) == 2
    assert result.messages[-1]["role"] == "system"
    assert result.messages[-1]["content"] == MICRO_BLOCK
    assert result.item_count == 1
    assert result.estimated_tokens <= 80
    assert result.sources == ["alexis.guest_db"]


def test_enabled_lower_third_injects_nothing():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = apply(shared_capability="create_lower_third")

    assert result.injection_performed is False
    assert result.messages == base_messages()


def test_wrong_agent_injects_nothing():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = apply(agent_name="yossi")

    assert result.injection_performed is False
    assert result.messages == base_messages()


def test_enabled_send_email_injects_nothing():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = apply(shared_capability="send_email", operation="ACTION")

    assert result.injection_performed is False
    assert result.messages == base_messages()


def test_transform_request_injects_nothing():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = apply(
            shared_capability="draft_email",
            operation="TRANSFORM",
        )

    assert result.injection_performed is False
    assert result.messages == base_messages()


def test_missing_shared_capability_injects_nothing():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = apply(shared_capability=None)

    assert result.injection_performed is False
    assert result.messages == base_messages()


def test_provenance_failure_injects_nothing():
    original_validate = composer.validate_context_provenance

    def fail_provenance(*args, **kwargs):
        return SimpleNamespace(
            provenance_errors=[
                SimpleNamespace(error_code="forced_failure")
            ]
        )

    composer.validate_context_provenance = fail_provenance

    try:
        with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
            result = apply()
    finally:
        composer.validate_context_provenance = original_validate

    assert result.injection_performed is False
    assert result.messages == base_messages()
    assert "provenance:forced_failure" in result.skipped_reasons


def test_disabled_registry_entry_injects_nothing():
    original_find = composer.find_context_injection_contracts

    def disabled_contract(*args, **kwargs):
        return [registry_contract(enabled=False)]

    composer.find_context_injection_contracts = disabled_contract

    try:
        with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
            result = apply()
    finally:
        composer.find_context_injection_contracts = original_find

    assert result.injection_performed is False
    assert result.messages == base_messages()
    assert "injection_contract_disabled" in result.skipped_reasons


def test_registry_load_failure_fails_closed():
    original_find = composer.find_context_injection_contracts

    def fail_registry(*args, **kwargs):
        raise ContextInjectionRegistryError("forced registry failure")

    composer.find_context_injection_contracts = fail_registry

    try:
        with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
            result = apply()
    finally:
        composer.find_context_injection_contracts = original_find

    assert result.injection_performed is False
    assert result.messages == base_messages()
    assert "registry_load_failed" in result.skipped_reasons


def test_telemetry_payload_shape():
    events = []

    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        apply(events=events)

    payload = events[0]["payload"]
    assert events[0]["event_type"] == "bounded_context_injection"
    assert payload["enabled"] is True
    assert payload["injection_id"] == "alexis_guest_context_notice"
    assert payload["telemetry_label"] == "guest_context_notice"
    assert payload["source_contract_id"] == "alexis_guest_db"
    assert payload["agent"] == "alexis"
    assert payload["shared_capability"] == "draft_email"
    assert payload["item_count"] == 1
    assert payload["estimated_tokens"] <= 80
    assert payload["source_attribution"] == ["alexis.guest_db"]
    assert payload["injection_performed"] is True
    assert payload["skipped_reasons"] == []
    assert payload["provenance_validated"] is True
    assert payload["rollback_enabled"] is False


def test_injected_block_is_attributable_and_bounded():
    with Env(JUNIPER_ENABLE_CONTEXT_INJECTION="1"):
        result = apply()

    assert "guest_db" in result.messages[-1]["content"]
    assert "synthetic, attributed, no retrieval" in result.messages[-1]["content"]
    assert result.estimated_tokens <= 80


def test_allowlist_must_include_draft_email():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_ENABLE_CONTEXT_INJECTION_CAPABILITIES="producer_note",
    ):
        result = apply()

    assert result.injection_performed is False
    assert result.messages == base_messages()


def main():
    test_default_disabled_no_message_mutation()
    test_hard_rollback_disables_injection()
    test_enabled_draft_email_injects_exactly_one_bounded_block()
    test_enabled_lower_third_injects_nothing()
    test_wrong_agent_injects_nothing()
    test_enabled_send_email_injects_nothing()
    test_transform_request_injects_nothing()
    test_missing_shared_capability_injects_nothing()
    test_provenance_failure_injects_nothing()
    test_disabled_registry_entry_injects_nothing()
    test_registry_load_failure_fails_closed()
    test_telemetry_payload_shape()
    test_injected_block_is_attributable_and_bounded()
    test_allowlist_must_include_draft_email()
    print("PASS micro context injection")


if __name__ == "__main__":
    main()
