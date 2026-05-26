from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from agents.alexis.adapters.guest_db.readonly_adapter import (
    CANONICAL_GUESTS_CSV_PATH,
)
from agents.alexis.adapters.guest_db.record_validator import (
    validate_guest_record,
)
from runtime.registries.exact_entity_lookup_registry import (
    validate_exact_entity_lookup_request,
)


ALEXIS_GUEST_SOURCE_SCOPE = "alexis_guest_canonical_csv"
AUTHORIZED_SOURCE_SCOPES = {
    ALEXIS_GUEST_SOURCE_SCOPE: CANONICAL_GUESTS_CSV_PATH,
}
SAFE_PAYLOAD_FIELDS = {
    "display_name",
    "title",
    "expertise",
    "public_booking_notes",
    "known_contact_channels",
}


@dataclass(frozen=True)
class AlexisExactEntityLookupResult:
    ok: bool
    payload: dict[str, Any] | None
    retrieval_executed: bool
    skipped_reasons: tuple[str, ...]
    provenance: dict[str, Any]


def execute_alexis_guest_exact_entity_lookup(
    request: dict[str, Any],
    *,
    rows: Iterable[Mapping[str, Any]] | None = None,
) -> AlexisExactEntityLookupResult:
    validation_errors = validate_exact_entity_lookup_request(request)
    base_provenance = _safe_provenance(
        request=request if isinstance(request, dict) else {},
        retrieval_executed=False,
        records_matched=0,
        skipped_reasons=(),
    )

    if validation_errors:
        return AlexisExactEntityLookupResult(
            ok=False,
            payload=None,
            retrieval_executed=False,
            skipped_reasons=("invalid_exact_entity_lookup_request",),
            provenance={
                **base_provenance,
                "skipped_reasons": [
                    "invalid_exact_entity_lookup_request"
                ],
            },
        )

    source_scope = request.get("source_scope")
    if source_scope not in AUTHORIZED_SOURCE_SCOPES:
        return _closed_result(
            request=request,
            retrieval_executed=False,
            records_matched=0,
            skipped_reason="unauthorized_source_scope",
        )

    entity_name = request["entity_name"]

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

    matches = [
        dict(row)
        for row in candidate_rows
        if isinstance(row, Mapping)
        and row.get("display_name") == entity_name
    ]

    if not matches:
        return _closed_result(
            request=request,
            retrieval_executed=True,
            records_matched=0,
            skipped_reason="no_exact_match",
        )

    if len(matches) > 1:
        return _closed_result(
            request=request,
            retrieval_executed=True,
            records_matched=len(matches),
            skipped_reason="multiple_exact_matches",
        )

    payload = _normalize_guest_row(matches[0])
    if payload is None:
        return _closed_result(
            request=request,
            retrieval_executed=True,
            records_matched=1,
            skipped_reason="malformed_datasource_row",
        )

    return AlexisExactEntityLookupResult(
        ok=True,
        payload=payload,
        retrieval_executed=True,
        skipped_reasons=(),
        provenance=_safe_provenance(
            request=request,
            retrieval_executed=True,
            records_matched=1,
            skipped_reasons=(),
        ),
    )


def _read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _normalize_guest_row(row: dict[str, Any]) -> dict[str, Any] | None:
    validation = validate_guest_record(row)
    if not validation.ok:
        return None

    payload: dict[str, Any] = {}
    _copy_string(row, payload, "display_name")
    _copy_string(row, payload, "title")
    _copy_string(row, payload, "expertise")

    booking_notes = row.get("booking_notes")
    if isinstance(booking_notes, str) and booking_notes.strip():
        payload["public_booking_notes"] = booking_notes.strip()

    channels: list[str] = []
    if isinstance(row.get("phone"), str) and row["phone"].strip():
        channels.append("phone")
    if isinstance(row.get("email_contact"), str) and row[
        "email_contact"
    ].strip():
        channels.append("email")
    if channels:
        payload["known_contact_channels"] = channels

    if set(payload) - SAFE_PAYLOAD_FIELDS:
        return None

    return payload


def _copy_string(
    source: Mapping[str, Any],
    target: dict[str, Any],
    key: str,
) -> None:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        target[key] = value.strip()


def _closed_result(
    *,
    request: dict[str, Any],
    retrieval_executed: bool,
    records_matched: int,
    skipped_reason: str,
) -> AlexisExactEntityLookupResult:
    return AlexisExactEntityLookupResult(
        ok=False,
        payload=None,
        retrieval_executed=retrieval_executed,
        skipped_reasons=(skipped_reason,),
        provenance=_safe_provenance(
            request=request,
            retrieval_executed=retrieval_executed,
            records_matched=records_matched,
            skipped_reasons=(skipped_reason,),
        ),
    )


def _safe_provenance(
    *,
    request: dict[str, Any],
    retrieval_executed: bool,
    records_matched: int,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "lookup_id": request.get("lookup_id"),
        "operation_id": "exact_entity_lookup",
        "lookup_type": request.get("lookup_type"),
        "entity_type": request.get("entity_type"),
        "workflow_topic": request.get("workflow_topic"),
        "source_scope": request.get("source_scope"),
        "retrieval_executed": retrieval_executed,
        "records_matched": records_matched,
        "records_returned": 1 if records_matched == 1 and not skipped_reasons else 0,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "ALEXIS_GUEST_SOURCE_SCOPE",
    "AUTHORIZED_SOURCE_SCOPES",
    "AlexisExactEntityLookupResult",
    "SAFE_PAYLOAD_FIELDS",
    "execute_alexis_guest_exact_entity_lookup",
]
