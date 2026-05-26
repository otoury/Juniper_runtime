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
from runtime.scheduling.workflow_orchestration import (  # noqa: E402
    build_due_scheduled_workflow_plans,
    build_scheduled_workflow_summary,
    discover_scheduled_workflows,
    resolve_due_scheduled_workflows,
    scheduled_workflow_trace_payload,
)


def alexis_declarations():
    declarations, errors = discover_scheduled_workflows("alexis", root=ROOT)
    assert errors == ()
    return declarations


def write_alexis_manifest(root, declarations):
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


def raw_alexis_declarations():
    data = json.loads(
        (ROOT / "agents/alexis/scheduled_tasks.json").read_text(
            encoding="utf-8"
        )
    )
    return data["task_declarations"]


def test_registry_discovers_alexis_scheduled_tasks():
    declarations = alexis_declarations()

    assert len(declarations) == 4
    assert [declaration.agent for declaration in declarations] == [
        "alexis",
        "alexis",
        "alexis",
        "alexis",
    ]
    assert {
        declaration.id
        for declaration in declarations
    } == {
        "alexis_daily_news_briefing",
        "alexis_rss_feed_check",
        "alexis_guest_db_freshness_audit",
        "alexis_booking_workflow_smoke_check",
    }


def test_due_task_resolver_uses_supplied_timestamps():
    declarations = alexis_declarations()
    monday_0800 = datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc)
    monday_0830 = datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc)

    first = resolve_due_scheduled_workflows(declarations, now=monday_0800)
    second = resolve_due_scheduled_workflows(declarations, now=monday_0830)

    first_due = {resolution.task_id for resolution in first if resolution.due}
    second_due = {resolution.task_id for resolution in second if resolution.due}
    assert first_due == {
        "alexis_rss_feed_check",
        "alexis_guest_db_freshness_audit",
    }
    assert second_due == {
        "alexis_rss_feed_check",
        "alexis_booking_workflow_smoke_check",
    }


def test_enabled_newsroom_rss_interval_is_discovered_and_scheduled():
    declarations = alexis_declarations()
    rss_task = next(
        declaration for declaration in declarations
        if declaration.id == "alexis_rss_feed_check"
    )

    plans = build_due_scheduled_workflow_plans(
        declarations,
        now=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
    )

    rss_plan = next(plan for plan in plans if plan.task_id == "alexis_rss_feed_check")
    assert rss_task.governance_state == "enabled"
    assert rss_task.schedule_type == "interval"
    assert rss_task.schedule["every_ms"] == 1800000
    assert rss_plan.workflow == "alexis_rss_feed_check"
    assert rss_plan.binding_id == "alexis_rss_feed_check"
    assert rss_plan.execution_allowed_by_governance is True
    assert rss_plan.skipped_reasons == ()


def test_disabled_tasks_do_not_produce_executable_plans():
    declarations = alexis_declarations()
    daily_due = datetime(2026, 5, 18, 7, 0, tzinfo=timezone.utc)

    resolutions = resolve_due_scheduled_workflows(declarations, now=daily_due)
    plans = build_due_scheduled_workflow_plans(declarations, now=daily_due)

    daily = next(
        resolution
        for resolution in resolutions
        if resolution.task_id == "alexis_daily_news_briefing"
    )
    interval = next(
        resolution
        for resolution in resolutions
        if resolution.task_id == "alexis_rss_feed_check"
    )
    assert daily.due is False
    assert daily.skipped_reasons == ("governance_disabled",)
    assert interval.due is True
    assert interval.skipped_reasons == ()
    assert all(plan.governance_state != "disabled" for plan in plans)


def test_audit_only_tasks_produce_dry_run_audit_plans_only():
    declarations = alexis_declarations()
    monday_0800 = datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc)

    plans = build_due_scheduled_workflow_plans(declarations, now=monday_0800)

    assert {plan.task_id for plan in plans} == {
        "alexis_rss_feed_check",
        "alexis_guest_db_freshness_audit",
    }
    plan = next(
        item for item in plans if item.task_id == "alexis_guest_db_freshness_audit"
    )
    assert plan.task_id == "alexis_guest_db_freshness_audit"
    assert plan.governance_state == "audit_only"
    assert plan.dry_run is True
    assert plan.execution_allowed_by_governance is False
    assert plan.execution_performed is False
    assert plan.skipped_reasons == ("governance_audit_only",)
    assert plan.semantic_operation == {
        "operation_type": "DATABASE_AUDIT",
        "capability_id": "alexis_guest_db_freshness_audit",
        "produces_artifact": False,
        "external_side_effects_allowed": False,
        "memory_write_allowed": False,
        "requires_approval": False,
    }


