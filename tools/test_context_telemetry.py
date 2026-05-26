import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_collection import (  # noqa: E402
    validate_context_item_collection,
)
from runtime.context_micro_injection import (  # noqa: E402
    MICRO_BLOCK,
    maybe_apply_micro_context_injection,
)
from runtime.context_telemetry import (  # noqa: E402
    summarize_context_collection,
)
from runtime.context_types import (  # noqa: E402
    ResolvedContextItem,
    ResolvedContextProvenance,
)


def item(item_id, *, tokens=5, content=None, source="alexis_guest_db"):
    item_content = (
        f"context item {item_id}"
        if content is None
        else content
    )

    return ResolvedContextItem(
        id=item_id,
        source_contract_id=source,
        content=item_content,
        content_type="synthetic_notice",
        provenance=ResolvedContextProvenance(
            source_contract_id=source,
            retrieval_executed=False,
            attribution="synthetic_system_notice",
        ),
        estimated_tokens=tokens,
        trust_level="system_declared",
        rendering_policy="bounded_context_block",
        metadata={},
    )


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


def test_summary_counts_original_accepted_dropped():
    original = [item("a"), item("b", content="")]
    accepted = validate_context_item_collection(
        original,
        max_items=2,
        max_total_tokens=20,
    )
    summary = summarize_context_collection(
        original,
        accepted,
        max_items=2,
        max_total_tokens=20,
    )

    assert summary["original_count"] == 2
    assert summary["accepted_count"] == 1
    assert summary["dropped_count"] == 1


def test_summary_item_ids_are_correct():
    original = [item("a"), item("b", content=""), item("c")]
    accepted = validate_context_item_collection(
        original,
        max_items=2,
        max_total_tokens=20,
    )
    summary = summarize_context_collection(
        original,
        accepted,
        max_items=2,
        max_total_tokens=20,
    )

    assert summary["accepted_item_ids"] == ["a", "c"]
    assert summary["dropped_item_ids"] == ["b"]


def test_summary_source_ids_are_included():
    original = [
        item("a", source="alexis_guest_db"),
        item("b", source="producer_notes"),
    ]
    accepted = validate_context_item_collection(
        original,
        max_items=2,
        max_total_tokens=20,
    )
    summary = summarize_context_collection(
        original,
        accepted,
        max_items=2,
        max_total_tokens=20,
    )

    assert summary["accepted_source_contract_ids"] == [
        "alexis_guest_db",
        "producer_notes",
    ]


def test_summary_token_total_uses_accepted_items_only():
    original = [
        item("a", tokens=4),
        item("b", tokens=9),
        item("c", tokens=5),
    ]
    accepted = validate_context_item_collection(
        original,
        max_items=3,
        max_total_tokens=10,
    )
    summary = summarize_context_collection(
        original,
        accepted,
        max_items=3,
        max_total_tokens=10,
    )

    assert summary["accepted_item_ids"] == ["a", "c"]
    assert summary["total_estimated_tokens"] == 9


def test_summary_never_includes_content_field():
    original = [
        item("a", content="secret context content"),
    ]
    accepted = validate_context_item_collection(
        original,
        max_items=1,
        max_total_tokens=20,
    )
    summary = summarize_context_collection(
        original,
        accepted,
        max_items=1,
        max_total_tokens=20,
    )

    assert "content" not in summary
    assert "secret context content" not in repr(summary)


def test_synthetic_injection_behavior_and_telemetry_summary():
    previous_enable = os.environ.get("JUNIPER_ENABLE_CONTEXT_INJECTION")
    previous_disable = os.environ.get("JUNIPER_DISABLE_CONTEXT_INJECTION")
    events = []

    try:
        os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = "1"
        os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_context_telemetry",
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

    summary = events[0]["payload"]["context_collection"]
    normalized_summary = events[0]["payload"]["collection_summary"]

    assert normalized_summary == summary
    assert summary["original_count"] == 1
    assert summary["accepted_count"] == 1
    assert summary["dropped_count"] == 0
    assert summary["accepted_source_contract_ids"] == ["alexis_guest_db"]
    assert "content" not in summary


def main():
    test_summary_counts_original_accepted_dropped()
    test_summary_item_ids_are_correct()
    test_summary_source_ids_are_included()
    test_summary_token_total_uses_accepted_items_only()
    test_summary_never_includes_content_field()
    test_synthetic_injection_behavior_and_telemetry_summary()
    print("PASS context telemetry")


if __name__ == "__main__":
    main()
