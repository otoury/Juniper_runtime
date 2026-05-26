from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEDULED_WORKFLOW_AUDIT_LOG_PATH = Path(
    "logs/scheduled_workflow_audit.jsonl"
)
SAFE_AUDIT_SUMMARY_KEYS = {
    "attempted",
    "audit_only",
    "checks",
    "context_materialized",
    "disabled",
    "dry_run_plan",
    "enabled",
    "external_call_performed",
    "external_network_fetch_blocked",
    "external_network_fetch_reason",
    "failed",
    "failed_count",
    "fetch_status_counts",
    "fetched",
    "fetched_count",
    "execution_status",
    "failed_lookup_count",
    "governance_state",
    "injected_block_count",
    "injection_allowed",
    "known_guest",
    "local_cache_hit",
    "local_cache_item_count",
    "local_cache_operation_allowed",
    "local_cache_read_allowed",
    "local_cache_synthesis_allowed",
    "lookup_status_counts",
    "known_guest_success",
    "no_match",
    "records_returned",
    "render_allowed",
    "render_mode",
    "request_created",
    "skipped",
    "skipped_reasons",
    "skipped_count",
    "source_count",
    "source_governance_counts",
    "successful_lookup_count",
    "success",
    "total_entry_count",
    "unknown_guest",
    "unknown_guest_fail_closed",
    "workflow",
}
FORBIDDEN_AUDIT_KEYS = {
    "feed",
    "guest_id",
    "message",
    "messages",
    "model_messages",
    "prompt",
    "raw_database_path",
    "raw_guest_data",
    "raw_lookup_results",
    "rss",
    "semantic_operation",
    "telegram",
}


def build_scheduled_workflow_audit_record(
    result: Any,
    *,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    event_time = timestamp or datetime.now(timezone.utc)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    else:
        event_time = event_time.astimezone(timezone.utc)

    return {
        "timestamp": event_time.isoformat(),
        "task_id": _safe_string(getattr(result, "task_id", "")),
        "agent": _safe_string(getattr(result, "agent", "")),
        "workflow": _safe_string(getattr(result, "workflow", "")),
        "binding_id": _safe_string(getattr(result, "binding_id", "")),
        "governance_state": _safe_string(
            getattr(result, "governance_state", "")
        ),
        "execution_mode": _safe_string(
            getattr(result, "execution_mode", "")
        ),
        "execution_status": _safe_string(
            getattr(result, "execution_status", "")
        ),
        "execution_performed": bool(
            getattr(result, "execution_performed", False)
        ),
        "skipped_reasons": _safe_string_list(
            getattr(result, "skipped_reasons", ())
        ),
        "duration_ms": _safe_non_negative_int(
            getattr(result, "duration_ms", 0)
        ),
        "audit_summary": _safe_audit_summary(
            getattr(result, "audit_summary", {})
        ),
        "operator_diagnostics": _safe_operator_diagnostics(
            getattr(result, "operator_diagnostics", {})
        ),
    }


def append_scheduled_workflow_audit_record(
    result: Any,
    *,
    audit_path: str | Path = SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    record = build_scheduled_workflow_audit_record(
        result,
        timestamp=timestamp,
    )
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return record


def load_scheduled_workflow_audit_records(
    audit_path: str | Path = SCHEDULED_WORKFLOW_AUDIT_LOG_PATH,
) -> tuple[dict[str, Any], ...]:
    path = Path(audit_path)
    if not path.exists():
        return ()
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return tuple(records)


def _safe_audit_summary(value: Any) -> dict[str, Any]:
    safe = _safe_value(value)
    return safe if isinstance(safe, dict) else {}


def _safe_operator_diagnostics(value: Any) -> dict[str, Any]:
    safe = _safe_diagnostic_value(value)
    return safe if isinstance(safe, dict) else {}


def _safe_diagnostic_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            normalized = key.strip()
            if (
                not normalized
                or normalized.lower() in FORBIDDEN_AUDIT_KEYS
            ):
                continue
            safe_item = _safe_diagnostic_value(item)
            if safe_item is not None:
                safe[normalized] = safe_item
        return safe
    if isinstance(value, list) or isinstance(value, tuple):
        return [
            item
            for item in (_safe_diagnostic_value(item) for item in value)
            if item is not None
        ]
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            normalized = key.strip()
            if (
                not normalized
                or normalized not in SAFE_AUDIT_SUMMARY_KEYS
                or normalized.lower() in FORBIDDEN_AUDIT_KEYS
            ):
                continue
            safe_item = _safe_value(item)
            if safe_item is not None:
                safe[normalized] = safe_item
        return safe
    if isinstance(value, list) or isinstance(value, tuple):
        return [
            item
            for item in (_safe_value(item) for item in value)
            if item is not None
        ]
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _safe_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _safe_non_negative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return 0
    return value


__all__ = [
    "SCHEDULED_WORKFLOW_AUDIT_LOG_PATH",
    "append_scheduled_workflow_audit_record",
    "build_scheduled_workflow_audit_record",
    "load_scheduled_workflow_audit_records",
]
