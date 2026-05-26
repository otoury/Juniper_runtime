from __future__ import annotations

from typing import Any

from runtime.context_types import ResolvedContextItem


def _item_id(item: Any) -> str | None:
    if isinstance(item, ResolvedContextItem):
        return item.id

    return None


def summarize_context_collection(
    original_items: list[ResolvedContextItem],
    accepted_items: list[ResolvedContextItem],
    max_items: int,
    max_total_tokens: int,
) -> dict[str, Any]:
    accepted_ids = {
        item.id
        for item in accepted_items
        if isinstance(item, ResolvedContextItem)
    }
    original_ids = [
        item_id
        for item_id in (_item_id(item) for item in original_items)
        if item_id is not None
    ]
    accepted_item_ids = [
        item.id
        for item in accepted_items
        if isinstance(item, ResolvedContextItem)
    ]

    return {
        "original_count": len(original_items),
        "accepted_count": len(accepted_item_ids),
        "dropped_count": max(
            0,
            len(original_items) - len(accepted_item_ids),
        ),
        "accepted_item_ids": accepted_item_ids,
        "dropped_item_ids": [
            item_id
            for item_id in original_ids
            if item_id not in accepted_ids
        ],
        "accepted_source_contract_ids": [
            item.source_contract_id
            for item in accepted_items
            if isinstance(item, ResolvedContextItem)
        ],
        "total_estimated_tokens": sum(
            item.estimated_tokens
            for item in accepted_items
            if isinstance(item, ResolvedContextItem)
        ),
        "max_items": max_items,
        "max_total_tokens": max_total_tokens,
    }


__all__ = [
    "summarize_context_collection",
]
