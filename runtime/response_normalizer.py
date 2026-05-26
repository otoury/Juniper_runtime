# runtime/response_normalizer.py

from __future__ import annotations

import ast
import json
import re
from typing import Any


def normalize_key(value: str) -> str:
    return "".join(
        ch.lower()
        for ch in str(value)
        if ch.isalnum()
    )


def strip_code_fences(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    return text.strip()


def try_parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def try_parse_python_dict(text: str):
    try:
        return ast.literal_eval(text)
    except Exception:
        return None


def normalize_dict_keys(data: dict) -> dict:
    return {
        normalize_key(k): v
        for k, v in data.items()
    }


def recover_string_artifact(data: dict) -> str | None:
    normalized = normalize_dict_keys(data)

    if isinstance(data, dict):
        if (
            data.get("artifact_type") == "lower_third"
            and isinstance(data.get("content"), str)
        ):
            return data["content"].strip()

    preferred_keys = [
        "artifact",
        "content",
        "response",
        "result",
        "output",
        "text",
        "lowerthird",
        "headline",
        "title",
        "email",
        "body",
    ]

    for key in preferred_keys:
        value = normalized.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    for value in normalized.values():
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def recover_guest_booking(data: dict) -> str | None:
    normalized = normalize_dict_keys(data)

    guests = normalized.get("guests")

    if not isinstance(guests, list):
        return None

    lines = []

    for guest in guests:
        if not isinstance(guest, dict):
            continue

        name = guest.get("name", "").strip()
        title = guest.get("title", "").strip()

        if name and title:
            lines.append(f"{name} — {title}")
        elif name:
            lines.append(name)

    if not lines:
        return None

    return "\n".join(lines)


def normalize_response(
    response: Any,
    semantic_output_type: str | None = None,
) -> str:

    if response is None:
        return ""

    if isinstance(response, str):
        text = strip_code_fences(response)

        parsed = try_parse_json(text)

        if parsed is None:
            parsed = try_parse_python_dict(text)

    else:
        parsed = response

    if isinstance(parsed, dict):

        if semantic_output_type == "guest_booking":
            recovered = recover_guest_booking(parsed)

            if recovered:
                return recovered

        recovered = recover_string_artifact(parsed)

        if recovered:
            return recovered

        return ""

    if isinstance(parsed, list):
        cleaned = [
            str(x).strip()
            for x in parsed
            if str(x).strip()
        ]

        return "\n".join(cleaned)

    if isinstance(response, str):
        return response.strip()

    return str(response).strip()


def normalize_model_response(
    response,
    semantic_output_type=None,
):
    return normalize_response(
        response=response,
        semantic_output_type=semantic_output_type,
    )


__all__ = [
    "normalize_response",
    "normalize_model_response",
    "normalize_key",
]
