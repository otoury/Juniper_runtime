from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.lookup.types import (
    BoundedLookupRequest,
    validate_bounded_lookup_request,
)


ADAPTER_BINDING_REGISTRY_PATH = Path(
    "agents/alexis/bindings/adapters.json"
)
# Backward-compatible alias kept for existing imports.
CONTEXT_ADAPTER_REGISTRY_PATH = ADAPTER_BINDING_REGISTRY_PATH
SUPPORTED_ADAPTER_TYPES = {"structured_database", "synthetic"}
SUPPORTED_EXECUTION_MODES = {
    "read_only_declared",
    "read_only_fixed_id",
    "read_only_fixture",
    "synthetic_only",
}
SUPPORTED_READ_SCOPES = {
    "declared_local_database",
    "local_fixture_file",
}
SINGLE_RECORD_READ_MODES = {
    "read_only_declared",
    "read_only_fixed_id",
    "read_only_fixture",
}
UNCONFIGURED_READ_TARGET = "UNCONFIGURED"


class ContextAdapterRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextAdapterContract:
    adapter_id: str
    source_contract_id: str
    enabled: bool
    adapter_type: str
    execution_mode: str
    external_reads_allowed: bool
    read_scope: str | None
    read_target: str | None
    max_records: int | None
    writes_allowed: bool | None
    raw_data: dict[str, Any]
    lookup_request: BoundedLookupRequest | None = None


def _registry_path(root: str | Path | None = None) -> Path:
    if root is None:
        return ADAPTER_BINDING_REGISTRY_PATH

    return Path(root) / ADAPTER_BINDING_REGISTRY_PATH


def _require_string(
    entry: dict[str, Any],
    key: str,
    *,
    adapter_id: str,
) -> str:
    value = entry.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' field '{key}' must be "
            "a non-empty string."
        )

    return value.strip()


def _require_bool(
    entry: dict[str, Any],
    key: str,
    *,
    adapter_id: str,
) -> bool:
    value = entry.get(key)

    if not isinstance(value, bool):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' field '{key}' must be "
            "a boolean."
        )

    return value


def _require_positive_int(
    entry: dict[str, Any],
    key: str,
    *,
    adapter_id: str,
) -> int:
    value = entry.get(key)

    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' field '{key}' must be "
            "an integer >= 1."
        )

    return value


def _validate_local_fixture_read_target(
    *,
    adapter_id: str,
    read_target: str,
) -> None:
    path = Path(read_target)

    if path.is_absolute():
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' local_fixture_file "
            "read_target must be relative."
        )

    if ".." in path.parts:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' local_fixture_file "
            "read_target must not contain '..'."
        )

    if not read_target.startswith("tools/fixtures/"):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' local_fixture_file "
            "read_target must start with 'tools/fixtures/'."
        )

    if not read_target.endswith(".json"):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' local_fixture_file "
            "read_target must end with '.json'."
        )


def _validate_declared_local_database_read_target(
    *,
    adapter_id: str,
    enabled: bool,
    read_target: str,
) -> None:
    if read_target == UNCONFIGURED_READ_TARGET:
        if enabled:
            raise ContextAdapterRegistryError(
                f"Context adapter '{adapter_id}' declared_local_database "
                "read_target must not be UNCONFIGURED when enabled=true."
            )
        return

    path = Path(read_target)

    if path.is_absolute():
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' declared_local_database "
            "read_target must be relative."
        )

    if ".." in path.parts:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' declared_local_database "
            "read_target must not contain '..'."
        )

    canonical_csv_prefix = (
        "agents/alexis/adapters/guest_db/resources/canonical/"
    )

    if read_target.startswith(canonical_csv_prefix):
        if not read_target.endswith(".csv"):
            raise ContextAdapterRegistryError(
                f"Context adapter '{adapter_id}' declared_local_database "
                "canonical read_target must end with '.csv'."
            )
        return

    if not read_target.startswith("data/"):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' declared_local_database "
            "read_target must start with 'data/' or the approved "
            "Alexis guest DB canonical resource path."
        )

    if not read_target.endswith((".json", ".sqlite")):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' declared_local_database "
            "read_target must end with '.json' or '.sqlite'."
        )


def _lookup_request_from_entry(
    entry: dict[str, Any],
    *,
    adapter_id: str,
    source_contract_id: str,
    execution_mode: str,
    max_records: int | None,
) -> BoundedLookupRequest | None:
    raw_request = entry.get("bounded_lookup_request")

    if raw_request is None:
        return None

    if not isinstance(raw_request, dict):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' bounded_lookup_request "
            "must be an object."
        )

    try:
        request = BoundedLookupRequest(
            lookup_id=raw_request.get("lookup_id"),
            source_contract_id=raw_request.get("source_contract_id"),
            lookup_mode=raw_request.get("lookup_mode"),
            query=raw_request.get("query"),
            lookup_key=raw_request.get("lookup_key"),
            lookup_value=raw_request.get("lookup_value"),
            max_records=raw_request.get("max_records"),
        )
    except TypeError as exc:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' bounded_lookup_request "
            "has invalid fields."
        ) from exc

    errors = validate_bounded_lookup_request(request)

    if errors:
        fields = ", ".join(error.field for error in errors)
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' bounded_lookup_request "
            f"is invalid: {fields}."
        )

    if request.source_contract_id != source_contract_id:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' bounded_lookup_request "
            "source_contract_id must match adapter source_contract_id."
        )

    if max_records is None or request.max_records > max_records:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' bounded_lookup_request "
            "max_records must not exceed adapter max_records."
        )

    if (
        execution_mode == "read_only_fixed_id"
        and request.lookup_mode != "fixed_id"
    ):
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' read_only_fixed_id "
            "execution_mode requires lookup_mode='fixed_id'."
        )

    return request


