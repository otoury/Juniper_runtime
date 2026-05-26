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
    load_scheduled_workflow_audit_records,
)
from runtime.scheduling.workflow_locking import (  # noqa: E402
    ScheduledWorkflowLockState,
    acquire_scheduled_workflow_lock,
    scheduled_workflow_window_key,
)
from runtime.scheduling.workflow_loop import run_scheduler_loop  # noqa: E402
from runtime.scheduling.workflow_orchestration import (  # noqa: E402
    ScheduledWorkflowExecutionPlan,
    build_due_scheduled_workflow_plans,
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


def enabled_booking_declarations():
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
    return loaded


def enabled_interval_declarations():
    declarations = raw_alexis_declarations()
    for declaration in declarations:
        if declaration["id"] == "alexis_rss_feed_check":
            declaration["governance_state"] = "enabled"
    with TemporaryDirectory() as tmp:
        path = write_manifest(tmp, declarations)
        loaded, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )
        assert errors == ()
    return loaded


def due_plan(declarations, now):
    plans = build_due_scheduled_workflow_plans(declarations, now=now)
    assert len(plans) == 1
    return plans[0]


def plan_by_task_id(declarations, now, task_id):
    plans = build_due_scheduled_workflow_plans(declarations, now=now)
    matches = [plan for plan in plans if plan.task_id == task_id]
    assert len(matches) == 1
    return matches[0]


def test_same_due_task_does_not_execute_twice_within_same_window():
    times = iter(
        [
            datetime(2026, 5, 18, 8, 30, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 18, 8, 30, 30, tzinfo=timezone.utc),
        ]
    )
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = run_scheduler_loop(
            declarations=enabled_booking_declarations(),
            max_iterations=2,
            poll_interval_seconds=0,
            now_provider=lambda: next(times),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert len(result.execution_results) == 1
    assert len(records) == 1
    assert result.iteration_traces[1].duplicate_skipped_count == 1
    assert result.iteration_traces[1].skipped_reasons == (
        "duplicate_due_window",
    )


def test_future_due_windows_execute_normally():
    times = iter(
        [
            datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
            datetime(2026, 5, 25, 8, 30, tzinfo=timezone.utc),
        ]
    )
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = run_scheduler_loop(
            declarations=enabled_booking_declarations(),
            max_iterations=2,
            poll_interval_seconds=0,
            now_provider=lambda: next(times),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert len(result.execution_results) == 2
    assert len(records) == 2
    assert all(item.execution_performed for item in result.execution_results)


def test_different_tasks_do_not_collide():
    now = datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc)
    declarations = enabled_booking_declarations()
    first = due_plan(declarations, now)
    second = ScheduledWorkflowExecutionPlan(
        task_id="another_safe_task",
        agent="alexis",
        workflow="another_safe_task",
        binding_id="another_safe_task",
        semantic_operation={
            "operation_type": "SMOKE_CHECK",
            "capability_id": "another_safe_task",
            "produces_artifact": False,
            "external_side_effects_allowed": False,
            "memory_write_allowed": False,
            "requires_approval": False,
        },
        governance_state="enabled",
        schedule_type=first.schedule_type,
        plan_mode=first.plan_mode,
        dry_run=True,
        execution_allowed_by_governance=True,
        execution_performed=False,
        max_runtime_ms=first.max_runtime_ms,
        max_concurrent_runs=1,
        retry_policy="none",
        skipped_reasons=(),
        manifest_path="test",
    )

    assert scheduled_workflow_window_key(first, due_at=now) != (
        scheduled_workflow_window_key(second, due_at=now)
    )
    state = ScheduledWorkflowLockState()
    assert acquire_scheduled_workflow_lock(first, due_at=now, state=state).acquired
    assert acquire_scheduled_workflow_lock(second, due_at=now, state=state).acquired


def test_malformed_lock_state_fails_closed_safely():
    now = datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc)
    plan = due_plan(enabled_booking_declarations(), now)
    state = ScheduledWorkflowLockState()
    state.completed_windows = []  # type: ignore[assignment]

    decision = acquire_scheduled_workflow_lock(plan, due_at=now, state=state)

    assert decision.acquired is False
    assert decision.status == "malformed_lock_state"
    assert decision.skipped_reason == "malformed_lock_state"


def test_interval_windows_are_supported():
    declarations = enabled_interval_declarations()
    plan = plan_by_task_id(
        declarations,
        datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
        "alexis_rss_feed_check",
    )
    declaration = next(item for item in declarations if item.id == plan.task_id)
    first = scheduled_workflow_window_key(
        plan,
        due_at=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
        declaration=declaration,
    )
    future = scheduled_workflow_window_key(
        plan,
        due_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        declaration=declaration,
    )

    assert first != future
    assert first.startswith("alexis_rss_feed_check|interval|")
    assert future.startswith("alexis_rss_feed_check|interval|")


def test_governance_behavior_remains_unchanged():
    times = iter(
        [
            datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
            datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
        ]
    )
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = run_scheduler_loop(
            declarations=enabled_booking_declarations(),
            max_iterations=2,
            poll_interval_seconds=0,
            now_provider=lambda: next(times),
            audit_path=audit_path,
        )

    assert result.iteration_traces[0].execution_attempt_count == 1
    assert result.iteration_traces[0].execution_performed_count == 1
    assert result.iteration_traces[1].execution_attempt_count == 1
    assert result.iteration_traces[1].duplicate_skipped_count == 1


def test_no_daemon_thread_process_or_distributed_behavior_added():
    source = (ROOT / "runtime/scheduling/workflow_locking.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "threading",
        "multiprocessing",
        "subprocess",
        "daemon",
        "socket",
        "redis",
        "sqlite",
        "postgres",
        "telegram",
        "feedparser",
        "openai",
    )
    lowered = source.lower()

    assert all(term not in lowered for term in forbidden)


def main():
    test_same_due_task_does_not_execute_twice_within_same_window()
    test_future_due_windows_execute_normally()
    test_different_tasks_do_not_collide()
    test_malformed_lock_state_fails_closed_safely()
    test_interval_windows_are_supported()
    test_governance_behavior_remains_unchanged()
    test_no_daemon_thread_process_or_distributed_behavior_added()
    print("PASS scheduled workflow locking")


if __name__ == "__main__":
    main()
