import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.workflows.declarations import resolve_workflow_declaration  # noqa: E402
from runtime.workflows.instances import (  # noqa: E402
    APPROVAL_STATE_PENDING,
    STATUS_SUSPENDED,
    get_workflow_instance_by_continuation_id,
    load_workflow_transition_audit_records,
    list_workflow_instances,
    persist_suspended_workflow_instance,
    workflow_transition_audit_path_for_store,
)
from runtime.workflows.suspension import (  # noqa: E402
    materialize_workflow_suspension_action,
)


WORKFLOW_ID = "guest_booking_outreach"
CREATED_AT = datetime(2026, 5, 19, tzinfo=timezone.utc)


def _suspension_state():
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=ROOT,
    )
    result = materialize_workflow_suspension_action(
        workflow=workflow,
        artifact_refs=("artifact:email_draft:abc123",),
        action_refs=("action:send_email:def456",),
        step_id="future_delivery_placeholder",
        created_at=CREATED_AT,
    )
    assert result.suspension_state is not None
    return result.suspension_state


def test_suspended_workflow_instance_persists_and_loads_by_continuation_id():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "suspended_workflows.json"
        state = _suspension_state()
        persisted = persist_suspended_workflow_instance(
            state,
            store_path=store_path,
            updated_at=CREATED_AT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            state.continuation_id,
            store_path=store_path,
        )

    assert persisted is not None
    assert loaded is not None
    assert loaded["workflow_id"] == WORKFLOW_ID
    assert loaded["workflow_instance_id"].startswith("wfi_")
    assert loaded["continuation_id"] == state.continuation_id


def test_suspended_status_and_pending_approval_survive_round_trip():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "suspended_workflows.json"
        state = _suspension_state()
        persist_suspended_workflow_instance(
            state,
            store_path=store_path,
            updated_at=CREATED_AT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            state.continuation_id,
            store_path=store_path,
        )

    assert loaded["status"] == STATUS_SUSPENDED
    assert loaded["approval_state"] == APPROVAL_STATE_PENDING
    assert loaded["created_at"] == "2026-05-19T00:00:00+00:00"
    assert loaded["updated_at"] == "2026-05-19T00:00:00+00:00"


def test_suspended_instance_records_initial_state_lineage_and_audit():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "suspended_workflows.json"
        audit_path = workflow_transition_audit_path_for_store(store_path)
        state = _suspension_state()
        persisted = persist_suspended_workflow_instance(
            state,
            store_path=store_path,
            updated_at=CREATED_AT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            state.continuation_id,
            store_path=store_path,
        )
        audit_records = load_workflow_transition_audit_records(audit_path)

    assert persisted is not None
    assert loaded is not None
    lineage = loaded["state_lineage"]
    assert len(lineage) == 1
    assert len(audit_records) == 1
    assert lineage[0] == audit_records[0]
    assert lineage[0]["transition_type"] == "instance_suspended"
    assert lineage[0]["from_status"] is None
    assert lineage[0]["to_status"] == STATUS_SUSPENDED
    assert lineage[0]["transition_sequence"] == 1
    assert lineage[0]["previous_lineage_record_id"] is None
    assert lineage[0]["execution_performed"] is False


def test_artifact_and_action_refs_survive_round_trip():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "suspended_workflows.json"
        state = _suspension_state()
        persist_suspended_workflow_instance(
            state,
            store_path=store_path,
            updated_at=CREATED_AT,
        )
        loaded = get_workflow_instance_by_continuation_id(
            state.continuation_id,
            store_path=store_path,
        )

    assert loaded["artifact_refs"] == ["artifact:email_draft:abc123"]
    assert loaded["action_refs"] == ["action:send_email:def456"]
    assert "Hi " not in repr(loaded)
    assert "Subject:" not in repr(loaded)
    assert "draft_text" not in repr(loaded)
    assert "body" not in repr(loaded).lower()


def test_missing_and_malformed_loads_fail_safely():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "missing.json"
        assert list_workflow_instances(store_path=store_path) == []
        assert (
            get_workflow_instance_by_continuation_id(
                "missing",
                store_path=store_path,
            )
            is None
        )

        store_path.write_text("{not-json", encoding="utf-8")
        assert list_workflow_instances(store_path=store_path) == []

        store_path.write_text(
            json.dumps({"version": 1, "instances": [{"workflow_id": "x"}]}),
            encoding="utf-8",
        )
        assert list_workflow_instances(store_path=store_path) == []


def test_instance_persistence_is_domain_and_transport_neutral():
    source = (ROOT / "runtime" / "workflows" / "instances.py").read_text(
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
        "resume_execution",
        "execute_delivery",
    )
    assert all(term not in lowered for term in forbidden)


def test_no_delivery_or_resume_execution_occurs():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "suspended_workflows.json"
        state = _suspension_state()
        persisted = persist_suspended_workflow_instance(
            state,
            store_path=store_path,
            updated_at=CREATED_AT,
        )

    assert persisted is not None
    assert persisted["status"] == STATUS_SUSPENDED
    assert persisted["approval_state"] == APPROVAL_STATE_PENDING
    assert persisted["provenance"]["delivery_performed"] is False
    assert "resume" not in persisted
    assert "delivery_result" not in persisted


def main():
    test_suspended_workflow_instance_persists_and_loads_by_continuation_id()
    test_suspended_status_and_pending_approval_survive_round_trip()
    test_suspended_instance_records_initial_state_lineage_and_audit()
    test_artifact_and_action_refs_survive_round_trip()
    test_missing_and_malformed_loads_fail_safely()
    test_instance_persistence_is_domain_and_transport_neutral()
    test_no_delivery_or_resume_execution_occurs()
    print("PASS guest booking workflow instance persistence")


if __name__ == "__main__":
    main()
