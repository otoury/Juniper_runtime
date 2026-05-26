from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from agents.alexis.adapters.guest_db.exact_entity_lookup_adapter import (
    ALEXIS_GUEST_SOURCE_SCOPE,
    AUTHORIZED_SOURCE_SCOPES,
    SAFE_PAYLOAD_FIELDS,
    _normalize_guest_row,
)
from runtime.registries.bounded_entity_search_registry import (
    validate_bounded_entity_search_request,
)


SEARCH_FIELDS = (
    "display_name",
    "title",
    "expertise",
    "booking_notes",
)
MAX_ALEXIS_BOUNDED_SEARCH_RESULTS = 5


@dataclass(frozen=True)
class AlexisBoundedEntitySearchResult:
    ok: bool
    payloads: list[dict[str, Any]]
    retrieval_executed: bool
    skipped_reasons: tuple[str, ...]
    provenance: dict[str, Any]


def execute_alexis_guest_bounded_entity_search(
    request: dict[str, Any],
    *,
    rows: Iterable[Mapping[str, Any]] | None = None,
) -> AlexisBoundedEntitySearchResult:
    validation_errors = validate_bounded_entity_search_request(
        request,
        allow_policy_fields=True,
    )
    if validation_errors:
        return _closed_result(
            request=request if isinstance(request, dict) else {},
            retrieval_executed=False,
            records_matched=0,
            skipped_reason="invalid_bounded_entity_search_request",
        )

    source_scope = request.get("source_scope")
    if source_scope not in AUTHORIZED_SOURCE_SCOPES:
        return _closed_result(
            request=request,
            retrieval_executed=False,
            records_matched=0,
            skipped_reason="unauthorized_source_scope",
        )

    terms = _query_terms(request)
    if not terms:
        return _closed_result(
            request=request,
            retrieval_executed=False,
            records_matched=0,
            skipped_reason="missing_search_topic_or_query_intent",
        )

    max_results = request.get("max_results")
    if (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or max_results < 1
        or max_results > MAX_ALEXIS_BOUNDED_SEARCH_RESULTS
    ):
        return _closed_result(
            request=request,
            retrieval_executed=False,
            records_matched=0,
            skipped_reason="invalid_max_results",
        )

    try:
        candidate_rows = list(rows) if rows is not None else list(
            _read_rows(AUTHORIZED_SOURCE_SCOPES[source_scope])
        )
    except OSError:
        return _closed_result(
            request=request,
            retrieval_executed=False,
            records_matched=0,
            skipped_reason="datasource_read_failed",
        )

    payloads: list[dict[str, Any]] = []
    records_matched = 0
    for row in candidate_rows:
        if not isinstance(row, Mapping) or not _row_matches(row, terms):
            continue

        records_matched += 1
        payload = _normalize_guest_row(dict(row))
        if payload is None:
            return _closed_result(
                request=request,
                retrieval_executed=True,
                records_matched=records_matched,
                skipped_reason="malformed_datasource_row",
            )

        payloads.append(payload)
        if len(payloads) >= max_results:
            break

    if not payloads:
        return _closed_result(
            request=request,
            retrieval_executed=True,
            records_matched=0,
            skipped_reason="no_lexical_match",
        )

    return AlexisBoundedEntitySearchResult(
        ok=True,
        payloads=payloads,
        retrieval_executed=True,
        skipped_reasons=(),
        provenance=_safe_provenance(
            request=request,
            retrieval_executed=True,
            records_matched=records_matched,
            records_returned=len(payloads),
            skipped_reasons=(),
        ),
    )


def _read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _query_terms(request: Mapping[str, Any]) -> tuple[str, ...]:
    text_parts = [
        value.strip()
        for value in (
            request.get("search_topic"),
            request.get("query_intent"),
        )
        if isinstance(value, str) and value.strip()
    ]
    return _normalized_terms(" ".join(text_parts))


def _row_matches(row: Mapping[str, Any], terms: tuple[str, ...]) -> bool:
    searchable = " ".join(
        value.strip()
        for field in SEARCH_FIELDS
        for value in [row.get(field)]
        if isinstance(value, str) and value.strip()
    )
    normalized = _normalized_text(searchable)
    field_terms = set(_normalized_terms(searchable))
    return all(term in field_terms or term in normalized for term in terms)


def _normalized_terms(value: str) -> tuple[str, ...]:
    return tuple(
        term for term in re.split(r"[^a-z0-9]+", _normalized_text(value))
        if term
    )


def _normalized_text(value: str) -> str:
    return value.lower()


def _closed_result(
    *,
    request: dict[str, Any],
    retrieval_executed: bool,
    records_matched: int,
    skipped_reason: str,
) -> AlexisBoundedEntitySearchResult:
    return AlexisBoundedEntitySearchResult(
        ok=False,
        payloads=[],
        retrieval_executed=retrieval_executed,
        skipped_reasons=(skipped_reason,),
        provenance=_safe_provenance(
            request=request,
            retrieval_executed=retrieval_executed,
            records_matched=records_matched,
            records_returned=0,
            skipped_reasons=(skipped_reason,),
        ),
    )


def _safe_provenance(
    *,
    request: dict[str, Any],
    retrieval_executed: bool,
    records_matched: int,
    records_returned: int,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "lookup_id": request.get("lookup_id"),
        "operation_id": "bounded_entity_search",
        "lookup_type": request.get("lookup_type"),
        "entity_type": request.get("entity_type"),
        "source_scope": request.get("source_scope"),
        "retrieval_executed": retrieval_executed,
        "records_matched": records_matched,
        "records_returned": records_returned,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "AlexisBoundedEntitySearchResult",
    "MAX_ALEXIS_BOUNDED_SEARCH_RESULTS",
    "SEARCH_FIELDS",
    "execute_alexis_guest_bounded_entity_search",
]
