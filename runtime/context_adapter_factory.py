from __future__ import annotations

from collections.abc import Callable

from agents.alexis.adapters.guest_db.fixture_adapter import (
    GuestDbReadonlyFixtureAdapter,
)
from agents.alexis.adapters.guest_db.readonly_adapter import (
    AlexisGuestDbReadonlyAdapter,
)
from runtime.adapters.synthetic_guest_context_adapter import (
    SyntheticGuestContextAdapter,
)
from runtime.context_adapter import ContextRetrievalAdapter
from runtime.registries.context_injection_binding_registry import (
    ContextInjectionContract,
)
from runtime.registries.adapter_binding_registry import (
    ContextAdapterContract,
)


ContextAdapterFactory = Callable[
    [ContextInjectionContract, ContextAdapterContract],
    ContextRetrievalAdapter,
]


APPROVED_CONTEXT_ADAPTER_FACTORIES: dict[str, ContextAdapterFactory] = {
    "guest_db_readonly": AlexisGuestDbReadonlyAdapter,
    "guest_db_readonly_fixture": (
        lambda contract, adapter_contract: GuestDbReadonlyFixtureAdapter(
            contract
        )
    ),
    "synthetic_guest_context": (
        lambda contract, adapter_contract: SyntheticGuestContextAdapter(
            contract
        )
    ),
}


def get_context_adapter_factory(
    adapter_id: str,
) -> ContextAdapterFactory | None:
    return APPROVED_CONTEXT_ADAPTER_FACTORIES.get(adapter_id)


def create_context_adapter(
    adapter_id: str,
    contract: ContextInjectionContract,
    adapter_contract: ContextAdapterContract,
) -> ContextRetrievalAdapter | None:
    factory = get_context_adapter_factory(adapter_id)

    if factory is None:
        return None

    return factory(contract, adapter_contract)


__all__ = [
    "APPROVED_CONTEXT_ADAPTER_FACTORIES",
    "ContextAdapterFactory",
    "create_context_adapter",
    "get_context_adapter_factory",
]
