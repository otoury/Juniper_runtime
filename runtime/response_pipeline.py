# runtime/response_pipeline.py

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from runtime.artifacts.extractors import (
    normalize_artifact_response,
)
from runtime.response_normalizer import normalize_model_response


@dataclass
class ResponsePipelineResult:
    raw_response: Any
    parsed_payload: dict | list | None
    normalized_response: str
    semantic_output_type: str | None
    is_empty: bool


def _strip_code_fences(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    return text.strip()


def _extract_json_payload(raw_response: Any):
    if isinstance(raw_response, (dict, list)):
        return raw_response

    if not isinstance(raw_response, str):
        return None

    text = _strip_code_fences(raw_response)

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        return None

    try:
        return json.loads(match.group())
    except Exception:
        return None


def process_response(
    raw_response: Any,
    semantic_output_type: str | None = None,
    agent_root=None,
) -> ResponsePipelineResult:
    parsed_payload = _extract_json_payload(raw_response)

    normalized_response = ""

    if (
        semantic_output_type is None
        and isinstance(parsed_payload, dict)
        and (
            "assistant_response" in parsed_payload
            or "actions" in parsed_payload
        )
    ):
        if isinstance(raw_response, str):
            normalized_response = _strip_code_fences(raw_response)
        else:
            normalized_response = json.dumps(
                raw_response,
                ensure_ascii=False,
            )

    elif semantic_output_type:
        normalized_artifact = normalize_artifact_response(
            artifact_type=semantic_output_type,
            response=raw_response,
        )

        normalized_response = (
            normalized_artifact.extracted_content
        )

        if parsed_payload is None:
            parsed_payload = (
                normalized_artifact.structured_payload
            )

    if not normalized_response:
        normalized_response = normalize_model_response(
            raw_response,
            semantic_output_type=semantic_output_type,
        )

    if normalized_response is None:
        normalized_response = ""

    normalized_response = str(normalized_response).strip()

    return ResponsePipelineResult(
        raw_response=raw_response,
        parsed_payload=parsed_payload,
        normalized_response=normalized_response,
        semantic_output_type=semantic_output_type,
        is_empty=not bool(normalized_response),
    )


__all__ = [
    "ResponsePipelineResult",
    "process_response",
]
