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
from runtime.scheduling.workflow_loop import run_scheduler_loop  # noqa: E402
from runtime.scheduling.workflow_telemetry import (  # noqa: E402
    load_scheduled_executor_status_records,
)
import runtime.scheduling.workflow_telemetry as workflow_telemetry  # noqa: E402


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


def current_alexis_declarations():
    with TemporaryDirectory() as tmp:
        path = write_manifest(tmp, raw_alexis_declarations())
        loaded, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )
        assert errors == ()
    return loaded


def test_enabled_allowlisted_workflow_executes_from_scheduler_loop():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = run_scheduler_loop(
            declarations=enabled_booking_declarations(),
            max_iterations=1,
            poll_interval_seconds=0,
            now_provider=lambda: datetime(
                2026,
                5,
                18,
                8,
                30,
                tzinfo=timezone.utc,
            ),
            audit_path=audit_path,
        )

    assert result.iterations_run == 1
    assert {
        item.workflow: item.execution_performed
        for item in result.execution_results
    } == {
        "alexis_rss_feed_check": True,
        "alexis_booking_workflow_smoke_check": True,
    }


def test_audit_only_and_disabled_tasks_never_execute():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        result = run_scheduler_loop(
            declarations=current_alexis_declarations(),
            max_iterations=1,
            poll_interval_seconds=0,
            now_provider=lambda: datetime(
                2026,
                5,
                18,
                8,
                31,
                tzinfo=timezone.utc,
            ),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert result.execution_results == ()
    assert records == ()
    assert result.iteration_traces[0].skipped_reasons == ()


def test_audit_records_persist_through_loop_execution():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        run_scheduler_loop(
            declarations=enabled_booking_declarations(),
            max_iterations=1,
            poll_interval_seconds=0,
            now_provider=lambda: datetime(
                2026,
                5,
                18,
                8,
                30,
                tzinfo=timezone.utc,
            ),
            audit_path=audit_path,
        )
        records = load_scheduled_workflow_audit_records(audit_path)

    assert {
        record["workflow"]: record["execution_status"]
        for record in records
    } == {
        "alexis_rss_feed_check": "executed",
        "alexis_booking_workflow_smoke_check": "executed",
    }


def test_loop_respects_max_iterations():
    calls = []

    def now_provider():
        calls.append(len(calls))
        return datetime(2026, 5, 18, 7, 1, tzinfo=timezone.utc)

    sleeps = []
    result = run_scheduler_loop(
        declarations=current_alexis_declarations(),
        max_iterations=3,
        poll_interval_seconds=5,
        now_provider=now_provider,
        sleep_fn=sleeps.append,
        audit_path=Path("/tmp/nonexistent_scheduled_loop_test.jsonl"),
    )

    assert result.iterations_run == 3
    assert calls == [0, 1, 2]
    assert sleeps == [5, 5]


def test_loop_uses_deterministic_supplied_timestamps():
    times = iter(
        [
            datetime(2026, 5, 18, 7, 0, tzinfo=timezone.utc),
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

    assert [trace.timestamp for trace in result.iteration_traces] == [
        "2026-05-18T07:00:00+00:00",
        "2026-05-18T08:30:00+00:00",
    ]
    assert [trace.execution_attempt_count for trace in result.iteration_traces] == [
        1,
        2,
    ]


def test_loop_emits_scheduler_telemetry_and_bounded_status():
    events = []
    original_report_event = workflow_telemetry.report_event

    def capture_event(source_bot, event_type, payload, request_id=None):
        events.append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    workflow_telemetry.report_event = capture_event
    try:
        with TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
            status_path = Path(tmp) / "scheduled_executor_status.jsonl"
            run_scheduler_loop(
                declarations=enabled_booking_declarations(),
                max_iterations=1,
                poll_interval_seconds=0,
                now_provider=lambda: datetime(
                    2026,
                    5,
                    18,
                    8,
                    30,
                    tzinfo=timezone.utc,
                ),
                audit_path=audit_path,
                status_path=status_path,
                heartbeat_min_interval_seconds=0,
            )
            status_records = load_scheduled_executor_status_records(status_path)
    finally:
        workflow_telemetry.report_event = original_report_event

    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "scheduled_executor_started",
        "scheduled_task_due",
        "scheduled_task_completed",
        "scheduled_task_due",
        "scheduled_task_completed",
        "scheduled_executor_heartbeat",
    ]
    assert status_records
    assert status_records[-1]["status_type"] == "scheduled_executor_heartbeat"
    enabled_tasks = status_records[-1]["enabled_tasks"]
    rss_task = next(
        task for task in enabled_tasks
        if task["task_id"] == "alexis_rss_feed_check"
    )
    assert rss_task["next_due_at"] == "2026-05-18T08:30:00+00:00"
    assert rss_task["cadence"] == "every_1800_seconds"
    assert rss_task["cadence_seconds"] == 1800
    assert rss_task["staleness"] == {
        "last_run_age_seconds": 0,
        "stale_after_seconds": 1800,
        "is_stale": False,
    }


def test_heartbeat_status_records_are_throttled():
    times = iter(
        [
            datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 18, 8, 1, tzinfo=timezone.utc),
        ]
    )
    with TemporaryDirectory() as tmp:
        status_path = Path(tmp) / "scheduled_executor_status.jsonl"
        run_scheduler_loop(
            declarations=current_alexis_declarations(),
            max_iterations=2,
            poll_interval_seconds=0,
            now_provider=lambda: next(times),
            audit_path=Path(tmp) / "scheduled_workflow_audit.jsonl",
            status_path=status_path,
            heartbeat_min_interval_seconds=300,
            telemetry_enabled=False,
        )
        status_records = load_scheduled_executor_status_records(status_path)

    assert len(status_records) == 1
    assert status_records[0]["timestamp"] == "2026-05-18T08:00:00+00:00"


def test_no_threads_subprocesses_or_daemons_are_created():
    source = (ROOT / "runtime/scheduling/workflow_loop.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "threading",
        "multiprocessing",
        "subprocess",
        "daemon",
        "while true",
        "asyncio",
        "telegram",
        "feedparser",
        "openai",
    )
    lowered = source.lower()

    assert all(term not in lowered for term in forbidden)


def main():
    test_enabled_allowlisted_workflow_executes_from_scheduler_loop()
    test_audit_only_and_disabled_tasks_never_execute()
    test_audit_records_persist_through_loop_execution()
    test_loop_respects_max_iterations()
    test_loop_uses_deterministic_supplied_timestamps()
    test_loop_emits_scheduler_telemetry_and_bounded_status()
    test_heartbeat_status_records_are_throttled()
    test_no_threads_subprocesses_or_daemons_are_created()
    print("PASS scheduled workflow loop")


if __name__ == "__main__":
    main()
