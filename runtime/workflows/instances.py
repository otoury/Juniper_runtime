from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.atomic_write import atomic_write_text
from runtime.workflows.suspension import (
    APPROVAL_STATE_PENDING,
    WorkflowSuspensionState,
)


DEFAULT_WORKFLOW_INSTANCE_STORE_PATH = Path(
    "workflow/instances/suspended_workflows.json"
)
DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH = Path(
    "workflow/instances/workflow_transition_audit.jsonl"
)
STATUS_SUSPENDED = "suspended"
STATUS_APPROVED_PENDING_RESUME = "approved_pending_resume"
STATUS_TERMINATED_DENIED = "terminated_denied"
STATUS_RESUMED_PENDING_EXECUTION = "resumed_pending_execution"
APPROVAL_STATE_APPROVED = "approved"
APPROVAL_STATE_DENIED = "denied"
TRANSITION_INSTANCE_SUSPENDED = "instance_suspended"
TRANSITION_INSTANCE_REPLACED = "instance_replaced"
TRANSITION_INSTANCE_UPDATED = "instance_updated"


def build_suspended_workflow_instance(
    suspension_state: WorkflowSuspensionState | dict[str, Any],
    *,
    workflow_instance_id: str | None = None,
    updated_at: datetime | None = None,
) -> dict[str, Any] | None:
    state = _state_record(suspension_state)
    if not state:
        return None

    workflow_id = _string(state.get("workflow_id"))
    owning_agent = _string(state.get("owning_agent"))
    step_id = _string(state.get("step_id"))
    operation_id = _string(state.get("operation_id"))
    continuation_id = _string(state.get("continuation_id"))
    approval_state = _string(state.get("approval_state"))
    if not workflow_id or not owning_agent or not step_id or not continuation_id:
        return None
    if approval_state != APPROVAL_STATE_PENDING:
        return None
    if state.get("suspended") is not True:
        return None
    if state.get("delivery_performed") is not False:
        return None

    instance_id = (
        workflow_instance_id.strip()
        if isinstance(workflow_instance_id, str) and workflow_instance_id.strip()
        else _workflow_instance_id(workflow_id, continuation_id)
    )
    timestamp = _timestamp(updated_at)
    created_at = _string(state.get("created_at")) or timestamp
    provenance = {
        **_safe_mapping(state.get("provenance")),
        "workflow_instance_id": instance_id,
    }
    return {
        "workflow_id": workflow_id,
        "owning_agent": owning_agent,
        "workflow_instance_id": instance_id,
        "continuation_id": continuation_id,
        "step_id": step_id,
        "operation_id": operation_id,
        "status": STATUS_SUSPENDED,
        "approval_state": APPROVAL_STATE_PENDING,
        "suspended": True,
        "action_refs": _string_list(state.get("action_refs")),
        "artifact_refs": _string_list(state.get("artifact_refs")),
        "created_at": created_at,
        "updated_at": timestamp,
        "provenance": provenance,
    }


def persist_suspended_workflow_instance(
    suspension_state: WorkflowSuspensionState | dict[str, Any],
    *,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    transition_audit_path: str | Path | None = DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH,
    workflow_instance_id: str | None = None,
    updated_at: datetime | None = None,
) -> dict[str, Any] | None:
    instance = build_suspended_workflow_instance(
        suspension_state,
        workflow_instance_id=workflow_instance_id,
        updated_at=updated_at,
    )
    if instance is None:
        return None

    path = Path(store_path)
    records = list_workflow_instances(store_path=path)
    replaced = False
    audit_record: dict[str, Any] | None = None
    for index, record in enumerate(records):
        if record.get("continuation_id") == instance["continuation_id"]:
            lineage_record = build_workflow_state_lineage_record(
                previous_instance=record,
                new_instance=instance,
                transition_type=TRANSITION_INSTANCE_REPLACED,
                transitioned_at=updated_at,
            )
            instance["state_lineage"] = [
                *record.get("state_lineage", []),
                lineage_record,
            ]
            records[index] = instance
            audit_record = lineage_record
            replaced = True
            break

    if not replaced:
        lineage_record = build_workflow_state_lineage_record(
            previous_instance=None,
            new_instance=instance,
            transition_type=TRANSITION_INSTANCE_SUSPENDED,
            transitioned_at=updated_at,
        )
        instance["state_lineage"] = [lineage_record]
        records.append(instance)
        audit_record = lineage_record

    payload = {
        "version": 1,
        "instances": records,
    }
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resolved_audit_path = _resolve_transition_audit_path(
        store_path=path,
        audit_path=transition_audit_path,
    )
    if audit_record is not None and resolved_audit_path is not None:
        append_workflow_transition_audit_record(
            audit_record,
            audit_path=resolved_audit_path,
        )
    return instance


