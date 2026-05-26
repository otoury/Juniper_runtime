from __future__ import annotations

from runtime.artifacts.models import NormalizedArtifact
from runtime.quality.validators import validate_text_constraints


def validate_normalized_artifact_quality(
    *,
    artifact: NormalizedArtifact,
    interaction_mode: str | None = None,
    transform_type: str | None = None,
):
    if not artifact.artifact_type:
        return None

    return validate_text_constraints(
        artifact_type=artifact.artifact_type,
        content=artifact.extracted_content,
        interaction_mode=interaction_mode,
        transform_type=transform_type,
    )


def validate_artifact_quality(
    *,
    artifact_type: str | None,
    content: str,
    interaction_mode: str | None = None,
    transform_type: str | None = None,
):
    artifact = NormalizedArtifact(
        artifact_type=artifact_type,
        raw_response=content,
        extracted_content=content,
        structured_payload=None,
    )

    return validate_normalized_artifact_quality(
        artifact=artifact,
        interaction_mode=interaction_mode,
        transform_type=transform_type,
    )
