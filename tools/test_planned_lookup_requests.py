import inspect
import json
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.lookup.request_planner as lookup_request_planner  # noqa: E402
import runtime.request_planner as request_planner  # noqa: E402
import runtime.lookup.execution as lookup_execution  # noqa: E402
import planner.execution as execution_planner  # noqa: E402
from agents.alexis import AlexisAgent  # noqa: E402
from agents.alexis.adapters.guest_db.exact_entity_lookup_adapter import (  # noqa: E402
    execute_alexis_guest_exact_entity_lookup,
)
from runtime.lookup.request_planner import (  # noqa: E402
    create_explicit_lookup_request,
)
from runtime.lookup.execution import execute_lookup_request  # noqa: E402
from runtime.lookup.pipeline_summary import build_lookup_pipeline_summary  # noqa: E402
from runtime.registries.lookup_capability_registry import (  # noqa: E402
    ResolvedLookupCapability,
    resolve_lookup_capability,
)
from runtime.request_planner import (  # noqa: E402
    attach_lookup_execution_results,
    build_planning_result_without_lookup_execution,
    execute_planned_lookup_requests,
    plan_request,
)


def dispatch():
    return SimpleNamespace(
        target_agent="alexis",
        cognition="LOCAL",
        task_type="planned_lookup_request_test",
        tools_needed=[],
        reason="Focused planned lookup request test.",
        confidence=1.0,
    )


def alexis_agent():
    return AlexisAgent(workspace_path="/tmp/juniper_stage_13a_alexis")


def planner_lookup(**overrides):
    data = {
        "entity_name": "Dr. Saju Matthew",
        "workflow_topic": "Iran talks",
    }
    data.update(overrides)
    return data


def bounded_search_lookup(**overrides):
    data = {
        "search_requests": [
            {
                "lookup_type": "bounded_entity_search",
                "search_topic": "healthcare reform",
                "max_results": 5,
            }
        ]
    }
    data.update(overrides)
    return data


def generic_lookup_binding(**overrides):
    binding = {
        "shared_capability": "summarize_entity",
        "skills": [],
        "resources": ["directory_adapter"],
        "lookup_capability_compatibility": {
            "contract_version": 1,
            "min_runtime_version": 1,
            "max_runtime_version": 1,
            "required_features": [
                "exact_entity_lookup",
                "bounded_context_materialization",
            ],
        },
        "lookup_request_policy": {
            "enabled": True,
            "lookup_type": "exact_entity_lookup",
            "entity_type": "person",
            "source_scope": "directory_scope",
            "allowed_source_scopes": ["directory_scope"],
            "required_planner_fields": ["entity_name"],
            "optional_planner_fields": ["workflow_topic"],
        },
        "lookup_context_materialization_policy": {
            "enabled": True,
            "context_type": "bounded_lookup_result",
            "allowed_fields": ["display_name"],
            "max_fields": 1,
        },
        "lookup_context_render_policy": {
            "allowed": True,
            "render_modes": ["structured_fact_block"],
            "max_packets": 1,
            "require_successful_retrieval": True,
            "allowed_context_types": ["bounded_lookup_result"],
            "allowed_lookup_types": ["exact_entity_lookup"],
            "allowed_source_scopes": ["directory_scope"],
            "allowed_entity_types": ["person"],
            "field_order": ["display_name"],
            "field_labels": {"display_name": "Display name"},
        },
        "lookup_context_injection_policy": {
            "allowed": True,
            "require_render_decision": True,
            "require_rendered_context": True,
            "allowed_content_types": ["lookup_context_block"],
            "allowed_render_modes": ["structured_fact_block"],
            "max_blocks": 1,
            "max_facts_per_block": 1,
            "max_total_characters": 600,
            "truncation_mode": "drop_tail",
        },
    }
    binding.update(overrides)
    return binding


def write_lookup_manifest(root, agent_name, bindings):
    path = (
        Path(root)
        / "agents"
        / agent_name
        / "capabilities"
        / "bindings.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"bindings": bindings}, indent=2),
        encoding="utf-8",
    )


