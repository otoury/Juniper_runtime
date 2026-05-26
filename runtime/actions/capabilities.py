from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


CONFIG_PATH = Path("agents/shared/capabilities/actions.json")
COMPAT_CONFIG_PATH = Path("config/capabilities/actions.json")
LEGACY_CONFIG_PATH = Path("config/semantic/actions.json")
RETIRED_COMPAT_CONFIG_PATHS = (
    LEGACY_CONFIG_PATH,
    COMPAT_CONFIG_PATH,
)
AGENTS_SHARED_CAPABILITIES_DIR = Path("agents/shared/capabilities")


@dataclass(frozen=True)
class Capability:
    name: str
    requires_approval: bool
    allowed_agents: list[str]
    description: str


class CapabilityConfigError(RuntimeError):
    pass


def _read_json_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CapabilityConfigError(
            f"Invalid action capability config JSON in {path}: {exc}"
        ) from exc


def _merge_config(base: dict, override: dict) -> dict:
    merged = {
        "capabilities": dict(base.get("capabilities", {})),
        "aliases": dict(base.get("aliases", {})),
    }

    merged["capabilities"].update(
        override.get("capabilities", {})
    )
    merged["aliases"].update(
        override.get("aliases", {})
    )

    return merged


def _load_directory_configs(folder: Path) -> dict:
    data = {}

    if not folder.exists():
        return data

    for path in sorted(folder.glob("*.json")):
        data = _merge_config(
            data,
            _read_json_config(path),
        )

    return data


def _load_json_config() -> dict:
    data = {}

    for path in RETIRED_COMPAT_CONFIG_PATHS:
        if path.exists():
            data = _merge_config(
                data,
                _read_json_config(path),
            )

    data = _merge_config(
        data,
        _load_directory_configs(AGENTS_SHARED_CAPABILITIES_DIR),
    )

    if not data.get("capabilities"):
        raise CapabilityConfigError(
            f"Missing action capability config: {CONFIG_PATH}"
        )

    return data


def _load_capabilities(data: dict) -> dict[str, Capability]:
    raw_capabilities = data.get("capabilities")

    if not isinstance(raw_capabilities, dict):
        raise CapabilityConfigError(
            "Action capability config must contain a capabilities object."
        )

    capabilities = {}

    for name, config in raw_capabilities.items():
        if not isinstance(config, dict):
            raise CapabilityConfigError(
                f"Capability '{name}' config must be an object."
            )

        allowed_agents = config.get("allowed_agents")

        if not isinstance(allowed_agents, list):
            raise CapabilityConfigError(
                f"Capability '{name}' allowed_agents must be a list."
            )

        capabilities[name] = Capability(
            name=name,
            requires_approval=bool(config.get("requires_approval", True)),
            allowed_agents=[str(agent) for agent in allowed_agents],
            description=str(config.get("description", "")),
        )

    return capabilities


def _load_aliases(data: dict) -> dict[str, str]:
    raw_aliases = data.get("aliases", {})

    if not isinstance(raw_aliases, dict):
        raise CapabilityConfigError(
            "Action capability aliases must be an object."
        )

    return {
        str(alias): str(target)
        for alias, target in raw_aliases.items()
    }


@lru_cache(maxsize=None)
def load_action_capability_config() -> tuple[
    dict[str, Capability],
    dict[str, str],
]:
    data = _load_json_config()
    capabilities = _load_capabilities(data)
    aliases = _load_aliases(data)

    for alias, target in aliases.items():
        if target not in capabilities:
            raise CapabilityConfigError(
                f"Capability alias '{alias}' targets unknown "
                f"capability '{target}'."
            )

    return capabilities, aliases


CAPABILITIES, CAPABILITY_ALIASES = load_action_capability_config()


def normalize_capability_name(name: str) -> str:
    return CAPABILITY_ALIASES.get(name, name)


def get_capability(name: str):
    return CAPABILITIES.get(normalize_capability_name(name))


def validate_action_capability(
    *,
    agent_name: str,
    action_type: str,
):
    normalized = normalize_capability_name(action_type)
    capability = CAPABILITIES.get(normalized)

    if not capability:
        raise ValueError(f"Unknown capability: {action_type}")

    if agent_name not in capability.allowed_agents:
        raise ValueError(
            f"Agent '{agent_name}' cannot emit capability '{normalized}'"
        )

    return capability, normalized


__all__ = [
    "Capability",
    "CapabilityConfigError",
    "CAPABILITIES",
    "CAPABILITY_ALIASES",
    "CONFIG_PATH",
    "COMPAT_CONFIG_PATH",
    "LEGACY_CONFIG_PATH",
    "RETIRED_COMPAT_CONFIG_PATHS",
    "load_action_capability_config",
    "normalize_capability_name",
    "get_capability",
    "validate_action_capability",
]
