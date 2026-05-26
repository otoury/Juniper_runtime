from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DirectResponseType(str, Enum):
    GREETING = "greeting"
    ACKNOWLEDGEMENT = "acknowledgement"
    FAREWELL = "farewell"
    CAPABILITY_SUMMARY = "capability_summary"


CLOSED_DIRECT_RESPONSE_TYPES = frozenset(
    response_type.value for response_type in DirectResponseType
)


@dataclass(frozen=True)
class DirectResponseDecision:
    direct_response_type: str
    response_text: str | None
    reason: str
    deterministic_direct_response: bool = True
    needs_model: bool = False
    needs_lookup_context: bool = False
    needs_workflow: bool = False

    @property
    def response_type(self) -> str:
        return self.direct_response_type


DIRECT_RESPONSE_TAXONOMY = {
    DirectResponseType.GREETING.value: {
        "utterances": {
            "good afternoon",
            "good evening",
            "good morning",
            "hello",
            "hello alexis",
            "hey",
            "hey alexis",
            "hi",
            "hi alexis",
        },
        "response_text": "Hi, I'm Alexis. How can I help?",
        "reason": "Low-content greeting.",
    },
    DirectResponseType.ACKNOWLEDGEMENT.value: {
        "utterances": {
            "awesome",
            "cool",
            "got it",
            "great",
            "nice",
            "ok",
            "okay",
            "sounds good",
            "thanks",
            "thank you",
            "ty",
        },
        "response_text": "Got it.",
        "reason": "Low-content acknowledgement.",
    },
    DirectResponseType.FAREWELL.value: {
        "utterances": {
            "bye",
            "good night",
            "goodbye",
            "goodnight",
            "see you",
            "talk later",
        },
        "response_text": "Goodbye.",
        "reason": "Low-content farewell.",
    },
    DirectResponseType.CAPABILITY_SUMMARY.value: {
        "utterances": {
            "help",
            "how can you help",
            "what can you do",
            "what do you do",
        },
        "response_text": None,
        "reason": (
            "Lightweight capability question; no lookup, workflow, "
            "or model execution required."
        ),
    },
}


if set(DIRECT_RESPONSE_TAXONOMY) != CLOSED_DIRECT_RESPONSE_TYPES:
    raise RuntimeError("Direct response taxonomy must match the closed act set.")


def classify_deterministic_direct_response(
    text: str,
) -> DirectResponseDecision | None:
    normalized = _normalize_low_content_utterance(text)

    if not normalized:
        return None

    for response_type, config in DIRECT_RESPONSE_TAXONOMY.items():
        if normalized in config["utterances"]:
            return DirectResponseDecision(
                direct_response_type=response_type,
                response_text=config["response_text"],
                reason=config["reason"],
            )

    return None


def render_deterministic_direct_response(
    response_type: str | None,
) -> str | None:
    normalized = str(response_type or "").strip().lower()

    if not normalized:
        return None

    config = DIRECT_RESPONSE_TAXONOMY.get(normalized)

    if not config:
        return None

    response_text = config.get("response_text")
    return str(response_text) if response_text else None


def _normalize_low_content_utterance(text: str) -> str:
    normalized = " ".join(
        (text or "")
        .lower()
        .replace(",", " ")
        .replace(".", " ")
        .replace("!", " ")
        .replace("?", " ")
        .split()
    )

    if not normalized:
        return ""

    if len(normalized.split()) > 4:
        return ""

    return normalized


__all__ = [
    "CLOSED_DIRECT_RESPONSE_TYPES",
    "DIRECT_RESPONSE_TAXONOMY",
    "DirectResponseDecision",
    "DirectResponseType",
    "classify_deterministic_direct_response",
    "render_deterministic_direct_response",
]
