from __future__ import annotations

from runtime.lookup.types import (
    BoundedLookupRequest,
    BoundedLookupResult,
)


def _records_returned(result: BoundedLookupResult | None) -> int:
    if result is None or not isinstance(result.records, list):
        return 0

    return len(result.records)


def _skipped_reasons(result: BoundedLookupResult | None) -> list[str]:
    if result is None or not isinstance(result.skipped_reasons, list):
        return []

    return [
        reason for reason in result.skipped_reasons
        if isinstance(reason, str)
    ]


def build_bounded_lookup_trace(
    *,
    request: BoundedLookupRequest | None,
    result: BoundedLookupResult | None,
) -> dict:
    return {
        "lookup_id": (
            request.lookup_id
            if request is not None
            else result.lookup_id if result is not None else None
        ),
        "source_contract_id": (
            request.source_contract_id
            if request is not None
            else result.source_contract_id if result is not None else None
        ),
        "lookup_mode": (
            request.lookup_mode
            if request is not None
            else None
        ),
        "lookup_key": (
            request.lookup_key
            if request is not None
            else None
        ),
        "max_records": (
            request.max_records
            if request is not None
            else None
        ),
        "retrieval_executed": (
            result.retrieval_executed
            if result is not None
            and isinstance(result.retrieval_executed, bool)
            else False
        ),
        "records_returned": _records_returned(result),
        "skipped_reasons": _skipped_reasons(result),
    }


__all__ = ["build_bounded_lookup_trace"]
