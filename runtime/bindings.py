from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.actions.capabilities import CAPABILITIES


ROOT = Path(__file__).resolve().parents[1]

SPLIT_BINDING_PATHS = (
    Path("bindings/capabilities.json"),
    Path("governance/lookup_capabilities.json"),
    Path("policies/lookup_execution.json"),
    Path("policies/context_rendering.json"),
    Path("policies/context_injection.json"),
    Path("policies/context_assembly.json"),
    Path("contracts/lookup_runtime_compatibility.json"),
)

STRICT_APPROVAL_POLICIES = {
    "always_require_approval",
    "requires_approval",
    "shared_capability_required",
}

WEAK_APPROVAL_POLICIES = {
    "approval_not_required",
    "auto_approve",
    "disabled",
    "false",
    "none",
    "no_approval",
    "not_required",
}


@dataclass(frozen=True)
class AgentBinding:
    agent_name: str
    binding_id: str
    shared_capability: str
    skills: list[str]
    resources: list[str]
    tone: str | None
    approval_policy: str | bool | None
    raw_manifest_path: Path
    raw_binding_data: dict[str, Any]


@dataclass(frozen=True)
class BindingResolutionError:
    agent_name: str
    shared_capability: str
    error_code: str
    message: str
    raw_manifest_path: Path | None = None
    details: list[str] = field(default_factory=list)


def _error(
    *,
    agent_name: str,
    shared_capability: str,
    error_code: str,
    message: str,
    raw_manifest_path: Path | None = None,
    details: list[str] | None = None,
) -> BindingResolutionError:
    return BindingResolutionError(
        agent_name=agent_name,
        shared_capability=shared_capability,
        error_code=error_code,
        message=message,
        raw_manifest_path=raw_manifest_path,
        details=list(details or []),
    )


def _agent_dir(
    agent_name: str,
    *,
    root: Path,
) -> Path:
    return root / "agents" / agent_name


def _manifest_path(
    agent_name: str,
    *,
    root: Path,
) -> Path:
    return _agent_dir(agent_name, root=root) / "bindings" / "capabilities.json"


def _legacy_manifest_path(
    agent_name: str,
    *,
    root: Path,
) -> Path:
    return _agent_dir(agent_name, root=root) / "capabilities" / "bindings.json"


def _read_json(path: Path) -> dict[str, Any] | BindingResolutionError:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return _error(
            agent_name=path.parts[-3] if len(path.parts) >= 3 else "",
            shared_capability="",
            error_code="malformed_manifest",
            message=f"Invalid agent binding JSON: {exc}",
            raw_manifest_path=path,
        )
    except OSError as exc:
        return _error(
            agent_name=path.parts[-3] if len(path.parts) >= 3 else "",
            shared_capability="",
            error_code="unreadable_manifest",
            message=f"Unable to read agent binding manifest: {exc}",
            raw_manifest_path=path,
        )

    if not isinstance(data, dict):
        return _error(
            agent_name=path.parts[-3] if len(path.parts) >= 3 else "",
            shared_capability="",
            error_code="malformed_manifest",
            message="Agent binding manifest must be an object.",
            raw_manifest_path=path,
        )

    return data