def get_workflow_instance_by_continuation_id(
    continuation_id: str,
    *,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
) -> dict[str, Any] | None:
    wanted = _string(continuation_id)
    if not wanted:
        return None

    for instance in list_workflow_instances(store_path=store_path):
        if instance.get("continuation_id") == wanted:
            return instance

    return None


def get_workflow_instance_by_instance_id(
    workflow_instance_id: str,
    *,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
) -> dict[str, Any] | None:
    wanted = _string(workflow_instance_id)
    if not wanted:
        return None

    for instance in list_workflow_instances(store_path=store_path):
        if instance.get("workflow_instance_id") == wanted:
            return instance

    return None


def update_workflow_instance(
    workflow_instance_id: str,
    updates: dict[str, Any],
    *,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
    transition_audit_path: str | Path | None = DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH,
    transition_type: str = TRANSITION_INSTANCE_UPDATED,
) -> dict[str, Any] | None:
    instance_id = _string(workflow_instance_id)
    if not instance_id or not isinstance(updates, dict):
        return None

    path = Path(store_path)
    records = list_workflow_instances(store_path=path)
    changed: dict[str, Any] | None = None
    audit_record: dict[str, Any] | None = None
    for index, record in enumerate(records):
        if record.get("workflow_instance_id") != instance_id:
            continue

        merged = dict(record)
        for key, value in updates.items():
            if key == "provenance" and isinstance(value, dict):
                merged[key] = _safe_mapping(value)
            elif key in {"action_refs", "artifact_refs"}:
                merged[key] = _string_list(value)
            elif key == "suspended":
                merged[key] = value is True
            elif isinstance(value, (str, int, float, bool)) or value is None:
                merged[key] = value
        normalized = _normalize_instance(merged)
        if normalized is None:
            return None
        lineage_record = build_workflow_state_lineage_record(
            previous_instance=record,
            new_instance=normalized,
            transition_type=transition_type,
            transitioned_at=_datetime_from_iso(_string(updates.get("updated_at"))),
        )
        normalized["state_lineage"] = [
            *record.get("state_lineage", []),
            lineage_record,
        ]
        records[index] = normalized
        audit_record = lineage_record
        changed = normalized
        break

    if changed is None:
        return None

    payload = {
        "version": 1,
        "instances": records,
    }
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resolved_audit_path = _resolve_transition_audit_path(
        store_path=path,
        audit_path=transition_audit_path,
    )
    if audit_record is not None and resolved_audit_path is not None:
        append_workflow_transition_audit_record(
            audit_record,
            audit_path=resolved_audit_path,
        )
    return changed


