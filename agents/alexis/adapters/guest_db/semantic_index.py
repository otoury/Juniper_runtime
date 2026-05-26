from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from agents.alexis.adapters.guest_db.exact_entity_lookup_adapter import (
    ALEXIS_GUEST_SOURCE_SCOPE,
    AUTHORIZED_SOURCE_SCOPES,
)
from agents.alexis.adapters.guest_db.record_validator import (
    validate_guest_record,
)
from runtime.semantic_index import (
    LocalSemanticIndex,
    MAX_CATEGORIES,
    MAX_SEMANTIC_INDEX_ENTRIES,
    MAX_TAGS,
    SemanticIndexEntry,
    build_local_semantic_index,
    normalize_semantic_labels,
    normalize_semantic_text,
)


GUEST_DB_SEMANTIC_INDEX_ID = "alexis_guest_db_semantic_index_v1"
GUEST_DB_SEMANTIC_INDEX_VERSION = 1
GUEST_SEMANTIC_TEXT_FIELDS = (
    "display_name",
    "title",
    "expertise",
    "booking_notes",
)
GUEST_TAG_FIELDS = (
    "expertise",
)
GUEST_CATEGORY_FIELDS = (
    "title",
)


@dataclass(frozen=True)
class GuestDbSemanticIndexBuildResult:
    ok: bool
    index: LocalSemanticIndex
    records_seen: int
    records_indexed: int
    skipped_reasons: tuple[str, ...]
    provenance: dict[str, Any]


def build_guest_db_semantic_index(
    *,
    source_scope: str = ALEXIS_GUEST_SOURCE_SCOPE,
    rows: Iterable[Mapping[str, Any]] | None = None,
    max_entries: int = MAX_SEMANTIC_INDEX_ENTRIES,
) -> GuestDbSemanticIndexBuildResult:
    if source_scope not in AUTHORIZED_SOURCE_SCOPES:
        return _closed_result(
            source_scope=source_scope,
            records_seen=0,
            skipped_reasons=("unauthorized_source_scope",),
        )

    try:
        source_rows = list(rows) if rows is not None else list(
            _read_rows(AUTHORIZED_SOURCE_SCOPES[source_scope])
        )
    except OSError:
        return _closed_result(
            source_scope=source_scope,
            records_seen=0,
            skipped_reasons=("datasource_read_failed",),
        )

    entries: list[SemanticIndexEntry] = []
    skipped_reasons: list[str] = []

    for row in source_rows:
        if len(entries) >= max_entries:
            skipped_reasons.append("max_entries_reached")
            break

        entry = guest_record_to_semantic_index_entry(
            row,
            source_scope=source_scope,
        )
        if entry is None:
            skipped_reasons.append("malformed_guest_record")
            continue

        entries.append(entry)

    provenance = _safe_provenance(
        source_scope=source_scope,
        records_seen=len(source_rows),
        records_indexed=len(entries),
        skipped_reasons=tuple(skipped_reasons),
    )
    index = build_local_semantic_index(
        index_id=GUEST_DB_SEMANTIC_INDEX_ID,
        entries=entries,
        provenance=provenance,
        max_entries=max_entries,
    )

    return GuestDbSemanticIndexBuildResult(
        ok=not skipped_reasons,
        index=index,
        records_seen=len(source_rows),
        records_indexed=len(index.entries),
        skipped_reasons=tuple(skipped_reasons),
        provenance=provenance,
    )


def guest_record_to_semantic_index_entry(
    record: Mapping[str, Any],
    *,
    source_scope: str,
) -> SemanticIndexEntry | None:
    row = dict(record) if isinstance(record, Mapping) else record
    validation = validate_guest_record(row)
    if not validation.ok or not isinstance(row, dict):
        return None

    candidate_id = row.get("guest_id")
    semantic_text = normalize_semantic_text(
        row.get(field) for field in GUEST_SEMANTIC_TEXT_FIELDS
    )
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        return None
    if not semantic_text:
        return None

    return SemanticIndexEntry(
        candidate_id=candidate_id.strip(),
        semantic_text=semantic_text,
        tags=normalize_semantic_labels(
            (row.get(field) for field in GUEST_TAG_FIELDS),
            max_labels=MAX_TAGS,
        ),
        categories=normalize_semantic_labels(
            (row.get(field) for field in GUEST_CATEGORY_FIELDS),
            max_labels=MAX_CATEGORIES,
        ),
        provenance={
            "source_scope": source_scope,
            "source_record_id": candidate_id.strip(),
            "source_updated_at": _optional_string(row.get("source_updated_at")),
            "index_id": GUEST_DB_SEMANTIC_INDEX_ID,
            "index_version": GUEST_DB_SEMANTIC_INDEX_VERSION,
        },
    )


def _read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _closed_result(
    *,
    source_scope: str,
    records_seen: int,
    skipped_reasons: tuple[str, ...],
) -> GuestDbSemanticIndexBuildResult:
    provenance = _safe_provenance(
        source_scope=source_scope,
        records_seen=records_seen,
        records_indexed=0,
        skipped_reasons=skipped_reasons,
    )
    index = build_local_semantic_index(
        index_id=GUEST_DB_SEMANTIC_INDEX_ID,
        entries=(),
        provenance=provenance,
    )
    return GuestDbSemanticIndexBuildResult(
        ok=False,
        index=index,
        records_seen=records_seen,
        records_indexed=0,
        skipped_reasons=skipped_reasons,
        provenance=provenance,
    )


def _safe_provenance(
    *,
    source_scope: str,
    records_seen: int,
    records_indexed: int,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "source_scope": source_scope,
        "operation_id": "local_semantic_index_build",
        "index_id": GUEST_DB_SEMANTIC_INDEX_ID,
        "index_version": GUEST_DB_SEMANTIC_INDEX_VERSION,
        "records_seen": records_seen,
        "records_indexed": records_indexed,
        "skipped_reasons": list(skipped_reasons),
        "embedding_generated": False,
        "external_calls_executed": False,
    }


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "GUEST_CATEGORY_FIELDS",
    "GUEST_DB_SEMANTIC_INDEX_ID",
    "GUEST_DB_SEMANTIC_INDEX_VERSION",
    "GUEST_SEMANTIC_TEXT_FIELDS",
    "GUEST_TAG_FIELDS",
    "GuestDbSemanticIndexBuildResult",
    "build_guest_db_semantic_index",
    "guest_record_to_semantic_index_entry",
]