def get_binding_manifest(
    agent_name: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any] | BindingResolutionError:
    path = _manifest_path(agent_name, root=root)

    if not _agent_dir(agent_name, root=root).exists():
        return _error(
            agent_name=agent_name,
            shared_capability="",
            error_code="missing_agent",
            message=f"Agent does not exist: {agent_name}",
            raw_manifest_path=path,
        )

    split_manifest = _compose_split_binding_manifest(
        agent_name,
        root=root,
    )
    if not isinstance(split_manifest, BindingResolutionError):
        return split_manifest
    if split_manifest.error_code != "missing_manifest":
        return split_manifest

    legacy_path = _legacy_manifest_path(agent_name, root=root)
    if legacy_path.exists():
        path = legacy_path
    elif not path.exists():
        return _error(
            agent_name=agent_name,
            shared_capability="",
            error_code="missing_manifest",
            message=f"Agent binding manifest does not exist: {path}",
            raw_manifest_path=path,
        )

    data = _read_json(path)

    if isinstance(data, BindingResolutionError):
        return _error(
            agent_name=agent_name,
            shared_capability="",
            error_code=data.error_code,
            message=data.message,
            raw_manifest_path=path,
            details=data.details,
        )

    bindings = data.get("bindings", {})

    if not isinstance(bindings, dict):
        return _error(
            agent_name=agent_name,
            shared_capability="",
            error_code="malformed_manifest",
            message="Agent binding manifest must contain a bindings object.",
            raw_manifest_path=path,
        )

    return data


def _compose_split_binding_manifest(
    agent_name: str,
    *,
    root: Path,
) -> dict[str, Any] | BindingResolutionError:
    agent_dir = _agent_dir(agent_name, root=root)
    section_paths = [agent_dir / relative for relative in SPLIT_BINDING_PATHS]
    existing_paths = [path for path in section_paths if path.exists()]

    if not existing_paths:
        return _error(
            agent_name=agent_name,
            shared_capability="",
            error_code="missing_manifest",
            message="Split agent binding manifest does not exist.",
            raw_manifest_path=_manifest_path(agent_name, root=root),
        )

    if len(existing_paths) != len(section_paths):
        missing = [
            str(path.relative_to(root))
            for path in section_paths
            if not path.exists()
        ]
        return _error(
            agent_name=agent_name,
            shared_capability="",
            error_code="missing_manifest_section",
            message="Split agent binding manifest is incomplete.",
            raw_manifest_path=_manifest_path(agent_name, root=root),
            details=missing,
        )

    merged: dict[str, dict[str, Any]] = {}
    for path in section_paths:
        data = _read_json(path)
        if isinstance(data, BindingResolutionError):
            return _error(
                agent_name=agent_name,
                shared_capability="",
                error_code=data.error_code,
                message=data.message,
                raw_manifest_path=path,
                details=data.details,
            )

        bindings = data.get("bindings")
        if not isinstance(bindings, dict):
            return _error(
                agent_name=agent_name,
                shared_capability="",
                error_code="malformed_manifest",
                message="Split agent binding file must contain a bindings object.",
                raw_manifest_path=path,
            )

        for binding_id, section in bindings.items():
            if not isinstance(binding_id, str) or not binding_id.strip():
                return _error(
                    agent_name=agent_name,
                    shared_capability="",
                    error_code="malformed_binding",
                    message="Binding id must be a non-empty string.",
                    raw_manifest_path=path,
                )
            if not isinstance(section, dict):
                return _error(
                    agent_name=agent_name,
                    shared_capability="",
                    error_code="malformed_binding",
                    message="Split binding section must be an object.",
                    raw_manifest_path=path,
                )

            target = merged.setdefault(binding_id, {})
            overlap = sorted(set(target).intersection(section))
            if overlap:
                return _error(
                    agent_name=agent_name,
                    shared_capability="",
                    error_code="duplicate_binding_fields",
                    message="Split binding files define duplicate fields.",
                    raw_manifest_path=path,
                    details=[
                        f"{binding_id}.{field}"
                        for field in overlap
                    ],
                )
            target.update(section)

    return {"bindings": merged}


