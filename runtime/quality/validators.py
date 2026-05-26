from __future__ import annotations

from runtime.quality.contracts import QualityResult, QualityViolation
from runtime.registries.artifacts import get_artifact_constraints


def _add(
    violations: list[QualityViolation],
    *,
    code: str,
    message: str,
):
    violations.append(
        QualityViolation(
            code=code,
            message=message,
        )
    )


def validate_text_constraints(
    *,
    artifact_type: str | None,
    content: str,
    interaction_mode: str | None = None,
    transform_type: str | None = None,
) -> QualityResult:
    text = (content or "").strip()
    constraints = get_artifact_constraints(artifact_type)
    violations: list[QualityViolation] = []
    compact_email_transform = _is_compact_email_transform(
        artifact_type=artifact_type,
        interaction_mode=interaction_mode,
        transform_type=transform_type,
    )

    if constraints.get("non_empty", True) and not text:
        _add(
            violations,
            code="empty",
            message="Artifact content is empty.",
        )

    if constraints.get("single_line") and "\n" in text:
        _add(
            violations,
            code="not_single_line",
            message="Artifact must be a single line.",
        )

    max_words = constraints.get("max_words")

    if max_words and len(text.split()) > int(max_words):
        _add(
            violations,
            code="too_many_words",
            message=f"Artifact exceeds {max_words} words.",
        )

    max_chars = constraints.get("max_chars")

    if max_chars and len(text) > int(max_chars):
        _add(
            violations,
            code="too_many_chars",
            message=f"Artifact exceeds {max_chars} characters.",
        )

    if (
        constraints.get("must_not_end_with_period")
        and text.endswith(".")
    ):
        _add(
            violations,
            code="terminal_period",
            message="Artifact must not end with a period.",
        )

    if constraints.get("forbid_meta_response"):
        lowered = text.lower()

        meta_markers = constraints.get(
            "meta_markers",
            [
                "here is",
                "here's",
                "here’s",
                "option:",
                "headline:",
                "draft:",
                "response:",
            ],
        )

        for marker in meta_markers:
            if marker.lower() in lowered:
                _add(
                    violations,
                    code="meta_language",
                    message="Artifact contains meta-language.",
                )
                break

    structure = constraints.get("required_structure", {})

    if structure:
        paragraphs = [
            p.strip()
            for p in text.split("\n\n")
            if p.strip()
        ]

        min_paragraphs = structure.get("min_paragraphs")

        if (
            min_paragraphs
            and len(paragraphs) < int(min_paragraphs)
            and not compact_email_transform
        ):
            _add(
                violations,
                code="insufficient_structure",
                message=(
                    "Artifact does not contain the required "
                    f"minimum of {min_paragraphs} paragraphs."
                ),
            )

        starts = structure.get("must_start_with_any", [])

        if starts and not any(
            text.startswith(prefix)
            for prefix in starts
        ):
            _add(
                violations,
                code="invalid_start",
                message="Artifact does not start with an allowed opening.",
            )

        contains = structure.get("must_contain_any", [])

        if contains and not any(
            item in text
            for item in contains
        ):
            _add(
                violations,
                code="missing_required_content",
                message="Artifact is missing required structural content.",
            )

        if compact_email_transform:
            _validate_compact_email_transform(
                text=text,
                structure=structure,
                violations=violations,
            )
    if violations:
        return QualityResult.fail(violations)

    return QualityResult.pass_()


def _is_compact_email_transform(
    *,
    artifact_type: str | None,
    interaction_mode: str | None,
    transform_type: str | None,
) -> bool:
    return (
        artifact_type == "email_draft"
        and interaction_mode == "TRANSFORM_EXISTING"
        and transform_type in {"expand_scope", "shorten"}
    )


def _validate_compact_email_transform(
    *,
    text: str,
    structure: dict,
    violations: list[QualityViolation],
) -> None:
    starts = structure.get("must_start_with_any", [])
    signoffs = structure.get("must_contain_any", [])

    salutation = next(
        (
            prefix
            for prefix in starts
            if text.startswith(prefix)
        ),
        None,
    )

    signoff_index = _first_marker_index(
        text=text,
        markers=signoffs,
    )

    if not salutation or signoff_index < 0:
        return

    body = text[len(salutation):signoff_index].strip()

    if not body:
        _add(
            violations,
            code="missing_body",
            message="Artifact is missing email body content.",
        )

    if not _contains_email_ask(body):
        _add(
            violations,
            code="missing_ask",
            message="Artifact is missing an email ask.",
        )


def _first_marker_index(
    *,
    text: str,
    markers: list[str],
) -> int:
    indexes = [
        text.find(marker)
        for marker in markers
        if marker and text.find(marker) >= 0
    ]

    if not indexes:
        return -1

    return min(indexes)


def _contains_email_ask(text: str) -> bool:
    lowered = text.lower()

    if "?" in text:
        return True

    ask_markers = [
        "please",
        "could you",
        "would you",
        "are you available",
        "let me know",
        "availability",
        "available for",
    ]

    return any(marker in lowered for marker in ask_markers)
