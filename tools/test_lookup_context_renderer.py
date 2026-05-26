import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_renderer import (  # noqa: E402
    render_lookup_context_blocks,
)


def policy(**overrides):
    data = {
        "allowed": True,
        "render_modes": ["structured_fact_block"],
        "field_order": [
            "display_name",
            "title",
            "known_contact_channels",
        ],
        "field_labels": {
            "display_name": "Display name",
            "title": "Title",
            "known_contact_channels": "Known contact channels",
        },
    }
    data.update(overrides)
    return data


def decision(**overrides):
    data = {
        "render_allowed": True,
        "render_mode": "structured_fact_block",
        "reasons": [],
        "packet_ids": ["lookup-001"],
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
            "known_contact_channels": ["phone"],
            "raw_database_path": "/private/source.csv",
        },
        "provenance": {
            "lookup_id": "lookup-001",
            "lookup_lineage_id": "lineage-001",
            "lookup_request_id": "request-001",
            "lookup_execution_id": "execution-001",
            "lookup_packet_id": "packet-001",
            "lookup_render_id": "render-001",
            "lookup_injection_id": "injection-001",
            "retrieval_executed": True,
            "records_returned": 1,
            "skipped_reasons": [],
            "raw_database_path": "/private/source.csv",
        },
    }
    data.update(overrides)
    return data


def test_positive_gate_allows_structured_fact_block_rendering():
    rendered = render_lookup_context_blocks(
        lookup_context_packets=[packet()],
        render_decision=decision(),
        render_policy=policy(),
    )

    assert rendered == {
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
                        "label": "Title",
                        "field": "title",
                        "value": "Policy Analyst",
                    },
                    {
                        "label": "Known contact channels",
                        "field": "known_contact_channels",
                        "value": ["phone"],
                    },
                ],
                "provenance": {
                    "lookup_id": "lookup-001",
                    "lookup_lineage_id": "lineage-001",
                    "lookup_request_id": "request-001",
                    "lookup_execution_id": "execution-001",
                    "lookup_packet_id": "packet-001",
                    "lookup_render_id": "render-001",
                    "lookup_injection_id": "injection-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                },
            }
        ],
    }


def test_negative_gate_decision_fails_closed():
    assert render_lookup_context_blocks(
        lookup_context_packets=[packet()],
        render_decision=decision(render_allowed=False),
        render_policy=policy(),
    ) is None


def test_missing_render_decision_fails_closed():
    assert render_lookup_context_blocks(
        lookup_context_packets=[packet()],
        render_decision=None,
        render_policy=policy(),
    ) is None


def test_unsupported_render_mode_fails_closed():
    assert render_lookup_context_blocks(
        lookup_context_packets=[packet()],
        render_decision=decision(render_mode="freeform_summary"),
        render_policy=policy(render_modes=["freeform_summary"]),
    ) is None


def test_renderer_uses_only_packet_fields_and_declarative_labels():
    rendered = render_lookup_context_blocks(
        lookup_context_packets=[packet()],
        render_decision=decision(),
        render_policy=policy(
            field_order=["title", "display_name"],
            field_labels={
                "title": "Role",
                "display_name": "Name",
            },
        ),
    )

    facts = rendered["blocks"][0]["facts"]
    assert facts == [
        {"label": "Role", "field": "title", "value": "Policy Analyst"},
        {"label": "Name", "field": "display_name", "value": "Jane Doe"},
    ]


def test_renderer_does_not_output_raw_rows_paths_or_unrestricted_metadata():
    rendered = render_lookup_context_blocks(
        lookup_context_packets=[packet()],
        render_decision=decision(),
        render_policy=policy(),
    )
    serialized = repr(rendered)

    assert "raw_database_path" not in serialized
    assert "/private/source.csv" not in serialized
    assert "skipped_reasons" not in serialized


def test_bounded_search_renders_neutral_structured_result_blocks():
    rendered = render_lookup_context_blocks(
        lookup_context_packets=[
            packet(
                lookup_type="bounded_entity_search",
                provenance={
                    "lookup_id": "lookup-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                    "result_index": 1,
                    "result_count": 2,
                },
            )
        ],
        render_decision=decision(),
        render_policy=policy(),
    )

    block = rendered["blocks"][0]
    serialized = repr(rendered).lower()
    assert block["title"] == "Bounded entity search result"
    assert block["provenance"]["result_index"] == 1
    assert block["provenance"]["result_count"] == 2
    assert "recommended" not in serialized
    assert "best candidate" not in serialized
    assert "ranking" not in serialized


def test_runtime_renderer_source_has_no_recommendation_language():
    source = (
        ROOT / "runtime/lookup/context_renderer.py"
    ).read_text(encoding="utf-8").lower()

    assert "recommended" not in source
    assert "best candidate" not in source
    assert "ranking" not in source


def main():
    test_positive_gate_allows_structured_fact_block_rendering()
    test_negative_gate_decision_fails_closed()
    test_missing_render_decision_fails_closed()
    test_unsupported_render_mode_fails_closed()
    test_renderer_uses_only_packet_fields_and_declarative_labels()
    test_renderer_does_not_output_raw_rows_paths_or_unrestricted_metadata()
    test_bounded_search_renders_neutral_structured_result_blocks()
    test_runtime_renderer_source_has_no_recommendation_language()
    print("PASS lookup context renderer")


if __name__ == "__main__":
    main()
