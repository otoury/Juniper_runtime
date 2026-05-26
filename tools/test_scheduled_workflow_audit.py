import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.scheduled_task_registry import (  # noqa: E402
    audit_scheduled_task_declarations_from_path,
)
from runtime.scheduling.workflow_audit import (  # noqa: E402
    build_scheduled_workflow_audit_record,
    load_scheduled_workflow_audit_records,
)
from runtime.scheduling.workflow_executor import (  # noqa: E402
    execute_scheduled_workflow_manually,
)
from runtime.scheduling.workflow_orchestration import (  # noqa: E402
    ScheduledWorkflowExecutionPlan,
    build_due_scheduled_workflow_plans,
    discover_scheduled_workflows,
)


RAW_MARKERS = (
    "Dr. Saju Matthew",
    "Unknown Person",
    "Family Practice Physician",
    "GUESTS_CANONICAL.csv",
    "guest_id",
    "raw_lookup_results",
    "prompt",
    "model_messages",
    "telegram",
)


def raw_alexis_declarations():
    data = json.loads(
        (ROOT / "agents/alexis/scheduled_tasks.json").read_text(
            encoding="utf-8"
        )
    )
    return data["task_declarations"]


def write_manifest(root, declarations):
    path = Path(root) / "agents/alexis/scheduled_tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "agent": "alexis",
                "task_declarations": declarations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def enabled_booking_smoke_plan():
    declarations = raw_alexis_declarations()
    for declaration in declarations:
        if declaration["id"] == "alexis_booking_workflow_smoke_check":
            declaration["governance_state"] = "enabled"

    with TemporaryDirectory() as tmp:
        path = write_manifest(tmp, declarations)
        loaded, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )
        assert errors == ()
        plans = build_due_scheduled_workflow_plans(
            loaded,
            now=datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
        )

    assert len(plans) == 1
    return plans[0]


def audit_only_booking_smoke_plan():
    declarations, errors = discover_scheduled_workflows("alexis", root=ROOT)
    assert errors == ()
    plans = build_due_scheduled_workflow_plans(
        declarations,
        now=datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
    )
    assert len(plans) == 1
    return plans[0]


def test_manual_execution_attempt_writes_one_audit_record():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = execute_scheduled_workflow_manually(
            enabled_booking_smoke_plan(),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert result.execution_performed is True
    assert len(records) == 1
    record = records[0]
    assert record["task_id"] == "alexis_booking_workflow_smoke_check"
    assert record["execution_status"] == "executed"
    assert record["execution_performed"] is True
    assert isinstance(record["duration_ms"], int)


def test_failed_skipped_execution_writes_one_audit_record():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = execute_scheduled_workflow_manually(
            audit_only_booking_smoke_plan(),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert result.execution_performed is False
    assert len(records) == 1
    assert records[0]["execution_status"] == "skipped"
    assert records[0]["skipped_reasons"] == ["governance_audit_only"]
    assert records[0]["audit_summary"] == {}


def test_audit_record_is_content_safe():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        execute_scheduled_workflow_manually(
            enabled_booking_smoke_plan(),
            audit_path=audit_path,
        )
        serialized = audit_path.read_text(encoding="utf-8")

    for marker in RAW_MARKERS:
        assert marker not in serialized


def test_audit_append_behavior_preserves_previous_records():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        execute_scheduled_workflow_manually(
            audit_only_booking_smoke_plan(),
            audit_path=audit_path,
        )
        execute_scheduled_workflow_manually(
            enabled_booking_smoke_plan(),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert len(records) == 2
    assert records[0]["execution_status"] == "skipped"
    assert records[1]["execution_status"] == "executed"


def test_executor_behavior_remains_unchanged_with_audit_disabled():
    result = execute_scheduled_workflow_manually(
        enabled_booking_smoke_plan(),
        write_audit=False,
    )
    record = build_scheduled_workflow_audit_record(
        result,
        timestamp=datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
    )

    assert result.execution_performed is True
    assert result.execution_status == "executed"
    assert record["execution_performed"] is True
    assert record["execution_status"] == "executed"


def test_no_background_or_autonomous_behavior_is_added():
    source = (
        ROOT / "runtime/scheduling/workflow_audit.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "feedparser",
        "openai",
        "subprocess",
        "threading",
        "asyncio",
        "while true",
        "schedule.",
    )
    lowered = source.lower()

    assert all(term not in lowered for term in forbidden)


def test_disabled_execution_audit_record_shape():
    plan = ScheduledWorkflowExecutionPlan(
        task_id="alexis_booking_workflow_smoke_check",
        agent="alexis",
        workflow="alexis_booking_workflow_smoke_check",
        binding_id="alexis_booking_workflow_smoke_check",
        semantic_operation={
            "operation_type": "SMOKE_CHECK",
            "capability_id": "alexis_booking_workflow_smoke_check",
            "produces_artifact": False,
            "external_side_effects_allowed": False,
            "memory_write_allowed": False,
            "requires_approval": False,
        },
        governance_state="disabled",
        schedule_type="cron",
        plan_mode="dry_run",
        dry_run=True,
        execution_allowed_by_governance=False,
        execution_performed=False,
        max_runtime_ms=15000,
        max_concurrent_runs=1,
        retry_policy="none",
        skipped_reasons=("governance_disabled",),
        manifest_path="test",
    )

    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        execute_scheduled_workflow_manually(plan, audit_path=audit_path)
        records = load_scheduled_workflow_audit_records(audit_path)

    assert records[0] == {
        "agent": "alexis",
        "audit_summary": {},
        "binding_id": "alexis_booking_workflow_smoke_check",
        "duration_ms": records[0]["duration_ms"],
        "execution_mode": "manual",
        "execution_performed": False,
        "execution_status": "skipped",
        "governance_state": "disabled",
        "operator_diagnostics": records[0]["operator_diagnostics"],
        "skipped_reasons": ["governance_disabled"],
        "task_id": "alexis_booking_workflow_smoke_check",
        "timestamp": records[0]["timestamp"],
        "workflow": "alexis_booking_workflow_smoke_check",
    }
    assert records[0]["operator_diagnostics"]["approval_governance"][
        "scheduler_governance_bypass_performed"
    ] is False


def main():
    test_manual_execution_attempt_writes_one_audit_record()
    test_failed_skipped_execution_writes_one_audit_record()
    test_audit_record_is_content_safe()
    test_audit_append_behavior_preserves_previous_records()
    test_executor_behavior_remains_unchanged_with_audit_disabled()
    test_no_background_or_autonomous_behavior_is_added()
    test_disabled_execution_audit_record_shape()
    print("PASS scheduled workflow audit")


if __name__ == "__main__":
    main()
