from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTEXT_INJECTION_BINDING_REGISTRY_PATH = Path(
    "agents/alexis/bindings/context_injections.json"
)
# Backward-compatible alias kept for existing imports.
CONTEXT_INJECTION_REGISTRY_PATH = CONTEXT_INJECTION_BINDING_REGISTRY_PATH
SUPPORTED_INJECTION_MODES = {"synthetic"}
SUPPORTED_SOURCE_TYPES = {"agent_resource"}


class ContextInjectionRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextInjectionContract:
    id: str
    enabled: bool
    agent_scope: list[str]
    shared_capability_scope: list[str]
    source_contract_id: str
    operation_scope: list[str]
    injection_mode: str
    content: str
    source_name: str
    source_type: str
    max_items: int
    max_tokens: int
    requires_provenance_validation: bool
    rollback_env_flag: str
    telemetry_label: str
    raw_data: dict[str, Any]


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return CONTEXT_INJECTION_BINDING_REGISTRY_PATH

    return Path(root) / CONTEXT_INJECTION_BINDING_REGISTRY_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> str:
    value = entry.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ContextInjectionRegistryError(
            f"Context injection '{entry_id}' field '{key}' must be "
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
        raise ContextInjectionRegistryError(
            f"Context injection '{entry_id}' field '{key}' must be "
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
        raise ContextInjectionRegistryError(
            f"Context injection '{entry_id}' field '{key}' must be "
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
        raise ContextInjectionRegistryError(
            f"Context injection '{entry_id}' field '{key}' must be "
            "a positive integer."
        )

    return value


def _contract_from_entry(entry: Any) -> ContextInjectionContract:
    if not isinstance(entry, dict):
        raise ContextInjectionRegistryError(
            "Context injection entries must be objects."
        )

    entry_id = _require_string(
        entry,
        "id",
        entry_id="<unknown>",
    )
    injection_mode = _require_string(
        entry,
        "injection_mode",
        entry_id=entry_id,
    )
    source_type = _require_string(
        entry,
        "source_type",
        entry_id=entry_id,
    )

    if injection_mode not in SUPPORTED_INJECTION_MODES:
        raise ContextInjectionRegistryError(
            f"Context injection '{entry_id}' uses unsupported "
            f"injection_mode '{injection_mode}'."
        )

    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ContextInjectionRegistryError(
            f"Context injection '{entry_id}' uses unsupported "
            f"source_type '{source_type}'."
        )

    return ContextInjectionContract(
        id=entry_id,
        enabled=_require_bool(
            entry,
            "enabled",
            entry_id=entry_id,
        ),
        agent_scope=_require_string_list(
            entry,
            "agent_scope",
            entry_id=entry_id,
        ),
        shared_capability_scope=_require_string_list(
            entry,
            "shared_capability_scope",
            entry_id=entry_id,
        ),
        source_contract_id=_require_string(
            entry,
            "source_contract_id",
            entry_id=entry_id,
        ),
        operation_scope=_require_string_list(
            entry,
            "operation_scope",
            entry_id=entry_id,
        ),
        injection_mode=injection_mode,
        content=_require_string(
            entry,
            "content",
            entry_id=entry_id,
        ),
        source_name=_require_string(
            entry,
            "source_name",
            entry_id=entry_id,
        ),
        source_type=source_type,
        max_items=_require_positive_int(
            entry,
            "max_items",
            entry_id=entry_id,
        ),
        max_tokens=_require_positive_int(
            entry,
            "max_tokens",
            entry_id=entry_id,
        ),
        requires_provenance_validation=_require_bool(
            entry,
            "requires_provenance_validation",
            entry_id=entry_id,
        ),
        rollback_env_flag=_require_string(
            entry,
            "rollback_env_flag",
            entry_id=entry_id,
        ),
        telemetry_label=_require_string(
            entry,
            "telemetry_label",
            entry_id=entry_id,
        ),
        raw_data=dict(entry),
    )


@lru_cache(maxsize=None)
def load_context_injection_registry(
    root: str | Path | None = None,
) -> tuple[ContextInjectionContract, ...]:
    path = _registry_path(root)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContextInjectionRegistryError(
            f"Missing context injection registry: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ContextInjectionRegistryError(
            f"Invalid context injection registry JSON in {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ContextInjectionRegistryError(
            "Context injection registry must be an object."
        )

    if data.get("version") != 1:
        raise ContextInjectionRegistryError(
            "Context injection registry version must be 1."
        )

    injections = data.get("injections")

    if not isinstance(injections, list):
        raise ContextInjectionRegistryError(
            "Context injection registry 'injections' must be a list."
        )

    return tuple(_contract_from_entry(entry) for entry in injections)


def list_context_injection_contracts(
    root: str | Path | None = None,
) -> list[ContextInjectionContract]:
    return list(load_context_injection_registry(root))


def find_context_injection_contracts(
    *,
    agent_name: str,
    shared_capability: str | None,
    operation: str | None = None,
    root: str | Path | None = None,
) -> list[ContextInjectionContract]:
    operation_name = str(operation or "NEW_REQUEST").upper().strip()

    return [
        contract
        for contract in load_context_injection_registry(root)
        if agent_name in contract.agent_scope
        and shared_capability in contract.shared_capability_scope
        and operation_name in contract.operation_scope
    ]


__all__ = [
    "CONTEXT_INJECTION_BINDING_REGISTRY_PATH",
    "CONTEXT_INJECTION_REGISTRY_PATH",
    "ContextInjectionContract",
    "ContextInjectionRegistryError",
    "find_context_injection_contracts",
    "list_context_injection_contracts",
    "load_context_injection_registry",
]