def _agent_skill_ids(agent_dir: Path) -> set[str]:
    skill_ids = {path.stem for path in (agent_dir / "skills").glob("*.md")}
    manifest_path = agent_dir / "skills" / "manifest.json"

    if not manifest_path.exists():
        return skill_ids

    try:
        with manifest_path.open(encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return skill_ids

    def collect(value):
        if isinstance(value, str):
            skill_ids.add(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(manifest)
    return skill_ids


def _agent_resource_exists(agent_dir: Path, resource_id: str) -> bool:
    resource_path = Path(resource_id)

    if resource_path.is_absolute() or ".." in resource_path.parts:
        return False

    candidates = [
        agent_dir / resource_path,
        agent_dir / "tools" / resource_path,
        agent_dir / "tools" / f"{resource_id}.py",
        agent_dir / "resources" / resource_path,
        agent_dir / "resources" / f"{resource_id}.json",
    ]

    return any(path.exists() for path in candidates)


def _list_field(
    binding: dict[str, Any],
    field_name: str,
) -> list[str] | None:
    value = binding.get(field_name, [])

    if not isinstance(value, list):
        return None

    return [str(item) for item in value]


def _approval_policy_error(
    *,
    agent_name: str,
    shared_capability: str,
    binding: dict[str, Any],
    manifest_path: Path,
) -> BindingResolutionError | None:
    capability = CAPABILITIES[shared_capability]
    policy = binding.get("approval_policy")

    if policy is None:
        return None

    if isinstance(policy, bool):
        if capability.requires_approval and policy is False:
            return _error(
                agent_name=agent_name,
                shared_capability=shared_capability,
                error_code="approval_policy_weakened",
                message=(
                    "Agent binding cannot weaken shared capability "
                    "approval requirements."
                ),
                raw_manifest_path=manifest_path,
                details=["approval_policy=false"],
            )
        return None

    policy_id = str(policy).strip()

    if not policy_id:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="invalid_approval_policy",
            message="Approval policy must not be empty.",
            raw_manifest_path=manifest_path,
        )

    normalized = policy_id.lower()

    if capability.requires_approval and normalized in WEAK_APPROVAL_POLICIES:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="approval_policy_weakened",
            message=(
                "Agent binding cannot weaken shared capability approval "
                "requirements."
            ),
            raw_manifest_path=manifest_path,
            details=[f"approval_policy={policy_id}"],
        )

    if normalized in WEAK_APPROVAL_POLICIES | STRICT_APPROVAL_POLICIES:
        return None

    return _error(
        agent_name=agent_name,
        shared_capability=shared_capability,
        error_code="invalid_approval_policy",
        message=f"Unknown approval policy: {policy_id}",
        raw_manifest_path=manifest_path,
    )


def _validate_binding(
    *,
    agent_name: str,
    binding_id: str,
    binding: Any,
    requested_capability: str,
    manifest_path: Path,
    root: Path,
) -> AgentBinding | BindingResolutionError:
    if not isinstance(binding, dict):
        return _error(
            agent_name=agent_name,
            shared_capability=requested_capability,
            error_code="malformed_binding",
            message=f"Binding must be an object: {binding_id}",
            raw_manifest_path=manifest_path,
        )

    shared_capability = str(binding.get("shared_capability", "")).strip()

    if shared_capability != requested_capability:
        return _error(
            agent_name=agent_name,
            shared_capability=requested_capability,
            error_code="capability_mismatch",
            message=(
                f"Binding '{binding_id}' maps to '{shared_capability}', "
                f"not '{requested_capability}'."
            ),
            raw_manifest_path=manifest_path,
        )

    if shared_capability not in CAPABILITIES:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="missing_shared_capability",
            message=f"Unknown shared capability: {shared_capability}",
            raw_manifest_path=manifest_path,
        )

    skills = _list_field(binding, "skills")
    resources = _list_field(binding, "resources")

    if skills is None:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="malformed_binding",
            message="Binding skills must be a list.",
            raw_manifest_path=manifest_path,
        )

    if resources is None:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="malformed_binding",
            message="Binding resources must be a list.",
            raw_manifest_path=manifest_path,
        )

    agent_dir = _agent_dir(agent_name, root=root)
    skill_ids = _agent_skill_ids(agent_dir)
    missing_references = []

    for skill in skills:
        if skill not in skill_ids:
            missing_references.append(f"skill:{skill}")

    for resource in resources:
        if not _agent_resource_exists(agent_dir, resource):
            missing_references.append(f"resource:{resource}")

    if missing_references:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="missing_local_reference",
            message="Agent binding references missing local skills/resources.",
            raw_manifest_path=manifest_path,
            details=missing_references,
        )

    approval_error = _approval_policy_error(
        agent_name=agent_name,
        shared_capability=shared_capability,
        binding=binding,
        manifest_path=manifest_path,
    )

    if approval_error:
        return approval_error

    return AgentBinding(
        agent_name=agent_name,
        binding_id=binding_id,
        shared_capability=shared_capability,
        skills=skills,
        resources=resources,
        tone=(
            str(binding["tone"])
            if binding.get("tone") is not None
            else None
        ),
        approval_policy=binding.get("approval_policy"),
        raw_manifest_path=manifest_path,
        raw_binding_data=dict(binding),
    )


