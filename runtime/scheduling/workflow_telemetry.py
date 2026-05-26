from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from runtime.scheduling.workflow_audit import (
    SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
    load_scheduled_workflow_audit_records,
)
from runtime.scheduling.workflow_orchestration import (
    ScheduledWorkflowExecutionPlan,
    resolve_due_scheduled_workflows,
)
from runtime.scheduling.cadence_diagnostics import (
    build_run_staleness_diagnostics,
    build_schedule_cadence_diagnostics,
)
from runtime.telemetry_manager import report_event


SCHEDULED_EXECUTOR_STATUS_LOG_PATH = Path(
    "logs/scheduled_executor_status.jsonl"
)
DEFAULT_HEARTBEAT_MIN_INTERVAL_SECONDS = 300
MAX_STATUS_RECORDS = 200
MAX_CRON_LOOKAHEAD_DAYS = 366


@dataclass
class ScheduledExecutorTelemetryState:
    last_heartbeat_at: datetime | None = None


def emit_scheduled_executor_started(
    *,
    agent: str,
    timestamp: datetime,
    poll_interval_seconds: int,
    max_iterations: int,
    task_count: int,
    enabled_task_count: int,
    status_path: str | Path = SCHEDULED_EXECUTOR_STATUS_LOG_PATH,
    telemetry_enabled: bool = True,
) -> None:
    payload = {
        "agent": agent,
        "timestamp": _iso(timestamp),
        "poll_interval_seconds": poll_interval_seconds,
        "max_iterations": max_iterations,
        "task_count": task_count,
        "enabled_task_count": enabled_task_count,
        "status_path": str(status_path),
    }
    _report("scheduled_executor_started", payload, enabled=telemetry_enabled)


def emit_scheduled_executor_heartbeat(
    *,
    agent: str,
    timestamp: datetime,
    iteration: int,
    declarations: tuple[Any, ...],
    plans: tuple[ScheduledWorkflowExecutionPlan, ...],
    execution_performed_count: int,
    skipped_reasons: tuple[str, ...],
    audit_path: str | Path = SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
    status_path: str | Path = SCHEDULED_EXECUTOR_STATUS_LOG_PATH,
    state: ScheduledExecutorTelemetryState | None = None,
    heartbeat_min_interval_seconds: int = DEFAULT_HEARTBEAT_MIN_INTERVAL_SECONDS,
    telemetry_enabled: bool = True,
) -> bool:
    event_time = _normalize_timestamp(timestamp)
    if state is not None and state.last_heartbeat_at is not None:
        elapsed = (event_time - state.last_heartbeat_at).total_seconds()
        if elapsed < _bounded_heartbeat_interval(heartbeat_min_interval_seconds):
            return False

    payload = _heartbeat_payload(
        agent=agent,
        timestamp=event_time,
        iteration=iteration,
        declarations=declarations,
        plans=plans,
        execution_performed_count=execution_performed_count,
        skipped_reasons=skipped_reasons,
        audit_path=audit_path,
    )
    append_scheduled_executor_status_record(
        payload,
        status_path=status_path,
    )
    _report("scheduled_executor_heartbeat", payload, enabled=telemetry_enabled)
    if state is not None:
        state.last_heartbeat_at = event_time
    return True


def emit_scheduled_task_due(
    *,
    plan: ScheduledWorkflowExecutionPlan,
    timestamp: datetime,
    telemetry_enabled: bool = True,
) -> None:
    _report(
        "scheduled_task_due",
        {
            "timestamp": _iso(timestamp),
            "task_id": plan.task_id,
            "agent": plan.agent,
            "workflow": plan.workflow,
            "binding_id": plan.binding_id,
            "governance_state": plan.governance_state,
            "schedule_type": plan.schedule_type,
            "plan_mode": plan.plan_mode,
            "dry_run": plan.dry_run,
        },
        enabled=telemetry_enabled,
    )


def emit_scheduled_task_completed(
    *,
    result: Any,
    timestamp: datetime,
    telemetry_enabled: bool = True,
) -> None:
    _report(
        "scheduled_task_completed",
        _result_payload(result, timestamp=timestamp),
        enabled=telemetry_enabled,
    )