def test_guest_booking_workflow_creates_valid_exact_entity_lookup_request():
    planned = plan_request(
        text="Draft an outreach email to Dr. Saju Matthew about Iran talks.",
        agent=alexis_agent(),
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    assert planned.shared_capability == "draft_email"
    assert planned.plan.lookup_metadata == planner_lookup()
    assert "entity_type" not in planned.plan.lookup_metadata
    assert "source_scope" not in planned.plan.lookup_metadata
    assert "guest" not in repr(planned.plan.lookup_metadata).lower()
    assert len(planned.lookup_requests) == 1
    assert planned.lookup_requests[0]["lookup_type"] == "exact_entity_lookup"
    assert planned.lookup_requests[0]["lookup_id"] == (
        "alexis:draft_email:exact_entity_lookup"
    )
    assert planned.lookup_requests[0]["entity_name"] == "Dr. Saju Matthew"
    assert planned.lookup_requests[0]["entity_type"] == "guest"
    assert planned.lookup_requests[0]["workflow_topic"] == "Iran talks"
    assert planned.lookup_requests[0]["source_scope"] == (
        "alexis_guest_canonical_csv"
    )
    assert planned.lookup_requests[0]["lookup_lineage_id"]
    assert len(planned.lookup_execution_traces) == 1
    assert planned.lookup_execution_traces[0]["retrieval_executed"] is True
    assert planned.lookup_execution_traces[0]["records_returned"] == 1
    assert planned.lookup_execution_traces[0]["lookup_lineage_id"] == (
        planned.lookup_requests[0]["lookup_lineage_id"]
    )
    assert planned.lookup_results[0]["retrieval_executed"] is True
    assert planned.lookup_results[0]["payloads"][0]["display_name"] == (
        "Dr. Saju Matthew"
    )
    assert planned.lookup_context_packets[0]["context_type"] == (
        "bounded_lookup_result"
    )
    assert planned.lookup_context_packets[0]["fields"][
        "display_name"
    ] == "Dr. Saju Matthew"
    assert planned.lookup_context_render_decision["render_allowed"] is True
    assert planned.lookup_context_render_decision["render_mode"] == (
        "structured_fact_block"
    )
    assert planned.lookup_context_render_decision["packet_ids"] == [
        "alexis:draft_email:exact_entity_lookup"
    ]
    assert planned.rendered_lookup_context["content_type"] == (
        "lookup_context_block"
    )


def test_pure_planning_creates_lookup_request_without_execution():
    planned = build_planning_result_without_lookup_execution(
        text="Draft an outreach email to Dr. Saju Matthew about Iran talks.",
        agent=alexis_agent(),
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    assert len(planned.lookup_requests) == 1
    assert planned.lookup_requests[0]["lookup_type"] == "exact_entity_lookup"
    assert planned.lookup_requests[0]["lookup_lineage_id"]
    assert planned.lookup_capability is not None
    assert planned.lookup_capability.registration.agent == "alexis"
    assert planned.lookup_capability.registration.shared_capability == (
        "draft_email"
    )
    assert planned.lookup_capability.policy_section(
        "lookup_context_materialization_policy"
    )["allowed_fields"] == [
        "display_name",
        "title",
        "expertise",
        "public_booking_notes",
        "known_contact_channels",
    ]
    assert planned.lookup_capability.policy_section(
        "lookup_context_render_policy"
    )["render_modes"] == ["structured_fact_block"]
    assert planned.lookup_capability.policy_section(
        "lookup_context_injection_policy"
    )["allowed_content_types"] == ["lookup_context_block"]
    assert planned.lookup_request_traces[0]["retrieval_executed"] is False
    assert planned.lookup_results == []
    assert planned.lookup_execution_traces == []
    assert planned.lookup_context_packets == []
    assert planned.lookup_context_render_decision is None
    assert planned.rendered_lookup_context is None


def test_bounded_execution_phase_attaches_lookup_results():
    agent = alexis_agent()
    planned = build_planning_result_without_lookup_execution(
        text="Draft an outreach email to Dr. Saju Matthew about Iran talks.",
        agent=agent,
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    lookup_results, lookup_execution_traces = execute_planned_lookup_requests(
        planning_result=planned,
        agent=agent,
    )
    executed = attach_lookup_execution_results(
        planning_result=planned,
        agent=agent,
    )

    assert lookup_results[0]["retrieval_executed"] is True
    assert lookup_execution_traces[0]["retrieval_executed"] is True
    assert executed.lookup_results == lookup_results
    assert executed.lookup_execution_traces == lookup_execution_traces
    assert executed.lookup_context_packets[0]["fields"][
        "display_name"
    ] == "Dr. Saju Matthew"
    assert executed.lookup_context_render_decision["render_allowed"] is True
    assert executed.rendered_lookup_context["render_mode"] == (
        "structured_fact_block"
    )
    assert executed.resolved_text == planned.resolved_text
    assert "Family Practice Physician" not in executed.resolved_text
    assert "BOOK MONTHLY" not in executed.resolved_text


def test_post_planning_lookup_phases_use_resolved_capability_bundle():
    agent = alexis_agent()
    planned = build_planning_result_without_lookup_execution(
        text="Draft an outreach email to Dr. Saju Matthew about Iran talks.",
        agent=agent,
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )
    original_resolve = request_planner.resolve_lookup_capability

    def fail_if_called(**_kwargs):
        raise AssertionError("lookup capability should already be resolved")

    request_planner.resolve_lookup_capability = fail_if_called
    try:
        executed = attach_lookup_execution_results(
            planning_result=planned,
            agent=agent,
        )
    finally:
        request_planner.resolve_lookup_capability = original_resolve

    assert executed.lookup_results[0]["retrieval_executed"] is True
    assert executed.lookup_context_packets[0]["fields"][
        "display_name"
    ] == "Dr. Saju Matthew"
    assert executed.lookup_context_render_decision["render_allowed"] is True
    assert executed.rendered_lookup_context["content_type"] == (
        "lookup_context_block"
    )


def test_missing_resolved_lookup_capability_fails_closed_after_planning():
    agent = alexis_agent()
    planned = build_planning_result_without_lookup_execution(
        text="Draft an outreach email to Dr. Saju Matthew about Iran talks.",
        agent=agent,
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )
    without_capability = replace(planned, lookup_capability=None)

    lookup_results, lookup_execution_traces = execute_planned_lookup_requests(
        planning_result=without_capability,
        agent=agent,
    )
    executed = attach_lookup_execution_results(
        planning_result=without_capability,
        agent=agent,
    )

    assert lookup_results[0]["retrieval_executed"] is False
    assert lookup_execution_traces[0]["skipped_reasons"] == [
        "lookup_capability_resolution_failed"
    ]
    assert executed.lookup_context_packets == []
    assert executed.lookup_context_render_decision["render_allowed"] is False
    assert executed.rendered_lookup_context is None


def test_planner_can_declare_bounded_entity_search_metadata():
    metadata = execution_planner.declare_lookup_metadata(
        text="Find sources about healthcare reform.",
        agent_name="alexis",
        shared_capability="discover_entities",
        model_lookup_metadata=bounded_search_lookup(),
    )

    assert metadata is not None
    request_metadata = metadata.to_request_metadata()
    assert request_metadata == bounded_search_lookup()


def test_runtime_creates_valid_bounded_entity_search_request():
    planned = lookup_request_planner.create_explicit_lookup_requests(
        agent_name="alexis",
        shared_capability="discover_entities",
        planner_lookup=bounded_search_lookup(),
    )

    assert len(planned) == 1
    result = planned[0]
    assert result.status == "lookup_request_created"
    assert result.request is not None
    assert result.request["lookup_type"] == "bounded_entity_search"
    assert result.request["lookup_id"] == (
        "alexis:discover_entities:bounded_entity_search:1"
    )
    assert result.request["search_topic"] == "healthcare reform"
    assert result.request["max_results"] == 5
    assert result.request["entity_type"] == "guest"
    assert result.request["source_scope"] == "alexis_guest_canonical_csv"
    assert result.trace["lookup_type"] == "bounded_entity_search"
    assert result.trace["request_created"] is True
    assert result.trace["governance_state"] == "audit_only"
    assert "healthcare reform" not in repr(result.trace)


def test_bounded_entity_search_missing_topic_fails_closed():
    planned = lookup_request_planner.create_explicit_lookup_requests(
        agent_name="alexis",
        shared_capability="discover_entities",
        planner_lookup={
            "search_requests": [
                {
                    "lookup_type": "bounded_entity_search",
                    "max_results": 5,
                }
            ]
        },
    )

    assert len(planned) == 1
    result = planned[0]
    assert result.request is None
    assert result.status == "lookup_request_not_created"
    assert result.skipped_reasons == (
        "missing_search_topic_or_query_intent",
    )


def test_bounded_entity_search_does_not_infer_from_raw_text():
    metadata = execution_planner.declare_lookup_metadata(
        text="Find possible sources about healthcare reform.",
        agent_name="alexis",
        shared_capability="discover_entities",
    )

    assert metadata is None


def test_bounded_entity_search_uses_discover_entities_capability():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="discover_entities",
        root=ROOT,
    )

    assert isinstance(resolved, ResolvedLookupCapability)
    assert resolved.registration.binding_id == "bounded_guest_search"
    assert resolved.registration.shared_capability == "discover_entities"
    assert "bounded_entity_search" in (
        resolved.registration.supported_lookup_types
    )
    assert resolved.policy_section("lookup_request_policy")[
        "execution_status"
    ] == "implemented"


def test_bounded_entity_search_missing_executor_fails_closed():
    request = lookup_request_planner.create_explicit_lookup_requests(
        agent_name="alexis",
        shared_capability="discover_entities",
        planner_lookup=bounded_search_lookup(),
    )[0].request

    result = execute_lookup_request(
        agent=object(),
        lookup_request=request,
    )

    assert result.retrieval_executed is False
    assert result.payloads == []
    assert result.skipped_reasons == (
        "bounded_entity_search_not_implemented",
    )
    assert result.trace["lookup_type"] == "bounded_entity_search"
    assert result.trace["records_returned"] == 0
    assert "healthcare reform" not in repr(result.trace)


def test_bounded_entity_search_governed_binding_prevents_execution():
    request = lookup_request_planner.create_explicit_lookup_requests(
        agent_name="alexis",
        shared_capability="discover_entities",
        planner_lookup=bounded_search_lookup(),
    )[0].request
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="discover_entities",
        root=ROOT,
    )

    result = execute_lookup_request(
        agent=alexis_agent(),
        lookup_request=request,
        lookup_capability=resolved,
        require_lookup_capability=True,
    )

    assert result.retrieval_executed is False
    assert result.payloads == []
    assert result.skipped_reasons == ("lookup_capability_audit_only",)
    assert result.trace["governance_state"] == "audit_only"


def test_planner_lookup_metadata_excludes_agent_policy_fields():
    plan = execution_planner.build_execution_plan(
        original_text=(
            "Draft an outreach email to Dr. Saju Matthew about Iran talks."
        ),
        resolved_text=(
            "Draft an outreach email to Dr. Saju Matthew about Iran talks."
        ),
        resolution=SimpleNamespace(action="NONE"),
        dispatch=dispatch(),
        user_id="planned_lookup_user",
        semantic_output_type="email_draft",
        shared_capability="draft_email",
    )

    assert plan.lookup_metadata == planner_lookup()
    assert "entity_type" not in plan.lookup_metadata
    assert "source_scope" not in plan.lookup_metadata
    assert "guest" not in repr(plan.lookup_metadata).lower()


def test_lookup_request_creation_is_explicit_and_observable():
    result = create_explicit_lookup_request(
        agent_name="alexis",
        shared_capability="draft_email",
        planner_lookup=planner_lookup(),
    )

    assert result.status == "lookup_request_created"
    assert result.request is not None
    assert result.trace["lookup_type"] == "exact_entity_lookup"
    assert result.trace["lookup_id"] == "alexis:draft_email:exact_entity_lookup"
    assert result.trace["entity_type"] == "guest"
    assert result.trace["workflow_topic"] == "Iran talks"
    assert result.trace["source_scope"] == "alexis_guest_canonical_csv"
    assert result.trace["request_created"] is True
    assert result.trace["retrieval_executed"] is False
    assert result.trace["records_returned"] == 0
    assert result.trace["skipped_reasons"] == []
    assert result.trace["validation_errors"] == []
    assert result.trace["lookup_lineage_id"]
    assert "Dr. Saju Matthew" not in repr(result.trace)
    assert result.request["entity_type"] == "guest"
    assert result.request["source_scope"] == "alexis_guest_canonical_csv"


def test_lookup_request_creation_resolves_through_capability_registry():
    with TemporaryDirectory() as tmp:
        write_lookup_manifest(
            tmp,
            "neutral_agent",
            {"summarize_entity": generic_lookup_binding()},
        )
        result = create_explicit_lookup_request(
            agent_name="neutral_agent",
            shared_capability="summarize_entity",
            planner_lookup={
                "entity_name": "Ada Lovelace",
                "workflow_topic": "computing history",
            },
            root=Path(tmp),
        )

    assert result.status == "lookup_request_created"
    assert result.request is not None
    assert result.request["lookup_id"] == (
        "neutral_agent:summarize_entity:exact_entity_lookup"
    )
    assert result.request["entity_type"] == "person"
    assert result.request["source_scope"] == "directory_scope"
    assert result.trace["request_created"] is True


def test_missing_lookup_capability_registration_fails_closed():
    result = create_explicit_lookup_request(
        agent_name="alexis",
        shared_capability="producer_note",
        planner_lookup=planner_lookup(),
    )

    assert result.request is None
    assert result.status == "lookup_not_declared"
    assert result.skipped_reasons == (
        "lookup_capability_resolution_failed",
    )
    assert result.trace["request_created"] is False
    assert result.trace["validation_errors"] == ["lookup_capability"]


def test_malformed_lookup_capability_registration_fails_closed():
    bad = generic_lookup_binding()
    bad["lookup_request_policy"] = {
        **bad["lookup_request_policy"],
        "lookup_type": "semantic_search",
    }

    with TemporaryDirectory() as tmp:
        write_lookup_manifest(
            tmp,
            "neutral_agent",
            {"summarize_entity": bad},
        )
        result = create_explicit_lookup_request(
            agent_name="neutral_agent",
            shared_capability="summarize_entity",
            planner_lookup={"entity_name": "Ada Lovelace"},
            root=Path(tmp),
        )

    assert result.request is None
    assert result.status == "lookup_not_declared"
    assert result.skipped_reasons == (
        "lookup_capability_resolution_failed",
    )
    assert result.trace["validation_errors"] == [
        "lookup_request_policy.lookup_type"
    ]


def test_disabled_lookup_governance_prevents_request_creation():
    disabled = generic_lookup_binding(
        lookup_capability_governance={"state": "disabled"}
    )

    with TemporaryDirectory() as tmp:
        write_lookup_manifest(
            tmp,
            "neutral_agent",
            {"summarize_entity": disabled},
        )
        result = create_explicit_lookup_request(
            agent_name="neutral_agent",
            shared_capability="summarize_entity",
            planner_lookup={"entity_name": "Ada Lovelace"},
            root=Path(tmp),
        )

    assert result.request is None
    assert result.status == "lookup_request_not_created"
    assert result.skipped_reasons == ("lookup_capability_disabled",)
    assert result.trace["governance_state"] == "disabled"
    assert result.trace["retrieval_executed"] is False


def test_blocked_lookup_governance_hard_fails_closed():
    blocked = generic_lookup_binding(
        lookup_capability_governance={"state": "blocked"}
    )

    with TemporaryDirectory() as tmp:
        write_lookup_manifest(
            tmp,
            "neutral_agent",
            {"summarize_entity": blocked},
        )
        result = create_explicit_lookup_request(
            agent_name="neutral_agent",
            shared_capability="summarize_entity",
            planner_lookup={"entity_name": "Ada Lovelace"},
            root=Path(tmp),
        )

    assert result.request is None
    assert result.status == "lookup_request_not_created"
    assert result.skipped_reasons == ("lookup_capability_blocked",)
    assert result.trace["governance_state"] == "blocked"


def test_audit_only_lookup_governance_allows_trace_but_prevents_execution():
    audit_only = generic_lookup_binding(
        lookup_capability_governance={"state": "audit_only"}
    )
    called = {"executor": False}

    with TemporaryDirectory() as tmp:
        write_lookup_manifest(
            tmp,
            "neutral_agent",
            {"summarize_entity": audit_only},
        )
        planned = create_explicit_lookup_request(
            agent_name="neutral_agent",
            shared_capability="summarize_entity",
            planner_lookup={"entity_name": "Ada Lovelace"},
            root=Path(tmp),
        )
        resolved = resolve_lookup_capability(
            agent="neutral_agent",
            shared_capability="summarize_entity",
            root=Path(tmp),
        )

    def executor(_request):
        called["executor"] = True

    agent = SimpleNamespace(get_lookup_executor=lambda request, meta: executor)
    executed = execute_lookup_request(
        agent=agent,
        lookup_request=planned.request,
        lookup_capability=resolved,
        require_lookup_capability=True,
    )
    summary = build_lookup_pipeline_summary(
        planning=SimpleNamespace(
            lookup_requests=[planned.request],
            lookup_request_traces=[planned.trace],
            lookup_execution_traces=[executed.trace],
            lookup_context_packets=[],
            lookup_context_render_decision=None,
        )
    )["lookup_pipeline"]

    assert planned.request is not None
    assert planned.trace["request_created"] is True
    assert planned.trace["governance_state"] == "audit_only"
    assert executed.payloads == []
    assert executed.retrieval_executed is False
    assert executed.skipped_reasons == ("lookup_capability_audit_only",)
    assert executed.trace["governance_state"] == "audit_only"
    assert called["executor"] is False
    assert summary["governance_state"] == "audit_only"
    assert summary["records_returned"] == 0


def test_missing_entity_name_fails_closed():
    result = create_explicit_lookup_request(
        agent_name="alexis",
        shared_capability="draft_email",
        planner_lookup=planner_lookup(entity_name=""),
    )

    assert result.request is None
    assert result.status == "lookup_request_not_created"
    assert result.skipped_reasons == ("missing_entity_name",)
    assert result.trace["request_created"] is False
    assert result.trace["retrieval_executed"] is False


def test_planner_policy_fields_fail_closed():
    result = create_explicit_lookup_request(
        agent_name="alexis",
        shared_capability="draft_email",
        planner_lookup=planner_lookup(source_scope="unauthorized_source"),
    )

    assert result.request is None
    assert result.status == "lookup_request_not_created"
    assert result.skipped_reasons == ("planner_policy_field_not_allowed",)
    assert result.trace["source_scope"] == "alexis_guest_canonical_csv"
    assert result.trace["retrieval_executed"] is False


def test_non_lookup_workflow_does_not_create_lookup_request():
    planned = plan_request(
        text="Write a quick producer note about the rundown.",
        agent=alexis_agent(),
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    assert planned.shared_capability == "producer_note"
    assert planned.lookup_requests == []
    assert planned.lookup_request_traces == []
    assert planned.lookup_results == []
    assert planned.lookup_execution_traces == []
    assert planned.lookup_context_packets == []
    assert planned.lookup_context_render_decision == {
        "render_allowed": False,
        "render_mode": None,
        "reasons": ["missing_or_malformed_render_policy"],
        "packet_ids": [],
        "lookup_lineage_ids": [],
        "lookup_render_ids": [],
    }
    assert planned.rendered_lookup_context is None


def test_runtime_shared_code_has_no_datasource_specific_logic():
    lookup_source = inspect.getsource(lookup_request_planner)
    request_source = inspect.getsource(request_planner)
    execution_source = inspect.getsource(lookup_execution)

    assert "guest_db" not in lookup_source
    assert "canonical_csv" not in lookup_source
    assert "adapters.guest_db" not in lookup_source
    assert "execute_alexis" not in lookup_source
    assert "guest_db" not in request_source
    assert "canonical_csv" not in request_source
    assert "adapters.guest_db" not in request_source
    assert "execute_alexis" not in request_source
    assert "guest_db" not in execution_source
    assert "canonical_csv" not in execution_source
    assert "adapters.guest_db" not in execution_source
    assert "execute_alexis" not in execution_source
    assert "resolve_agent_binding" not in lookup_source
    assert "resolve_agent_binding" not in request_source


def test_runtime_does_not_extract_entity_names_from_raw_text():
    original_declare = execution_planner.declare_lookup_metadata

    def no_lookup_metadata(**kwargs):
        return None

    execution_planner.declare_lookup_metadata = no_lookup_metadata

    try:
        planned = plan_request(
            text=(
                "Draft an outreach email to Dr. Saju Matthew about "
                "Iran talks."
            ),
            agent=alexis_agent(),
            user_id="planned_lookup_user",
            recent_memory=[],
            context_packet={},
            dispatch=dispatch(),
        )
    finally:
        execution_planner.declare_lookup_metadata = original_declare

    assert planned.plan.lookup_metadata is None
    assert planned.lookup_requests == []
    assert len(planned.lookup_request_traces) == 1
    assert planned.lookup_request_traces[0]["lookup_type"] == (
        "exact_entity_lookup"
    )
    assert planned.lookup_request_traces[0]["request_created"] is False
    assert planned.lookup_request_traces[0]["retrieval_executed"] is False
    assert planned.lookup_request_traces[0]["skipped_reasons"] == [
        "missing_planner_lookup_metadata"
    ]
    assert planned.lookup_results == []
    assert planned.lookup_execution_traces == []
    assert planned.lookup_context_packets == []
    assert planned.lookup_context_render_decision == {
        "render_allowed": False,
        "render_mode": None,
        "reasons": ["no_lookup_context_packets"],
        "packet_ids": [],
        "lookup_lineage_ids": [],
        "lookup_render_ids": [],
    }
    assert planned.rendered_lookup_context is None


def test_lookup_execution_does_not_inject_context():
    planned = plan_request(
        text="Draft an outreach email to Dr. Saju Matthew about Iran talks.",
        agent=alexis_agent(),
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    assert planned.lookup_requests
    assert planned.lookup_request_traces[0]["retrieval_executed"] is False
    assert planned.lookup_execution_traces[0]["retrieval_executed"] is True
    assert planned.lookup_execution_traces[0]["records_returned"] == 1
    assert planned.lookup_results[0]["payloads"]
    assert planned.lookup_context_packets[0]["fields"]
    assert planned.lookup_context_render_decision["render_allowed"] is True
    assert planned.rendered_lookup_context is not None
    assert planned.active_artifact is None
    assert "Guest:" not in planned.resolved_text
    assert "Family Practice Physician" not in planned.resolved_text
    assert "BOOK MONTHLY" not in planned.resolved_text
    assert "Retrieved entity context" not in planned.resolved_text
    assert "Dr. Saju Matthew" not in repr(planned.lookup_request_traces)
    assert "Dr. Saju Matthew" not in repr(planned.lookup_execution_traces)
    assert "Dr. Saju Matthew" not in repr(
        planned.lookup_context_render_decision
    )


def test_no_match_lookup_execution_fails_closed():
    planned = plan_request(
        text="Draft an outreach email to Unknown Person about Iran talks.",
        agent=alexis_agent(),
        user_id="planned_lookup_user",
        recent_memory=[],
        context_packet={},
        dispatch=dispatch(),
    )

    assert len(planned.lookup_results) == 1
    assert planned.lookup_results[0]["lookup_id"] == (
        "alexis:draft_email:exact_entity_lookup"
    )
    assert planned.lookup_results[0]["retrieval_executed"] is True
    assert planned.lookup_results[0]["records_returned"] == 0
    assert planned.lookup_results[0]["skipped_reasons"] == ["no_exact_match"]
    assert planned.lookup_results[0]["payloads"] == []
    assert planned.lookup_results[0]["lookup_lineage_id"] == (
        planned.lookup_requests[0]["lookup_lineage_id"]
    )
    assert planned.lookup_context_packets == []
    assert planned.lookup_context_render_decision == {
        "render_allowed": False,
        "render_mode": None,
        "reasons": ["no_lookup_context_packets"],
        "packet_ids": [],
        "lookup_lineage_ids": [],
        "lookup_render_ids": [],
    }
    assert planned.rendered_lookup_context is None


def test_unauthorized_lookup_execution_fails_closed():
    result = execute_lookup_request(
        agent=alexis_agent(),
        lookup_request={
            "lookup_type": "exact_entity_lookup",
            "lookup_id": "stage-13-unauthorized",
            "entity_name": "Dr. Saju Matthew",
            "entity_type": "guest",
            "workflow_topic": "Iran talks",
            "source_scope": "raw_private_csv",
        },
    )

    assert result.payloads == []
    assert result.retrieval_executed is False
    assert result.skipped_reasons == ("lookup_executor_unavailable",)
    assert result.trace["records_returned"] == 0


def test_lookup_execution_uses_resolved_capability_metadata():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="draft_email",
        root=ROOT,
    )
    seen = {}

    def resolver(lookup_request, lookup_capability):
        seen["lookup_capability"] = lookup_capability
        return execute_alexis_guest_exact_entity_lookup

    result = execute_lookup_request(
        agent=SimpleNamespace(get_lookup_executor=resolver),
        lookup_request={
            "lookup_type": "exact_entity_lookup",
            "lookup_id": "stage-20c-metadata",
            "entity_name": "Dr. Saju Matthew",
            "entity_type": "guest",
            "workflow_topic": "Iran talks",
            "source_scope": "alexis_guest_canonical_csv",
        },
        lookup_capability=resolved,
    )

    assert result.retrieval_executed is True
    assert result.payloads[0]["display_name"] == "Dr. Saju Matthew"
    assert seen["lookup_capability"]["adapter_owners"] == ["guest_db"]
    assert seen["lookup_capability"]["supported_lookup_types"] == [
        "exact_entity_lookup"
    ]
    assert seen["lookup_capability"]["source_scopes"] == [
        "alexis_guest_canonical_csv"
    ]


def test_lookup_execution_missing_executor_fails_closed():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="draft_email",
        root=ROOT,
    )
    result = execute_lookup_request(
        agent=SimpleNamespace(),
        lookup_request={
            "lookup_type": "exact_entity_lookup",
            "lookup_id": "stage-20c-missing-executor",
            "entity_name": "Dr. Saju Matthew",
            "entity_type": "guest",
            "workflow_topic": "Iran talks",
            "source_scope": "alexis_guest_canonical_csv",
        },
        lookup_capability=resolved,
    )

    assert result.payloads == []
    assert result.retrieval_executed is False
    assert result.skipped_reasons == ("lookup_executor_unavailable",)


def test_lookup_execution_capability_source_scope_mismatch_fails_closed():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="draft_email",
        root=ROOT,
    )
    result = execute_lookup_request(
        agent=alexis_agent(),
        lookup_request={
            "lookup_type": "exact_entity_lookup",
            "lookup_id": "stage-20c-scope-mismatch",
            "entity_name": "Dr. Saju Matthew",
            "entity_type": "guest",
            "workflow_topic": "Iran talks",
            "source_scope": "raw_private_csv",
        },
        lookup_capability=resolved,
    )

    assert result.payloads == []
    assert result.retrieval_executed is False
    assert result.skipped_reasons == (
        "source_scope_not_supported_by_capability",
    )


