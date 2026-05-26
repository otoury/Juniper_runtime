import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_materializer import (  # noqa: E402
    materialize_lookup_context_packets,
)


def policy(**overrides):
    data = {
        "enabled": True,
        "context_type": "bounded_lookup_result",
        "allowed_fields": [
            "display_name",
            "title",
            "expertise",
            "public_booking_notes",
            "known_contact_channels",
        ],
        "max_fields": 5,
    }
    data.update(overrides)
    return data


def lookup_result(**overrides):
    data = {
        "lookup_id": "lookup-001",
        "lookup_type": "exact_entity_lookup",
        "entity_type": "person",
        "workflow_topic": "Iran talks",
        "source_scope": "bounded_source",
        "retrieval_executed": True,
        "records_returned": 1,
        "skipped_reasons": [],
        "payloads": [
            {
                "display_name": "Jane Doe",
                "title": "Policy Analyst",
                "expertise": "Energy policy",
                "public_booking_notes": "Available for live segments",
                "known_contact_channels": ["phone", "email"],
                "raw_database_path": "/private/source.csv",
                "private_notes": "do not expose",
            }
        ],
    }
    data.update(overrides)
    return data


def bounded_search_result(**overrides):
    data = {
        "lookup_id": "bounded-search-001",
        "lookup_type": "bounded_entity_search",
        "entity_type": "person",
        "source_scope": "bounded_source",
        "retrieval_executed": True,
        "records_returned": 2,
        "skipped_reasons": [],
        "payloads": [
            {
                "display_name": "Jane Doe",
                "title": "Health Policy Analyst",
                "expertise": "Healthcare reform",
                "private_notes": "do not expose",
            },
            {
                "display_name": "John Smith",
                "title": "Physician",
                "expertise": "Healthcare systems",
                "raw_database_path": "/private/source.csv",
            },
        ],
    }
    data.update(overrides)
    return data


def test_executed_lookup_result_materializes_bounded_packet():
    packets = materialize_lookup_context_packets(
        lookup_results=[lookup_result()],
        materialization_policy=policy(),
    )

    assert packets == [
        {
            "context_type": "bounded_lookup_result",
            "lookup_type": "exact_entity_lookup",
            "entity_type": "person",
            "source_scope": "bounded_source",
            "fields": {
                "display_name": "Jane Doe",
                "title": "Policy Analyst",
                "expertise": "Energy policy",
                "public_booking_notes": "Available for live segments",
                "known_contact_channels": ["phone", "email"],
            },
            "provenance": {
                "lookup_id": "lookup-001",
                "retrieval_executed": True,
                "records_returned": 1,
                "skipped_reasons": [],
            },
        }
    ]


def test_materialized_context_contains_only_allowlisted_fields():
    packet = materialize_lookup_context_packets(
        lookup_results=[lookup_result()],
        materialization_policy=policy(
            allowed_fields=["display_name"],
            max_fields=1,
        ),
    )[0]

    assert packet["fields"] == {"display_name": "Jane Doe"}
    rendered = repr(packet)
    assert "raw_database_path" not in rendered
    assert "/private/source.csv" not in rendered
    assert "private_notes" not in rendered
    assert "do not expose" not in rendered


def test_disallowed_raw_fields_are_dropped():
    packet = materialize_lookup_context_packets(
        lookup_results=[lookup_result()],
        materialization_policy=policy(
            allowed_fields=["display_name", "title"],
            max_fields=2,
        ),
    )[0]

    assert packet["fields"] == {
        "display_name": "Jane Doe",
        "title": "Policy Analyst",
    }
    assert "private_notes" not in repr(packet)
    assert "raw_database_path" not in repr(packet)


def test_bounded_search_results_materialize_as_bounded_packets():
    packets = materialize_lookup_context_packets(
        lookup_results=[bounded_search_result()],
        materialization_policy=policy(
            allowed_fields=["display_name", "title", "expertise"],
            max_fields=3,
        ),
    )

    assert len(packets) == 2
    assert packets[0]["lookup_type"] == "bounded_entity_search"
    assert packets[0]["fields"] == {
        "display_name": "Jane Doe",
        "title": "Health Policy Analyst",
        "expertise": "Healthcare reform",
    }
    assert packets[0]["provenance"]["result_index"] == 1
    assert packets[0]["provenance"]["result_count"] == 2
    assert packets[1]["fields"]["display_name"] == "John Smith"
    serialized = repr(packets)
    assert "private_notes" not in serialized
    assert "raw_database_path" not in serialized
    assert "/private/source.csv" not in serialized


def test_missing_materialization_policy_fails_closed():
    assert materialize_lookup_context_packets(
        lookup_results=[lookup_result()],
        materialization_policy=None,
    ) == []


def test_unsafe_allowed_field_fails_closed():
    result = lookup_result()
    result["payloads"][0]["known_contact_channels"] = [
        "email",
        {"raw": "bad"},
    ]

    assert materialize_lookup_context_packets(
        lookup_results=[result],
        materialization_policy=policy(),
    ) == []


def test_failed_lookup_execution_produces_no_packet():
    assert materialize_lookup_context_packets(
        lookup_results=[
            lookup_result(
                retrieval_executed=True,
                records_returned=0,
                skipped_reasons=["no_exact_match"],
                payloads=[],
            )
        ],
        materialization_policy=policy(),
    ) == []


def main():
    test_executed_lookup_result_materializes_bounded_packet()
    test_materialized_context_contains_only_allowlisted_fields()
    test_disallowed_raw_fields_are_dropped()
    test_bounded_search_results_materialize_as_bounded_packets()
    test_missing_materialization_policy_fails_closed()
    test_unsafe_allowed_field_fails_closed()
    test_failed_lookup_execution_produces_no_packet()
    print("PASS lookup context materializer")


if __name__ == "__main__":
    main()
