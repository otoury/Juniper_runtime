from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.policies.cloud_provider_authorization import (
    ALLOWED_AUTHORIZATION_MODES,
    AUTHORIZATION_MODE_ALL_TELEGRAM_USERS,
)
from runtime.policies.model_registry import ENGINES


CLOUD_PROVIDER_PILOT_REGISTRY_PATH_PATTERN = Path(
    "agents/{agent_name}/bindings/cloud_provider_pilots.json"
)
REQUIRED_PILOT_FIELDS = {
    "pilot_id",
    "agent_id",
    "channel",
    "provider_id",
    "authorization_mode",
    "governance_state",
    "max_queries",
    "max_results",
    "engine_policy_ref",
    "execution_policy",
}
SUPPORTED_PILOT_CHANNELS = {"telegram"}
SUPPORTED_PILOT_GOVERNANCE_STATES = {"enabled", "audit_only", "disabled"}
MAX_PILOT_QUERIES = 3
MAX_PILOT_RESULTS = 10
FORBIDDEN_PILOT_FIELDS = {
    "adapter_callable",
    "delivery_target",
    "execute",
    "executor",
    "gateway",
    "normalizer",
    "outreach_template",
    "prompt",
    "ranking",
    "send_email",
}


class CloudProviderPilotRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CloudProviderPilotBinding:
    pilot_id: str
    agent_id: str
    channel: str
    provider_id: str
    authorization_mode: str
    governance_state: str
    max_queries: int
    max_results: int
    engine_policy_ref: str
    execution_policy: dict[str, bool]
    raw_data: dict[str, Any]

    @property
    def declaration_only(self) -> bool:
        return (
            self.execution_policy.get("authorization_declaration_only") is True
            and self.execution_policy.get("provider_call_implemented") is False
            and self.execution_policy.get("network_calls_allowed") is False
            and self.execution_policy.get("cloud_model_calls_allowed") is False
            and self.execution_policy.get("delivery_allowed") is False
            and self.execution_policy.get("normalization_allowed") is False
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "pilot_id": self.pilot_id,
            "agent_id": self.agent_id,
            "channel": self.channel,
            "provider_id": self.provider_id,
            "authorization_mode": self.authorization_mode,
            "governance_state": self.governance_state,
            "max_queries": self.max_queries,
            "max_results": self.max_results,
            "engine_policy_ref": self.engine_policy_ref,
            "execution_policy": dict(self.execution_policy),
            "declaration_only": self.declaration_only,
        }


def cloud_provider_pilot_registry_path(
    agent_name: str,
    *,
    root: str | Path | None = None,
) -> Path:
    path = Path(
        str(CLOUD_PROVIDER_PILOT_REGISTRY_PATH_PATTERN).format(
            agent_name=str(agent_name or "").strip()
        )
    )
    if root is None:
        return path
    return Path(root) / path


def _require_string(entry: dict[str, Any], key: str, *, entry_id: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' field '{key}' must be a "
            "non-empty string."
        )
    return value.strip()


def _require_int(
    entry: dict[str, Any],
    key: str,
    *,
    entry_id: str,
    minimum: int = 1,
    maximum: int,
) -> int:
    value = entry.get(key)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' field '{key}' must be an "
            f"integer from {minimum} to {maximum}."
        )
    return value


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
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' field '{key}' must be an "
            "object with boolean values."
        )
    return dict(value)


