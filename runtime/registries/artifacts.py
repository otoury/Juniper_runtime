from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


ROOT_REGISTRY_PATH = Path("config/artifacts.json")
SHARED_ARTIFACTS_DIR = Path("config/artifacts/shared")
AGENTS_SHARED_ARTIFACTS_DIR = Path("agents/shared/artifacts")
AGENTS_SHARED_ARTIFACTS_PATH = (
    AGENTS_SHARED_ARTIFACTS_DIR / "artifacts.json"
)
AGENTS_SHARED_ARTIFACT_POLICIES_PATH = (
    AGENTS_SHARED_ARTIFACTS_DIR / "artifact_policies.json"
)
RETIRED_COMPAT_ARTIFACT_PATHS = (
    SHARED_ARTIFACTS_DIR,
    ROOT_REGISTRY_PATH,
)
CANONICAL_SHARED_ARTIFACT_PATHS = (
    AGENTS_SHARED_ARTIFACTS_PATH,
    AGENTS_SHARED_ARTIFACT_POLICIES_PATH,
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)

    for key, value in override.items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = _deep_merge(
                merged[key],
                value,
            )
        else:
            merged[key] = value

    return merged


def _load_directory_registry(folder: Path) -> dict:
    registry = {}

    if not folder.exists():
        return registry

    for path in sorted(folder.glob("*.json")):
        data = _read_json(path)

        if not data:
            continue

        if "name" in data:
            registry[data["name"]] = data
        else:
            registry = _deep_merge(
                registry,
                data,
            )

    return registry


def _load_retired_compat_artifact_path(path: Path) -> dict:
    if path.is_dir():
        return _load_directory_registry(path)

    return _read_json(path)


def _load_canonical_shared_artifacts() -> dict:
    registry = {}

    for path in CANONICAL_SHARED_ARTIFACT_PATHS:
        registry = _deep_merge(
            registry,
            _read_json(path),
        )

    return registry


@lru_cache(maxsize=None)
def load_artifact_registry(
    agent_root: str | Path | None = None,
) -> dict:
    registry = {}

    for path in RETIRED_COMPAT_ARTIFACT_PATHS:
        registry = _deep_merge(
            registry,
            _load_retired_compat_artifact_path(path),
        )

    registry = _deep_merge(registry, _load_canonical_shared_artifacts())

    if agent_root:
        agent_dir = Path(agent_root) / "artifacts"

        registry = _deep_merge(
            registry,
            _load_directory_registry(agent_dir),
        )

    return registry


def get_artifact_config(
    artifact_type: str | None,
    agent_root: str | Path | None = None,
) -> dict:
    if not artifact_type:
        return {}

    return load_artifact_registry(
        agent_root=agent_root,
    ).get(artifact_type, {})


def list_artifact_types(
    agent_root: str | Path | None = None,
) -> list[str]:
    return sorted(
        load_artifact_registry(
            agent_root=agent_root,
        ).keys()
    )


def should_persist_artifact(
    artifact_type: str | None,
    agent_root: str | Path | None = None,
) -> bool:
    return bool(
        get_artifact_config(
            artifact_type,
            agent_root=agent_root,
        ).get("persist_as_artifact", False)
    )


def get_artifact_extract_fields(
    artifact_type: str | None,
    agent_root: str | Path | None = None,
) -> list[str]:
    config = get_artifact_config(
        artifact_type,
        agent_root=agent_root,
    )

    fields = config.get("extract_fields")

    if fields:
        return list(fields)

    return []

def get_artifact_engine_policy(
    artifact_type: str | None,
    agent_root: str | Path | None = None,
) -> tuple[str | None, list[str]]:
    config = get_artifact_config(
        artifact_type,
        agent_root=agent_root,
    )

    return (
        config.get("preferred_engine"),
        list(config.get("fallback_engines", [])),
    )


def get_artifact_constraints(
    artifact_type: str | None,
    agent_root: str | Path | None = None,
) -> dict:
    return dict(
        get_artifact_config(
            artifact_type,
            agent_root=agent_root,
        ).get("formatting_constraints", {})
    )


def artifact_allows_semantic_grounding(
    artifact_type: str | None,
    *,
    authority: str,
    agent_root: str | Path | None = None,
) -> bool:
    if authority not in {"planner", "runtime"}:
        raise ValueError("semantic grounding authority must be planner or runtime")

    constraints = get_artifact_constraints(
        artifact_type,
        agent_root=agent_root,
    )
    field = f"{authority}_semantic_grounding_allowed"
    return constraints.get(field) is not False
