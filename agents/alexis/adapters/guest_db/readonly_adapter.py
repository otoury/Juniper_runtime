from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from agents.alexis.adapters.guest_db.context_item import (
    guest_record_to_context_item,
)
from runtime.context_types import ResolvedContextItem
from runtime.lookup.context import lookup_result_to_context_items
from runtime.lookup.types import (
    BoundedLookupRequest,
    BoundedLookupResult,
    validate_bounded_lookup_request,
)
from runtime.registries.adapter_binding_registry import ContextAdapterContract
from runtime.registries.context_injection_binding_registry import (
    ContextInjectionContract,
)


CANONICAL_GUESTS_CSV_PATH = Path(
    "agents/alexis/adapters/guest_db/resources/canonical/"
    "GUESTS_CANONICAL.csv"
)
FIXED_ID_LOOKUP_MODE = "fixed_id"
FIXED_ID_LOOKUP_KEY = "entity_id"


class AlexisGuestDbReadonlyAdapter:
    adapter_id = "guest_db_readonly"

    def __init__(
        self,
        contract: ContextInjectionContract,
        adapter_contract: ContextAdapterContract,
    ) -> None:
        self.contract = contract
        self.adapter_contract = adapter_contract
        self.csv_path = Path(
            adapter_contract.read_target or CANONICAL_GUESTS_CSV_PATH
        )
        self.last_lookup_result: BoundedLookupResult | None = None

    def lookup(
        self,
        request: BoundedLookupRequest,
    ) -> BoundedLookupResult:
        validation_errors = validate_bounded_lookup_request(request)

        if validation_errors:
            return BoundedLookupResult(
                lookup_id=getattr(request, "lookup_id", ""),
                source_contract_id=getattr(request, "source_contract_id", ""),
                records=[],
                retrieval_executed=False,
                skipped_reasons=["invalid_lookup_request"],
            )

        if request.lookup_mode != FIXED_ID_LOOKUP_MODE:
            return BoundedLookupResult(
                lookup_id=request.lookup_id,
                source_contract_id=request.source_contract_id,
                records=[],
                retrieval_executed=False,
                skipped_reasons=["unsupported_lookup_mode"],
            )

        if request.lookup_key != FIXED_ID_LOOKUP_KEY:
            return BoundedLookupResult(
                lookup_id=request.lookup_id,
                source_contract_id=request.source_contract_id,
                records=[],
                retrieval_executed=False,
                skipped_reasons=["unsupported_lookup_key"],
            )

        guest_id = request.lookup_value.strip()

        try:
            record = self._read_one_record_by_guest_id(guest_id)
        except OSError:
            return BoundedLookupResult(
                lookup_id=request.lookup_id,
                source_contract_id=request.source_contract_id,
                records=[],
                retrieval_executed=False,
                skipped_reasons=["guest_db_read_failed"],
            )

        if record is None:
            return BoundedLookupResult(
                lookup_id=request.lookup_id,
                source_contract_id=request.source_contract_id,
                records=[],
                retrieval_executed=True,
                skipped_reasons=["guest_id_not_found"],
            )

        return BoundedLookupResult(
            lookup_id=request.lookup_id,
            source_contract_id=request.source_contract_id,
            records=[record],
            retrieval_executed=True,
            skipped_reasons=[],
        )

    def retrieve(
        self,
        *,
        request_id: str | None,
        agent: str,
        shared_capability: str | None,
    ) -> list[ResolvedContextItem]:
        lookup_request = self.adapter_contract.lookup_request

        if lookup_request is None:
            return []

        lookup_result = self.lookup(lookup_request)
        self.last_lookup_result = lookup_result

        return lookup_result_to_context_items(
            lookup_result,
            record_converter=self._record_to_context_item,
        )

    def _read_one_record_by_guest_id(
        self,
        guest_id: str,
    ) -> dict[str, Any] | None:
        with self.csv_path.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            reader = csv.DictReader(handle)

            for row in reader:
                if row.get("guest_id") == guest_id:
                    return dict(row)

        return None

    @staticmethod
    def _record_to_context_item(
        record: dict[str, Any],
        source_contract_id: str,
    ) -> ResolvedContextItem | None:
        return guest_record_to_context_item(
            record,
            source_contract_id=source_contract_id,
            item_id_prefix="guest_db_readonly",
        )


__all__ = [
    "AlexisGuestDbReadonlyAdapter",
    "CANONICAL_GUESTS_CSV_PATH",
    "FIXED_ID_LOOKUP_MODE",
    "FIXED_ID_LOOKUP_KEY",
]
