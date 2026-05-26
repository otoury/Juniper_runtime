import json
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
from runtime.workflows.delivery import (  # noqa: E402
    DELIVERY_ACTION_DESCRIPTOR_TYPE,
    materialize_delivery_action,
)
from runtime.workflows.instances import (  # noqa: E402
    APPROVAL_STATE_APPROVED,
    STATUS_APPROVED_PENDING_RESUME,
    get_workflow_instance_by_continuation_id,
    persist_suspended_workflow_instance,
)
from runtime.workflows.suspension import (  # noqa: E402
    materialize_workflow_suspension_action,
)


WORKFLOW_ID = "guest_booking_outreach"
CREATED_AT = datetime(2026, 5, 19, tzinfo=timezone.utc)
DECIDED_AT = datetime(2026, 5, 19, 2, tzinfo=timezone.utc)
PREPARED_AT = datetime(2026, 5, 19, 3, tzinfo=timezone.utc)


def _write_temp_workflow(root: Path, *, delivery_governance: str = "enabled"):
    source = (
        ROOT
        / "agents"
        / "alexis"
        / "workflows"
        / "guest_booking_outreach.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    for step in payload["steps"]:
        if step["step_id"] == "future_delivery_placeholder":
            step["governance_state"] = delivery_governance
            step["constraints"]["delivery_channel"] = "declared_delivery_capability"
            step["constraints"][
                "delivery_preparation_execution_allowed"
            ] = False

    workflow_dir = root / "agents" / "alexis" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "guest_booking_outreach.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persisted_instance(store_path: Path, *, root: Path):
    workflow = resolve_workflow_declaration(
        agent_name="alexis",
        workflow_id=WORKFLOW_ID,
        root=root,
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
    return instance


def _approved_instance(store_path: Path, *, root: Path):
    instance = _persisted_instance(store_path, root=root)
    receipt = process_workflow_approval_event(
        continuation_id=instance["continuation_id"],
        decision=DECISION_APPROVE,
        decided_by="operator:test",
        decided_at=DECIDED_AT,
        store_path=store_path,
        root=root,
    )
    assert receipt.decided is True
    loaded = get_workflow_instance_by_continuation_id(
        instance["continuation_id"],
        store_path=store_path,
    )
    assert loaded["approval_state"] == APPROVAL_STATE_APPROVED
    assert loaded["status"] == STATUS_APPROVED_PENDING_RESUME
    return loaded


def test_approved_workflow_materializes_one_delivery_action_descriptor():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root, delivery_governance="enabled")
        instance = _approved_instance(store_path, root=temp_root)
        result = materialize_delivery_action(
            continuation_id=instance["continuation_id"],
            store_path=store_path,
            root=temp_root,
            prepared_at=PREPARED_AT,
        )

    assert result.materialized is True
    assert result.delivery_action is not None
    action = result.delivery_action
    assert action["descriptor_type"] == DELIVERY_ACTION_DESCRIPTOR_TYPE
    assert action["action_type"] == "send_email"
    assert action["workflow_id"] == WORKFLOW_ID
    assert action["workflow_instance_id"] == instance["workflow_instance_id"]
    assert action["continuation_id"] == instance["continuation_id"]
    assert action["delivery_capability"] == "send_email"
    assert action["delivery_channel"] == "declared_delivery_capability"
    assert action["delivery_prepared"] is True
    assert action["delivery_performed"] is False
    assert action["execution_allowed"] is False


def test_pending_approval_fails_safely():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root)
        instance = _persisted_instance(store_path, root=temp_root)
        result = materialize_delivery_action(
            continuation_id=instance["continuation_id"],
            store_path=store_path,
            root=temp_root,
        )

    assert result.materialized is False
    assert result.delivery_action is None
    assert result.skipped_reasons == ("workflow_not_approved",)
    assert result.delivery_performed is False


def test_denied_workflow_fails_safely():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root)
        instance = _persisted_instance(store_path, root=temp_root)
        receipt = process_workflow_approval_event(
            continuation_id=instance["continuation_id"],
            decision=DECISION_DENY,
            decided_by="operator:test",
            decided_at=DECIDED_AT,
            store_path=store_path,
            root=temp_root,
        )
        result = materialize_delivery_action(
            continuation_id=instance["continuation_id"],
            store_path=store_path,
            root=temp_root,
        )

    assert receipt.decided is True
    assert result.materialized is False
    assert result.delivery_action is None
    assert result.skipped_reasons == ("workflow_not_approved",)
    assert result.delivery_performed is False


