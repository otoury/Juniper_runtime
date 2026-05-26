import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_injection import (  # noqa: E402
    maybe_inject_lookup_context,
)


def messages():
    return [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Draft an email."},
    ]


def policy(**overrides):
    data = {
        "allowed": True,
        "require_render_decision": True,
        "require_rendered_context": True,
        "allowed_content_types": ["lookup_context_block"],
        "allowed_render_modes": ["structured_fact_block"],
        "max_blocks": 1,
        "max_facts_per_block": 5,
        "max_total_characters": 1200,
        "truncation_mode": "drop_tail",
    }
    data.update(overrides)
    return data


def render_decision(**overrides):
    data = {
        "render_allowed": True,
        "render_mode": "structured_fact_block",
        "reasons": [],
        "packet_ids": ["lookup-001"],
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
                    {
                        "label": "Display name",
                        "field": "display_name",
                        "value": "Jane Doe",
                    },
                    {
                        "label": "Known contact channels",
                        "field": "known_contact_channels",
                        "value": ["phone"],
                    },
                ],
                "provenance": {
                    "lookup_id": "lookup-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                },
            }
        ],
    }
    data.update(overrides)
    return data


def test_rendered_context_injected_when_policy_allows():
    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=rendered_context(),
        render_decision=render_decision(),
        injection_policy=policy(),
    )

    assert result.trace == {
        "injection_attempted": True,
        "injection_allowed": True,
        "injected_block_count": 1,
        "skipped_reasons": [],
        "attachment_guard": result.trace["attachment_guard"],
        "budget_applied": True,
        "truncated": False,
        "dropped_blocks": 0,
        "dropped_facts": 0,
        "final_character_count": result.trace["final_character_count"],
    }
    assert len(result.messages) == 3
    assert result.messages[1]["role"] == "system"
    assert result.fragment["content_type"] == "lookup_context_block"
    assert result.fragment["attachment_provenance"]["explicit_attachment"] is True
    assert "LOOKUP_CONTEXT_BLOCK" in result.messages[1]["content"]
    assert "Jane Doe" in result.messages[1]["content"]


def test_missing_render_decision_fails_closed():
    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=rendered_context(),
        render_decision=None,
        injection_policy=policy(),
    )

    assert result.messages == messages()
    assert result.fragment is None
    assert result.trace["injection_allowed"] is False
    assert result.trace["skipped_reasons"] == ["render_decision_not_allowed"]


def test_negative_render_decision_fails_closed():
    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=rendered_context(),
        render_decision=render_decision(render_allowed=False),
        injection_policy=policy(),
    )

    assert result.messages == messages()
    assert result.trace["skipped_reasons"] == ["render_decision_not_allowed"]


def test_missing_rendered_context_fails_closed():
    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=None,
        render_decision=render_decision(),
        injection_policy=policy(),
    )

    assert result.messages == messages()
    assert result.trace["skipped_reasons"] == [
        "missing_rendered_lookup_context"
    ]


def test_missing_or_malformed_injection_policy_fails_closed():
    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=rendered_context(),
        render_decision=render_decision(),
        injection_policy=policy(max_blocks=0),
    )

    assert result.messages == messages()
    assert result.trace["skipped_reasons"] == [
        "missing_or_malformed_injection_policy"
    ]


def test_raw_lookup_data_fails_closed():
    context = rendered_context()
    context["blocks"][0]["raw_lookup_results"] = [{"private": "do not inject"}]
    context["blocks"][0]["provenance"]["raw_database_path"] = "/private/source.csv"

    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=context,
        render_decision=render_decision(),
        injection_policy=policy(),
    )

    assert result.fragment is None
    assert result.messages == messages()
    assert result.trace["injection_allowed"] is False
    assert result.trace["skipped_reasons"] == [
        "hidden_attachment_leakage_detected"
    ]
    assert "blocks[0].raw_lookup_results" in result.trace["blocked_fields"]


def test_injection_output_bounded_by_max_blocks():
    context = rendered_context()
    context["blocks"].append(context["blocks"][0])

    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=context,
        render_decision=render_decision(),
        injection_policy=policy(max_blocks=1),
    )

    assert result.fragment is not None
    assert result.trace["injection_allowed"] is True
    assert result.trace["injected_block_count"] == 1
    assert result.trace["truncated"] is True
    assert result.trace["dropped_blocks"] == 1


def test_injection_output_bounded_by_fact_and_character_limits():
    context = rendered_context()
    context["blocks"][0]["facts"].append(
        {
            "label": "Long note",
            "field": "long_note",
            "value": "x" * 1000,
        }
    )

    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=context,
        render_decision=render_decision(),
        injection_policy=policy(
            max_facts_per_block=2,
            max_total_characters=600,
        ),
    )

    assert result.fragment is not None
    assert len(result.fragment["blocks"][0]["facts"]) == 2
    assert result.trace["truncated"] is True
    assert result.trace["dropped_facts"] == 1
    assert result.trace["final_character_count"] <= 600


def test_non_lookup_messages_inject_nothing_without_policy():
    result = maybe_inject_lookup_context(
        messages(),
        rendered_lookup_context=None,
        render_decision=None,
        injection_policy=None,
    )

    assert result.messages == messages()
    assert result.trace == {
        "injection_attempted": True,
        "injection_allowed": False,
        "injected_block_count": 0,
        "skipped_reasons": ["missing_or_malformed_injection_policy"],
    }


def main():
    test_rendered_context_injected_when_policy_allows()
    test_missing_render_decision_fails_closed()
    test_negative_render_decision_fails_closed()
    test_missing_rendered_context_fails_closed()
    test_missing_or_malformed_injection_policy_fails_closed()
    test_raw_lookup_data_fails_closed()
    test_injection_output_bounded_by_max_blocks()
    test_injection_output_bounded_by_fact_and_character_limits()
    test_non_lookup_messages_inject_nothing_without_policy()
    print("PASS lookup context injection")


if __name__ == "__main__":
    main()
