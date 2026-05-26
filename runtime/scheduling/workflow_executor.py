from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from runtime.ingestion.source_audit import SOURCE_INGESTION_AUDIT_LOG_PATH
from runtime.ingestion.source_execution import FetchFunction
from runtime.ingestion.source_item_store import SOURCE_ITEM_STORE_PATH
from runtime.execution_classes import (
    EXECUTION_CLASS_EXTERNAL_NETWORK_FETCH,
    evaluate_execution_class_dry_run,
)
from runtime.scheduling.workflow_audit import (
    SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
    append_scheduled_workflow_audit_record,
)
from runtime.scheduling.workflow_orchestration import (
    PLAN_MODE_DRY_RUN,
    ScheduledWorkflowExecutionPlan,
)
from runtime.scheduling.workflow_diagnostics import (
    build_scheduled_workflow_execution_diagnostics,
    scheduler_execution_block_reasons,
)


EXECUTION_MODE_MANUAL = "manual"
EXECUTION_MODE_SCHEDULED = "scheduled"
EXECUTION_STATUS_EXECUTED = "executed"
EXECUTION_STATUS_SKIPPED = "skipped"
ALLOWLISTED_WORKFLOW = "alexis_booking_workflow_smoke_check"
ALLOWLISTED_WORKFLOWS = frozenset(
    {
        "alexis_daily_news_briefing",
        "alexis_booking_workflow_smoke_check",
        "alexis_rss_feed_check",
    }
)


@dataclass(frozen=True)
class ScheduledWorkflowExecutionResult:
    task_id: str
    agent: str
    workflow: str
    binding_id: str
    governance_state: str
    execution_mode: str
    source_plan_mode: str
    allowlisted: bool
    execution_status: str
    execution_performed: bool
    skipped_reasons: tuple[str, ...]
    duration_ms: int
    audit_summary: dict[str, Any]
    operator_diagnostics: dict[str, Any]

    def to_trace(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "workflow": self.workflow,
            "binding_id": self.binding_id,
            "governance_state": self.governance_state,
            "execution_mode": self.execution_mode,
            "source_plan_mode": self.source_plan_mode,
            "allowlisted": self.allowlisted,
            "execution_status": self.execution_status,
            "execution_performed": self.execution_performed,
            "skipped_reasons": list(self.skipped_reasons),
            "duration_ms": self.duration_ms,
            "audit_summary": dict(self.audit_summary),
            "operator_diagnostics": dict(self.operator_diagnostics),
        }


