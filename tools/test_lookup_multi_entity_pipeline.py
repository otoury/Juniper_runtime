import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.adapters.guest_db.exact_entity_lookup_adapter import (  # noqa: E402
    execute_alexis_guest_exact_entity_lookup,
)
from planner.lookup_metadata import declare_lookup_metadata  # noqa: E402
from runtime.lookup.context_budgeting import apply_lookup_context_budget  # noqa: E402
from runtime.lookup.context_injection import maybe_inject_lookup_context  # noqa: E402
from runtime.lookup.context_materializer import (  # noqa: E402
    materialize_lookup_context_packets,
)
from runtime.lookup.context_render_gate import (  # noqa: E402
    evaluate_lookup_context_render_gate,
)
from runtime.lookup.context_renderer import render_lookup_context_blocks  # noqa: E402
from runtime.lookup.execution import (  # noqa: E402
    execute_lookup_requests,
    lookup_execution_result_to_metadata,
)
from runtime.lookup.execution_policy import (  # noqa: E402
    DEFAULT_LOOKUP_EXECUTION_POLICY,
)
from runtime.lookup.governance import LookupGovernancePolicy  # noqa: E402
from runtime.lookup.pipeline_summary import build_lookup_pipeline_summary  # noqa: E402
from runtime.lookup.request_planner import create_explicit_lookup_requests  # noqa: E402


def lookup_binding():
    return {
        "lookup_request_policy": {
            "enabled": True,
            "lookup_type": "exact_entity_lookup",
            "entity_type": "person",
            "source_scope": "alexis_guest_canonical_csv",
            "allowed_source_scopes": ["alexis_guest_canonical_csv"],
            "required_planner_fields": ["entity_name"],
            "optional_planner_fields": ["workflow_topic"],
        }
    }


def materialization_policy():
    return {
        "enabled": True,
        "context_type": "bounded_lookup_result",
        "allowed_fields": ["display_name", "title"],
        "max_fields": 2,
    }


def render_policy(max_packets=2):
    return {
        "allowed": True,
        "render_modes": ["structured_fact_block"],
        "max_packets": max_packets,
        "require_successful_retrieval": True,
        "allowed_context_types": ["bounded_lookup_result"],
        "allowed_lookup_types": ["exact_entity_lookup"],
        "allowed_source_scopes": ["alexis_guest_canonical_csv"],
        "allowed_entity_types": ["person"],
        "field_order": ["display_name", "title"],
        "field_labels": {
            "display_name": "Display name",
            "title": "Title",
        },
    }


def injection_policy(max_blocks=2, max_total_characters=2400):
    return {
        "allowed": True,
        "require_render_decision": True,
        "require_rendered_context": True,
        "allowed_content_types": ["lookup_context_block"],
        "allowed_render_modes": ["structured_fact_block"],
        "max_blocks": max_blocks,
        "max_facts_per_block": 2,
        "max_total_characters": max_total_characters,
        "truncation_mode": "drop_tail",
    }


def rows():
    return [
        {
            "guest_id": "dr_saju_matthew",
            "display_name": "Dr. Saju Matthew",
            "title": "Family Practice Physician",
            "expertise": "",
            "booking_notes": "Monthly booking",
            "source_updated_at": "",
        },
        {
            "guest_id": "dr_shikha_jain",
            "display_name": "Dr. Shikha Jain",
            "title": "Oncology",
            "expertise": "",
            "booking_notes": "",
            "source_updated_at": "",
        },
    ]


def agent(data_rows=None):
    def resolver(request):
        return lambda lookup_request: execute_alexis_guest_exact_entity_lookup(
            lookup_request,
            rows=data_rows if data_rows is not None else rows(),
        )

    return SimpleNamespace(get_lookup_executor=resolver)


def patch_binding(monkey_policy):
    import runtime.lookup.request_planner as planner

    original = planner.resolve_lookup_capability

    def fake_resolve_lookup_capability(
        *,
        agent,
        shared_capability,
        root=planner.ROOT,
    ):
        return SimpleNamespace(
            governance=LookupGovernancePolicy(state="enabled"),
            execution_policy=DEFAULT_LOOKUP_EXECUTION_POLICY,
            policy_section=lambda name: (
                monkey_policy.get(name)
                if isinstance(monkey_policy, dict)
                else None
            )
        )

    planner.resolve_lookup_capability = fake_resolve_lookup_capability
    return planner, original


def restore_binding(planner, original):
    planner.resolve_lookup_capability = original


def multi_metadata(*names):
    return {
        "target_entities": [
            {"entity_name": name}
            for name in names
        ],
        "workflow_topic": "healthcare reform",
    }