def _contract_from_entry(entry: Any) -> ContextAdapterContract:
    if not isinstance(entry, dict):
        raise ContextAdapterRegistryError(
            "Context adapter entries must be objects."
        )

    adapter_id = _require_string(
        entry,
        "adapter_id",
        adapter_id="<unknown>",
    )
    adapter_type = _require_string(
        entry,
        "adapter_type",
        adapter_id=adapter_id,
    )
    execution_mode = _require_string(
        entry,
        "execution_mode",
        adapter_id=adapter_id,
    )
    enabled = _require_bool(
        entry,
        "enabled",
        adapter_id=adapter_id,
    )

    if adapter_type not in SUPPORTED_ADAPTER_TYPES:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' uses unsupported "
            f"adapter_type '{adapter_type}'."
        )

    if execution_mode not in SUPPORTED_EXECUTION_MODES:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' uses unsupported "
            f"execution_mode '{execution_mode}'."
        )

    external_reads_allowed = _require_bool(
        entry,
        "external_reads_allowed",
        adapter_id=adapter_id,
    )

    if execution_mode == "synthetic_only" and external_reads_allowed:
        raise ContextAdapterRegistryError(
            f"Context adapter '{adapter_id}' uses synthetic_only "
            "execution_mode but allows external reads."
        )

    read_scope: str | None = None
    read_target: str | None = None
    max_records: int | None = None
    writes_allowed: bool | None = None

    if external_reads_allowed:
        read_scope = _require_string(
            entry,
            "read_scope",
            adapter_id=adapter_id,
        )
        read_target = _require_string(
            entry,
            "read_target",
            adapter_id=adapter_id,
        )
        max_records = _require_positive_int(
            entry,
            "max_records",
            adapter_id=adapter_id,
        )
        writes_allowed = _require_bool(
            entry,
            "writes_allowed",
            adapter_id=adapter_id,
        )

        if writes_allowed:
            raise ContextAdapterRegistryError(
                f"Context adapter '{adapter_id}' field 'writes_allowed' "
                "must be false."
            )

        if execution_mode in SINGLE_RECORD_READ_MODES and max_records != 1:
            raise ContextAdapterRegistryError(
                f"Context adapter '{adapter_id}' uses {execution_mode} "
                "execution_mode and must declare max_records=1."
            )

        if read_scope not in SUPPORTED_READ_SCOPES:
            raise ContextAdapterRegistryError(
                f"Context adapter '{adapter_id}' uses unsupported "
                f"read_scope '{read_scope}'."
            )

        if read_scope == "local_fixture_file":
            _validate_local_fixture_read_target(
                adapter_id=adapter_id,
                read_target=read_target,
            )

        if read_scope == "declared_local_database":
            _validate_declared_local_database_read_target(
                adapter_id=adapter_id,
                enabled=enabled,
                read_target=read_target,
            )

    source_contract_id = _require_string(
        entry,
        "source_contract_id",
        adapter_id=adapter_id,
    )

    return ContextAdapterContract(
        adapter_id=adapter_id,
        source_contract_id=source_contract_id,
        enabled=enabled,
        adapter_type=adapter_type,
        execution_mode=execution_mode,
        external_reads_allowed=external_reads_allowed,
        read_scope=read_scope,
        read_target=read_target,
        max_records=max_records,
        writes_allowed=writes_allowed,
        raw_data=dict(entry),
        lookup_request=_lookup_request_from_entry(
            entry,
            adapter_id=adapter_id,
            source_contract_id=source_contract_id,
            execution_mode=execution_mode,
            max_records=max_records,
        ),
    )


def _load_context_adapter_registry_strict(
    root: str | Path | None = None,
) -> tuple[ContextAdapterContract, ...]:
    path = _registry_path(root)
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ContextAdapterRegistryError(
            "Context adapter registry must be an object."
        )

    if data.get("version") != 1:
        raise ContextAdapterRegistryError(
            "Context adapter registry version must be 1."
        )

    adapters = data.get("adapters")

    if not isinstance(adapters, list):
        raise ContextAdapterRegistryError(
            "Context adapter registry 'adapters' must be a list."
        )

    return tuple(_contract_from_entry(entry) for entry in adapters)


def load_context_adapter_registry_strict(
    root: str | Path | None = None,
) -> tuple[ContextAdapterContract, ...]:
    return _load_context_adapter_registry_strict(root)


@lru_cache(maxsize=None)
def load_context_adapter_registry(
    root: str | Path | None = None,
) -> tuple[ContextAdapterContract, ...]:
    try:
        return _load_context_adapter_registry_strict(root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ContextAdapterRegistryError,
    ):
        return ()


def list_context_adapter_contracts(
    root: str | Path | None = None,
) -> list[ContextAdapterContract]:
    return list(load_context_adapter_registry(root))


def get_context_adapter_for_source(
    source_contract_id: str,
    *,
    root: str | Path | None = None,
) -> ContextAdapterContract | None:
    normalized = str(source_contract_id or "").strip()

    if not normalized:
        return None

    matches = [
        contract
        for contract in load_context_adapter_registry(root)
        if contract.source_contract_id == normalized
        and contract.enabled
    ]

    if len(matches) != 1:
        return None

    return matches[0]


__all__ = [
    "ADAPTER_BINDING_REGISTRY_PATH",
    "CONTEXT_ADAPTER_REGISTRY_PATH",
    "ContextAdapterContract",
    "ContextAdapterRegistryError",
    "get_context_adapter_for_source",
    "list_context_adapter_contracts",
    "load_context_adapter_registry",
    "load_context_adapter_registry_strict",
]