def test_enabled_tasks_produce_dry_run_plans_but_are_not_executed():
    declarations = raw_alexis_declarations()
    declarations[0]["governance_state"] = "enabled"

    with TemporaryDirectory() as tmp:
        path = write_alexis_manifest(tmp, declarations)
        loaded, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )
        assert errors == ()
        plans = build_due_scheduled_workflow_plans(
            loaded,
            now=datetime(2026, 5, 18, 7, 0, tzinfo=timezone.utc),
        )

    assert {plan.task_id for plan in plans} == {
        "alexis_daily_news_briefing",
        "alexis_rss_feed_check",
    }
    plan = next(
        item for item in plans if item.task_id == "alexis_daily_news_briefing"
    )
    assert plan.task_id == "alexis_daily_news_briefing"
    assert plan.governance_state == "enabled"
    assert plan.dry_run is True
    assert plan.execution_allowed_by_governance is True
    assert plan.execution_performed is False
    assert plan.semantic_operation["operation_type"] == "NEWS_INGESTION"

    current_daily = next(
        declaration
        for declaration in alexis_declarations()
        if declaration.id == "alexis_daily_news_briefing"
    )
    assert current_daily.governance_state == "disabled"


def test_dry_run_trace_includes_semantic_metadata():
    declarations = alexis_declarations()
    now = datetime(2026, 5, 18, 8, 30, tzinfo=timezone.utc)

    plans = build_due_scheduled_workflow_plans(declarations, now=now)
    trace = scheduled_workflow_trace_payload(plans, now=now)

    semantic_operation = next(
        plan for plan in trace["plans"]
        if plan["task_id"] == "alexis_booking_workflow_smoke_check"
    )["semantic_operation"]
    assert semantic_operation == {
        "operation_type": "SMOKE_CHECK",
        "capability_id": "alexis_booking_workflow_smoke_check",
        "produces_artifact": False,
        "external_side_effects_allowed": False,
        "memory_write_allowed": False,
        "requires_approval": False,
    }


def test_no_external_or_runtime_side_effect_apis_are_invoked():
    source = (
        ROOT / "runtime/scheduling/workflow_orchestration.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "openai",
        "requests",
        "feedparser",
        "telegram",
        "persist_conversation_memory",
        "persist_runtime_result",
        "execute_request",
        "execute_with_fallbacks",
        "subprocess",
        "threading",
        "asyncio",
    )

    lowered = source.lower()
    assert all(term not in lowered for term in forbidden)


def test_trace_and_summary_output_is_content_safe():
    declarations = alexis_declarations()
    now = datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc)
    resolutions = resolve_due_scheduled_workflows(declarations, now=now)
    plans = build_due_scheduled_workflow_plans(declarations, now=now)
    trace = scheduled_workflow_trace_payload(plans, now=now)
    summary = build_scheduled_workflow_summary(resolutions, plans)
    serialized = json.dumps(
        {
            "trace": trace,
            "summary": summary,
        },
        sort_keys=True,
    )

    assert trace["dry_run"] is True
    assert trace["execution_performed"] is False
    assert summary["scheduled_workflows"]["execution_performed"] is False
    assert "expression" not in serialized
    assert "every_ms" not in serialized
    assert "prompt" not in serialized.lower()
    assert "content" not in serialized.lower()
    assert "memory_contents" not in serialized.lower()
    assert "memory_write_allowed" in serialized


def test_unknown_and_malformed_schedules_fail_closed():
    declarations = raw_alexis_declarations()
    declarations[2]["schedule"]["expression"] = "*/5 * * * *"
    declarations[3]["schedule"]["timezone"] = "America/New_York"

    with TemporaryDirectory() as tmp:
        path = write_alexis_manifest(tmp, declarations)
        loaded, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )
        assert errors == ()
        resolutions = resolve_due_scheduled_workflows(
            loaded,
            now=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
        )

    malformed = next(
        resolution
        for resolution in resolutions
        if resolution.task_id == "alexis_guest_db_freshness_audit"
    )
    unknown_timezone = next(
        resolution
        for resolution in resolutions
        if resolution.task_id == "alexis_booking_workflow_smoke_check"
    )
    assert malformed.due is False
    assert malformed.skipped_reasons == ("unsupported_cron_expression",)
    assert unknown_timezone.due is False
    assert unknown_timezone.skipped_reasons == ("unsupported_cron_timezone",)


def main():
    test_registry_discovers_alexis_scheduled_tasks()
    test_due_task_resolver_uses_supplied_timestamps()
    test_enabled_newsroom_rss_interval_is_discovered_and_scheduled()
    test_disabled_tasks_do_not_produce_executable_plans()
    test_audit_only_tasks_produce_dry_run_audit_plans_only()
    test_enabled_tasks_produce_dry_run_plans_but_are_not_executed()
    test_dry_run_trace_includes_semantic_metadata()
    test_no_external_or_runtime_side_effect_apis_are_invoked()
    test_trace_and_summary_output_is_content_safe()
    test_unknown_and_malformed_schedules_fail_closed()
    print("PASS scheduled workflow orchestration")


if __name__ == "__main__":
    main()
