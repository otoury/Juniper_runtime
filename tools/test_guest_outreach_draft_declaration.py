import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import (  # noqa: E402
    build_dry_run_workflow_plan,
    resolve_workflow_declaration,
)


WORKFLOW_PATH = (
    ROOT / "agents" / "alexis" / "workflows" / "guest_booking_outreach.json"
)


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id="guest_booking_outreach",
        root=ROOT,
    )


def _draft_step():
    for step in _workflow().steps:
        if step.semantic_operation == "draft_guest_outreach":
            return step
    raise AssertionError("missing draft_guest_outreach operation")


def _raw_draft_step():
    data = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for step in data["steps"]:
        if step.get("operation_id") == "draft_guest_outreach":
            return step
    raise AssertionError("missing raw draft_guest_outreach operation")


def test_draft_guest_outreach_declaration_loads():
    step = _draft_step()
    assert step.step_kind == "artifact_generation"
    assert step.operation_kind == "draft_artifact"
    assert step.semantic_operation == "draft_guest_outreach"
    assert step.capability == "draft_email"
    assert step.governance_state == "enabled"


def test_declares_expected_operation_id_and_kind():
    raw = _raw_draft_step()
    assert raw["operation_id"] == "draft_guest_outreach"
    assert raw["operation_kind"] == "draft_artifact"
    assert raw["semantic_operation"] == "draft_guest_outreach"


def test_input_refs_are_typed_ranked_guest_candidate_refs():
    step = _draft_step()
    assert step.input_refs == (
        "artifact:ranked_guest_candidate_list:rank_guest_candidates",
    )
    assert step.constraints["input_artifact_type"] == (
        "ranked_guest_candidate_list"
    )
    assert step.constraints["selected_candidate_refs_allowed"] is True


def test_output_artifact_type_is_email_draft():
    step = _draft_step()
    assert step.output_type == "artifact"
    assert step.produces_artifact_type == "email_draft"
    assert step.output_ref == "artifact:email_draft:draft_guest_outreach"
    assert step.constraints["output_artifact_type"] == "email_draft"


def test_approval_requirement_is_represented():
    step = _draft_step()
    assert step.requires_approval is True
    assert step.constraints["requires_later_approval"] is True


def test_no_draft_generation_or_delivery_occurs():
    step = _draft_step()
    plan = build_dry_run_workflow_plan(_workflow())
    assert plan.execution_performed is False
    assert step.constraints["declaration_only"] is True
    assert step.constraints["draft_generation_allowed"] is False
    assert step.constraints["draft_content_materialized"] is False
    assert step.constraints["delivery_performed"] is False
    assert step.constraints["send_email_execution_allowed"] is False
    rendered = repr(step).lower()
    assert "subject:" not in rendered
    assert "hi " not in rendered
    assert "body" not in rendered
    assert "draft_text" not in rendered


def test_runtime_parser_stays_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "declarations.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "alexis_guest_db",
        "draft_guest_outreach",
        "ranked_guest_candidate_list",
        "guest_candidate_list",
        "email_draft",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_draft_guest_outreach_declaration_loads()
    test_declares_expected_operation_id_and_kind()
    test_input_refs_are_typed_ranked_guest_candidate_refs()
    test_output_artifact_type_is_email_draft()
    test_approval_requirement_is_represented()
    test_no_draft_generation_or_delivery_occurs()
    test_runtime_parser_stays_domain_neutral()
    print("PASS guest outreach draft declaration")


if __name__ == "__main__":
    main()
