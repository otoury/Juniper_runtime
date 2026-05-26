import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_render_gate import (  # noqa: E402
    evaluate_lookup_context_render_gate,
)


def policy(**overrides):
    data = {
        "allowed": True,
        "render_modes": ["structured_fact_block"],
        "max_packets": 1,
        "require_successful_retrieval": True,
        "allowed_context_types": ["bounded_lookup_result"],
        "allowed_lookup_types": ["exact_entity_lookup"],
        "allowed_source_scopes": ["bounded_source"],
        "allowed_entity_types": ["person"],
    }
    data.update(overrides)
    return data


def packet(**overrides):
    data = {
        "context_type": "bounded_lookup_result",
        "lookup_type": "exact_entity_lookup",
        "entity_type": "person",
        "source_scope": "bounded_source",
        "fields": {
            "display_name": "Jane Doe",
            "title": "Policy Analyst",
        },
        "provenance": {
            "lookup_id": "lookup-001",
            "lookup_lineage_id": "lineage-001",
            "lookup_render_id": "render-001",
            "retrieval_executed": True,
            "records_returned": 1,
            "skipped_reasons": [],
        },
    }
    data.update(overrides)
    return data


def test_valid_packet_is_render_allowed_by_policy():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[packet()],
        render_policy=policy(),
    )

    assert decision == {
        "render_allowed": True,
        "render_mode": "structured_fact_block",
        "reasons": [],
        "packet_ids": ["lookup-001"],
        "lookup_lineage_ids": ["lineage-001"],
        "lookup_render_ids": ["render-001"],
    }


def test_missing_render_policy_fails_closed():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[packet()],
        render_policy=None,
    )

    assert decision["render_allowed"] is False
    assert decision["reasons"] == ["missing_or_malformed_render_policy"]


def test_malformed_render_policy_fails_closed():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[packet()],
        render_policy=policy(max_packets=0),
    )

    assert decision["render_allowed"] is False
    assert decision["reasons"] == ["missing_or_malformed_render_policy"]


def test_no_packets_fails_closed():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[],
        render_policy=policy(),
    )

    assert decision["render_allowed"] is False
    assert decision["reasons"] == ["no_lookup_context_packets"]


def test_too_many_packets_fails_closed():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[
            packet(),
            packet(provenance={"lookup_id": "lookup-002"}),
        ],
        render_policy=policy(max_packets=1),
    )

    assert decision["render_allowed"] is False
    assert decision["reasons"] == ["lookup_context_packet_limit_exceeded"]


def test_disallowed_context_type_fails_closed():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[packet(context_type="raw_lookup_result")],
        render_policy=policy(),
    )

    assert decision["render_allowed"] is False
    assert decision["reasons"] == ["disallowed_context_type"]


def test_bounded_search_packets_can_be_render_allowed_by_policy():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[
            packet(
                lookup_type="bounded_entity_search",
                provenance={
                    "lookup_id": "bounded-search-001",
                    "lookup_lineage_id": "lineage-001",
                    "lookup_render_id": "render-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                    "result_index": 1,
                    "result_count": 2,
                    "skipped_reasons": [],
                },
            ),
            packet(
                lookup_type="bounded_entity_search",
                provenance={
                    "lookup_id": "bounded-search-001",
                    "lookup_lineage_id": "lineage-001",
                    "lookup_render_id": "render-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                    "result_index": 2,
                    "result_count": 2,
                    "skipped_reasons": [],
                },
            ),
        ],
        render_policy=policy(
            max_packets=2,
            allowed_lookup_types=["bounded_entity_search"],
        ),
    )

    assert decision["render_allowed"] is True
    assert decision["packet_ids"] == [
        "bounded-search-001",
        "bounded-search-001",
    ]


def test_gate_output_is_telemetry_safe():
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=[packet()],
        render_policy=policy(),
    )
    rendered = repr(decision)

    assert "Jane Doe" not in rendered
    assert "Policy Analyst" not in rendered
    assert "fields" not in rendered
    assert "lookup-001" in rendered


def main():
    test_valid_packet_is_render_allowed_by_policy()
    test_missing_render_policy_fails_closed()
    test_malformed_render_policy_fails_closed()
    test_no_packets_fails_closed()
    test_too_many_packets_fails_closed()
    test_disallowed_context_type_fails_closed()
    test_bounded_search_packets_can_be_render_allowed_by_policy()
    test_gate_output_is_telemetry_safe()
    print("PASS lookup context render gate")


if __name__ == "__main__":
    main()
