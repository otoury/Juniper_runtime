from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


PROVIDER_BINDING_REGISTRY_PATH_PATTERN = Path(
    "agents/{agent_name}/bindings/providers.json"
)
REQUIRED_PROVIDER_BINDING_FIELDS = {
    "provider_id",
    "provider_contract_id",
    "provider_type",
    "owner_agent",
    "resource_binding_id",
    "resource_id",
    "execution_mode",
    "governance_state",
    "supported_output_types",
    "max_queries",
    "max_results",
    "semantic_operation",
    "semantic_owner",
    "semantic_retrieval_path",
    "provenance_required",
    "execution_policy",
}
SUPPORTED_PROVIDER_TYPES = {"local_agent_owned_database"}
SUPPORTED_EXECUTION_MODES = {"local_only"}
SUPPORTED_GOVERNANCE_STATES = {"enabled", "audit_only", "disabled"}
SUPPORTED_OUTPUT_TYPES = {"guest_candidate_list"}
FORBIDDEN_PROVIDER_BINDING_FIELDS = {
    "browser_callable",
    "cloud_model",
    "delivery_target",
    "execute",
    "executor",
    "gateway",
    "outreach_template",
    "prompt",
    "ranking",
    "send_email",
    "telegram",
    "web_search",
}


class ProviderBindingRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    provider_contract_id: str
    provider_type: str
    owner_agent: str
    resource_binding_id: str
    resource_id: str
    execution_mode: str
    governance_state: str
    supported_output_types: tuple[str, ...]
    max_queries: int
    max_results: int
    semantic_operation: str
    semantic_owner: str
    semantic_retrieval_path: str
    provenance_required: bool
    execution_policy: dict[str, bool]
    raw_data: dict[str, Any]

    @property
    def local_only(self) -> bool:
        return (
            self.execution_mode == "local_only"
            and self.execution_policy.get("local_only") is True
            and self.execution_policy.get("network_calls_allowed") is False
            and self.execution_policy.get("cloud_model_calls_allowed") is False
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_contract_id": self.provider_contract_id,
            "provider_type": self.provider_type,
            "owner_agent": self.owner_agent,
            "resource_binding_id": self.resource_binding_id,
            "resource_id": self.resource_id,
            "execution_mode": self.execution_mode,
            "governance_state": self.governance_state,
            "supported_output_types": list(self.supported_output_types),
            "max_queries": self.max_queries,
            "max_results": self.max_results,
            "semantic_operation": self.semantic_operation,
            "semantic_owner": self.semantic_owner,
            "semantic_retrieval_path": self.semantic_retrieval_path,
            "provenance_required": self.provenance_required,
            "execution_policy": dict(self.execution_policy),
            "local_only": self.local_only,
        }


def provider_binding_registry_path(
    agent_name: str,
    *,
    root: str | Path | None = None,
) -> Path:
    path = Path(
        str(PROVIDER_BINDING_REGISTRY_PATH_PATTERN).format(
            agent_name=str(agent_name or "").strip()
        )
    )
    if root is None:
        return path
    return Path(root) / path


def _require_string(entry: dict[str, Any], key: str, *, entry_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' field '{key}' must be a "
            "non-empty string."
        )
    return value.strip()


def _require_bool(entry: dict[str, Any], key: str, *, entry_id: str) -> bool:
    value = entry.get(key)
    if not isinstance(value, bool):
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' field '{key}' must be a boolean."
        )
    return value


def _require_int(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
    minimum: int = 1,
) -> int:
    value = entry.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' field '{key}' must be an integer "
            f"greater than or equal to {minimum}."
        )
    return value


def _require_string_list(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> tuple[str, ...]:
    value = entry.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' field '{key}' must be a "
            "non-empty list of strings."
        )
    return tuple(item.strip() for item in value)


def _require_bool_object(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
) -> dict[str, bool]:
    value = entry.get(key)
    if (
        not isinstance(value, dict)
        or not value
        or any(not isinstance(item, bool) for item in value.values())
    ):
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' field '{key}' must be an object "
            "with boolean values."
        )
    return dict(value)


def _forbidden_field_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_PROVIDER_BINDING_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_field_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


