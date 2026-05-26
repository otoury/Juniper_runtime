# runtime/persistence_manager.py

from __future__ import annotations

from memory.artifacts import (
    save_active_artifact,
    load_active_artifact,
    score_transform_outcome,
)
from memory.transform_feedback import record_transform_feedback
from runtime.artifacts.models import NormalizedArtifact
from runtime.artifacts.extractors import extract_artifact_payload
from runtime.registries.artifacts import should_persist_artifact

def persist_runtime_result(
    *,
    agent_name: str,
    user_id: str,
    request_id: str,
    response: str,
    resolved_text: str,
    plan,
    gate,
    transform_type,
    is_dry_run: bool,
):
    """
    Persist successful runtime artifacts.

    Responsibilities:
    - decide whether response should be saved as artifact
    - preserve artifact lineage
    - record transform feedback

    Does NOT write chat memory.
    """

    if is_dry_run:
        return None

    if not response or not response.strip():
        return None

    previous_artifact = load_active_artifact(
        agent_name=agent_name,
        user_id=user_id,
    )

    is_artifact_transform = (
        gate.interaction_mode == "TRANSFORM_EXISTING"
        and previous_artifact
    )

    if is_artifact_transform:
        artifact_transform_type = transform_type

        artifact_type = previous_artifact.get(
            "artifact_type",
            "general",
        )

        should_save_artifact = True

    else:
        artifact_transform_type = None

        artifact_type = (
            plan.semantic_output_type
        )

        should_save_artifact = should_persist_artifact(
            artifact_type
        )

    if not should_save_artifact:
        return None

    normalized_content = extract_artifact_payload(
        artifact_type=artifact_type,
        response=response.strip(),
    )

    metadata = {
        "user_id": user_id,
        "request_id": request_id,
        "operation": (
            "transform"
            if is_artifact_transform
            else "create"
        ),
        "source_text": resolved_text,
        "transform_type": artifact_transform_type,
    }

    lineage = (
        [previous_artifact.get("artifact_id")]
        if is_artifact_transform and previous_artifact
        else []
    )
    saved_artifact = save_active_artifact(
        agent_name=agent_name,
        user_id=user_id,
        request_id=request_id,
        artifact_type=artifact_type,
        content=normalized_content,
        source_text=resolved_text,
        operation=metadata["operation"],
        parent_artifact_id=(
            lineage[0]
            if lineage
            else None
        ),
        transform_type=artifact_transform_type,
    )
        
    if is_artifact_transform and artifact_transform_type:
        outcome = score_transform_outcome(
            previous_artifact=previous_artifact,
            new_artifact=saved_artifact,
        )

        record_transform_feedback(
            agent_name=agent_name,
            user_id=user_id,
            artifact_id=saved_artifact["artifact_id"],
            transform_type=artifact_transform_type,
            outcome=outcome,
        )

    return saved_artifact


__all__ = [
    "persist_runtime_result",
]
