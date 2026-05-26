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


def test_valid_collection_passes():
    items = [item("a"), item("b")]

    accepted = validate_context_item_collection(
        items,
        max_items=2,
        max_total_tokens=20,
    )

    assert accepted == items


def test_invalid_item_is_dropped():
    valid = item("valid")
    invalid = item("invalid", content="")

    accepted = validate_context_item_collection(
        [invalid, valid],
        max_items=2,
        max_total_tokens=20,
    )

    assert accepted == [valid]


def test_max_items_limit_is_enforced():
    items = [item("a"), item("b"), item("c")]

    accepted = validate_context_item_collection(
        items,
        max_items=2,
        max_total_tokens=50,
    )

    assert [accepted_item.id for accepted_item in accepted] == ["a", "b"]


def test_max_total_tokens_limit_is_enforced():
    items = [
        item("a", tokens=4),
        item("b", tokens=7),
        item("c", tokens=3),
    ]

    accepted = validate_context_item_collection(
        items,
        max_items=3,
        max_total_tokens=10,
    )

    assert [accepted_item.id for accepted_item in accepted] == ["a", "c"]


def test_original_order_is_preserved():
    items = [
        item("first", tokens=3),
        item("second", tokens=3),
        item("third", tokens=3),
    ]

    accepted = validate_context_item_collection(
        items,
        max_items=3,
        max_total_tokens=9,
    )

    assert [accepted_item.id for accepted_item in accepted] == [
        "first",
        "second",
        "third",
    ]


def test_zero_or_negative_limits_fail_closed():
    items = [item("a")]

    assert validate_context_item_collection(
        items,
        max_items=0,
        max_total_tokens=10,
    ) == []
    assert validate_context_item_collection(
        items,
        max_items=1,
        max_total_tokens=0,
    ) == []
    assert validate_context_item_collection(
        items,
        max_items=-1,
        max_total_tokens=10,
    ) == []
    assert validate_context_item_collection(
        items,
        max_items=1,
        max_total_tokens=-1,
    ) == []


def test_synthetic_injection_behavior_remains_unchanged():
    previous_enable = os.environ.get("JUNIPER_ENABLE_CONTEXT_INJECTION")
    previous_disable = os.environ.get("JUNIPER_DISABLE_CONTEXT_INJECTION")

    try:
        os.environ["JUNIPER_ENABLE_CONTEXT_INJECTION"] = "1"
        os.environ.pop("JUNIPER_DISABLE_CONTEXT_INJECTION", None)
        result = maybe_apply_micro_context_injection(
            [{"role": "user", "content": "draft outreach"}],
            request_id="req_context_collection",
            agent_name="alexis",
            shared_capability="draft_email",
            operation="NEW_REQUEST",
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
    assert result.sources == ["alexis.guest_db"]


def main():
    test_valid_collection_passes()
    test_invalid_item_is_dropped()
    test_max_items_limit_is_enforced()
    test_max_total_tokens_limit_is_enforced()
    test_original_order_is_preserved()
    test_zero_or_negative_limits_fail_closed()
    test_synthetic_injection_behavior_remains_unchanged()
    print("PASS context collection")


if __name__ == "__main__":
    main()