def make_requests(metadata):
    planner, original = patch_binding(lookup_binding())
    try:
        return create_explicit_lookup_requests(
            agent_name="test_agent",
            shared_capability="draft_email",
            planner_lookup=metadata,
        )
    finally:
        restore_binding(planner, original)


def execute_pipeline(metadata, *, data_rows=None, request_mutator=None):
    planned = make_requests(metadata)
    lookup_requests = [
        item.request for item in planned if item.request is not None
    ]
    if request_mutator is not None:
        lookup_requests = [request_mutator(request) for request in lookup_requests]

    execution_results = execute_lookup_requests(
        agent=agent(data_rows=data_rows),
        lookup_requests=lookup_requests,
    )
    lookup_results = [
        lookup_execution_result_to_metadata(result)
        for result in execution_results
    ]
    execution_traces = [result.trace for result in execution_results]
    packets = materialize_lookup_context_packets(
        lookup_results=lookup_results,
        materialization_policy=materialization_policy(),
    )
    decision = evaluate_lookup_context_render_gate(
        lookup_context_packets=packets,
        render_policy=render_policy(max_packets=2),
    )
    rendered = render_lookup_context_blocks(
        lookup_context_packets=packets,
        render_decision=decision,
        render_policy=render_policy(max_packets=2),
    )
    injection = maybe_inject_lookup_context(
        [{"role": "user", "content": "Draft"}],
        rendered_lookup_context=rendered,
        render_decision=decision,
        injection_policy=injection_policy(max_blocks=2),
    )
    planning = SimpleNamespace(
        lookup_requests=lookup_requests,
        lookup_request_traces=[item.trace for item in planned],
        lookup_execution_traces=execution_traces,
        lookup_context_packets=packets,
        lookup_context_render_decision=decision,
    )
    summary = build_lookup_pipeline_summary(
        planning=planning,
        injection_trace=injection.trace,
    )
    return SimpleNamespace(
        planned=planned,
        lookup_requests=lookup_requests,
        lookup_results=lookup_results,
        execution_traces=execution_traces,
        packets=packets,
        decision=decision,
        rendered=rendered,
        injection=injection,
        summary=summary,
    )


def test_planner_can_declare_multiple_explicit_target_entities():
    metadata = declare_lookup_metadata(
        text="ignored",
        agent_name="alexis",
        shared_capability="draft_email",
        model_lookup_metadata=multi_metadata(
            "Dr. Saju Matthew",
            "Dr. Shikha Jain",
        ),
    )

    assert metadata is not None
    assert metadata.to_request_metadata() == multi_metadata(
        "Dr. Saju Matthew",
        "Dr. Shikha Jain",
    )


def test_runtime_creates_multiple_deterministic_lookup_requests():
    result = make_requests(multi_metadata("Dr. Saju Matthew", "Dr. Shikha Jain"))
    requests = [item.request for item in result]

    assert len(requests) == 2
    assert requests[0]["lookup_id"].endswith(":1")
    assert requests[1]["lookup_id"].endswith(":2")
    assert requests[0]["workflow_topic"] == "healthcare reform"
    assert requests[1]["workflow_topic"] == "healthcare reform"
    assert requests[0]["lookup_lineage_id"] != requests[1]["lookup_lineage_id"]


def test_multiple_lookups_execute_and_render_in_planner_order():
    result = execute_pipeline(
        multi_metadata("Dr. Saju Matthew", "Dr. Shikha Jain")
    )

    assert [item["records_returned"] for item in result.execution_traces] == [
        1,
        1,
    ]
    assert len(result.packets) == 2
    assert result.decision["render_allowed"] is True
    assert [
        block["facts"][0]["value"]
        for block in result.rendered["blocks"]
    ] == ["Dr. Saju Matthew", "Dr. Shikha Jain"]
    assert result.injection.trace["injection_allowed"] is True
    assert result.injection.trace["injected_block_count"] == 2


def test_failed_lookup_does_not_corrupt_successful_lookup_lineage():
    result = execute_pipeline(
        multi_metadata("Dr. Saju Matthew", "Unknown Person")
    )

    assert [item["records_returned"] for item in result.execution_traces] == [
        1,
        0,
    ]
    assert result.execution_traces[0]["lookup_lineage_id"] != (
        result.execution_traces[1]["lookup_lineage_id"]
    )
    assert len(result.packets) == 1
    assert result.packets[0]["fields"]["display_name"] == "Dr. Saju Matthew"
    assert result.summary["lookup_pipeline"]["execution_status"] == (
        "partial_success"
    )
    assert result.summary["lookup_pipeline"]["lookup_status_counts"] == {
        "success": 1,
        "no_match": 1,
    }


