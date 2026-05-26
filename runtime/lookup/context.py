from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.context_types import ResolvedContextItem
from runtime.lookup.types import (
    BoundedLookupResult,
    validate_bounded_lookup_result,
)


RecordToContextItemConverter = Callable[
    [dict[str, Any], str],
    ResolvedContextItem | None,
]


def lookup_result_to_context_items(
    result: BoundedLookupResult,
    *,
    record_converter: RecordToContextItemConverter,
) -> list[ResolvedContextItem]:
    if validate_bounded_lookup_result(result):
        return []

    if result.retrieval_executed is not True:
        return []

    if not result.records:
        return []

    first_record = result.records[0]

    if not isinstance(first_record, dict):
        return []

    item = record_converter(first_record, result.source_contract_id)

    if item is None:
        return []

    return [item]


__all__ = [
    "RecordToContextItemConverter",
    "lookup_result_to_context_items",
]
