import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.approval import (  # noqa: E402
    DECISION_APPROVE,
    DECISION_DENY,
    process_workflow_approval_event,
)
from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.instances import (  # noqa: E402
    APPROVAL_STATE_APPROVED,
    APPROVAL_STATE_DENIED,
    APPROVAL_STATE_PENDING,
    STATUS_APPROVED_PENDING_RESUME,
    STATUS_SUSPENDED,
    STATUS_TERMINATED_DENIED,
    get_workflow_instance_by_continuation_id,
    load_workflow_transition_audit_records,
    persist_suspended_workflow_instance,
    workflow_transition_audit_path_for_store,
)
from runtime.workflows.suspension import (  # noqa: E402
    materialize_workflow_suspension_action,
)


WORKFLOW_ID = "guest_booking_outreach"
CREATED_AT = datetime(2026, 5, 19, tzinfo=timezone.utc)
DECIDED_AT = datetime(2026, 5, 19, 2, tzinfo=timezone.utc)


def _persisted_instance(store_path: Path):
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )
    materialized = materialize_workflow_suspension_action(
        workflow=workflow,
        artifact_refs=("artifact:email_draft:abc123",),
        action_refs=("action:send_email:def456",),
        step_id="approval_required_handoff",
        created_at=CREATED_AT,
    )
    assert materialized.suspension_state is not None
    instance = persist_suspended_workflow_instance(
        materialized.suspension_state,
        store_path=store_path,
        updated_at=CREATED_AT,
    )
    assert instance is not None
    assert instance["status"] == STATUS_SUSPENDED
    assert instance["approval_state"] == APPROVAL_STATE_PENDING
    return instance


def test_approve_event_updates_workflow_instance():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            reason="approved for next stage",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    assert receipt.decided is True
    assert receipt.decision == DECISION_APPROVE
    assert receipt.previous_state["status"] == STATUS_SUSPENDED
    assert receipt.new_state["status"] == STATUS_APPROVED_PENDING_RESUME
    assert loaded["status"] == STATUS_APPROVED_PENDING_RESUME
    assert loaded["approval_state"] == APPROVAL_STATE_APPROVED
    assert loaded["suspended"] is True


def test_deny_event_updates_workflow_instance():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = process_workflow_approval_event(
            workflow_instance_id=instance["workflow_instance_id"],
            decision=DECISION_DENY,
            decided_by="operator:test",
            reason="not appropriate",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    assert receipt.decided is True
    assert receipt.decision == DECISION_DENY
    assert loaded["status"] == STATUS_TERMINATED_DENIED
    assert loaded["approval_state"] == APPROVAL_STATE_DENIED
    assert loaded["suspended"] is False


def test_invalid_continuation_id_fails_safely():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        receipt = process_workflow_approval_event(
            continuation_id="missing",
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            store_path=store_path,
            root=ROOT,
        )

    assert receipt.decided is False
    assert receipt.skipped_reasons == ("workflow_instance_not_found",)
    assert receipt.execution_performed is False


def test_already_decided_workflows_cannot_be_redecided():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        first = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )
        second = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_DENY,
            decided_by="operator:test",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )

    assert first.decided is True
    assert second.decided is False
    assert second.skipped_reasons == ("approval_already_decided",)


def test_governance_restrictions_block_approval_processing():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            approval_governance_state="disabled",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    assert receipt.decided is False
    assert receipt.skipped_reasons == ("approval_governance_disabled",)
    assert loaded["approval_state"] == APPROVAL_STATE_PENDING
    assert loaded["status"] == STATUS_SUSPENDED


def test_audit_safe_receipt_metadata_is_persisted():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            reason="safe operator reason",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    audit_record = receipt.to_audit_record()
    persisted = loaded["provenance"]["approval"]
    assert audit_record["continuation_id"] == instance["continuation_id"]
    assert audit_record["decision"] == DECISION_APPROVE
    assert audit_record["decided_by"] == "operator:test"
    assert audit_record["decided_at"] == "2026-05-19T02:00:00+00:00"
    assert audit_record["reason"] == "safe operator reason"
    assert persisted["decision"] == DECISION_APPROVE
    assert persisted["execution_performed"] is False
    assert persisted["delivery_performed"] is False
    assert "Hi " not in repr(audit_record)
    assert "Subject:" not in repr(audit_record)
    assert "draft_text" not in repr(audit_record)
    assert "body" not in repr(audit_record).lower()


def test_approval_appends_state_lineage_and_transition_audit_record():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        audit_path = workflow_transition_audit_path_for_store(store_path)
        instance = _persisted_instance(store_path)
        process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )
        audit_records = load_workflow_transition_audit_records(audit_path)

    lineage = loaded["state_lineage"]
    assert len(lineage) == 2
    assert len(audit_records) == 2
    assert audit_records == tuple(lineage)
    assert lineage[0]["transition_type"] == "instance_suspended"
    assert lineage[1]["transition_type"] == "approval_decision"
    assert lineage[1]["transition_sequence"] == 2
    assert lineage[1]["previous_lineage_record_id"] == lineage[0]["lineage_record_id"]
    assert lineage[1]["from_status"] == STATUS_SUSPENDED
    assert lineage[1]["to_status"] == STATUS_APPROVED_PENDING_RESUME
    assert lineage[1]["from_approval_state"] == APPROVAL_STATE_PENDING
    assert lineage[1]["to_approval_state"] == APPROVAL_STATE_APPROVED


def test_no_continuation_execution_occurs_automatically():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_APPROVE,
            decided_by="operator:test",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=ROOT,
        )

    assert receipt.execution_performed is False
    assert receipt.new_state["status"] == STATUS_APPROVED_PENDING_RESUME
    assert "remaining_actions" not in receipt.to_audit_record()
    assert "resumed" not in receipt.to_audit_record()


def test_runtime_approval_intake_is_domain_and_transport_neutral():
    source = (ROOT / "runtime" / "workflows" / "approval.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "agents.alexis",
        "telegram",
        "gateway",
        "send_email(",
        "smtp",
        "mailgun",
        "ui",
        "draft generation",
        "guest ranking",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_approve_event_updates_workflow_instance()
    test_deny_event_updates_workflow_instance()
    test_invalid_continuation_id_fails_safely()
    test_already_decided_workflows_cannot_be_redecided()
    test_governance_restrictions_block_approval_processing()
    test_audit_safe_receipt_metadata_is_persisted()
    test_approval_appends_state_lineage_and_transition_audit_record()
    test_no_continuation_execution_occurs_automatically()
    test_runtime_approval_intake_is_domain_and_transport_neutral()
    print("PASS guest booking workflow approval")


if __name__ == "__main__":
    main()
