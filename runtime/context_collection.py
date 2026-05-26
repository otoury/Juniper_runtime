from __future__ import annotations

from runtime.context_types import (
    ResolvedContextItem,
    validate_resolved_context_item,
)


def validate_context_item_collection(
    items: list[ResolvedContextItem],
    max_items: int,
    max_total_tokens: int,
) -> list[ResolvedContextItem]:
    if (
        not isinstance(items, list)
        or not isinstance(max_items, int)
        or isinstance(max_items, bool)
        or max_items <= 0
        or not isinstance(max_total_tokens, int)
        or isinstance(max_total_tokens, bool)
        or max_total_tokens <= 0
    ):
        return []

    accepted: list[ResolvedContextItem] = []
    total_tokens = 0

    for item in items:
        if len(accepted) >= max_items:
            break

        if not isinstance(item, ResolvedContextItem):
            continue

        if validate_resolved_context_item(item):
            continue

        if total_tokens + item.estimated_tokens > max_total_tokens:
            continue

        accepted.append(item)
        total_tokens += item.estimated_tokens

    return accepted


__all__ = [
    "validate_context_item_collection",
]
