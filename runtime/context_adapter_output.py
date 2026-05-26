from __future__ import annotations

from runtime.context_types import (
    ResolvedContextItem,
    validate_resolved_context_item,
)


def validate_adapter_output(
    items: object,
) -> list[ResolvedContextItem]:
    if not isinstance(items, list):
        return []

    valid_items: list[ResolvedContextItem] = []

    for item in items:
        if not isinstance(item, ResolvedContextItem):
            continue

        if validate_resolved_context_item(item):
            continue

        valid_items.append(item)

    return valid_items


__all__ = ["validate_adapter_output"]
