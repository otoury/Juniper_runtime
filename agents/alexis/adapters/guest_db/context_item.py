from __future__ import annotations

from typing import Any

from agents.alexis.adapters.guest_db.record_renderer import (
    render_guest_record_summary,
)
from runtime.context_types import (
    ResolvedContextItem,
    ResolvedContextProvenance,
)


DEFAULT_SOURCE_CONTRACT_ID = "alexis_guest_db"
DEFAULT_ITEM_ID_PREFIX = "guest_db_record"
GUEST_DB_RECORD_ATTRIBUTION = "guest_db_record"


def _estimated_tokens(content: str) -> int:
    return max(1, (len(content) + 3) // 4)


def guest_record_to_context_item(
    record: dict[str, Any],
    *,
    source_contract_id: str = DEFAULT_SOURCE_CONTRACT_ID,
    item_id_prefix: str = DEFAULT_ITEM_ID_PREFIX,
) -> ResolvedContextItem | None:
    summary = render_guest_record_summary(record)

    if summary is None:
        return None

    guest_id = record.get("guest_id")

    if not isinstance(guest_id, str) or not guest_id.strip():
        return None

    normalized_source_contract_id = str(source_contract_id or "").strip()
    normalized_item_id_prefix = str(item_id_prefix or "").strip()

    if not normalized_source_contract_id or not normalized_item_id_prefix:
        return None

    return ResolvedContextItem(
        id=f"{normalized_item_id_prefix}:{guest_id.strip()}",
        source_contract_id=normalized_source_contract_id,
        content=summary,
        content_type="database_summary",
        provenance=ResolvedContextProvenance(
            source_contract_id=normalized_source_contract_id,
            retrieval_executed=True,
            attribution=GUEST_DB_RECORD_ATTRIBUTION,
        ),
        estimated_tokens=_estimated_tokens(summary),
        trust_level="retrieved_unverified",
        rendering_policy="bounded_context_block",
        metadata={
            "converter": "guest_record_to_context_item",
            "guest_id": guest_id.strip(),
        },
    )


__all__ = [
    "DEFAULT_ITEM_ID_PREFIX",
    "DEFAULT_SOURCE_CONTRACT_ID",
    "GUEST_DB_RECORD_ATTRIBUTION",
    "guest_record_to_context_item",
]
