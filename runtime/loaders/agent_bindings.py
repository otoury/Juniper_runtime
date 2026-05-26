from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.bindings import BindingResolutionError, get_binding_manifest


ROOT = Path(__file__).resolve().parents[2]


class AgentBindingConfigError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise AgentBindingConfigError(
            f"Invalid agent binding JSON in {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise AgentBindingConfigError(
            f"Unable to read agent binding manifest {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise AgentBindingConfigError(
            f"Agent binding manifest must be an object: {path}"
        )

    return data


def agent_binding_manifest_paths(
    root: Path = ROOT,
) -> list[Path]:
    return sorted(
        path
        for path in root.glob("agents/*/bindings/capabilities.json")
        if path.parts[-3] != "shared"
    )


def load_agent_binding_manifest(
    path: Path,
) -> dict[str, Any]:
    data = _read_json(path)
    bindings = data.get("bindings", {})

    if not isinstance(bindings, dict):
        raise AgentBindingConfigError(
            f"Agent binding manifest must contain a bindings object: {path}"
        )

    return data


def load_agent_binding_manifests(
    root: Path = ROOT,
) -> dict[str, dict[str, Any]]:
    manifests = {}

    for path in agent_binding_manifest_paths(root):
        agent_name = path.parts[-3]
        relative_path = path.relative_to(root)
        manifest = get_binding_manifest(agent_name, root=root)
        if isinstance(manifest, BindingResolutionError):
            raise AgentBindingConfigError(manifest.message)
        manifests.setdefault(agent_name, {})
        manifests[agent_name][str(relative_path)] = manifest

    return manifests


__all__ = [
    "AgentBindingConfigError",
    "agent_binding_manifest_paths",
    "load_agent_binding_manifest",
    "load_agent_binding_manifests",
]
