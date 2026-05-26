import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.continuation import (  # noqa: E402
    APPROVAL_STATE_APPROVED,
    resume_workflow_continuation,
)
from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.instances import (  # noqa: E402
    APPROVAL_STATE_PENDING,
    STATUS_RESUMED_PENDING_EXECUTION,
    STATUS_SUSPENDED,
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
RESUMED_AT = datetime(2026, 5, 19, 1, tzinfo=timezone.utc)


def _persisted_instance(store_path: Path, *, step_id: str = "approval_required_handoff"):
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )
    materialized = materialize_workflow_suspension_action(
        workflow=workflow,
        artifact_refs=("artifact:email_draft:abc123",),
        action_refs=("action:send_email:def456",),
        step_id=step_id,
        created_at=CREATED_AT,
    )
    assert materialized.suspension_state is not None
    instance = persist_suspended_workflow_instance(
        materialized.suspension_state,
        store_path=store_path,
        updated_at=CREATED_AT,
    )
    assert instance is not None
    return instance


def test_continuation_id_loads_suspended_workflow_instance():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    assert loaded is not None
    assert loaded["status"] == STATUS_SUSPENDED
    assert loaded["approval_state"] == APPROVAL_STATE_PENDING


def test_valid_approval_state_allows_resume_transition():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    assert receipt.resumed is True
    assert receipt.previous_status == STATUS_SUSPENDED
    assert receipt.new_status == STATUS_RESUMED_PENDING_EXECUTION
    assert receipt.resumed_by == "operator:test"
    assert receipt.resumed_at == "2026-05-19T01:00:00+00:00"
    assert loaded["status"] == STATUS_RESUMED_PENDING_EXECUTION
    assert loaded["approval_state"] == APPROVAL_STATE_APPROVED
    assert loaded["suspended"] is False


def test_invalid_continuation_id_fails_safely():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        receipt = resume_workflow_continuation(
            continuation_id="missing",
            approved=True,
            resumed_by="operator:test",
            store_path=store_path,
            root=ROOT,
        )

    assert receipt.resumed is False
    assert receipt.skipped_reasons == ("workflow_instance_not_found",)
    assert receipt.execution_performed is False


def test_already_resumed_workflow_cannot_resume_twice():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        first = resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )
        second = resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )

    assert first.resumed is True
    assert second.resumed is False
    assert second.skipped_reasons == ("workflow_not_suspended",)


def test_governance_restrictions_block_continuation():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            continuation_governance_state="disabled",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )

    assert receipt.resumed is False
    assert receipt.skipped_reasons == ("continuation_governance_disabled",)
    assert receipt.execution_performed is False


def test_resumed_workflow_exposes_remaining_actions_only():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )

    assert receipt.resumed is True
    assert len(receipt.remaining_actions) == 1
    action = receipt.remaining_actions[0]
    assert action["step_id"] == "future_delivery_placeholder"
    assert action["action_type"] == "send_email"
    assert action["execution_performed"] is False
    assert action["delivery_performed"] is False
    assert action["governance_state"] == "disabled"


def test_delivery_send_email_actions_are_not_executed():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        instance = _persisted_instance(store_path)
        receipt = resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )

    assert receipt.execution_performed is False
    assert receipt.provenance["delivery_performed"] is False
    assert all(
        action["execution_performed"] is False
        for action in receipt.remaining_actions
    )


def test_continuation_appends_lineage_without_rewriting_prior_audit_records():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        audit_path = workflow_transition_audit_path_for_store(store_path)
        instance = _persisted_instance(store_path)
        before_records = load_workflow_transition_audit_records(audit_path)
        resume_workflow_continuation(
            continuation_id=instance["continuation_id"],
            approved=True,
            resumed_by="operator:test",
            resumed_at=RESUMED_AT,
            store_path=store_path,
            root=ROOT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )
        after_records = load_workflow_transition_audit_records(audit_path)

    lineage = loaded["state_lineage"]
    assert len(before_records) == 1
    assert len(after_records) == 2
    assert after_records[0] == before_records[0]
    assert after_records == tuple(lineage)
    assert lineage[1]["transition_type"] == "continuation_resumed"
    assert lineage[1]["previous_lineage_record_id"] == lineage[0]["lineage_record_id"]
    assert lineage[1]["from_status"] == STATUS_SUSPENDED
    assert lineage[1]["to_status"] == STATUS_RESUMED_PENDING_EXECUTION
    assert lineage[1]["from_suspended"] is True
    assert lineage[1]["to_suspended"] is False


def test_runtime_continuation_code_remains_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "continuation.py").read_text(
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
        "draft generation",
        "guest ranking",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_continuation_id_loads_suspended_workflow_instance()
    test_valid_approval_state_allows_resume_transition()
    test_invalid_continuation_id_fails_safely()
    test_already_resumed_workflow_cannot_resume_twice()
    test_governance_restrictions_block_continuation()
    test_resumed_workflow_exposes_remaining_actions_only()
    test_delivery_send_email_actions_are_not_executed()
    test_continuation_appends_lineage_without_rewriting_prior_audit_records()
    test_runtime_continuation_code_remains_domain_neutral()
    print("PASS guest booking workflow continuation")


if __name__ == "__main__":
    main()
