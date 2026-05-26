from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


MAX_SEMANTIC_INDEX_ENTRIES = 500
MAX_SEMANTIC_TEXT_CHARS = 2000
MAX_TAGS = 25
MAX_CATEGORIES = 25


@dataclass(frozen=True)
class SemanticIndexEntry:
    candidate_id: str
    semantic_text: str
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class SemanticIndexValidationError:
    error_code: str
    field_name: str | None
    message: str


@dataclass(frozen=True)
class SemanticIndexValidationResult:
    ok: bool
    errors: tuple[SemanticIndexValidationError, ...] = ()


@dataclass(frozen=True)
class LocalSemanticIndex:
    index_id: str
    entries: tuple[SemanticIndexEntry, ...]
    provenance: dict[str, Any]


def normalize_semantic_text(
    parts: Iterable[Any],
    *,
    max_chars: int = MAX_SEMANTIC_TEXT_CHARS,
) -> str:
    normalized_parts: list[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue

        normalized = " ".join(part.split())
        if normalized:
            normalized_parts.append(normalized)

    text = " ".join(normalized_parts)
    return text[:max_chars]


def normalize_semantic_labels(
    labels: Iterable[Any],
    *,
    max_labels: int,
) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()

    for label in labels:
        if not isinstance(label, str):
            continue

        value = " ".join(label.split()).strip().lower()
        if not value or value in seen:
            continue

        normalized.append(value)
        seen.add(value)

        if len(normalized) >= max_labels:
            break

    return tuple(normalized)


def validate_semantic_index_entry(
    entry: Any,
) -> SemanticIndexValidationResult:
    if not isinstance(entry, SemanticIndexEntry):
        return _validation_result(
            "entry_not_semantic_index_entry",
            "Semantic index entry must use the SemanticIndexEntry contract.",
        )

    errors: list[SemanticIndexValidationError] = []

    if not _is_non_empty_string(entry.candidate_id):
        errors.append(
            _error(
                "candidate_id_invalid",
                "candidate_id must be a non-empty string.",
                field_name="candidate_id",
            )
        )

    if not _is_non_empty_string(entry.semantic_text):
        errors.append(
            _error(
                "semantic_text_invalid",
                "semantic_text must be a non-empty string.",
                field_name="semantic_text",
            )
        )
    elif len(entry.semantic_text) > MAX_SEMANTIC_TEXT_CHARS:
        errors.append(
            _error(
                "semantic_text_too_long",
                "semantic_text exceeds the local bounded index limit.",
                field_name="semantic_text",
            )
        )

    errors.extend(_validate_string_tuple(entry.tags, "tags", MAX_TAGS))
    errors.extend(
        _validate_string_tuple(entry.categories, "categories", MAX_CATEGORIES)
    )

    if not isinstance(entry.provenance, dict):
        errors.append(
            _error(
                "provenance_invalid",
                "provenance must be an object.",
                field_name="provenance",
            )
        )

    return SemanticIndexValidationResult(
        ok=not errors,
        errors=tuple(errors),
    )


def build_local_semantic_index(
    *,
    index_id: str,
    entries: Iterable[SemanticIndexEntry],
    provenance: Mapping[str, Any] | None = None,
    max_entries: int = MAX_SEMANTIC_INDEX_ENTRIES,
) -> LocalSemanticIndex:
    if not _is_non_empty_string(index_id):
        raise ValueError("index_id must be a non-empty string.")

    if (
        not isinstance(max_entries, int)
        or isinstance(max_entries, bool)
        or max_entries < 1
        or max_entries > MAX_SEMANTIC_INDEX_ENTRIES
    ):
        raise ValueError("max_entries is outside the local index bounds.")

    accepted: list[SemanticIndexEntry] = []
    for entry in entries:
        if len(accepted) >= max_entries:
            break

        validation = validate_semantic_index_entry(entry)
        if validation.ok:
            accepted.append(entry)

    return LocalSemanticIndex(
        index_id=index_id.strip(),
        entries=tuple(accepted),
        provenance=dict(provenance or {}),
    )


def _validate_string_tuple(
    value: Any,
    field_name: str,
    max_values: int,
) -> tuple[SemanticIndexValidationError, ...]:
    if not isinstance(value, tuple):
        return (
            _error(
                f"{field_name}_invalid",
                f"{field_name} must be a tuple of non-empty strings.",
                field_name=field_name,
            ),
        )

    if len(value) > max_values:
        return (
            _error(
                f"{field_name}_too_many",
                f"{field_name} exceeds the local bounded index limit.",
                field_name=field_name,
            ),
        )

    if any(not _is_non_empty_string(item) for item in value):
        return (
            _error(
                f"{field_name}_contains_invalid_value",
                f"{field_name} must contain only non-empty strings.",
                field_name=field_name,
            ),
        )

    return ()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validation_result(
    error_code: str,
    message: str,
    *,
    field_name: str | None = None,
) -> SemanticIndexValidationResult:
    return SemanticIndexValidationResult(
        ok=False,
        errors=(
            _error(error_code, message, field_name=field_name),
        ),
    )


def _error(
    error_code: str,
    message: str,
    *,
    field_name: str | None = None,
) -> SemanticIndexValidationError:
    return SemanticIndexValidationError(
        error_code=error_code,
        field_name=field_name,
        message=message,
    )


__all__ = [
    "LocalSemanticIndex",
    "MAX_CATEGORIES",
    "MAX_SEMANTIC_INDEX_ENTRIES",
    "MAX_SEMANTIC_TEXT_CHARS",
    "MAX_TAGS",
    "SemanticIndexEntry",
    "SemanticIndexValidationError",
    "SemanticIndexValidationResult",
    "build_local_semantic_index",
    "normalize_semantic_labels",
    "normalize_semantic_text",
    "validate_semantic_index_entry",
]