def _forbidden_field_paths(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_PILOT_FIELDS:
                paths.append(path)
            paths.extend(_forbidden_field_paths(item, prefix=path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_field_paths(item, prefix=f"{prefix}[{index}]"))
        return tuple(paths)
    return ()


def _pilot_from_entry(entry: Any, *, agent_name: str) -> CloudProviderPilotBinding:
    if not isinstance(entry, dict):
        raise CloudProviderPilotRegistryError(
            "Cloud provider pilot entries must be objects."
        )

    entry_id = _require_string(entry, "pilot_id", entry_id="<unknown>")
    missing = sorted(REQUIRED_PILOT_FIELDS - set(entry))
    if missing:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' is missing required fields: "
            + ", ".join(missing)
        )

    forbidden_paths = _forbidden_field_paths(entry)
    if forbidden_paths:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' contains forbidden fields: "
            + ", ".join(forbidden_paths)
        )

    agent_id = _require_string(entry, "agent_id", entry_id=entry_id)
    if agent_id != agent_name:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' agent_id must match registry agent."
        )

    channel = _require_string(entry, "channel", entry_id=entry_id).lower()
    if channel not in SUPPORTED_PILOT_CHANNELS:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' has unsupported channel."
        )

    authorization_mode = _require_string(
        entry,
        "authorization_mode",
        entry_id=entry_id,
    )
    if authorization_mode not in ALLOWED_AUTHORIZATION_MODES:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' has unsupported authorization mode."
        )
    if authorization_mode != AUTHORIZATION_MODE_ALL_TELEGRAM_USERS:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' must use all-channel-user mode."
        )

    governance_state = _require_string(entry, "governance_state", entry_id=entry_id)
    if governance_state not in SUPPORTED_PILOT_GOVERNANCE_STATES:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' has unsupported governance state."
        )

    engine_policy_ref = _require_string(
        entry,
        "engine_policy_ref",
        entry_id=entry_id,
    )
    if engine_policy_ref not in ENGINES:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' references an unknown engine policy."
        )

    execution_policy = _require_bool_object(
        entry,
        "execution_policy",
        entry_id=entry_id,
    )
    for key in (
        "provider_call_implemented",
        "network_calls_allowed",
        "cloud_model_calls_allowed",
        "delivery_allowed",
        "normalization_allowed",
    ):
        if execution_policy.get(key) is not False:
            raise CloudProviderPilotRegistryError(
                f"Cloud provider pilot '{entry_id}' must keep {key}=false."
            )
    if execution_policy.get("authorization_declaration_only") is not True:
        raise CloudProviderPilotRegistryError(
            f"Cloud provider pilot '{entry_id}' must be declaration-only."
        )

    return CloudProviderPilotBinding(
        pilot_id=entry_id,
        agent_id=agent_id,
        channel=channel,
        provider_id=_require_string(entry, "provider_id", entry_id=entry_id),
        authorization_mode=authorization_mode,
        governance_state=governance_state,
        max_queries=_require_int(
            entry,
            "max_queries",
            entry_id=entry_id,
            maximum=MAX_PILOT_QUERIES,
        ),
        max_results=_require_int(
            entry,
            "max_results",
            entry_id=entry_id,
            maximum=MAX_PILOT_RESULTS,
        ),
        engine_policy_ref=engine_policy_ref,
        execution_policy=execution_policy,
        raw_data=dict(entry),
    )


def _load_cloud_provider_pilots_strict(
    agent_name: str,
    *,
    root: str | Path | None = None,
) -> tuple[CloudProviderPilotBinding, ...]:
    normalized_agent = str(agent_name or "").strip()
    if not normalized_agent:
        raise CloudProviderPilotRegistryError("Cloud provider pilot agent is required.")

    data = json.loads(
        cloud_provider_pilot_registry_path(normalized_agent, root=root).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(data, dict) or data.get("version") != 1:
        raise CloudProviderPilotRegistryError(
            "Cloud provider pilot registry version must be 1."
        )

    pilots = data.get("pilots")
    if not isinstance(pilots, list):
        raise CloudProviderPilotRegistryError(
            "Cloud provider pilot registry 'pilots' must be a list."
        )

    loaded = tuple(
        _pilot_from_entry(entry, agent_name=normalized_agent)
        for entry in pilots
    )
    pilot_ids = [pilot.pilot_id for pilot in loaded]
    if len(pilot_ids) != len(set(pilot_ids)):
        raise CloudProviderPilotRegistryError(
            "Cloud provider pilot registry contains duplicate pilot IDs."
        )
    return loaded


@lru_cache(maxsize=None)
def load_cloud_provider_pilots(
    agent_name: str,
    *,
    root: str | Path | None = None,
) -> tuple[CloudProviderPilotBinding, ...]:
    try:
        return _load_cloud_provider_pilots_strict(agent_name, root=root)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        CloudProviderPilotRegistryError,
    ):
        return ()


def get_cloud_provider_pilot(
    *,
    agent_id: str | None,
    provider_id: str | None,
    channel: str | None,
    root: str | Path | None = None,
) -> CloudProviderPilotBinding | None:
    normalized_agent = str(agent_id or "").strip()
    normalized_provider = str(provider_id or "").strip()
    normalized_channel = str(channel or "").strip().lower()
    if not normalized_agent or not normalized_provider or not normalized_channel:
        return None

    for pilot in load_cloud_provider_pilots(normalized_agent, root=root):
        if (
            pilot.provider_id == normalized_provider
            and pilot.channel == normalized_channel
        ):
            return pilot
    return None


__all__ = [
    "CLOUD_PROVIDER_PILOT_REGISTRY_PATH_PATTERN",
    "CloudProviderPilotBinding",
    "CloudProviderPilotRegistryError",
    "FORBIDDEN_PILOT_FIELDS",
    "MAX_PILOT_QUERIES",
    "MAX_PILOT_RESULTS",
    "REQUIRED_PILOT_FIELDS",
    "SUPPORTED_PILOT_CHANNELS",
    "SUPPORTED_PILOT_GOVERNANCE_STATES",
    "cloud_provider_pilot_registry_path",
    "get_cloud_provider_pilot",
    "load_cloud_provider_pilots",
]
