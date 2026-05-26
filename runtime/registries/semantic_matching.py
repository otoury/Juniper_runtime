from __future__ import annotations

import re

from runtime.registries.artifacts import (
    load_artifact_registry,
)


WORD_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_-]*\b")


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(text or "")
    }


def _score_signal_matches(
    *,
    tokens: set[str],
    signals: dict,
) -> int:
    score = 0

    for category, weight in (
        ("verbs", 3),
        ("entities", 4),
        ("domains", 2),
        ("modifiers", 1),
    ):
        values = signals.get(category, [])

        for value in values:
            if value.lower() in tokens:
                score += weight

    return score


def infer_artifact_type_from_text(
    text: str,
) -> str | None:
    lowered = (text or "").lower()
    tokens = _tokenize(lowered)

    registry = load_artifact_registry()

    best_match = None
    best_score = 0

    for artifact_type, config in registry.items():
        score = 0

        aliases = config.get("aliases", [])
        examples = config.get(
            "intent_examples",
            [],
        )

        for phrase in aliases + examples:
            if phrase.lower() in lowered:
                score += 10

        semantic_signals = config.get(
            "semantic_signals",
            {},
        )

        score += _score_signal_matches(
            tokens=tokens,
            signals=semantic_signals,
        )

        if score > best_score:
            best_score = score
            best_match = artifact_type

    if best_score < 5:
        return None

    return best_match


def infer_explicit_artifact_type_from_text(
    text: str,
) -> str | None:
    lowered = (text or "").lower()

    registry = load_artifact_registry()

    best_match = None
    best_score = 0

    for artifact_type, config in registry.items():
        score = 0

        creation_examples = config.get(
            "creation_intent_examples",
            [],
        )

        for phrase in creation_examples:
            if phrase.lower() in lowered:
                score += 10

        if score > best_score:
            best_score = score
            best_match = artifact_type

    if best_score < 5:
        return None

    return best_match
