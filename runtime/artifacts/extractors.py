from __future__ import annotations

import json
from collections.abc import Mapping

from runtime.artifacts.models import NormalizedArtifact
from runtime.artifacts.normalization import normalize_structured_payload
from runtime.artifacts.user_rendering import render_artifact_for_user
from runtime.registries.artifacts import (
    get_artifact_extract_fields,
)


def _strip_email_subject_header(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").strip()

    if not normalized:
        return normalized

    lines = normalized.split("\n")

    if not lines:
        return normalized

    first = lines[0].strip()

    if not first.lower().startswith("subject:"):
        return normalized

    idx = 1

    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    stripped = "\n".join(lines[idx:]).strip()
    return stripped or normalized


def _extract_email_body_from_wrappers(data: Mapping) -> str | None:
    candidates: list[Mapping] = [data]

    for key in ("email_draft", "email"):
        value = data.get(key)
        if isinstance(value, Mapping):
            candidates.insert(0, value)

    for candidate in candidates:
        for key in ("Body", "body", "content", "text", "email"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def normalize_artifact_response(
    *,
    artifact_type: str | None,
    response: str,
) -> NormalizedArtifact:
    
    
    text = (response or "").strip()
    data = None
    structured_payload = None
    extracted_content = text

    try:
        data = json.loads(text)

        if isinstance(data, dict):
            structured_payload = data
            rendered = render_artifact_for_user(
                artifact_type=artifact_type,
                payload=data,
            )
            if rendered:
                extracted_content = rendered
                return NormalizedArtifact(
                    artifact_type=artifact_type,
                    raw_response=text,
                    extracted_content=extracted_content,
                    structured_payload=structured_payload,
                )

            if artifact_type == "email_draft":
                extracted_email = _extract_email_body_from_wrappers(
                    data
                )
                if extracted_email:
                    extracted_content = extracted_email
                else:
                    fields = get_artifact_extract_fields(
                        artifact_type
                    )
                    extracted_content = normalize_structured_payload(
                        data,
                        preferred_fields=fields,
                    )
            else:
                fields = get_artifact_extract_fields(
                    artifact_type
                )
                extracted_content = normalize_structured_payload(
                    data,
                    preferred_fields=fields,
                )

        
    except Exception:
        pass

    if artifact_type == "email_draft":
        extracted_content = _strip_email_subject_header(
            extracted_content
        )

    return NormalizedArtifact(
        artifact_type=artifact_type,
        raw_response=text,
        extracted_content=extracted_content,
        structured_payload=structured_payload,
    )


def extract_artifact_payload(
    *,
    artifact_type: str | None,
    response: str,
):
    normalized = normalize_artifact_response(
        artifact_type=artifact_type,
        response=response,
    )

    return normalized.extracted_content
