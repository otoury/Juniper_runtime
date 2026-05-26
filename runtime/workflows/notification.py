from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.workflows.declarations import WorkflowStepDeclaration


OPERATOR_NOTIFICATION_ACTION = "operator_notification"
NOTIFY_AND_CONTINUE = "notify_and_continue"
GUEST_CANDIDATE_ADEQUACY_ARTIFACT = "guest_candidate_adequacy"
GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
ALLOWED_TEMPLATE_FIELDS = {
    "candidate_count",
    "min_required_candidates",
    "candidate_names",
}


@dataclass(frozen=True)
class OperatorNotificationMaterialization:
    action: dict[str, Any] | None
    materialized: bool
    transition_outcome: str | None
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "action_type": None if self.action is None else self.action.get("action_type"),
            "materialized": self.materialized,
            "transition_outcome": self.transition_outcome,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_operator_notification(
    *,
    step: WorkflowStepDeclaration,
    adequacy_artifact: dict[str, Any],
    candidate_artifact: dict[str, Any] | None = None,
    artifact_refs: list[str] | tuple[str, ...] = (),
    action_refs: list[str] | tuple[str, ...] = (),
) -> OperatorNotificationMaterialization:
    if step.operation_kind != NOTIFY_AND_CONTINUE:
        return _closed(
            step=step,
            skipped_reasons=("operation_kind_not_notify_and_continue",),
        )

    template = _message_template(step)
    if template is None:
        return _closed(
            step=step,
            skipped_reasons=("message_template_not_declared",),
        )

    if not _valid_adequacy_artifact(adequacy_artifact):
        return _closed(
            step=step,
            skipped_reasons=("adequacy_artifact_invalid",),
        )

    bindings = _bindings(
        adequacy_artifact=adequacy_artifact,
        candidate_artifact=candidate_artifact,
    )
    text = _render_template(template["text"], bindings)
    if text is None:
        return _closed(
            step=step,
            skipped_reasons=("message_template_binding_failed",),
        )

    safe_artifact_refs = _string_list(artifact_refs)
    safe_action_refs = _string_list(action_refs)
    action = {
        "action_type": OPERATOR_NOTIFICATION_ACTION,
        "operation_kind": NOTIFY_AND_CONTINUE,
        "step_id": step.step_id,
        "semantic_operation": step.semantic_operation,
        "blocking": False,
        "suspending": False,
        "notification_prepared": True,
        "notification_sent": False,
        "requires_approval": False,
        "message": {
            "format": template["format"],
            "text": text,
            "rendered_text": text,
            "template_id": template.get("template_id"),
            "bindings": dict(bindings),
        },
        "artifact_refs": safe_artifact_refs,
        "action_refs": safe_action_refs,
        "provenance": {
            "template_id": template.get("template_id"),
            "declared_template_used": True,
            "runtime_prose_invented": False,
            "notification_sent": False,
            "web_search_executed": False,
            "ranking_performed": False,
            "selection_performed": False,
            "draft_generated": False,
            "delivery_performed": False,
        },
    }
    return OperatorNotificationMaterialization(
        action=action,
        materialized=True,
        transition_outcome="success",
        skipped_reasons=(),
        audit_summary=_audit_summary(
            step=step,
            materialized=True,
            skipped_reasons=(),
        ),
    )


def _message_template(step: WorkflowStepDeclaration) -> dict[str, Any] | None:
    template = step.constraints.get("message_template")
    if not isinstance(template, dict):
        return None

    text = template.get("text")
    fmt = template.get("format")
    if not isinstance(text, str) or not text.strip():
        return None
    if not isinstance(fmt, str) or not fmt.strip():
        return None

    placeholders = template.get("placeholders")
    if not isinstance(placeholders, list):
        return None
    for item in placeholders:
        if item not in ALLOWED_TEMPLATE_FIELDS:
            return None

    return {
        "template_id": _optional_string(template.get("template_id")),
        "format": fmt.strip(),
        "text": text,
        "placeholders": tuple(placeholders),
    }


def _valid_adequacy_artifact(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("artifact_type") == GUEST_CANDIDATE_ADEQUACY_ARTIFACT
    )


def _bindings(
    *,
    adequacy_artifact: dict[str, Any],
    candidate_artifact: dict[str, Any] | None,
) -> dict[str, str]:
    candidate_count = adequacy_artifact.get("candidate_count")
    min_required = adequacy_artifact.get("min_required_candidates")
    return {
        "candidate_count": str(_safe_int(candidate_count)),
        "min_required_candidates": str(_safe_int(min_required, default=1)),
        "candidate_names": _candidate_names(candidate_artifact),
    }


def _candidate_names(candidate_artifact: dict[str, Any] | None) -> str:
    if (
        not isinstance(candidate_artifact, dict)
        or candidate_artifact.get("artifact_type") != GUEST_CANDIDATE_LIST_ARTIFACT
    ):
        return "none"

    candidates = candidate_artifact.get("candidates")
    if not isinstance(candidates, list):
        return "none"

    names: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        name = (
            _optional_string(candidate.get("display_name"))
            or _optional_string(candidate.get("name"))
            or _optional_string(candidate.get("candidate_id"))
        )
        if name:
            names.append(name)
    return ", ".join(names) if names else "none"


def _render_template(
    template_text: str,
    bindings: dict[str, str],
) -> str | None:
    try:
        return template_text.format(**bindings)
    except (KeyError, ValueError):
        return None


def _safe_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return default


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(value: list[str] | tuple[str, ...]) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _closed(
    *,
    step: WorkflowStepDeclaration,
    skipped_reasons: tuple[str, ...],
) -> OperatorNotificationMaterialization:
    return OperatorNotificationMaterialization(
        action=None,
        materialized=False,
        transition_outcome="failure",
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            step=step,
            materialized=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _audit_summary(
    *,
    step: WorkflowStepDeclaration,
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "action_type": OPERATOR_NOTIFICATION_ACTION,
        "operation_kind": step.operation_kind,
        "step_id": step.step_id,
        "materialized": materialized,
        "blocking": False,
        "suspending": False,
        "notification_sent": False,
        "web_search_executed": False,
        "delivery_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "OPERATOR_NOTIFICATION_ACTION",
    "OperatorNotificationMaterialization",
    "materialize_operator_notification",
]