def _binding_from_entry(entry: Any, *, agent_name: str) -> ProviderBinding:
    if not isinstance(entry, dict):
        raise ProviderBindingRegistryError("Provider binding entries must be objects.")

    entry_id = _require_string(entry, "provider_id", entry_id="<unknown>")
    missing = sorted(REQUIRED_PROVIDER_BINDING_FIELDS - set(entry))
    if missing:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' is missing required fields: "
            + ", ".join(missing)
        )

    forbidden_paths = _forbidden_field_paths(entry)
    if forbidden_paths:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' contains forbidden fields: "
            + ", ".join(forbidden_paths)
        )

    owner_agent = _require_string(entry, "owner_agent", entry_id=entry_id)
    if owner_agent != agent_name:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' owner_agent must match registry agent."
        )

    provider_type = _require_string(entry, "provider_type", entry_id=entry_id)
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' has unsupported provider_type."
        )

    execution_mode = _require_string(entry, "execution_mode", entry_id=entry_id)
    if execution_mode not in SUPPORTED_EXECUTION_MODES:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' has unsupported execution_mode."
        )

    governance_state = _require_string(entry, "governance_state", entry_id=entry_id)
    if governance_state not in SUPPORTED_GOVERNANCE_STATES:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' has unsupported governance_state."
        )

    output_types = _require_string_list(
        entry,
        "supported_output_types",
        entry_id=entry_id,
    )
    if not set(output_types).issubset(SUPPORTED_OUTPUT_TYPES):
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' has unsupported output types."
        )

    execution_policy = _require_bool_object(
        entry,
        "execution_policy",
        entry_id=entry_id,
    )
    for key in (
        "network_calls_allowed",
        "cloud_model_calls_allowed",
        "live_embedding_calls_allowed",
        "delivery_allowed",
    ):
        if execution_policy.get(key) is not False:
            raise ProviderBindingRegistryError(
                f"Provider binding '{entry_id}' must keep {key}=false."
            )
    if execution_policy.get("local_only") is not True:
        raise ProviderBindingRegistryError(
            f"Provider binding '{entry_id}' must declare local_only=true."
        )

    return ProviderBinding(
        provider_id=entry_id,
        provider_contract_id=_require_string(
            entry,
            "provider_contract_id",
            entry_id=entry_id,
        ),
        provider_type=provider_type,
        owner_agent=owner_agent,
        resource_binding_id=_require_string(
            entry,
            "resource_binding_id",
            entry_id=entry_id,
        ),
        resource_id=_require_string(entry, "resource_id", entry_id=entry_id),
        execution_mode=execution_mode,
        governance_state=governance_state,
        supported_output_types=output_types,
        max_queries=_require_int(entry, "max_queries", entry_id=entry_id),
        max_results=_require_int(entry, "max_results", entry_id=entry_id),
        semantic_operation=_require_string(
            entry,
            "semantic_operation",
            entry_id=entry_id,
        ),
        semantic_owner=_require_string(entry, "semantic_owner", entry_id=entry_id),
        semantic_retrieval_path=_require_string(
            entry,
            "semantic_retrieval_path",
            entry_id=entry_id,
        ),
        provenance_required=_require_bool(
            entry,
            "provenance_required",
            entry_id=entry_id,
        ),
        execution_policy=execution_policy,
        raw_data=dict(entry),
    )


def _load_provider_bindings_strict(
    agent_name: str,
    *,
    root: str | Path | None = None,
) -> tuple[ProviderBinding, ...]:
    normalized_agent = str(agent_name or "").strip()
    if not normalized_agent:
        raise ProviderBindingRegistryError("Provider binding agent name is required.")

    data = json.loads(
        provider_binding_registry_path(normalized_agent, root=root).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ProviderBindingRegistryError(
            "Provider binding registry version must be 1."
        )

    bindings = data.get("bindings")
    if not isinstance(bindings, list):
        raise ProviderBindingRegistryError(
            "Provider binding registry 'bindings' must be a list."
        )

    loaded = tuple(
        _binding_from_entry(entry, agent_name=normalized_agent)
        for entry in bindings
    )
    provider_ids = [binding.provider_id for binding in loaded]
    if len(provider_ids) != len(set(provider_ids)):
        raise ProviderBindingRegistryError(
            "Provider binding registry contains duplicate provider IDs."
        )
    return loaded


@lru_cache(maxsize=None)
def load_provider_bindings(
    agent_name: str,
    *,
    root: str | Path | None = None,
) -> tuple[ProviderBinding, ...]:
    try:
        return _load_provider_bindings_strict(agent_name, root=root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        ProviderBindingRegistryError,
    ):
        return ()


def get_provider_binding(
    provider_id: str,
    *,
    agent_name: str,
    root: str | Path | None = None,
) -> ProviderBinding | None:
    normalized = str(provider_id or "").strip()
    if not normalized:
        return None

    for binding in load_provider_bindings(agent_name, root=root):
        if binding.provider_id == normalized:
            return binding
    return None


__all__ = [
    "FORBIDDEN_PROVIDER_BINDING_FIELDS",
    "PROVIDER_BINDING_REGISTRY_PATH_PATTERN",
    "ProviderBinding",
    "ProviderBindingRegistryError",
    "REQUIRED_PROVIDER_BINDING_FIELDS",
    "SUPPORTED_EXECUTION_MODES",
    "SUPPORTED_GOVERNANCE_STATES",
    "SUPPORTED_OUTPUT_TYPES",
    "SUPPORTED_PROVIDER_TYPES",
    "get_provider_binding",
    "load_provider_bindings",
    "provider_binding_registry_path",
]
