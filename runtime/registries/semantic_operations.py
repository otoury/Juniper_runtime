from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


OPERATIONS_PATH = Path("agents/shared/semantics/operations.json")
COMPAT_OPERATIONS_PATH = Path("config/semantic/operations.json")
RETIRED_COMPAT_OPERATION_PATHS = (
    COMPAT_OPERATIONS_PATH,
)
AGENTS_SHARED_SEMANTICS_DIR = Path("agents/shared/semantics")
REQUIRED_FIELDS = {
    "interaction_mode",
    "requires_active_artifact",
    "requires_artifact_context",
    "needs_capability_context",
    "preserves_artifact_type",
    "description",
}


class SemanticOperationRegistryError(RuntimeError):
    pass


def _read_operation_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SemanticOperationRegistryError(
            f"Invalid semantic operation registry JSON in {path}: {exc}"
        ) from exc


def _merge_operation_data(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    merged = {
        "operations": dict(base.get("operations", {})),
    }
    merged["operations"].update(
        override.get("operations", {})
    )
    return merged


def _load_operation_directory(folder: Path) -> dict[str, Any]:
    data = {}

    if not folder.exists():
        return data

    for path in sorted(folder.glob("*.json")):
        data = _merge_operation_data(
            data,
            _read_operation_file(path),
        )

    return data


@lru_cache(maxsize=None)
def load_operation_registry() -> dict[str, dict[str, Any]]:
    data = {}

    for path in RETIRED_COMPAT_OPERATION_PATHS:
        if path.exists():
            data = _merge_operation_data(
                data,
                _read_operation_file(path),
            )

    data = _merge_operation_data(
        data,
        _load_operation_directory(AGENTS_SHARED_SEMANTICS_DIR),
    )

    operations = data.get("operations")

    if not isinstance(operations, dict):
        raise SemanticOperationRegistryError(
            f"Missing semantic operation registry: {OPERATIONS_PATH}"
        )

    normalized = {}

    for name, policy in operations.items():
        operation = str(name or "").upper().strip()

        if not operation:
            raise SemanticOperationRegistryError(
                "Semantic operation registry contains an empty "
                "operation name."
            )

        if not isinstance(policy, dict):
            raise SemanticOperationRegistryError(
                f"Semantic operation '{operation}' policy must be "
                "an object."
            )

        missing = REQUIRED_FIELDS - set(policy)

        if missing:
            raise SemanticOperationRegistryError(
                f"Semantic operation '{operation}' missing required "
                f"fields: {sorted(missing)}"
            )

        normalized[operation] = dict(policy)

    return normalized


def list_operation_names() -> list[str]:
    return sorted(load_operation_registry())


def get_operation_policy(
    operation: str,
) -> dict[str, Any]:
    normalized = str(operation or "").upper().strip()

    if not normalized:
        raise SemanticOperationRegistryError(
            "Operation name is required."
        )

    registry = load_operation_registry()

    try:
        return dict(registry[normalized])
    except KeyError as exc:
        raise SemanticOperationRegistryError(
            f"Unknown semantic operation: {normalized}"
        ) from exc


def get_operation_metadata(
    operation: str,
    key: str,
    default: Any = None,
) -> Any:
    return get_operation_policy(operation).get(key, default)


__all__ = [
    "AGENTS_SHARED_SEMANTICS_DIR",
    "COMPAT_OPERATIONS_PATH",
    "OPERATIONS_PATH",
    "RETIRED_COMPAT_OPERATION_PATHS",
    "SemanticOperationRegistryError",
    "load_operation_registry",
    "list_operation_names",
    "get_operation_policy",
    "get_operation_metadata",
]