def execute_scheduled_workflow_manually(
    plan: ScheduledWorkflowExecutionPlan,
    *,
    execution_mode: str = EXECUTION_MODE_MANUAL,
    audit_path: str | Path = SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
    source_audit_path: str | Path = SOURCE_INGESTION_AUDIT_LOG_PATH,
    source_item_store_path: str | Path = SOURCE_ITEM_STORE_PATH,
    source_fetch_fn: FetchFunction | None = None,
    write_audit: bool = True,
) -> ScheduledWorkflowExecutionResult:
    started_at = perf_counter()
    mode = _execution_mode(execution_mode)
    if plan.governance_state == "disabled":
        return _finalize(
            _skipped(
                plan,
                "governance_disabled",
                execution_mode=mode,
                started_at=started_at,
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    if plan.governance_state == "audit_only":
        return _finalize(
            _skipped(
                plan,
                "governance_audit_only",
                execution_mode=mode,
                started_at=started_at,
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    if plan.governance_state != "enabled":
        return _finalize(
            _skipped(
                plan,
                "unsupported_governance_state",
                execution_mode=mode,
                started_at=started_at,
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    if plan.plan_mode != PLAN_MODE_DRY_RUN:
        return _finalize(
            _skipped(
                plan,
                "unsupported_plan_mode",
                execution_mode=mode,
                started_at=started_at,
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    block_reasons = scheduler_execution_block_reasons(plan)
    if block_reasons:
        return _finalize(
            _skipped_many(
                plan,
                block_reasons,
                execution_mode=mode,
                started_at=started_at,
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    if not _is_allowlisted(plan):
        return _finalize(
            _skipped(
                plan,
                "workflow_not_allowlisted",
                execution_mode=mode,
                started_at=started_at,
            ),
            audit_path=audit_path,
            write_audit=write_audit,
        )

    audit_summary = _run_allowlisted_workflow(
        plan,
        source_audit_path=source_audit_path,
        source_item_store_path=source_item_store_path,
        source_fetch_fn=source_fetch_fn,
    )()
    result = ScheduledWorkflowExecutionResult(
        task_id=plan.task_id,
        agent=plan.agent,
        workflow=plan.workflow,
        binding_id=plan.binding_id,
        governance_state=plan.governance_state,
        execution_mode=mode,
        source_plan_mode=plan.plan_mode,
        allowlisted=True,
        execution_status=EXECUTION_STATUS_EXECUTED,
        execution_performed=True,
        skipped_reasons=(),
        duration_ms=_duration_ms(started_at),
        audit_summary=audit_summary,
        operator_diagnostics=build_scheduled_workflow_execution_diagnostics(
            plan,
            execution_mode=mode,
            execution_status=EXECUTION_STATUS_EXECUTED,
            execution_performed=True,
            skipped_reasons=(),
            audit_summary=audit_summary,
        ),
    )
    return _finalize(result, audit_path=audit_path, write_audit=write_audit)


def scheduled_workflow_execution_trace_payload(
    result: ScheduledWorkflowExecutionResult,
) -> dict[str, Any]:
    return {
        "trace_type": "scheduled_workflow_manual_execution",
        **result.to_trace(),
    }


def _is_allowlisted(plan: ScheduledWorkflowExecutionPlan) -> bool:
    return (
        plan.agent == "alexis"
        and plan.workflow in ALLOWLISTED_WORKFLOWS
        and plan.binding_id == plan.workflow
        and plan.task_id == plan.workflow
    )


def _run_allowlisted_workflow(
    plan: ScheduledWorkflowExecutionPlan,
    *,
    source_audit_path: str | Path,
    source_item_store_path: str | Path,
    source_fetch_fn: FetchFunction | None,
) -> Callable[[], dict[str, Any]]:
    workflow = plan.workflow
    if workflow == "alexis_daily_news_briefing":
        return lambda: _run_alexis_daily_news_briefing(
            plan=plan,
            source_item_store_path=source_item_store_path,
        )
    if workflow == "alexis_booking_workflow_smoke_check":
        return _run_alexis_booking_workflow_smoke_check
    if workflow == "alexis_rss_feed_check":
        return lambda: _run_alexis_rss_feed_check(
            plan=plan,
            source_audit_path=source_audit_path,
            source_item_store_path=source_item_store_path,
            source_fetch_fn=source_fetch_fn,
        )
    raise ValueError("workflow is not allowlisted")


def _run_alexis_daily_news_briefing(
    *,
    plan: ScheduledWorkflowExecutionPlan,
    source_item_store_path: str | Path,
) -> dict[str, Any]:
    from agents.alexis.workflows.latest_news_workflow import (
        maybe_run_latest_news_workflow,
    )

    result = maybe_run_latest_news_workflow(
        text="latest news",
        store_path=source_item_store_path,
        workflow_dry_run=plan.dry_run,
    )
    cache_summary = _rss_cache_summary(result)
    return {
        "workflow": "alexis_daily_news_briefing",
        "execution_status": "success",
        "dry_run_plan": plan.plan_mode == PLAN_MODE_DRY_RUN,
        "local_cache_operation_allowed": cache_summary[
            "local_cache_operation_allowed"
        ],
        "local_cache_read_allowed": cache_summary["local_cache_read_allowed"],
        "local_cache_synthesis_allowed": cache_summary[
            "local_cache_synthesis_allowed"
        ],
        "local_cache_hit": cache_summary["local_cache_hit"],
        "local_cache_item_count": cache_summary["local_cache_item_count"],
        "external_network_fetch_blocked": True,
        "external_network_fetch_reason": "daily_briefing_uses_local_cache_only",
        "external_call_performed": False,
    }


def _run_alexis_booking_workflow_smoke_check() -> dict[str, Any]:
    from tools.alexis_booking_workflow_smoke import smoke_output

    output = smoke_output(diagnostics=True)
    diagnostics = output.get("lookup_diagnostics", {})
    known = _safe_diagnostics(diagnostics.get("known_guest"))
    unknown = _safe_diagnostics(diagnostics.get("unknown_guest"))
    return {
        "workflow": ALLOWLISTED_WORKFLOW,
        "known_guest": known,
        "unknown_guest": unknown,
        "checks": {
            "known_guest_success": known.get("execution_status") == "success",
            "unknown_guest_fail_closed": (
                unknown.get("execution_status") == "failed"
            ),
        },
    }


def _run_alexis_rss_feed_check(
    *,
    plan: ScheduledWorkflowExecutionPlan,
    source_audit_path: str | Path,
    source_item_store_path: str | Path,
    source_fetch_fn: FetchFunction | None,
) -> dict[str, Any]:
    from agents.alexis.workflows.latest_news_workflow import (
        maybe_run_latest_news_workflow,
    )
    from runtime.registries.source_ingestion_registry import (
        audit_agent_source_ingestion_declarations,
    )
    from runtime.ingestion.source_execution import fetch_declared_rss_sources

    declarations, errors = audit_agent_source_ingestion_declarations("alexis")
    if errors:
        return {
            "workflow": "alexis_rss_feed_check",
            "execution_status": "failed",
            "source_count": 0,
            "fetched_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "total_entry_count": 0,
            "skipped_reasons": ["source_declaration_validation_failed"],
        }

    owned_sources = tuple(
        declaration
        for declaration in declarations
        if declaration.owning_agent == "alexis"
    )
    cache_result = maybe_run_latest_news_workflow(
        text="latest news",
        store_path=source_item_store_path,
        workflow_dry_run=plan.dry_run,
    )
    cache_summary = _rss_cache_summary(cache_result)
    fetch_decision = evaluate_execution_class_dry_run(
        EXECUTION_CLASS_EXTERNAL_NETWORK_FETCH,
        dry_run=plan.dry_run,
    )
    if not fetch_decision.allowed:
        return {
            "workflow": "alexis_rss_feed_check",
            "execution_status": "success",
            "source_count": len(owned_sources),
            "fetched_count": 0,
            "failed_count": 0,
            "skipped_count": len(owned_sources),
            "total_entry_count": 0,
            "fetch_status_counts": {"skipped": len(owned_sources)},
            "skipped_reasons": [fetch_decision.reason],
            "dry_run_plan": plan.plan_mode == PLAN_MODE_DRY_RUN,
            "local_cache_operation_allowed": cache_summary[
                "local_cache_operation_allowed"
            ],
            "local_cache_read_allowed": cache_summary["local_cache_read_allowed"],
            "local_cache_synthesis_allowed": cache_summary[
                "local_cache_synthesis_allowed"
            ],
            "local_cache_hit": cache_summary["local_cache_hit"],
            "local_cache_item_count": cache_summary["local_cache_item_count"],
            "external_network_fetch_blocked": True,
            "external_network_fetch_reason": fetch_decision.reason,
            "external_call_performed": False,
        }

    results = fetch_declared_rss_sources(
        owned_sources,
        fetch_fn=source_fetch_fn,
        audit_path=str(source_audit_path),
        item_store_path=str(source_item_store_path),
    )
    status_counts = _count_strings(result.fetch_status for result in results)
    governance_counts = _count_strings(
        result.governance_state for result in results
    )
    return {
        "workflow": "alexis_rss_feed_check",
        "execution_status": "success",
        "source_count": len(results),
        "fetched_count": status_counts.get("fetched", 0),
        "failed_count": status_counts.get("failed", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "total_entry_count": sum(result.entry_count for result in results),
        "fetch_status_counts": status_counts,
        "source_governance_counts": governance_counts,
        "skipped_reasons": _unique_skipped_reasons(results),
        "dry_run_plan": plan.plan_mode == PLAN_MODE_DRY_RUN,
        "local_cache_operation_allowed": cache_summary[
            "local_cache_operation_allowed"
        ],
        "local_cache_read_allowed": cache_summary["local_cache_read_allowed"],
        "local_cache_synthesis_allowed": cache_summary[
            "local_cache_synthesis_allowed"
        ],
        "local_cache_hit": cache_summary["local_cache_hit"],
        "local_cache_item_count": cache_summary["local_cache_item_count"],
        "external_network_fetch_blocked": False,
        "external_network_fetch_reason": "",
        "external_call_performed": any(result.fetch_performed for result in results),
    }


def _rss_cache_summary(value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "local_cache_operation_allowed": False,
            "local_cache_read_allowed": False,
            "local_cache_synthesis_allowed": False,
            "local_cache_hit": False,
            "local_cache_item_count": 0,
        }
    authorization = getattr(value, "cache_authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}
    class_allowed = authorization.get("execution_class_allowed") is True
    cache_hit = bool(getattr(value, "cache_hit", False))
    return {
        "local_cache_operation_allowed": class_allowed,
        "local_cache_read_allowed": class_allowed,
        "local_cache_synthesis_allowed": class_allowed and cache_hit,
        "local_cache_hit": cache_hit,
        "local_cache_item_count": _safe_non_negative_int(
            getattr(value, "item_count", 0)
        ),
    }


def _safe_diagnostics(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "attempted": value.get("attempted"),
        "request_created": value.get("request_created"),
        "governance_state": value.get("governance_state"),
        "execution_status": value.get("execution_status"),
        "lookup_status_counts": _safe_string_int_map(
            value.get("lookup_status_counts")
        ),
        "successful_lookup_count": value.get("successful_lookup_count"),
        "failed_lookup_count": value.get("failed_lookup_count"),
        "records_returned": value.get("records_returned"),
        "context_materialized": value.get("context_materialized"),
        "render_allowed": value.get("render_allowed"),
        "render_mode": value.get("render_mode"),
        "injection_allowed": value.get("injection_allowed"),
        "injected_block_count": value.get("injected_block_count"),
        "skipped_reasons": _safe_string_list(value.get("skipped_reasons")),
    }


def _safe_string_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key.strip(): item
        for key, item in value.items()
        if (
            isinstance(key, str)
            and key.strip()
            and isinstance(item, int)
            and not isinstance(item, bool)
        )
    }


def _count_strings(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


def _unique_skipped_reasons(values: Any) -> list[str]:
    reasons = []
    for value in values:
        for reason in getattr(value, "skipped_reasons", ()):
            if isinstance(reason, str) and reason and reason not in reasons:
                reasons.append(reason)
    return reasons


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _safe_non_negative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _skipped(
    plan: ScheduledWorkflowExecutionPlan,
    reason: str,
    *,
    execution_mode: str = EXECUTION_MODE_MANUAL,
    started_at: float | None = None,
) -> ScheduledWorkflowExecutionResult:
    return _skipped_many(
        plan,
        (reason,),
        execution_mode=execution_mode,
        started_at=started_at,
    )


def _skipped_many(
    plan: ScheduledWorkflowExecutionPlan,
    reasons: tuple[str, ...],
    *,
    execution_mode: str = EXECUTION_MODE_MANUAL,
    started_at: float | None = None,
) -> ScheduledWorkflowExecutionResult:
    mode = _execution_mode(execution_mode)
    return ScheduledWorkflowExecutionResult(
        task_id=plan.task_id,
        agent=plan.agent,
        workflow=plan.workflow,
        binding_id=plan.binding_id,
        governance_state=plan.governance_state,
        execution_mode=mode,
        source_plan_mode=plan.plan_mode,
        allowlisted=_is_allowlisted(plan),
        execution_status=EXECUTION_STATUS_SKIPPED,
        execution_performed=False,
        skipped_reasons=tuple(reasons),
        duration_ms=_duration_ms(started_at),
        audit_summary={},
        operator_diagnostics=build_scheduled_workflow_execution_diagnostics(
            plan,
            execution_mode=mode,
            execution_status=EXECUTION_STATUS_SKIPPED,
            execution_performed=False,
            skipped_reasons=reasons,
            audit_summary={},
        ),
    )


def _duration_ms(started_at: float | None) -> int:
    if started_at is None:
        return 0
    return max(0, int((perf_counter() - started_at) * 1000))


def _execution_mode(value: str) -> str:
    return (
        value
        if value in {EXECUTION_MODE_MANUAL, EXECUTION_MODE_SCHEDULED}
        else EXECUTION_MODE_MANUAL
    )


def _finalize(
    result: ScheduledWorkflowExecutionResult,
    *,
    audit_path: str | Path,
    write_audit: bool,
) -> ScheduledWorkflowExecutionResult:
    if write_audit:
        append_scheduled_workflow_audit_record(result, audit_path=audit_path)
    return result


__all__ = [
    "ALLOWLISTED_WORKFLOW",
    "ALLOWLISTED_WORKFLOWS",
    "EXECUTION_MODE_MANUAL",
    "EXECUTION_MODE_SCHEDULED",
    "EXECUTION_STATUS_EXECUTED",
    "EXECUTION_STATUS_SKIPPED",
    "ScheduledWorkflowExecutionResult",
    "execute_scheduled_workflow_manually",
    "scheduled_workflow_execution_trace_payload",
]
