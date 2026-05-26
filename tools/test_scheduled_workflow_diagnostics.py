import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scheduled_workflow_diagnostics import (  # noqa: E402
    build_scheduled_workflow_diagnostics,
)


RAW_MARKERS = (
    "Dr. Saju Matthew",
    "Unknown Person",
    "Family Practice Physician",
    "guest_id",
    "raw_lookup_results",
    "prompt",
    "model_messages",
    "telegram",
    "rss_payload",
    "memory_contents",
)


def test_diagnostics_command_outputs_content_safe_scheduler_summary():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        output = subprocess.check_output(
            [
                sys.executable,
                str(ROOT / "tools/scheduled_workflow_diagnostics.py"),
                "--now",
                "2026-05-18T08:30:00+00:00",
                "--audit-path",
                str(audit_path),
                "--json",
            ],
            text=True,
            cwd=ROOT,
        )

    payload = json.loads(output)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["diagnostic_type"] == "scheduled_workflow_status"
    assert payload["agent"] == "alexis"
    assert payload["discovered_task_count"] == 4
    assert "alexis_booking_workflow_smoke_check" in payload["task_ids"]
    assert payload["execution_performed"] is False
    for marker in RAW_MARKERS:
        assert marker not in serialized


def test_supplied_timestamp_makes_due_resolution_deterministic():
    monday_0800 = build_scheduled_workflow_diagnostics(
        now=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
        audit_path="/tmp/juniper_missing_scheduled_audit.jsonl",
    )
    monday_0830 = build_scheduled_workflow_diagnostics(
        now=datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
        audit_path="/tmp/juniper_missing_scheduled_audit.jsonl",
    )

    assert monday_0800["due_task_ids"] == [
        "alexis_rss_feed_check",
        "alexis_guest_db_freshness_audit",
    ]
    assert monday_0830["due_task_ids"] == [
        "alexis_rss_feed_check",
        "alexis_booking_workflow_smoke_check"
    ]
    database_plan = next(
        plan for plan in monday_0800["dry_run_plans"]
        if plan["task_id"] == "alexis_guest_db_freshness_audit"
    )
    assert database_plan["semantic_operation"]["operation_type"] == "DATABASE_AUDIT"
    assert monday_0830["dry_run_plans"][0]["semantic_operation"][
        "operation_type"
    ] == "NEWS_INGESTION"


