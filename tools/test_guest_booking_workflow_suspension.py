import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.suspension import (  # noqa: E402
    APPROVAL_STATE_PENDING,
    SUSPENSION_ACTION_TYPE,
    materialize_workflow_suspension_action,
)


WORKFLOW_ID = "guest_booking_outreach"


def _workflow():
    return resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )


def _materialized():
    return materialize_workflow_suspension_action(
        workflow=_workflow(),
        artifact_refs=("artifact:email_draft:abc123",),
        action_refs=("action:send_email:def456",),
        step_id="future_delivery_placeholder",
        created_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


def test_delivery_placeholder_materializes_to_suspension_action():
    result = _materialized()
    assert result.materialized is True
    assert result.action is not None
    assert result.action["action_type"] == SUSPENSION_ACTION_TYPE
    assert result.action["workflow_id"] == WORKFLOW_ID
    assert result.action["step_id"] == "future_delivery_placeholder"
    assert result.action["operation_id"] == "future_delivery_placeholder"


def test_action_requires_approval_and_does_not_deliver():
    action = _materialized().action
    assert action["requires_approval"] is True
    assert action["approval_state"] == APPROVAL_STATE_PENDING
    assert action["delivery_performed"] is False
    assert action["suspended"] is True


def test_workflow_state_is_suspended_with_continuation_id():
    state = _materialized().suspension_state
    assert state is not None
    assert state.suspended is True
    assert state.approval_state == APPROVAL_STATE_PENDING
    assert state.continuation_id
    assert state.to_record()["continuation_id"] == state.continuation_id
    assert state.created_at == "2026-05-19T00:00:00+00:00"


def test_action_references_artifacts_and_actions_without_raw_draft_text():
    action = _materialized().action
    rendered = repr(action)
    assert action["artifact_refs"] == ["artifact:email_draft:abc123"]
    assert action["action_refs"] == ["action:send_email:def456"]
    assert "Hi " not in rendered
    assert "Subject:" not in rendered
    assert "draft_text" not in rendered
    assert "body" not in rendered.lower()


def test_provenance_is_audit_safe():
    provenance = _materialized().action["provenance"]
    assert provenance["workflow_id"] == WORKFLOW_ID
    assert provenance["operation_id"] == "future_delivery_placeholder"
    assert provenance["action_type"] == SUSPENSION_ACTION_TYPE
    assert provenance["requires_approval"] is True
    assert provenance["approval_state"] == APPROVAL_STATE_PENDING
    assert provenance["suspended"] is True
    assert provenance["delivery_performed"] is False
    assert provenance["continuation_id"]
    assert provenance["created_at"] == "2026-05-19T00:00:00+00:00"


def test_no_transport_or_delivery_imports_in_runtime_suspension_code():
    source = (ROOT / "runtime" / "workflows" / "suspension.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "telegram",
        "gateway",
        "send_email(",
        "smtp",
        "mailgun",
    )
    lowered = source.lower()
    assert all(term not in lowered for term in forbidden)


def test_no_email_delivery_execution_path_is_called():
    action = _materialized().action
    assert action["action_type"] == SUSPENSION_ACTION_TYPE
    assert action["delivery_performed"] is False
    assert action["approval_state"] == APPROVAL_STATE_PENDING
    assert "send_email" in action["action_refs"][0]


def main():
    test_delivery_placeholder_materializes_to_suspension_action()
    test_action_requires_approval_and_does_not_deliver()
    test_workflow_state_is_suspended_with_continuation_id()
    test_action_references_artifacts_and_actions_without_raw_draft_text()
    test_provenance_is_audit_safe()
    test_no_transport_or_delivery_imports_in_runtime_suspension_code()
    test_no_email_delivery_execution_path_is_called()
    print("PASS guest booking workflow suspension")


if __name__ == "__main__":
    main()
