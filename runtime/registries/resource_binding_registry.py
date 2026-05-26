from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


RESOURCE_BINDING_REGISTRY_PATH = Path(
    "agents/alexis/bindings/resources.json"
)
# Backward-compatible alias kept for existing imports.
CONTEXT_SOURCE_REGISTRY_PATH = RESOURCE_BINDING_REGISTRY_PATH
SUPPORTED_ADAPTER_TYPES = {"structured_database"}
SUPPORTED_EXECUTION_MODES = {"manual_future"}


class ContextSourceRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextSourceContract:
    binding_id: str
    adapter_type: str
    enabled: bool
    allowed_capabilities: list[str]
    requires_provenance_validation: bool
    max_injection_tokens: int
    execution_mode: str
    description: str
    raw_data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.binding_id

    @property
    def source_type(self) -> str:
        return self.adapter_type

    @property
    def allowed_shared_capabilities(self) -> list[str]:
        return self.allowed_capabilities


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return RESOURCE_BINDING_REGISTRY_PATH

    return Path(root) / RESOURCE_BINDING_REGISTRY_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> str:
    value = entry.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ContextSourceRegistryError(
            f"Context binding '{entry_id}' field '{key}' must be "
            "a non-empty string."
        )

    return value.strip()


def _require_string_list(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> list[str]:
    value = entry.get(key)

    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ContextSourceRegistryError(
            f"Context binding '{entry_id}' field '{key}' must be "
            "a non-empty list of strings."
        )

    return [item.strip() for item in value]


def _require_bool(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> bool:
    value = entry.get(key)

    if not isinstance(value, bool):
        raise ContextSourceRegistryError(
            f"Context binding '{entry_id}' field '{key}' must be "
            "a boolean."
        )

    return value


def _require_positive_int(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> int:
    value = entry.get(key)

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContextSourceRegistryError(
            f"Context binding '{entry_id}' field '{key}' must be "
            "a positive integer."
        )

    return value


def _contract_from_entry(entry: Any) -> ContextSourceContract:
    if not isinstance(entry, dict):
        raise ContextSourceRegistryError(
            "Context binding entries must be objects."
        )

    entry_id = _require_string(
        entry,
        "binding_id",
        entry_id="<unknown>",
    )
    adapter_type = _require_string(
        entry,
        "adapter_type",
        entry_id=entry_id,
    )
    execution_mode = _require_string(
        entry,
        "execution_mode",
        entry_id=entry_id,
    )

    if adapter_type not in SUPPORTED_ADAPTER_TYPES:
        raise ContextSourceRegistryError(
            f"Context binding '{entry_id}' uses unsupported "
            f"adapter_type '{adapter_type}'."
        )

    if execution_mode not in SUPPORTED_EXECUTION_MODES:
        raise ContextSourceRegistryError(
            f"Context binding '{entry_id}' uses unsupported "
            f"execution_mode '{execution_mode}'."
        )

    return ContextSourceContract(
        binding_id=entry_id,
        adapter_type=adapter_type,
        enabled=_require_bool(
            entry,
            "enabled",
            entry_id=entry_id,
        ),
        allowed_capabilities=_require_string_list(
            entry,
            "allowed_capabilities",
            entry_id=entry_id,
        ),
        requires_provenance_validation=_require_bool(
            entry,
            "requires_provenance_validation",
            entry_id=entry_id,
        ),
        max_injection_tokens=_require_positive_int(
            entry,
            "max_injection_tokens",
            entry_id=entry_id,
        ),
        execution_mode=execution_mode,
        description=_require_string(
            entry,
            "description",
            entry_id=entry_id,
        ),
        raw_data=dict(entry),
    )


def _load_context_source_registry_strict(
    root: str | Path | None = None,
) -> tuple[ContextSourceContract, ...]:
    path = _registry_path(root)

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ContextSourceRegistryError(
            "Context binding registry must be an object."
        )

    if data.get("version") != 1:
        raise ContextSourceRegistryError(
            "Context binding registry version must be 1."
        )

    bindings = data.get("bindings")

    if not isinstance(bindings, list):
        raise ContextSourceRegistryError(
            "Context binding registry 'bindings' must be a list."
        )

    return tuple(_contract_from_entry(entry) for entry in bindings)


@lru_cache(maxsize=None)
def load_context_source_registry(
    root: str | Path | None = None,
) -> tuple[ContextSourceContract, ...]:
    try:
        return _load_context_source_registry_strict(root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ContextSourceRegistryError,
    ):
        return ()


def list_context_source_contracts(
    root: str | Path | None = None,
) -> list[ContextSourceContract]:
    return list(load_context_source_registry(root))


def get_context_source_contract(
    source_id: str,
    *,
    root: str | Path | None = None,
) -> ContextSourceContract | None:
    normalized = str(source_id or "").strip()

    if not normalized:
        return None

    for contract in load_context_source_registry(root):
        if contract.binding_id == normalized:
            return contract

    return None


def list_context_sources_for_capability(
    shared_capability: str,
    *,
    root: str | Path | None = None,
) -> list[ContextSourceContract]:
    normalized = str(shared_capability or "").strip()

    if not normalized:
        return []

    return [
        contract
        for contract in load_context_source_registry(root)
        if normalized in contract.allowed_capabilities
    ]


def get_context_source_token_budget(
    source_id: str,
    *,
    root: str | Path | None = None,
) -> int | None:
    contract = get_context_source_contract(
        source_id,
        root=root,
    )

    if contract is None:
        return None

    return contract.max_injection_tokens


__all__ = [
    "RESOURCE_BINDING_REGISTRY_PATH",
    "CONTEXT_SOURCE_REGISTRY_PATH",
    "ContextSourceContract",
    "ContextSourceRegistryError",
    "get_context_source_contract",
    "get_context_source_token_budget",
    "list_context_source_contracts",
    "list_context_sources_for_capability",
    "load_context_source_registry",
]