def test_lookup_execution_adapter_owner_mismatch_fails_closed():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="draft_email",
        root=ROOT,
    )
    mismatched = ResolvedLookupCapability(
        registration=replace(
            resolved.registration,
            adapter_owners=("different_adapter",),
        ),
        binding_policy=resolved.binding_policy,
        compatibility=resolved.compatibility,
        governance=resolved.governance,
        execution_policy=resolved.execution_policy,
    )
    result = execute_lookup_request(
        agent=alexis_agent(),
        lookup_request={
            "lookup_type": "exact_entity_lookup",
            "lookup_id": "stage-20c-owner-mismatch",
            "entity_name": "Dr. Saju Matthew",
            "entity_type": "guest",
            "workflow_topic": "Iran talks",
            "source_scope": "alexis_guest_canonical_csv",
        },
        lookup_capability=mismatched,
    )

    assert result.payloads == []
    assert result.retrieval_executed is False
    assert result.skipped_reasons == ("lookup_executor_unavailable",)


def test_multiple_match_lookup_execution_fails_closed():
    def executor(request):
        return execute_alexis_guest_exact_entity_lookup(
            request,
            rows=[
                {
                    "guest_id": "guest-1",
                    "display_name": "Jane Doe",
                    "title": "Policy Analyst",
                    "expertise": "Energy policy",
                    "booking_notes": "Available",
                    "source_updated_at": "",
                },
                {
                    "guest_id": "guest-2",
                    "display_name": "Jane Doe",
                    "title": "Policy Analyst",
                    "expertise": "Energy policy",
                    "booking_notes": "Available",
                    "source_updated_at": "",
                },
            ],
        )

    agent = SimpleNamespace(get_lookup_executor=lambda request: executor)
    result = execute_lookup_request(
        agent=agent,
        lookup_request={
            "lookup_type": "exact_entity_lookup",
            "lookup_id": "stage-13-multiple",
            "entity_name": "Jane Doe",
            "entity_type": "guest",
            "workflow_topic": "Iran talks",
            "source_scope": "alexis_guest_canonical_csv",
        },
    )

    assert result.payloads == []
    assert result.retrieval_executed is True
    assert result.skipped_reasons == ("multiple_exact_matches",)
    assert result.trace["records_returned"] == 0


