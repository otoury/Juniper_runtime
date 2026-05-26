from __future__ import annotations

from runtime.context_types import (
    ResolvedContextItem,
    ResolvedContextProvenance,
)
from runtime.registries.context_injection_binding_registry import (
    ContextInjectionContract,
)


class SyntheticGuestContextAdapter:
    adapter_id = "synthetic_guest_context"

    def __init__(
        self,
        contract: ContextInjectionContract,
    ) -> None:
        self.contract = contract

    def retrieve(
        self,
        *,
        request_id: str | None,
        agent: str,
        shared_capability: str | None,
    ) -> list[ResolvedContextItem]:
        item_request_id = request_id or "context"
        rendered_text = (
            "BOUNDED CONTEXT (synthetic, attributed, no retrieval):\n"
            f"{self.contract.content}"
        )

        return [
            ResolvedContextItem(
                id=f"{item_request_id}:{self.contract.id}",
                source_contract_id=self.contract.source_contract_id,
                content=rendered_text,
                content_type="synthetic_notice",
                provenance=ResolvedContextProvenance(
                    source_contract_id=self.contract.source_contract_id,
                    retrieval_executed=False,
                    attribution="synthetic_system_notice",
                ),
                estimated_tokens=len(rendered_text.split()),
                trust_level="system_declared",
                rendering_policy="bounded_context_block",
                metadata={
                    "adapter_id": self.adapter_id,
                    "agent": agent,
                    "shared_capability": shared_capability,
                    "source_type": self.contract.source_type,
                    "injection_mode": self.contract.injection_mode,
                },
            )
        ]


__all__ = [
    "SyntheticGuestContextAdapter",
]