def test_invalid_continuation_id_and_workflow_instance_id_fail_safely():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "instances.json"
        missing_continuation = materialize_delivery_action(
            continuation_id="missing",
            store_path=store_path,
            root=ROOT,
        )
        missing_instance = materialize_delivery_action(
            workflow_instance_id="missing",
            store_path=store_path,
            root=ROOT,
        )

    assert missing_continuation.materialized is False
    assert missing_continuation.skipped_reasons == (
        "workflow_instance_not_found",
    )
    assert missing_instance.materialized is False
    assert missing_instance.skipped_reasons == ("workflow_instance_not_found",)


def test_blocked_delivery_governance_prevents_materialization():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root, delivery_governance="disabled")
        instance = _approved_instance(store_path, root=temp_root)
        result = materialize_delivery_action(
            continuation_id=instance["continuation_id"],
            store_path=store_path,
            root=temp_root,
        )

    assert result.materialized is False
    assert result.delivery_action is None
    assert result.skipped_reasons == ("delivery_governance_disabled",)
    assert result.delivery_performed is False


def test_delivery_performed_false_always():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root, delivery_governance="enabled")
        instance = _approved_instance(store_path, root=temp_root)
        result = materialize_delivery_action(
            workflow_instance_id=instance["workflow_instance_id"],
            store_path=store_path,
            root=temp_root,
        )

    assert result.delivery_performed is False
    assert result.audit_summary["delivery_performed"] is False
    assert result.delivery_action["delivery_performed"] is False
    assert result.delivery_action["provenance"]["delivery_performed"] is False


def test_no_external_delivery_adapter_is_called_or_imported():
    source = (ROOT / "runtime" / "workflows" / "delivery.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "telegram",
        "gateway",
        "send_email(",
        "smtp",
        "gmail",
        "mailgun",
        "requests.",
        "urllib",
    )
    assert all(term not in lowered for term in forbidden)


def test_descriptor_references_artifacts_and_actions_not_raw_prose():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root, delivery_governance="enabled")
        instance = _approved_instance(store_path, root=temp_root)
        action = materialize_delivery_action(
            continuation_id=instance["continuation_id"],
            store_path=store_path,
            root=temp_root,
        ).delivery_action

    rendered = repr(action)
    assert action["artifact_refs"] == ["artifact:email_draft:abc123"]
    assert action["action_refs"] == ["action:send_email:def456"]
    assert "Hi " not in rendered
    assert "Subject:" not in rendered
    assert "draft_text" not in rendered
    assert "body" not in rendered.lower()


def test_runtime_delivery_materialization_code_remains_domain_neutral():
    source = (ROOT / "runtime" / "workflows" / "delivery.py").read_text(
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
        "guest",
        "ranking",
        "draft generation",
    )
    assert all(term not in lowered for term in forbidden)


def test_no_ranking_draft_generation_continuation_or_delivery_execution():
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "root"
        store_path = Path(tmp) / "instances.json"
        _write_temp_workflow(temp_root, delivery_governance="enabled")
        instance = _approved_instance(store_path, root=temp_root)
        result = materialize_delivery_action(
            continuation_id=instance["continuation_id"],
            store_path=store_path,
            root=temp_root,
        )
        loaded = get_workflow_instance_by_continuation_id(
            instance["continuation_id"],
            store_path=store_path,
        )

    assert result.materialized is True
    assert result.delivery_action["delivery_prepared"] is True
    assert result.delivery_action["delivery_performed"] is False
    assert result.audit_summary["execution_allowed"] is False
    assert loaded["status"] == STATUS_APPROVED_PENDING_RESUME
    assert "remaining_actions" not in result.to_audit_record()
    assert "draft" not in result.delivery_action
    assert "ranking" not in result.delivery_action


def main():
    test_approved_workflow_materializes_one_delivery_action_descriptor()
    test_pending_approval_fails_safely()
    test_denied_workflow_fails_safely()
    test_invalid_continuation_id_and_workflow_instance_id_fail_safely()
    test_blocked_delivery_governance_prevents_materialization()
    test_delivery_performed_false_always()
    test_no_external_delivery_adapter_is_called_or_imported()
    test_descriptor_references_artifacts_and_actions_not_raw_prose()
    test_runtime_delivery_materialization_code_remains_domain_neutral()
    test_no_ranking_draft_generation_continuation_or_delivery_execution()
    print("PASS guest booking workflow delivery materialization")


if __name__ == "__main__":
    main()
