from __future__ import annotations

from typing import Protocol

from runtime.context_types import ResolvedContextItem


class ContextRetrievalAdapter(Protocol):
    adapter_id: str

    def retrieve(
        self,
        *,
        request_id: str | None,
        agent: str,
        shared_capability: str | None,
    ) -> list[ResolvedContextItem]:
        ...


__all__ = [
    "ContextRetrievalAdapter",
]