def resolve_agent_binding(
    agent_name: str,
    shared_capability_id: str,
    *,
    root: Path = ROOT,
) -> AgentBinding | BindingResolutionError:
    shared_capability = str(shared_capability_id or "").strip()
    manifest_path = _manifest_path(agent_name, root=root)

    if shared_capability not in CAPABILITIES:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="missing_shared_capability",
            message=f"Unknown shared capability: {shared_capability}",
            raw_manifest_path=manifest_path,
        )

    manifest = get_binding_manifest(agent_name, root=root)

    if isinstance(manifest, BindingResolutionError):
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code=manifest.error_code,
            message=manifest.message,
            raw_manifest_path=manifest.raw_manifest_path,
            details=manifest.details,
        )

    bindings = manifest["bindings"]
    matches = [
        (binding_id, binding)
        for binding_id, binding in bindings.items()
        if isinstance(binding, dict)
        and str(binding.get("shared_capability", "")).strip() == shared_capability
    ]

    if not matches:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="missing_binding",
            message=(
                f"Agent '{agent_name}' has no binding for shared "
                f"capability '{shared_capability}'."
            ),
            raw_manifest_path=manifest_path,
        )

    if len(matches) > 1:
        return _error(
            agent_name=agent_name,
            shared_capability=shared_capability,
            error_code="duplicate_binding",
            message=(
                f"Agent '{agent_name}' has multiple bindings for shared "
                f"capability '{shared_capability}'."
            ),
            raw_manifest_path=manifest_path,
            details=[binding_id for binding_id, _binding in matches],
        )

    binding_id, binding = matches[0]
    return _validate_binding(
        agent_name=agent_name,
        binding_id=str(binding_id),
        binding=binding,
        requested_capability=shared_capability,
        manifest_path=manifest_path,
        root=root,
    )


def list_agent_bindings(
    agent_name: str,
    *,
    root: Path = ROOT,
) -> list[AgentBinding] | BindingResolutionError:
    manifest = get_binding_manifest(agent_name, root=root)

    if isinstance(manifest, BindingResolutionError):
        return manifest

    resolved = []

    for binding in manifest["bindings"].values():
        if not isinstance(binding, dict):
            return _error(
                agent_name=agent_name,
                shared_capability="",
                error_code="malformed_binding",
                message="Binding must be an object.",
                raw_manifest_path=_manifest_path(agent_name, root=root),
            )

        shared_capability = str(binding.get("shared_capability", "")).strip()
        result = resolve_agent_binding(
            agent_name,
            shared_capability,
            root=root,
        )

        if isinstance(result, BindingResolutionError):
            return result

        resolved.append(result)

    return sorted(
        resolved,
        key=lambda binding: binding.binding_id,
    )


__all__ = [
    "AgentBinding",
    "BindingResolutionError",
    "get_binding_manifest",
    "list_agent_bindings",
    "resolve_agent_binding",
]