def build_workflow_state_lineage_record(
    *,
    previous_instance: dict[str, Any] | None,
    new_instance: dict[str, Any],
    transition_type: str,
    transitioned_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(transitioned_at)
    lineage = (
        previous_instance.get("state_lineage", [])
        if isinstance(previous_instance, dict)
        else []
    )
    previous_lineage_id = _latest_lineage_id(lineage)
    sequence = len(lineage) + 1
    base = {
        "version": 1,
        "workflow_id": _string(new_instance.get("workflow_id")),
        "owning_agent": _string(new_instance.get("owning_agent")),
        "workflow_instance_id": _string(new_instance.get("workflow_instance_id")),
        "continuation_id": _string(new_instance.get("continuation_id")),
        "transition_type": _string(transition_type) or TRANSITION_INSTANCE_UPDATED,
        "transition_sequence": sequence,
        "previous_lineage_record_id": previous_lineage_id,
        "from_status": _optional_instance_string(previous_instance, "status"),
        "to_status": _string(new_instance.get("status")),
        "from_approval_state": _optional_instance_string(
            previous_instance,
            "approval_state",
        ),
        "to_approval_state": _string(new_instance.get("approval_state")),
        "from_suspended": (
            previous_instance.get("suspended") is True
            if isinstance(previous_instance, dict)
            else None
        ),
        "to_suspended": new_instance.get("suspended") is True,
        "from_step_id": _optional_instance_string(previous_instance, "step_id"),
        "to_step_id": _string(new_instance.get("step_id")),
        "transitioned_at": timestamp,
        "execution_performed": False,
        "delivery_performed": False,
    }
    base["lineage_record_id"] = _lineage_record_id(base)
    return base


def append_workflow_transition_audit_record(
    record: dict[str, Any],
    *,
    audit_path: str | Path = DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH,
) -> dict[str, Any]:
    safe = _normalize_lineage_record(record)
    if safe is None:
        return {}
    path = Path(audit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return safe


def load_workflow_transition_audit_records(
    audit_path: str | Path = DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH,
) -> tuple[dict[str, Any], ...]:
    path = Path(audit_path)
    if not path.exists():
        return ()
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        normalized = _normalize_lineage_record(value)
        if normalized is not None:
            records.append(normalized)
    return tuple(records)


def workflow_transition_audit_path_for_store(
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
) -> Path:
    path = Path(store_path)
    if path == DEFAULT_WORKFLOW_INSTANCE_STORE_PATH:
        return DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH
    return path.parent / DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH.name


def list_workflow_instances(
    *,
    status: str | None = None,
    store_path: str | Path = DEFAULT_WORKFLOW_INSTANCE_STORE_PATH,
) -> list[dict[str, Any]]:
    records = _read_store(Path(store_path))
    if status is None:
        return records

    wanted = _string(status)
    return [
        record
        for record in records
        if record.get("status") == wanted
    ]


def _read_store(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, dict):
        return []

    raw_instances = data.get("instances")
    if not isinstance(raw_instances, list):
        return []

    records = []
    for item in raw_instances:
        normalized = _normalize_instance(item)
        if normalized is not None:
            records.append(normalized)
    return records


def _resolve_transition_audit_path(
    *,
    store_path: Path,
    audit_path: str | Path | None,
) -> Path | None:
    if audit_path is None:
        return None
    path = Path(audit_path)
    if path == DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH:
        return workflow_transition_audit_path_for_store(store_path)
    return path


def _normalize_instance(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    workflow_id = _string(item.get("workflow_id"))
    owning_agent = _string(item.get("owning_agent"))
    workflow_instance_id = _string(item.get("workflow_instance_id"))
    continuation_id = _string(item.get("continuation_id"))
    step_id = _string(item.get("step_id"))
    operation_id = _string(item.get("operation_id"))
    status = _string(item.get("status"))
    approval_state = _string(item.get("approval_state"))
    if not all(
        (
            workflow_id,
            owning_agent,
            workflow_instance_id,
            continuation_id,
            step_id,
            status,
            approval_state,
        )
    ):
        return None

    return {
        "workflow_id": workflow_id,
        "owning_agent": owning_agent,
        "workflow_instance_id": workflow_instance_id,
        "continuation_id": continuation_id,
        "step_id": step_id,
        "operation_id": operation_id,
        "status": status,
        "approval_state": approval_state,
        "suspended": item.get("suspended") is True,
        "action_refs": _string_list(item.get("action_refs")),
        "artifact_refs": _string_list(item.get("artifact_refs")),
        "created_at": _string(item.get("created_at")),
        "updated_at": _string(item.get("updated_at")),
        "provenance": _safe_mapping(item.get("provenance")),
        "state_lineage": _lineage_records(item.get("state_lineage")),
    }


def _state_record(
    suspension_state: WorkflowSuspensionState | dict[str, Any],
) -> dict[str, Any] | None:
    if isinstance(suspension_state, WorkflowSuspensionState):
        return suspension_state.to_record()
    if isinstance(suspension_state, dict):
        return dict(suspension_state)
    return None


def _workflow_instance_id(workflow_id: str, continuation_id: str) -> str:
    payload = json.dumps(
        {
            "workflow_id": workflow_id,
            "continuation_id": continuation_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"wfi_{hashlib.sha256(payload).hexdigest()[:16]}"


def _lineage_record_id(record: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "workflow_id": record.get("workflow_id"),
            "workflow_instance_id": record.get("workflow_instance_id"),
            "continuation_id": record.get("continuation_id"),
            "transition_type": record.get("transition_type"),
            "transition_sequence": record.get("transition_sequence"),
            "previous_lineage_record_id": record.get("previous_lineage_record_id"),
            "from_status": record.get("from_status"),
            "to_status": record.get("to_status"),
            "from_approval_state": record.get("from_approval_state"),
            "to_approval_state": record.get("to_approval_state"),
            "from_suspended": record.get("from_suspended"),
            "to_suspended": record.get("to_suspended"),
            "from_step_id": record.get("from_step_id"),
            "to_step_id": record.get("to_step_id"),
            "transitioned_at": record.get("transitioned_at"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"wfl_{hashlib.sha256(payload).hexdigest()[:16]}"


def _latest_lineage_id(lineage: Any) -> str | None:
    records = _lineage_records(lineage)
    if not records:
        return None
    return records[-1]["lineage_record_id"]


def _lineage_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records = []
    for item in value:
        normalized = _normalize_lineage_record(item)
        if normalized is not None:
            records.append(normalized)
    return records


def _normalize_lineage_record(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    workflow_id = _string(item.get("workflow_id"))
    workflow_instance_id = _string(item.get("workflow_instance_id"))
    continuation_id = _string(item.get("continuation_id"))
    transition_type = _string(item.get("transition_type"))
    lineage_record_id = _string(item.get("lineage_record_id"))
    if not all(
        (
            workflow_id,
            workflow_instance_id,
            continuation_id,
            transition_type,
            lineage_record_id,
        )
    ):
        return None

    return {
        "version": 1,
        "lineage_record_id": lineage_record_id,
        "workflow_id": workflow_id,
        "owning_agent": _string(item.get("owning_agent")),
        "workflow_instance_id": workflow_instance_id,
        "continuation_id": continuation_id,
        "transition_type": transition_type,
        "transition_sequence": _positive_int(item.get("transition_sequence")),
        "previous_lineage_record_id": _optional_string(
            item.get("previous_lineage_record_id")
        ),
        "from_status": _optional_string(item.get("from_status")),
        "to_status": _string(item.get("to_status")),
        "from_approval_state": _optional_string(item.get("from_approval_state")),
        "to_approval_state": _string(item.get("to_approval_state")),
        "from_suspended": _optional_bool(item.get("from_suspended")),
        "to_suspended": item.get("to_suspended") is True,
        "from_step_id": _optional_string(item.get("from_step_id")),
        "to_step_id": _string(item.get("to_step_id")),
        "transitioned_at": _string(item.get("transitioned_at")),
        "execution_performed": False,
        "delivery_performed": False,
    }


def _optional_instance_string(
    instance: dict[str, Any] | None,
    key: str,
) -> str | None:
    if not isinstance(instance, dict):
        return None
    return _optional_string(instance.get(key))


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _datetime_from_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _safe_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    safe: dict[str, Any] = {}
    for key, item in value.items():
        safe_key = _string(key)
        if not safe_key:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[safe_key] = item
        elif isinstance(item, list):
            safe[safe_key] = _string_list(item)
        elif isinstance(item, tuple):
            safe[safe_key] = _string_list(list(item))
        elif isinstance(item, dict):
            safe[safe_key] = _safe_mapping(item)
    return safe


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _positive_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


__all__ = [
    "APPROVAL_STATE_PENDING",
    "APPROVAL_STATE_APPROVED",
    "APPROVAL_STATE_DENIED",
    "DEFAULT_WORKFLOW_INSTANCE_STORE_PATH",
    "DEFAULT_WORKFLOW_TRANSITION_AUDIT_PATH",
    "STATUS_APPROVED_PENDING_RESUME",
    "STATUS_RESUMED_PENDING_EXECUTION",
    "STATUS_SUSPENDED",
    "STATUS_TERMINATED_DENIED",
    "TRANSITION_INSTANCE_REPLACED",
    "TRANSITION_INSTANCE_SUSPENDED",
    "TRANSITION_INSTANCE_UPDATED",
    "append_workflow_transition_audit_record",
    "build_workflow_state_lineage_record",
    "build_suspended_workflow_instance",
    "get_workflow_instance_by_instance_id",
    "get_workflow_instance_by_continuation_id",
    "load_workflow_transition_audit_records",
    "list_workflow_instances",
    "persist_suspended_workflow_instance",
    "update_workflow_instance",
    "workflow_transition_audit_path_for_store",
]
