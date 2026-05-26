from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_INGESTION_AUDIT_LOG_PATH = Path("logs/source_ingestion_audit.jsonl")


def build_source_ingestion_audit_record(
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
        "source_id": _safe_string(getattr(result, "source_id", "")),
        "source_type": _safe_string(getattr(result, "source_type", "")),
        "owning_agent": _safe_string(getattr(result, "owning_agent", "")),
        "governance_state": _safe_string(
            getattr(result, "governance_state", "")
        ),
        "fetch_status": _safe_string(getattr(result, "fetch_status", "")),
        "fetch_performed": bool(getattr(result, "fetch_performed", False)),
        "duration_ms": _safe_non_negative_int(
            getattr(result, "duration_ms", 0)
        ),
        "entry_count": _safe_non_negative_int(
            getattr(result, "entry_count", 0)
        ),
        "skipped_reasons": _safe_string_list(
            getattr(result, "skipped_reasons", ())
        ),
    }


def append_source_ingestion_audit_record(
    result: Any,
    *,
    audit_path: str | Path = SOURCE_INGESTION_AUDIT_LOG_PATH,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    record = build_source_ingestion_audit_record(result, timestamp=timestamp)
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return record


def load_source_ingestion_audit_records(
    audit_path: str | Path = SOURCE_INGESTION_AUDIT_LOG_PATH,
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
    "SOURCE_INGESTION_AUDIT_LOG_PATH",
    "append_source_ingestion_audit_record",
    "build_source_ingestion_audit_record",
    "load_source_ingestion_audit_records",
]