def emit_scheduled_task_failed(
    *,
    plan: ScheduledWorkflowExecutionPlan,
    timestamp: datetime,
    reason: str,
    telemetry_enabled: bool = True,
) -> None:
    _report(
        "scheduled_task_failed",
        {
            "timestamp": _iso(timestamp),
            "task_id": plan.task_id,
            "agent": plan.agent,
            "workflow": plan.workflow,
            "binding_id": plan.binding_id,
            "governance_state": plan.governance_state,
            "schedule_type": plan.schedule_type,
            "plan_mode": plan.plan_mode,
            "reason": _safe_string(reason),
        },
        enabled=telemetry_enabled,
    )


def append_scheduled_executor_status_record(
    record: dict[str, Any],
    *,
    status_path: str | Path = SCHEDULED_EXECUTOR_STATUS_LOG_PATH,
    max_records: int = MAX_STATUS_RECORDS,
) -> None:
    path = Path(status_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _load_jsonl_records(path)
    records.append(_safe_status_record(record))
    bounded = records[-_bounded_max_records(max_records) :]
    content = "".join(
        json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
        for item in bounded
    )
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def load_scheduled_executor_status_records(
    status_path: str | Path = SCHEDULED_EXECUTOR_STATUS_LOG_PATH,
) -> tuple[dict[str, Any], ...]:
    return tuple(_load_jsonl_records(Path(status_path)))


def _heartbeat_payload(
    *,
    agent: str,
    timestamp: datetime,
    iteration: int,
    declarations: tuple[Any, ...],
    plans: tuple[ScheduledWorkflowExecutionPlan, ...],
    execution_performed_count: int,
    skipped_reasons: tuple[str, ...],
    audit_path: str | Path,
) -> dict[str, Any]:
    enabled = tuple(
        declaration
        for declaration in declarations
        if getattr(declaration, "governance_state", "") == "enabled"
    )
    return {
        "status_type": "scheduled_executor_heartbeat",
        "timestamp": timestamp.isoformat(),
        "agent": agent,
        "iteration": iteration,
        "loaded_task_count": len(declarations),
        "enabled_task_count": len(enabled),
        "due_task_ids": [plan.task_id for plan in plans],
        "execution_performed_count": execution_performed_count,
        "skipped_reasons": list(skipped_reasons),
        "enabled_tasks": [
            _enabled_task_status(
                declaration,
                now=timestamp,
                audit_path=audit_path,
            )
            for declaration in enabled
        ],
    }


def _enabled_task_status(
    declaration: Any,
    *,
    now: datetime,
    audit_path: str | Path,
) -> dict[str, Any]:
    last_run = _last_run_at(
        task_id=getattr(declaration, "id", ""),
        audit_path=audit_path,
    )
    next_due = _next_due_at(declaration, now=now)
    cadence_diagnostics = build_schedule_cadence_diagnostics(declaration)
    staleness = build_run_staleness_diagnostics(
        last_run_at=last_run,
        now=now,
        cadence_seconds=cadence_diagnostics["cadence_seconds"],
    )
    return {
        "task_id": _safe_string(getattr(declaration, "id", "")),
        "agent": _safe_string(getattr(declaration, "agent", "")),
        "workflow": _safe_string(getattr(declaration, "workflow", "")),
        "binding_id": _safe_string(getattr(declaration, "binding_id", "")),
        "governance_state": _safe_string(
            getattr(declaration, "governance_state", "")
        ),
        "schedule_type": _safe_string(getattr(declaration, "schedule_type", "")),
        "cadence": cadence_diagnostics["cadence"],
        "cadence_seconds": cadence_diagnostics["cadence_seconds"],
        "last_run_at": last_run,
        "next_due_at": next_due.isoformat() if next_due else None,
        "staleness": staleness,
        "manifest_path": _safe_string(getattr(declaration, "manifest_path", "")),
    }


def _last_run_at(*, task_id: str, audit_path: str | Path) -> str | None:
    records = load_scheduled_workflow_audit_records(audit_path)
    for record in reversed(records):
        if (
            record.get("task_id") == task_id
            and record.get("execution_performed") is True
            and isinstance(record.get("timestamp"), str)
        ):
            return record["timestamp"]
    return None


def _next_due_at(declaration: Any, *, now: datetime) -> datetime | None:
    if getattr(declaration, "governance_state", "") == "disabled":
        return None
    schedule_type = getattr(declaration, "schedule_type", "")
    if schedule_type == "interval":
        return _next_interval_due_at(declaration, now=now)
    if schedule_type == "cron":
        return _next_cron_due_at(declaration, now=now)
    return None


def _next_interval_due_at(declaration: Any, *, now: datetime) -> datetime | None:
    every_ms = getattr(declaration, "schedule", {}).get("every_ms")
    if not isinstance(every_ms, int) or isinstance(every_ms, bool) or every_ms < 1:
        return None
    timestamp_ms = int(now.timestamp() * 1000)
    remainder = timestamp_ms % every_ms
    next_ms = timestamp_ms if remainder == 0 else timestamp_ms + every_ms - remainder
    return datetime.fromtimestamp(next_ms / 1000, tz=timezone.utc)


def _next_cron_due_at(declaration: Any, *, now: datetime) -> datetime | None:
    cursor = now.replace(second=0, microsecond=0)
    if cursor < now:
        cursor += timedelta(minutes=1)
    deadline = cursor + timedelta(days=MAX_CRON_LOOKAHEAD_DAYS)
    while cursor <= deadline:
        resolutions = resolve_due_scheduled_workflows((declaration,), now=cursor)
        if resolutions and resolutions[0].due:
            return cursor
        cursor += timedelta(minutes=1)
    return None


def _result_payload(result: Any, *, timestamp: datetime) -> dict[str, Any]:
    return {
        "timestamp": _iso(timestamp),
        "task_id": _safe_string(getattr(result, "task_id", "")),
        "agent": _safe_string(getattr(result, "agent", "")),
        "workflow": _safe_string(getattr(result, "workflow", "")),
        "binding_id": _safe_string(getattr(result, "binding_id", "")),
        "governance_state": _safe_string(
            getattr(result, "governance_state", "")
        ),
        "execution_mode": _safe_string(getattr(result, "execution_mode", "")),
        "execution_status": _safe_string(
            getattr(result, "execution_status", "")
        ),
        "execution_performed": bool(
            getattr(result, "execution_performed", False)
        ),
        "skipped_reasons": [
            _safe_string(reason)
            for reason in getattr(result, "skipped_reasons", ())
            if _safe_string(reason)
        ],
        "duration_ms": _safe_non_negative_int(getattr(result, "duration_ms", 0)),
    }


def _report(event_type: str, payload: dict[str, Any], *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        report_event("scheduled_executor", event_type, payload)
    except Exception:
        pass


def _safe_status_record(record: dict[str, Any]) -> dict[str, Any]:
    return _safe_json_value(record) if isinstance(record, dict) else {}


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                continue
            safe_item = _safe_json_value(item)
            if safe_item is not None:
                safe[key.strip()] = safe_item
        return safe
    if isinstance(value, list) or isinstance(value, tuple):
        return [
            item
            for item in (_safe_json_value(item) for item in value)
            if item is not None
        ]
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _normalize_timestamp(value).isoformat()


def _safe_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else str(value)


def _safe_non_negative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return value


def _bounded_heartbeat_interval(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return DEFAULT_HEARTBEAT_MIN_INTERVAL_SECONDS
    return value


def _bounded_max_records(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return MAX_STATUS_RECORDS
    return min(value, MAX_STATUS_RECORDS)


__all__ = [
    "DEFAULT_HEARTBEAT_MIN_INTERVAL_SECONDS",
    "MAX_STATUS_RECORDS",
    "SCHEDULED_EXECUTOR_STATUS_LOG_PATH",
    "ScheduledExecutorTelemetryState",
    "append_scheduled_executor_status_record",
    "emit_scheduled_executor_heartbeat",
    "emit_scheduled_executor_started",
    "emit_scheduled_task_completed",
    "emit_scheduled_task_due",
    "emit_scheduled_task_failed",
    "load_scheduled_executor_status_records",
]
