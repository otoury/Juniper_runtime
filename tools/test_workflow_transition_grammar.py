import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import (  # noqa: E402
    resolve_workflow_declaration,
    workflow_declaration_from_dict,
)
from runtime.workflows.transitions import (  # noqa: E402
    TERMINAL_OPERATION_ID,
    resolve_workflow_transition,
)


WORKFLOW_ID = "transition_fixture"


def _transition_workflow():
    return workflow_declaration_from_dict(
        {
            "workflow_id": WORKFLOW_ID,
            "workflow_type": "semantic_workflow_skeleton",
            "owning_agent": "neutral_agent",
            "description": "Transition grammar fixture.",
            "governance_state": "enabled",
            "planner_authority_required": True,
            "steps": [
                {
                    "step_id": "collect",
                    "step_kind": "retrieval",
                    "semantic_operation": "collect",
                    "capability": "discover_entities",
                    "output_type": "lookup_result_set",
                    "requires_approval": False,
                    "bounded": True,
                    "governance_state": "audit_only",
                    "constraints": {},
                    "on_success": "notify_operator",
                    "on_failure": "wait_for_operator",
                    "on_inadequate": "fallback_collect",
                },
                {
                    "step_id": "notify_operator",
                    "step_kind": "action_generation",
                    "operation_kind": "notify_and_continue",
                    "semantic_operation": "notify_operator",
                    "capability": "notify_operator",
                    "output_type": "typed_action",
                    "action_type": "notify_operator",
                    "requires_approval": False,
                    "bounded": True,
                    "governance_state": "enabled",
                    "constraints": {},
                    "on_success": TERMINAL_OPERATION_ID,
                },
                {
                    "step_id": "wait_for_operator",
                    "step_kind": "approval_handoff",
                    "operation_kind": "wait_for_approval",
                    "semantic_operation": "wait_for_operator",
                    "capability": "operator_approval",
                    "output_type": "approval_request",
                    "action_type": "operator_approval",
                    "requires_approval": True,
                    "bounded": True,
                    "governance_state": "enabled",
                    "constraints": {},
                    "on_success": TERMINAL_OPERATION_ID,
                },
                {
                    "step_id": "fallback_collect",
                    "step_kind": "retrieval",
                    "semantic_operation": "fallback_collect",
                    "capability": "discover_entities",
                    "output_type": "lookup_result_set",
                    "requires_approval": False,
                    "bounded": True,
                    "governance_state": "audit_only",
                    "constraints": {},
                },
            ],
            "non_goals": [
                "no web execution",
                "no ranking execution",
                "no draft generation",
                "no delivery execution",
            ],
        }
    )


def test_existing_guest_booking_outreach_workflow_still_loads():
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="guest_booking_outreach",
        root=ROOT,
    )
    assert workflow.workflow_id == "guest_booking_outreach"
    assert [step.semantic_operation for step in workflow.steps] == [
        "guest_retrieval",
        "rank_guest_candidates",
        "draft_guest_outreach",
        "structured_action_generation",
        "approval_required_handoff",
        "future_delivery_placeholder",
    ]


def test_transition_fields_validate_on_workflow_declaration():
    workflow = _transition_workflow()
    collect = workflow.steps[0]
    assert collect.on_success == "notify_operator"
    assert collect.on_failure == "wait_for_operator"
    assert collect.on_inadequate == "fallback_collect"


def test_transition_resolver_returns_next_operation_for_success():
    resolution = resolve_workflow_transition(
        workflow=_transition_workflow(),
        current_operation_id="collect",
        result_status="success",
    )
    assert resolution.resolved is True
    assert resolution.next_operation_id == "notify_operator"
    assert resolution.terminal is False


def test_transition_resolver_returns_next_operation_for_failure():
    resolution = resolve_workflow_transition(
        workflow=_transition_workflow(),
        current_operation_id="collect",
        result_status="failed",
    )
    assert resolution.resolved is True
    assert resolution.next_operation_id == "wait_for_operator"
    assert resolution.blocking is True
    assert resolution.suspending is True


def test_transition_resolver_returns_next_operation_for_inadequate():
    resolution = resolve_workflow_transition(
        workflow=_transition_workflow(),
        current_operation_id="collect",
        result_status="inadequate",
    )
    assert resolution.resolved is True
    assert resolution.next_operation_id == "fallback_collect"


def test_missing_transition_fails_safely():
    resolution = resolve_workflow_transition(
        workflow=_transition_workflow(),
        current_operation_id="fallback_collect",
        result_status="success",
    )
    assert resolution.resolved is False
    assert resolution.next_operation_id is None
    assert resolution.skipped_reasons == ("transition_not_declared",)
    assert resolution.audit_summary["execution_performed"] is False


def test_explicit_terminal_transition_terminates_cleanly():
    resolution = resolve_workflow_transition(
        workflow=_transition_workflow(),
        current_operation_id="notify_operator",
        result_status="success",
    )
    assert resolution.resolved is True
    assert resolution.terminal is True
    assert resolution.next_operation_id is None


def test_notify_and_continue_operation_is_non_blocking():
    notify = _transition_workflow().steps[1]
    assert notify.operation_kind == "notify_and_continue"
    assert notify.blocking is False
    assert notify.suspending is False


def test_wait_for_approval_operation_is_blocking_and_suspending():
    wait = _transition_workflow().steps[2]
    assert wait.operation_kind == "wait_for_approval"
    assert wait.blocking is True
    assert wait.suspending is True


def test_runtime_transition_code_remains_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "transitions.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "newsroom",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "web_search",
        "ranking",
        "draft generation",
        "send_email(",
    )
    assert all(term not in lowered for term in forbidden)


def test_no_web_ranking_draft_or_delivery_execution_occurs():
    resolution = resolve_workflow_transition(
        workflow=_transition_workflow(),
        current_operation_id="collect",
        result_status="success",
    )
    rendered = repr(resolution.to_audit_record()).lower()
    assert resolution.resolved is True
    assert resolution.audit_summary["execution_performed"] is False
    assert "web_result" not in rendered
    assert "ranked_entity" not in rendered
    assert "email_draft" not in rendered
    assert "delivery_performed" not in rendered


def main():
    test_existing_guest_booking_outreach_workflow_still_loads()
    test_transition_fields_validate_on_workflow_declaration()
    test_transition_resolver_returns_next_operation_for_success()
    test_transition_resolver_returns_next_operation_for_failure()
    test_transition_resolver_returns_next_operation_for_inadequate()
    test_missing_transition_fails_safely()
    test_explicit_terminal_transition_terminates_cleanly()
    test_notify_and_continue_operation_is_non_blocking()
    test_wait_for_approval_operation_is_blocking_and_suspending()
    test_runtime_transition_code_remains_domain_neutral()
    test_no_web_ranking_draft_or_delivery_execution_occurs()
    print("PASS workflow transition grammar")


if __name__ == "__main__":
    main()
