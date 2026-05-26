import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_budgeting import (  # noqa: E402
    apply_lookup_context_budget,
)


def policy(**overrides):
    data = {
        "max_blocks": 1,
        "max_facts_per_block": 3,
        "max_total_characters": 1000,
        "truncation_mode": "drop_tail",
    }
    data.update(overrides)
    return data


def rendered_context(**overrides):
    data = {
        "render_mode": "structured_fact_block",
        "content_type": "lookup_context_block",
        "blocks": [
            {
                "title": "Retrieved entity context",
                "facts": [
                    {"label": "A", "field": "a", "value": "one"},
                    {"label": "B", "field": "b", "value": "two"},
                    {"label": "C", "field": "c", "value": "three"},
                    {"label": "D", "field": "d", "value": "four"},
                ],
                "provenance": {
                    "lookup_id": "lookup-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                },
            },
            {
                "title": "Retrieved entity context",
                "facts": [
                    {"label": "E", "field": "e", "value": "five"},
                ],
                "provenance": {
                    "lookup_id": "lookup-002",
                    "retrieval_executed": True,
                    "records_returned": 1,
                },
            },
        ],
    }
    data.update(overrides)
    return data


def test_max_blocks_and_fact_limits_are_deterministic():
    result = apply_lookup_context_budget(
        rendered_lookup_context=rendered_context(),
        budget_policy=policy(max_blocks=1, max_facts_per_block=2),
    )

    assert result.rendered_lookup_context is not None
    blocks = result.rendered_lookup_context["blocks"]
    assert len(blocks) == 1
    assert [fact["field"] for fact in blocks[0]["facts"]] == ["a", "b"]
    assert result.trace["truncated"] is True
    assert result.trace["dropped_blocks"] == 1
    assert result.trace["dropped_facts"] == 2


def test_max_total_characters_drops_tail_facts():
    context = rendered_context(blocks=[rendered_context()["blocks"][0]])
    result = apply_lookup_context_budget(
        rendered_lookup_context=context,
        budget_policy=policy(max_total_characters=300),
    )

    assert result.rendered_lookup_context is not None
    fields = [
        fact["field"]
        for fact in result.rendered_lookup_context["blocks"][0]["facts"]
    ]
    assert fields == ["a"]
    assert result.trace["truncated"] is True
    assert result.trace["dropped_facts"] == 3
    assert result.trace["final_character_count"] <= 300


def test_malformed_budget_policy_fails_closed():
    result = apply_lookup_context_budget(
        rendered_lookup_context=rendered_context(),
        budget_policy=policy(truncation_mode="semantic_summary"),
    )

    assert result.rendered_lookup_context is None
    assert result.trace["budget_applied"] is False
    assert result.trace["skipped_reasons"] == [
        "missing_or_malformed_budget_policy"
    ]


def test_budgeting_does_not_mutate_input():
    context = rendered_context()
    original = copy.deepcopy(context)

    apply_lookup_context_budget(
        rendered_lookup_context=context,
        budget_policy=policy(max_blocks=1, max_facts_per_block=1),
    )

    assert context == original


def test_trace_is_content_safe():
    context = rendered_context()
    context["blocks"][0]["facts"][0]["value"] = "Sensitive Entity Name"
    result = apply_lookup_context_budget(
        rendered_lookup_context=context,
        budget_policy=policy(max_blocks=1, max_facts_per_block=1),
    )

    serialized_trace = json.dumps(result.trace, sort_keys=True)
    assert "Sensitive Entity Name" not in serialized_trace


def main():
    test_max_blocks_and_fact_limits_are_deterministic()
    test_max_total_characters_drops_tail_facts()
    test_malformed_budget_policy_fails_closed()
    test_budgeting_does_not_mutate_input()
    test_trace_is_content_safe()
    print("PASS lookup context budgeting")


if __name__ == "__main__":
    main()
