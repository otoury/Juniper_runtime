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
from runtime.scheduling.workflow_executor import (  # noqa: E402
    ALLOWLISTED_WORKFLOWS,
    execute_scheduled_workflow_manually,
    scheduled_workflow_execution_trace_payload,
)
from runtime.scheduling.workflow_orchestration import (  # noqa: E402
    ScheduledWorkflowExecutionPlan,
    build_due_scheduled_workflow_plans,
    discover_scheduled_workflows,
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

    return next(
        plan for plan in plans
        if plan.task_id == "alexis_booking_workflow_smoke_check"
    )


def test_audit_only_scheduled_tasks_do_not_execute():
    declarations, errors = discover_scheduled_workflows("alexis", root=ROOT)
    assert errors == ()
    plans = build_due_scheduled_workflow_plans(
        declarations,
        now=datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc),
    )

    audit_only_plan = next(
        plan for plan in plans
        if plan.task_id == "alexis_booking_workflow_smoke_check"
    )
    result = execute_scheduled_workflow_manually(audit_only_plan)

    assert result.execution_performed is False
    assert result.execution_status == "skipped"
    assert result.skipped_reasons == ("governance_audit_only",)
    assert result.audit_summary == {}


def test_disabled_scheduled_tasks_do_not_execute():
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

    result = execute_scheduled_workflow_manually(plan)

    assert result.execution_performed is False
    assert result.execution_status == "skipped"
    assert result.skipped_reasons == ("governance_disabled",)


def test_enabled_allowlisted_smoke_task_can_execute_manually():
    plan = enabled_booking_smoke_plan()

    result = execute_scheduled_workflow_manually(plan)

    assert result.execution_performed is True
    assert result.execution_status == "executed"
    assert result.allowlisted is True
    assert result.audit_summary["workflow"] == "alexis_booking_workflow_smoke_check"
    assert result.audit_summary["checks"] == {
        "known_guest_success": True,
        "unknown_guest_fail_closed": True,
    }
    assert result.audit_summary["known_guest"]["execution_status"] == "success"
    assert result.audit_summary["unknown_guest"]["execution_status"] == "failed"


def test_intended_scheduled_news_workflows_are_allowlisted():
    assert {
        "alexis_daily_news_briefing",
        "alexis_rss_feed_check",
    }.issubset(ALLOWLISTED_WORKFLOWS)


def test_operator_enabled_daily_news_briefing_is_not_rejected_by_allowlist():
    with TemporaryDirectory() as tmp:
        plan = ScheduledWorkflowExecutionPlan(
            task_id="alexis_daily_news_briefing",
            agent="alexis",
            workflow="alexis_daily_news_briefing",
            binding_id="alexis_daily_news_briefing",
            semantic_operation={
                "operation_type": "NEWS_INGESTION",
                "capability_id": "alexis_news_briefing",
                "produces_artifact": False,
                "external_side_effects_allowed": False,
                "memory_write_allowed": False,
                "requires_approval": False,
            },
            governance_state="enabled",
            schedule_type="cron",
            plan_mode="dry_run",
            dry_run=True,
            execution_allowed_by_governance=True,
            execution_performed=False,
            max_runtime_ms=30000,
            max_concurrent_runs=1,
            retry_policy="none",
            skipped_reasons=(),
            manifest_path="test",
        )

        result = execute_scheduled_workflow_manually(
            plan,
            source_item_store_path=Path(tmp) / "source_items.jsonl",
            write_audit=False,
        )

    assert result.execution_performed is True
    assert result.allowlisted is True
    assert result.execution_status == "executed"
    assert result.skipped_reasons == ()
    assert result.audit_summary["workflow"] == "alexis_daily_news_briefing"
    assert result.audit_summary["external_call_performed"] is False


def test_unknown_non_allowlisted_workflows_fail_closed():
    plan = ScheduledWorkflowExecutionPlan(
        task_id="alexis_unregistered_news_workflow",
        agent="alexis",
        workflow="alexis_unregistered_news_workflow",
        binding_id="alexis_unregistered_news_workflow",
        semantic_operation={
            "operation_type": "NEWS_INGESTION",
            "capability_id": "alexis_unregistered_news_workflow",
            "produces_artifact": False,
            "external_side_effects_allowed": False,
            "memory_write_allowed": False,
            "requires_approval": False,
        },
        governance_state="enabled",
        schedule_type="cron",
        plan_mode="dry_run",
        dry_run=True,
        execution_allowed_by_governance=True,
        execution_performed=False,
        max_runtime_ms=30000,
        max_concurrent_runs=1,
        retry_policy="none",
        skipped_reasons=(),
        manifest_path="test",
    )

    result = execute_scheduled_workflow_manually(plan)

    assert result.execution_performed is False
    assert result.allowlisted is False
    assert result.execution_status == "skipped"
    assert result.skipped_reasons == ("workflow_not_allowlisted",)


def test_execution_result_is_content_safe():
    result = execute_scheduled_workflow_manually(enabled_booking_smoke_plan())
    trace = scheduled_workflow_execution_trace_payload(result)
    serialized = json.dumps(trace, sort_keys=True)

    assert trace["trace_type"] == "scheduled_workflow_manual_execution"
    assert trace["execution_performed"] is True
    assert "Dr. Saju Matthew" not in serialized
    assert "Unknown Person" not in serialized
    assert "Family Practice Physician" not in serialized
    assert "GUESTS_CANONICAL.csv" not in serialized
    assert "guest_id" not in serialized
    assert "raw_lookup_results" not in serialized
    assert "response_preview" not in serialized


def test_no_rss_telegram_memory_model_or_background_behavior_is_invoked():
    source = (
        ROOT / "runtime/scheduling/workflow_executor.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "feedparser",
        "telegram",
        "persist_conversation_memory",
        "persist_runtime_result",
        "openai",
        "subprocess",
        "threading",
        "asyncio",
        "cron",
    )
    lowered = source.lower()

    assert all(term not in lowered for term in forbidden)


def main():
    test_audit_only_scheduled_tasks_do_not_execute()
    test_disabled_scheduled_tasks_do_not_execute()
    test_enabled_allowlisted_smoke_task_can_execute_manually()
    test_intended_scheduled_news_workflows_are_allowlisted()
    test_operator_enabled_daily_news_briefing_is_not_rejected_by_allowlist()
    test_unknown_non_allowlisted_workflows_fail_closed()
    test_execution_result_is_content_safe()
    test_no_rss_telegram_memory_model_or_background_behavior_is_invoked()
    print("PASS scheduled workflow executor")


if __name__ == "__main__":
    main()
