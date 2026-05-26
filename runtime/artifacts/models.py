from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NormalizedArtifact:
    artifact_type: str | None
    raw_response: str
    extracted_content: str
    structured_payload: dict | None
