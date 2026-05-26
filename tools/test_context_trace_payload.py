import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.context_trace import build_context_trace_payload  # noqa: E402


REQUIRED_FIELDS = {
    "request_id",
    "agent",
    "shared_capability",
    "injection_id",
    "source_contract_id",
    "injection_performed",
    "skipped_reasons",
    "collection_summary",
    "provenance_validated",
    "rollback_enabled",
}


FORBIDDEN_CONTEXT_TRACE_KEYS = {
    "content",
    "rendered_content",
    "rendered_text",
    "prompt_text",
    "context_text",
    "retrieved_text",
    "memory_text",
    "guest_db_rows",
    "raw_rows",
    "raw_content",
}


def forbidden_keys_in_payload(value):
    found = []

    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_CONTEXT_TRACE_KEYS:
                found.append(key)

            found.extend(forbidden_keys_in_payload(nested))

    if isinstance(value, list):
        for nested in value:
            found.extend(forbidden_keys_in_payload(nested))

    return found


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


def test_payload_includes_required_fields():
    payload = build_context_trace_payload(
        request_id="req_trace",
        agent="alexis",
        shared_capability="draft_email",
        injection_id="alexis_guest_context_notice",
        source_contract_id="alexis_guest_db",
        injection_performed=True,
        skipped_reasons=[],
        collection_summary={"accepted_count": 1},
        provenance_validated=True,
        rollback_enabled=False,
    )

    assert REQUIRED_FIELDS <= set(payload)


def test_skipped_reasons_are_preserved():
    payload = build_context_trace_payload(
        request_id="req_trace",
        agent="alexis",
        shared_capability="draft_email",
        injection_id=None,
        source_contract_id=None,
        injection_performed=False,
        skipped_reasons=["context_injection_disabled"],
        collection_summary=None,
        provenance_validated=False,
        rollback_enabled=False,
    )

    assert payload["skipped_reasons"] == ["context_injection_disabled"]


def test_collection_summary_included_without_content():
    payload = build_context_trace_payload(
        request_id="req_trace",
        agent="alexis",
        shared_capability="draft_email",
        injection_id="injection",
        source_contract_id="source",
        injection_performed=True,
        skipped_reasons=[],
        collection_summary={
            "accepted_item_ids": ["ctx_1"],
            "accepted_count": 1,
        },
        provenance_validated=True,
        rollback_enabled=False,
    )

    assert payload["collection_summary"]["accepted_item_ids"] == ["ctx_1"]
    assert "content" not in payload
    assert "content" not in payload["collection_summary"]


def test_none_values_allowed_for_optional_ids():
    payload = build_context_trace_payload(
        request_id=None,
        agent="alexis",
        shared_capability=None,
        injection_id=None,
        source_contract_id=None,
        injection_performed=False,
        skipped_reasons=[],
        collection_summary=None,
        provenance_validated=False,
        rollback_enabled=False,
    )

    assert payload["request_id"] is None
    assert payload["shared_capability"] is None
    assert payload["injection_id"] is None
    assert payload["source_contract_id"] is None


def test_content_and_rendered_text_are_not_included():
    payload = build_context_trace_payload(
        request_id="req_trace",
        agent="alexis",
        shared_capability="draft_email",
        injection_id="injection",
        source_contract_id="source",
        injection_performed=True,
        skipped_reasons=[],
        collection_summary={"dropped_item_ids": []},
        provenance_validated=True,
        rollback_enabled=False,
    )

    assert "content" not in payload
    assert "rendered_text" not in payload
    assert "raw_retrieved_text" not in payload
    assert "memory_text" not in payload
    assert "guest_db_rows" not in payload


def test_normal_payload_passes_recursive_forbidden_key_scan():
    payload = build_context_trace_payload(
        request_id="req_trace",
        agent="alexis",
        shared_capability="draft_email",
        injection_id="injection",
        source_contract_id="source",
        injection_performed=True,
        skipped_reasons=[],
        collection_summary={
            "accepted_item_ids": ["ctx_1"],
            "nested": {
                "safe_count": 1,
            },
        },
        provenance_validated=True,
        rollback_enabled=False,
    )

    assert forbidden_keys_in_payload(payload) == []


def test_synthetic_nested_payload_with_forbidden_key_fails_scan():
    payload = {
        "request_id": "req_trace",
        "collection_summary": {
            "accepted_item_ids": ["ctx_1"],
            "nested": {
                "rendered_text": "should not be logged",
            },
        },
    }

    assert forbidden_keys_in_payload(payload) == ["rendered_text"]


def test_synthetic_injection_behavior_remains_unchanged():
    previous_enable = os.environ.get("JUNIPER_ENABLE_CONTEXT_INJECTION")
    previous_disable = os.environ.get("JUNIPER_DISABLE_CONTEXT_INJECTION")
    events = []

    try:
        os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = "1"
        os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_context_trace_payload",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
            report_event=reporter(events),
            source_bot="alexis",
        )
    finally:
        if previous_enable is None:
            os.environ.pop("JUNIPER_ENABLE_CONTEXT_INJECTION", None)
        else:
            os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = previous_enable

        if previous_disable is None:
            os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        else:
            os.environ["JUNIPER_DISABLE_CONTEXT_INJECTION"] = previous_disable

    assert result.injection_performed is True
    assert result.messages[-1]["content"] == MICRO_BLOCK

    payload = events[0]["payload"]
    assert REQUIRED_FIELDS <= set(payload)
    assert payload["request_id"] == "req_context_trace_payload"
    assert payload["collection_summary"]["accepted_count"] == 1
    assert forbidden_keys_in_payload(payload) == []


def main():
    test_payload_includes_required_fields()
    test_skipped_reasons_are_preserved()
    test_collection_summary_included_without_content()
    test_none_values_allowed_for_optional_ids()
    test_content_and_rendered_text_are_not_included()
    test_normal_payload_passes_recursive_forbidden_key_scan()
    test_synthetic_nested_payload_with_forbidden_key_fails_scan()
    test_synthetic_injection_behavior_remains_unchanged()
    print("PASS context trace payload")


if __name__ == "__main__":
    main()
