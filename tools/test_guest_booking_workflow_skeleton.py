import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import (
    build_dry_run_workflow_plan,
    resolve_workflow_declaration,
)


WORKFLOW_ID = "guest_booking_outreach"


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )


def test_workflow_can_be_loaded_and_resolved():
    workflow = _workflow()
    assert workflow.workflow_id == WORKFLOW_ID
    assert workflow.owning_agent == "alexis"
    assert workflow.workflow_type == "semantic_workflow_skeleton"
    assert workflow.planner_authority_required is True


def test_workflow_declares_ordered_semantic_operations():
    workflow = _workflow()
    operations = [step.semantic_operation for step in workflow.steps]
    assert operations == [
        "guest_retrieval",
        "rank_guest_candidates",
        "draft_guest_outreach",
        "structured_action_generation",
        "approval_required_handoff",
        "future_delivery_placeholder",
    ]


def test_retrieval_step_is_bounded_and_governed():
    retrieval = _workflow().steps[0]
    assert retrieval.step_id == "guest_retrieval"
    assert retrieval.step_kind == "retrieval"
    assert retrieval.capability == "discover_entities"
    assert retrieval.bounded is True
    assert retrieval.governance_state == "audit_only"
    assert retrieval.constraints["lookup_type"] == "bounded_entity_search"
    assert retrieval.constraints["max_results"] == 5
    assert "governance_ref" in retrieval.constraints


def test_outreach_draft_is_typed_artifact_output():
    draft = _workflow().steps[2]
    assert draft.step_id == "outreach_draft_generation"
    assert draft.semantic_operation == "draft_guest_outreach"
    assert draft.operation_kind == "draft_artifact"
    assert draft.output_type == "artifact"
    assert draft.produces_artifact_type == "email_draft"
    assert draft.requires_approval is True
    assert draft.input_refs == (
        "artifact:ranked_guest_candidate_list:rank_guest_candidates",
    )
    assert draft.output_ref == "artifact:email_draft:draft_guest_outreach"
    assert draft.constraints["input_artifact_type"] == (
        "ranked_guest_candidate_list"
    )
    assert draft.constraints["output_artifact_type"] == "email_draft"
    assert draft.constraints["must_use_typed_artifact"] is True
    assert draft.constraints["declaration_only"] is True
    assert draft.constraints["draft_generation_allowed"] is False
    assert draft.constraints["delivery_performed"] is False


def test_ranking_step_is_deterministic_typed_artifact_boundary():
    ranking = _workflow().steps[1]
    assert ranking.semantic_operation == "rank_guest_candidates"
    assert ranking.operation_kind == "rank_candidates"
    assert ranking.output_type == "artifact"
    assert ranking.produces_artifact_type == "ranked_guest_candidate_list"
    assert ranking.input_refs == ("artifact:guest_candidate_list:guest_retrieval",)
    assert ranking.output_ref == "artifact:ranked_guest_candidate_list:rank_guest_candidates"
    assert ranking.constraints["input_artifact_type"] == "guest_candidate_list"
    assert ranking.constraints["output_artifact_type"] == "ranked_guest_candidate_list"
    assert ranking.constraints["signals_declarative_metadata_only"] is True
    assert ranking.constraints["ranking_execution_allowed"] is True
    assert ranking.constraints["ranking_logic_implemented"] is True
    assert ranking.constraints["scoring_implemented"] is True
    assert ranking.constraints["ranking_policy"]["policy_id"] == (
        "deterministic_guest_enrichment_score_v1"
    )
    assert ranking.constraints["ranking_policy"]["external_calls_allowed"] is False


def test_delivery_placeholder_is_blocked_and_approval_required():
    delivery = _workflow().steps[-1]
    assert delivery.step_id == "future_delivery_placeholder"
    assert delivery.step_kind == "delivery_placeholder"
    assert delivery.action_type == "send_email"
    assert delivery.requires_approval is True
    assert delivery.governance_state == "disabled"
    assert delivery.delivery_performed is False
    assert delivery.placeholder is True
    assert delivery.constraints["real_email_sending"] is False


def test_dry_run_plan_does_not_execute_or_deliver():
    plan = build_dry_run_workflow_plan(_workflow())
    summary = plan.to_summary()
    assert plan.execution_performed is False
    assert summary["execution_mode"] == "declaration_only"
    assert summary["step_count"] == 6


def main():
    test_workflow_can_be_loaded_and_resolved()
    test_workflow_declares_ordered_semantic_operations()
    test_retrieval_step_is_bounded_and_governed()
    test_outreach_draft_is_typed_artifact_output()
    test_ranking_step_is_deterministic_typed_artifact_boundary()
    test_delivery_placeholder_is_blocked_and_approval_required()
    test_dry_run_plan_does_not_execute_or_deliver()
    print("PASS guest booking workflow skeleton")


if __name__ == "__main__":
    main()