def test_partial_success_injects_only_successful_lookups_in_order():
    result = execute_pipeline(
        multi_metadata(
            "Dr. Saju Matthew",
            "Unknown Person",
            "Dr. Shikha Jain",
        )
    )

    assert [
        trace["lookup_status"] for trace in result.execution_traces
    ] == ["success", "no_match", "success"]
    assert [
        packet["fields"]["display_name"] for packet in result.packets
    ] == ["Dr. Saju Matthew", "Dr. Shikha Jain"]
    assert [
        block["facts"][0]["value"]
        for block in result.rendered["blocks"]
    ] == ["Dr. Saju Matthew", "Dr. Shikha Jain"]
    assert result.injection.trace["injection_allowed"] is True
    assert result.injection.trace["injected_block_count"] == 2

    injected = "\n".join(
        message["content"]
        for message in result.injection.messages
        if message["role"] == "system"
    )
    assert "Dr. Saju Matthew" in injected
    assert "Dr. Shikha Jain" in injected
    assert "Unknown Person" not in injected
    assert "payloads" not in injected
    assert "lookup_context_packets" not in injected

    summary = result.summary["lookup_pipeline"]
    assert summary["execution_status"] == "partial_success"
    assert summary["successful_lookup_count"] == 2
    assert summary["failed_lookup_count"] == 1


def test_duplicate_match_lifecycle_fails_closed_without_injection():
    duplicate_rows = [
        *rows(),
        {
            "guest_id": "dr_saju_matthew_duplicate",
            "display_name": "Dr. Saju Matthew",
            "title": "Duplicate",
            "expertise": "",
            "booking_notes": "",
            "source_updated_at": "",
        },
    ]
    result = execute_pipeline(
        multi_metadata("Dr. Saju Matthew"),
        data_rows=duplicate_rows,
    )

    assert result.execution_traces[0]["lookup_status"] == "duplicate_match"
    assert result.packets == []
    assert result.rendered is None
    assert result.injection.trace["injection_allowed"] is False
    assert result.injection.trace["injected_block_count"] == 0
    assert result.summary["lookup_pipeline"]["lookup_status_counts"] == {
        "duplicate_match": 1,
    }


def test_unauthorized_lookup_lifecycle_fails_closed_independently():
    def mutate(request):
        updated = dict(request)
        updated["source_scope"] = "unauthorized_scope"
        return updated

    result = execute_pipeline(
        multi_metadata("Dr. Saju Matthew"),
        request_mutator=mutate,
    )

    assert result.execution_traces[0]["lookup_status"] == "unauthorized"
    assert result.packets == []
    assert result.injection.trace["injection_allowed"] is False
    assert result.summary["lookup_pipeline"]["execution_status"] == (
        "unauthorized"
    )
    assert "unauthorized_source_scope" in result.summary["lookup_pipeline"][
        "skipped_reasons"
    ]


def test_budgeting_truncates_multiple_blocks_deterministically():
    result = execute_pipeline(
        multi_metadata("Dr. Saju Matthew", "Dr. Shikha Jain")
    )
    budgeted = apply_lookup_context_budget(
        rendered_lookup_context=result.rendered,
        budget_policy=injection_policy(max_blocks=1, max_total_characters=1200),
    )

    assert budgeted.rendered_lookup_context is not None
    assert len(budgeted.rendered_lookup_context["blocks"]) == 1
    assert budgeted.rendered_lookup_context["blocks"][0]["facts"][0][
        "value"
    ] == "Dr. Saju Matthew"
    assert budgeted.trace["dropped_blocks"] == 1


def test_no_autonomous_retrieval_expansion_occurs():
    metadata = multi_metadata("Dr. Saju Matthew", "Dr. Shikha Jain")
    result = execute_pipeline(metadata)

    assert len(result.lookup_requests) == len(metadata["target_entities"])
    assert len(result.execution_traces) == len(metadata["target_entities"])
    assert "semantic" not in repr(result.execution_traces).lower()
    assert "ranking" not in repr(result.execution_traces).lower()


def main():
    test_planner_can_declare_multiple_explicit_target_entities()
    test_runtime_creates_multiple_deterministic_lookup_requests()
    test_multiple_lookups_execute_and_render_in_planner_order()
    test_failed_lookup_does_not_corrupt_successful_lookup_lineage()
    test_partial_success_injects_only_successful_lookups_in_order()
    test_duplicate_match_lifecycle_fails_closed_without_injection()
    test_unauthorized_lookup_lifecycle_fails_closed_independently()
    test_budgeting_truncates_multiple_blocks_deterministically()
    test_no_autonomous_retrieval_expansion_occurs()
    print("PASS lookup multi entity pipeline")


if __name__ == "__main__":
    main()