def main():
    test_guest_booking_workflow_creates_valid_exact_entity_lookup_request()
    test_pure_planning_creates_lookup_request_without_execution()
    test_bounded_execution_phase_attaches_lookup_results()
    test_post_planning_lookup_phases_use_resolved_capability_bundle()
    test_missing_resolved_lookup_capability_fails_closed_after_planning()
    test_planner_can_declare_bounded_entity_search_metadata()
    test_runtime_creates_valid_bounded_entity_search_request()
    test_bounded_entity_search_missing_topic_fails_closed()
    test_bounded_entity_search_does_not_infer_from_raw_text()
    test_bounded_entity_search_uses_discover_entities_capability()
    test_bounded_entity_search_missing_executor_fails_closed()
    test_bounded_entity_search_governed_binding_prevents_execution()
    test_planner_lookup_metadata_excludes_agent_policy_fields()
    test_lookup_request_creation_is_explicit_and_observable()
    test_lookup_request_creation_resolves_through_capability_registry()
    test_missing_lookup_capability_registration_fails_closed()
    test_malformed_lookup_capability_registration_fails_closed()
    test_disabled_lookup_governance_prevents_request_creation()
    test_blocked_lookup_governance_hard_fails_closed()
    test_audit_only_lookup_governance_allows_trace_but_prevents_execution()
    test_missing_entity_name_fails_closed()
    test_planner_policy_fields_fail_closed()
    test_non_lookup_workflow_does_not_create_lookup_request()
    test_runtime_shared_code_has_no_datasource_specific_logic()
    test_runtime_does_not_extract_entity_names_from_raw_text()
    test_lookup_execution_does_not_inject_context()
    test_no_match_lookup_execution_fails_closed()
    test_unauthorized_lookup_execution_fails_closed()
    test_lookup_execution_uses_resolved_capability_metadata()
    test_lookup_execution_missing_executor_fails_closed()
    test_lookup_execution_capability_source_scope_mismatch_fails_closed()
    test_lookup_execution_adapter_owner_mismatch_fails_closed()
    test_multiple_match_lookup_execution_fails_closed()
    print("PASS planned lookup requests")


if __name__ == "__main__":
    main()