def test_audit_summaries_are_content_safe():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        audit_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-18T08:30:00+00:00",
                    "task_id": "alexis_booking_workflow_smoke_check",
                    "agent": "alexis",
                    "workflow": "alexis_booking_workflow_smoke_check",
                    "binding_id": "alexis_booking_workflow_smoke_check",
                    "governance_state": "enabled",
                    "execution_mode": "manual",
                    "execution_status": "executed",
                    "execution_performed": True,
                    "skipped_reasons": [],
                    "duration_ms": 1,
                    "audit_summary": {
                        "workflow": "alexis_booking_workflow_smoke_check",
                        "prompt": "raw prompt",
                        "raw_lookup_results": "raw lookup",
                        "guest_id": "secret",
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = build_scheduled_workflow_diagnostics(
            audit_path=audit_path,
        )

    serialized = json.dumps(payload, sort_keys=True)
    assert payload["recent_audit"]["record_count"] == 1
    assert payload["recent_audit"]["recent_records"][0]["audit_summary_keys"] == [
        "workflow"
    ]
    for marker in RAW_MARKERS:
        assert marker not in serialized
    assert "raw prompt" not in serialized
    assert "raw lookup" not in serialized
    assert "secret" not in serialized


def test_scheduler_decision_diagnostics_distinguish_dry_run_and_blocks():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        audit_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-18T08:00:00+00:00",
                    "task_id": "alexis_rss_feed_check",
                    "agent": "alexis",
                    "workflow": "alexis_rss_feed_check",
                    "binding_id": "alexis_rss_feed_check",
                    "governance_state": "enabled",
                    "execution_mode": "scheduled",
                    "execution_status": "executed",
                    "execution_performed": True,
                    "skipped_reasons": [],
                    "duration_ms": 1,
                    "audit_summary": {
                        "workflow": "alexis_rss_feed_check",
                    },
                    "operator_diagnostics": {
                        "diagnostic_type": (
                            "scheduled_workflow_execution_visibility"
                        ),
                        "scheduler_decisions": {
                            "dry_run_plan": True,
                            "local_cache_operation_allowed": True,
                            "local_cache_read_allowed": True,
                            "local_cache_synthesis_allowed": True,
                            "external_network_fetch_blocked": True,
                            "external_network_fetch_reason": (
                                "external_network_fetch_blocked_by_dry_run"
                            ),
                            "governance_disabled": False,
                            "governance_audit_only": False,
                            "workflow_not_allowlisted": False,
                            "fail_closed_external_calls": True,
                        },
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = build_scheduled_workflow_diagnostics(
            audit_path=audit_path,
        )

    decisions = payload["recent_audit"]["recent_records"][0][
        "operator_diagnostics"
    ]["scheduler_decisions"]
    assert decisions == {
        "dry_run_plan": True,
        "external_network_fetch_blocked": True,
        "external_network_fetch_reason": (
            "external_network_fetch_blocked_by_dry_run"
        ),
        "fail_closed_external_calls": True,
        "governance_audit_only": False,
        "governance_disabled": False,
        "local_cache_operation_allowed": True,
        "local_cache_read_allowed": True,
        "local_cache_synthesis_allowed": True,
        "workflow_not_allowlisted": False,
    }


def test_operator_status_shows_scheduler_liveness_and_rss_schedule():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        status_path = Path(tmp) / "scheduled_executor_status.jsonl"
        audit_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-18T08:00:00+00:00",
                    "task_id": "alexis_rss_feed_check",
                    "agent": "alexis",
                    "workflow": "alexis_rss_feed_check",
                    "binding_id": "alexis_rss_feed_check",
                    "governance_state": "enabled",
                    "execution_mode": "manual",
                    "execution_status": "executed",
                    "execution_performed": True,
                    "skipped_reasons": [],
                    "duration_ms": 1,
                    "audit_summary": {
                        "workflow": "alexis_rss_feed_check",
                        "execution_status": "success",
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        status_path.write_text(
            json.dumps(
                {
                    "status_type": "scheduled_executor_heartbeat",
                    "timestamp": "2026-05-18T08:25:00+00:00",
                    "agent": "alexis",
                    "iteration": 3,
                    "loaded_task_count": 4,
                    "enabled_task_count": 1,
                    "due_task_ids": [],
                    "execution_performed_count": 1,
                    "enabled_tasks": [
                        {
                            "task_id": "alexis_rss_feed_check",
                            "workflow": "alexis_rss_feed_check",
                            "last_run_at": "2026-05-18T08:00:00+00:00",
                            "next_due_at": "2026-05-18T08:30:00+00:00",
                            "cadence": "every_1800_seconds",
                            "cadence_seconds": 1800,
                            "staleness": {
                                "last_run_age_seconds": 1500,
                                "stale_after_seconds": 1800,
                                "is_stale": False,
                            },
                        }
                    ],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = build_scheduled_workflow_diagnostics(
            now=datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
            audit_path=audit_path,
            status_path=status_path,
        )

    rss_status = next(
        task for task in payload["task_statuses"]
        if task["task_id"] == "alexis_rss_feed_check"
    )
    assert payload["scheduler_alive"] is True
    assert payload["scheduler_last_heartbeat_at"] == (
        "2026-05-18T08:25:00+00:00"
    )
    assert rss_status["enabled"] is True
    assert rss_status["workflow"] == "alexis_rss_feed_check"
    assert rss_status["binding_id"] == "alexis_rss_feed_check"
    assert rss_status["cadence"] == "every_1800_seconds"
    assert rss_status["cadence_seconds"] == 1800
    assert rss_status["last_run_at"] == "2026-05-18T08:00:00+00:00"
    assert rss_status["next_due_at"] == "2026-05-18T08:30:00+00:00"
    assert rss_status["staleness"] == {
        "last_run_age_seconds": 1800,
        "stale_after_seconds": 1800,
        "is_stale": False,
    }


def test_cadence_and_staleness_diagnostics_show_stale_enabled_tasks():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        audit_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-18T08:00:00+00:00",
                    "task_id": "alexis_rss_feed_check",
                    "agent": "alexis",
                    "workflow": "alexis_rss_feed_check",
                    "binding_id": "alexis_rss_feed_check",
                    "governance_state": "enabled",
                    "execution_mode": "scheduled",
                    "execution_status": "executed",
                    "execution_performed": True,
                    "skipped_reasons": [],
                    "duration_ms": 1,
                    "audit_summary": {"workflow": "alexis_rss_feed_check"},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = build_scheduled_workflow_diagnostics(
            now=datetime(2026, 5, 18, 8, 45, tzinfo=timezone.utc),
            audit_path=audit_path,
        )

    rss_status = next(
        task for task in payload["task_statuses"]
        if task["task_id"] == "alexis_rss_feed_check"
    )
    assert rss_status["cadence"] == "every_1800_seconds"
    assert rss_status["cadence_seconds"] == 1800
    assert rss_status["last_run_at"] == "2026-05-18T08:00:00+00:00"
    assert rss_status["next_due_at"] == "2026-05-18T09:00:00+00:00"
    assert rss_status["staleness"] == {
        "last_run_age_seconds": 2700,
        "stale_after_seconds": 1800,
        "is_stale": True,
    }


def test_text_status_includes_operator_scheduler_fields():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        status_path = Path(tmp) / "scheduled_executor_status.jsonl"
        status_path.write_text(
            json.dumps(
                {
                    "status_type": "scheduled_executor_heartbeat",
                    "timestamp": "2026-05-18T08:25:00+00:00",
                    "agent": "alexis",
                    "iteration": 3,
                    "loaded_task_count": 4,
                    "enabled_task_count": 1,
                    "due_task_ids": [],
                    "execution_performed_count": 1,
                    "enabled_tasks": [],
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        output = subprocess.check_output(
            [
                sys.executable,
                str(ROOT / "tools/scheduled_workflow_diagnostics.py"),
                "--now",
                "2026-05-18T08:30:00+00:00",
                "--audit-path",
                str(audit_path),
                "--status-path",
                str(status_path),
            ],
            text=True,
            cwd=ROOT,
        )

    assert "scheduler_alive: true" in output
    assert "scheduler_last_heartbeat_at: 2026-05-18T08:25:00+00:00" in output
    assert (
        "task_status: alexis_rss_feed_check enabled=true "
        "workflow=alexis_rss_feed_check requires_approval=false "
        "cadence=every_1800_seconds "
        "staleness_seconds=none "
        "last_run_at=none "
        "next_due_at=2026-05-18T08:30:00+00:00"
    ) in output


def test_no_runtime_behavior_changes_or_execution_imports():
    source = (
        ROOT / "tools/scheduled_workflow_diagnostics.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "execute_scheduled_workflow_manually",
        "run_scheduler_loop",
        "feedparser",
        "persist_conversation_memory",
        "openai",
        "subprocess",
        "threading",
        "asyncio",
    )
    lowered = source.lower()

    assert all(term not in lowered for term in forbidden)


def main():
    test_diagnostics_command_outputs_content_safe_scheduler_summary()
    test_supplied_timestamp_makes_due_resolution_deterministic()
    test_audit_summaries_are_content_safe()
    test_scheduler_decision_diagnostics_distinguish_dry_run_and_blocks()
    test_operator_status_shows_scheduler_liveness_and_rss_schedule()
    test_cadence_and_staleness_diagnostics_show_stale_enabled_tasks()
    test_text_status_includes_operator_scheduler_fields()
    test_no_runtime_behavior_changes_or_execution_imports()
    print("PASS scheduled workflow diagnostics")


if __name__ == "__main__":
    main()
