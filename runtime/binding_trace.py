from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any, Callable

from runtime.bindings import (
    AgentBinding,
    BindingResolutionError,
    ROOT,
    resolve_agent_binding,
)


@dataclass(frozen=True)
class PlannedCapabilityTrace:
    request_id: str
    agent_name: str
    shared_capability: str
    semantic_operation: str | None
    expected_output_type: str | None
    resolved_binding: AgentBinding | None
    resolution_status: str
    resolution_error: BindingResolutionError | None
    skills: list[str]
    resources: list[str]
    tone: str | None
    approval_policy: str | bool | None


def trace_planned_capability(
    *,
    request_id: str,
    agent_name: str,
    shared_capability: str,
    semantic_operation: str | None = None,
    expected_output_type: str | None = None,
    root: Path = ROOT,
) -> PlannedCapabilityTrace:
    result = resolve_agent_binding(
        agent_name,
        shared_capability,
        root=root,
    )

    if isinstance(result, BindingResolutionError):
        return PlannedCapabilityTrace(
            request_id=request_id,
            agent_name=agent_name,
            shared_capability=shared_capability,
            semantic_operation=semantic_operation,
            expected_output_type=expected_output_type,
            resolved_binding=None,
            resolution_status="ERROR",
            resolution_error=result,
            skills=[],
            resources=[],
            tone=None,
            approval_policy=None,
        )

    return PlannedCapabilityTrace(
        request_id=request_id,
        agent_name=agent_name,
        shared_capability=shared_capability,
        semantic_operation=semantic_operation,
        expected_output_type=expected_output_type,
        resolved_binding=result,
        resolution_status="OK",
        resolution_error=None,
        skills=result.skills,
        resources=result.resources,
        tone=result.tone,
        approval_policy=result.approval_policy,
    )


def planned_capability_trace_dict(
    trace: PlannedCapabilityTrace,
) -> dict[str, Any]:
    payload = asdict(trace)

    if trace.resolved_binding:
        payload["resolved_binding"]["raw_manifest_path"] = str(
            trace.resolved_binding.raw_manifest_path
        )

    if trace.resolution_error and trace.resolution_error.raw_manifest_path:
        payload["resolution_error"]["raw_manifest_path"] = str(
            trace.resolution_error.raw_manifest_path
        )

    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, list):
        return [_json_safe(item) for item in value]

    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def binding_trace_to_payload(trace: PlannedCapabilityTrace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": trace.request_id,
        "agent": trace.agent_name,
        "shared_capability": trace.shared_capability,
        "semantic_operation": trace.semantic_operation,
        "expected_output_type": trace.expected_output_type,
        "resolution_status": trace.resolution_status,
        "binding": None,
        "error": None,
    }

    if trace.resolved_binding:
        payload["binding"] = {
            "binding_id": trace.resolved_binding.binding_id,
            "skills": list(trace.skills),
            "resources": list(trace.resources),
            "tone": trace.tone,
            "approval_policy": trace.approval_policy,
            "manifest_path": str(trace.resolved_binding.raw_manifest_path),
        }

    if trace.resolution_error:
        payload["error"] = {
            "error_code": trace.resolution_error.error_code,
            "message": trace.resolution_error.message,
            "manifest_path": (
                str(trace.resolution_error.raw_manifest_path)
                if trace.resolution_error.raw_manifest_path
                else None
            ),
            "details": _json_safe(trace.resolution_error.details),
        }

    return _json_safe(payload)


def binding_trace_telemetry_enabled() -> bool:
    return os.getenv("JUNIPER_TRACE_BINDINGS") == "1"


def emit_planned_capability_trace_telemetry(
    *,
    report_event: Callable[..., Any],
    source_bot: str,
    request_id: str,
    agent_name: str,
    shared_capability: str,
    user_id: str | None = None,
    semantic_operation: str | None = None,
    expected_output_type: str | None = None,
    root: Path = ROOT,
) -> PlannedCapabilityTrace | None:
    if not binding_trace_telemetry_enabled():
        return None

    trace = trace_planned_capability(
        request_id=request_id,
        agent_name=agent_name,
        shared_capability=shared_capability,
        semantic_operation=semantic_operation,
        expected_output_type=expected_output_type,
        root=root,
    )
    payload = binding_trace_to_payload(trace)

    if user_id is not None:
        payload["user_id"] = user_id

    try:
        report_event(
            source_bot,
            "planned_capability_trace",
            payload,
            request_id=request_id,
        )
    except Exception:
        pass

    return trace


__all__ = [
    "PlannedCapabilityTrace",
    "binding_trace_telemetry_enabled",
    "binding_trace_to_payload",
    "emit_planned_capability_trace_telemetry",
    "planned_capability_trace_dict",
    "trace_planned_capability",
]
