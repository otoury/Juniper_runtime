from __future__ import annotations

from runtime.actions.capabilities import CAPABILITIES


ARTIFACT_CREATION_CAPABILITIES = {
    "email_draft": "draft_email",
    "lower_third": "create_lower_third",
    "producer_note": "producer_note",
}

ACTION_CAPABILITIES = {
    "send_email": "send_email",
}

ARTIFACT_OPERATIONS = {
    "TRANSFORM",
    "CONVERT",
}


def normalize_planned_shared_capability(
    shared_capability: str | None,
) -> str | None:
    capability = str(shared_capability or "").strip()

    if capability in CAPABILITIES:
        return capability

    return None


def resolve_planned_shared_capability(
    *,
    operation: str | None = None,
    semantic_output_type: str | None = None,
    transform_type: str | None = None,
    explicit_shared_capability: str | None = None,
) -> str | None:
    normalized_operation = str(operation or "").upper().strip()

    if transform_type or normalized_operation in ARTIFACT_OPERATIONS:
        return None

    explicit = normalize_planned_shared_capability(
        explicit_shared_capability
    )

    if explicit in ACTION_CAPABILITIES.values():
        if normalized_operation in {"ACTION", "CONTINUE"}:
            return explicit
    elif explicit:
        return explicit

    if semantic_output_type:
        return ARTIFACT_CREATION_CAPABILITIES.get(
            semantic_output_type
        )

    return None


__all__ = [
    "ACTION_CAPABILITIES",
    "ARTIFACT_CREATION_CAPABILITIES",
    "resolve_planned_shared_capability",
    "normalize_planned_shared_capability",
]
