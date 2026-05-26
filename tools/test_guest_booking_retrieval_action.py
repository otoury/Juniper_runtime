import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import resolve_workflow_declaration
from runtime.workflows.materialization import (
    GUEST_CANDIDATE_LIST_ARTIFACT,
    RETRIEVAL_ACTION_TYPE,
    materialize_retrieval_action,
)


WORKFLOW_ID = "guest_booking_outreach"


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )


def _planner_lookup(**overrides):
    data = {
        "search_topic": "AI regulation",
        "query_intent": "find guests for booking outreach",
    }
    data.update(overrides)
    return data


def test_retrieval_operation_materializes_one_typed_lookup_action():
    result = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=_planner_lookup(),
        root=ROOT,
    )
    assert result.materialized is True
    assert result.action is not None
    assert result.action["action_type"] == RETRIEVAL_ACTION_TYPE
    assert result.action["workflow_id"] == WORKFLOW_ID
    assert result.action["step_id"] == "guest_retrieval"
    assert result.action["semantic_operation"] == "guest_retrieval"
    assert result.action["lookup_request"]["lookup_type"] == (
        "bounded_entity_search"
    )
    assert result.action["lookup_request"]["entity_type"] == "guest"
    assert result.action["lookup_request"]["search_topic"] == (
        "AI regulation"
    )


def test_action_references_alexis_guest_db_binding_without_source_logic():
    action = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=_planner_lookup(),
        root=ROOT,
    ).action
    assert action is not None
    assert action["source_binding"] == {
        "resource_binding_id": "alexis_guest_db",
        "source_scope": "alexis_guest_canonical_csv",
        "governance_ref": (
            "agents/alexis/governance/lookup_capabilities.json#bounded_guest_search"
        ),
        "execution_policy_ref": (
            "agents/alexis/policies/lookup_execution.json#bounded_guest_search"
        ),
    }
    assert "datasource_path" not in repr(action)
    assert "GUESTS_CANONICAL.csv" not in repr(action)


def test_max_results_is_enforced_at_five():
    action = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=_planner_lookup(max_results=50),
        root=ROOT,
    ).action
    assert action is not None
    assert action["lookup_request"]["max_results"] == 5


def test_audit_only_governance_materializes_but_does_not_execute():
    result = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=_planner_lookup(),
        root=ROOT,
    )
    assert result.materialized is True
    assert result.execution_allowed is False
    assert result.action is not None
    assert result.action["governance_state"] == "audit_only"
    assert result.action["execution_allowed"] is False
    assert result.audit_summary["retrieval_executed"] is False


def test_disabled_retrieval_governance_fails_closed():
    workflow = _workflow()
    disabled_steps = tuple(
        replace(step, governance_state="disabled")
        if step.step_id == "guest_retrieval"
        else step
        for step in workflow.steps
    )
    disabled_workflow = replace(workflow, steps=disabled_steps)
    result = materialize_retrieval_action(
        workflow=disabled_workflow,
        planner_lookup=_planner_lookup(),
        root=ROOT,
    )
    assert result.materialized is False
    assert result.action is None
    assert result.output_artifact is None
    assert result.skipped_reasons == ("retrieval_step_disabled",)


def test_output_shape_is_typed_guest_candidate_list_not_prose():
    result = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=_planner_lookup(),
        root=ROOT,
    )
    artifact = result.output_artifact
    assert artifact is not None
    assert artifact["artifact_type"] == GUEST_CANDIDATE_LIST_ARTIFACT
    assert artifact["candidate_count"] == 0
    assert artifact["max_results"] == 5
    assert artifact["candidates"] == []
    assert artifact["provenance"]["retrieval_executed"] is False
    assert isinstance(artifact, dict)
    assert not isinstance(artifact, str)


def test_no_delivery_draft_or_ranking_materialized():
    result = materialize_retrieval_action(
        workflow=_workflow(),
        planner_lookup=_planner_lookup(),
        root=ROOT,
    )
    assert result.action is not None
    assert result.action["action_type"] != "send_email"
    assert result.output_artifact is not None
    assert result.output_artifact["artifact_type"] != "email_draft"
    assert result.action["step_id"] == "guest_retrieval"


def main():
    test_retrieval_operation_materializes_one_typed_lookup_action()
    test_action_references_alexis_guest_db_binding_without_source_logic()
    test_max_results_is_enforced_at_five()
    test_audit_only_governance_materializes_but_does_not_execute()
    test_disabled_retrieval_governance_fails_closed()
    test_output_shape_is_typed_guest_candidate_list_not_prose()
    test_no_delivery_draft_or_ranking_materialized()
    print("PASS guest booking retrieval action")


if __name__ == "__main__":
    main()
