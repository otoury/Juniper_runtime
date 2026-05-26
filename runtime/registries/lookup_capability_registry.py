from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.bindings import BindingResolutionError, get_binding_manifest
from runtime.lookup.capability_compatibility import (
    LookupCapabilityCompatibility,
    normalize_lookup_capability_compatibility,
)
from runtime.lookup.governance import (
    LookupGovernancePolicy,
    normalize_lookup_governance_policy,
)
from runtime.lookup.execution_policy import (
    LookupExecutionPolicy,
    normalize_lookup_execution_policy,
)
from runtime.lookup.policy_validation import (
    LookupPolicyValidationError,
    validate_lookup_capability_policies,
)
from runtime.retrieval.terminology import bounded_lookup_retrieval_metadata


ROOT = Path(__file__).resolve().parents[2]

LOOKUP_POLICY_SECTIONS = (
    "lookup_request_policy",
    "lookup_context_materialization_policy",
    "lookup_context_render_policy",
    "lookup_context_injection_policy",
)


@dataclass(frozen=True)
class LookupCapabilityRegistration:
    agent: str
    binding_id: str
    shared_capability: str
    capability_type: str
    contract_version: int
    min_runtime_version: int
    max_runtime_version: int
    required_features: tuple[str, ...]
    supported_lookup_types: tuple[str, ...]
    source_scopes: tuple[str, ...]
    render_modes: tuple[str, ...]
    injection_enabled: bool
    governance_state: str
    timeout_ms: int
    cancellation_behavior: str
    max_concurrent_lookups: int
    adapter_owners: tuple[str, ...]
    manifest_path: Path

    def to_metadata(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "binding_id": self.binding_id,
            "shared_capability": self.shared_capability,
            "capability_type": self.capability_type,
            **bounded_lookup_retrieval_metadata(
                retrieval_types=self.supported_lookup_types,
            ),
            "contract_version": self.contract_version,
            "min_runtime_version": self.min_runtime_version,
            "max_runtime_version": self.max_runtime_version,
            "required_features": list(self.required_features),
            "supported_lookup_types": list(self.supported_lookup_types),
            "source_scopes": list(self.source_scopes),
            "render_modes": list(self.render_modes),
            "injection_enabled": self.injection_enabled,
            "governance_state": self.governance_state,
            "timeout_ms": self.timeout_ms,
            "cancellation_behavior": self.cancellation_behavior,
            "max_concurrent_lookups": self.max_concurrent_lookups,
            "adapter_owners": list(self.adapter_owners),
        }


@dataclass(frozen=True)
class LookupCapabilityRegistrationError:
    agent: str
    binding_id: str
    field: str
    message: str
    manifest_path: Path | None = None


@dataclass(frozen=True)
class ResolvedLookupCapability:
    registration: LookupCapabilityRegistration
    binding_policy: dict[str, Any]
    compatibility: LookupCapabilityCompatibility
    governance: LookupGovernancePolicy
    execution_policy: LookupExecutionPolicy

    def policy_section(self, name: str) -> dict[str, Any] | None:
        value = self.binding_policy.get(name)
        return dict(value) if isinstance(value, dict) else None


def discover_lookup_capabilities(
    *,
    root: Path | str = ROOT,
    agents: tuple[str, ...] | None = None,
) -> tuple[LookupCapabilityRegistration, ...]:
    registrations, _errors = audit_lookup_capability_registrations(
        root=root,
        agents=agents,
    )
    return registrations


def resolve_lookup_capability(
    *,
    agent: str,
    shared_capability: str | None,
    root: Path | str = ROOT,
) -> ResolvedLookupCapability | LookupCapabilityRegistrationError:
    capability = shared_capability.strip() if isinstance(
        shared_capability,
        str,
    ) else ""
    if not capability:
        return _error(
            agent=agent,
            binding_id="",
            field="shared_capability",
            message="shared_capability must be declared.",
        )

    root_path = Path(root)
    manifest_path = (
        root_path
        / "agents"
        / agent
        / "bindings"
        / "capabilities.json"
    )
    manifest = _read_binding_manifest(
        agent_name=agent,
        root=root_path,
        manifest_path=manifest_path,
    )
    if isinstance(manifest, LookupCapabilityRegistrationError):
        return manifest

    bindings = manifest.get("bindings")
    if not isinstance(bindings, dict):
        return _error(
            agent=agent,
            binding_id="",
            field="bindings",
            message="bindings must be an object.",
            manifest_path=manifest_path,
        )

    matches = [
        (str(binding_id), binding)
        for binding_id, binding in bindings.items()
        if isinstance(binding, dict)
        and str(binding.get("shared_capability", "")).strip() == capability
        and _has_lookup_policy(binding)
    ]
    if not matches:
        return _error(
            agent=agent,
            binding_id="",
            field="lookup_capability",
            message="lookup capability registration not found.",
            manifest_path=manifest_path,
        )

    if len(matches) > 1:
        return _error(
            agent=agent,
            binding_id="",
            field="lookup_capability",
            message="duplicate lookup capability registrations.",
            manifest_path=manifest_path,
        )

    binding_id, binding = matches[0]
    compatibility = normalize_lookup_capability_compatibility(
        binding.get("lookup_capability_compatibility")
    )
    if compatibility is None:
        return _error(
            agent=agent,
            binding_id=binding_id,
            field="lookup_capability_compatibility",
            message="lookup capability compatibility is incompatible.",
            manifest_path=manifest_path,
        )

    governance = normalize_lookup_governance_policy(
        binding.get("lookup_capability_governance")
    )
    if governance is None:
        return _error(
            agent=agent,
            binding_id=binding_id,
            field="lookup_capability_governance",
            message="lookup capability governance is malformed.",
            manifest_path=manifest_path,
        )

    execution_policy = normalize_lookup_execution_policy(
        binding.get("lookup_execution_policy")
    )
    if execution_policy is None:
        return _error(
            agent=agent,
            binding_id=binding_id,
            field="lookup_execution_policy",
            message="lookup execution policy is malformed.",
            manifest_path=manifest_path,
        )

    validation_errors = validate_lookup_capability_policies(binding)
    if validation_errors:
        first_error = validation_errors[0]
        return _error(
            agent=agent,
            binding_id=binding_id,
            field=first_error.field,
            message=first_error.message,
            manifest_path=manifest_path,
        )

    registration = _registration_from_binding(
        agent=agent,
        binding_id=binding_id,
        binding=binding,
        manifest_path=manifest_path,
    )
    if registration is None:
        return _error(
            agent=agent,
            binding_id=binding_id,
            field="registration",
            message="lookup registration could not be normalized.",
            manifest_path=manifest_path,
        )

    return ResolvedLookupCapability(
        registration=registration,
        binding_policy=dict(binding),
        compatibility=compatibility,
        governance=governance,
        execution_policy=execution_policy,
    )


def audit_lookup_capability_registrations(
    *,
    root: Path | str = ROOT,
    agents: tuple[str, ...] | None = None,
) -> tuple[
    tuple[LookupCapabilityRegistration, ...],
    tuple[LookupCapabilityRegistrationError, ...],
]:
    root_path = Path(root)
    registrations: list[LookupCapabilityRegistration] = []
    errors: list[LookupCapabilityRegistrationError] = []

    for agent_name, manifest_path in _manifest_paths(root=root_path, agents=agents):
        manifest = _read_binding_manifest(
            agent_name=agent_name,
            root=root_path,
            manifest_path=manifest_path,
        )
        if isinstance(manifest, LookupCapabilityRegistrationError):
            errors.append(manifest)
            continue

        bindings = manifest.get("bindings")
        if not isinstance(bindings, dict):
            errors.append(
                _error(
                    agent=agent_name,
                    binding_id="",
                    field="bindings",
                    message="bindings must be an object.",
                    manifest_path=manifest_path,
                )
            )
            continue

        for binding_id, binding in sorted(bindings.items()):
            if not isinstance(binding, dict):
                continue

            if not _has_lookup_policy(binding):
                continue

            compatibility = normalize_lookup_capability_compatibility(
                binding.get("lookup_capability_compatibility")
            )
            if compatibility is None:
                errors.append(
                    _error(
                        agent=agent_name,
                        binding_id=str(binding_id),
                        field="lookup_capability_compatibility",
                        message=(
                            "lookup capability compatibility is incompatible."
                        ),
                        manifest_path=manifest_path,
                    )
                )
                continue

            governance = normalize_lookup_governance_policy(
                binding.get("lookup_capability_governance")
            )
            if governance is None:
                errors.append(
                    _error(
                        agent=agent_name,
                        binding_id=str(binding_id),
                        field="lookup_capability_governance",
                        message="lookup capability governance is malformed.",
                        manifest_path=manifest_path,
                    )
                )
                continue

            execution_policy = normalize_lookup_execution_policy(
                binding.get("lookup_execution_policy")
            )
            if execution_policy is None:
                errors.append(
                    _error(
                        agent=agent_name,
                        binding_id=str(binding_id),
                        field="lookup_execution_policy",
                        message="lookup execution policy is malformed.",
                        manifest_path=manifest_path,
                    )
                )
                continue

            validation_errors = validate_lookup_capability_policies(binding)
            if validation_errors:
                errors.extend(
                    _registration_errors(
                        agent=agent_name,
                        binding_id=str(binding_id),
                        manifest_path=manifest_path,
                        validation_errors=validation_errors,
                    )
                )
                continue

            registration = _registration_from_binding(
                agent=agent_name,
                binding_id=str(binding_id),
                binding=binding,
                manifest_path=manifest_path,
            )
            if registration is None:
                errors.append(
                    _error(
                        agent=agent_name,
                        binding_id=str(binding_id),
                        field="registration",
                        message="lookup registration could not be normalized.",
                        manifest_path=manifest_path,
                    )
                )
                continue

            registrations.append(registration)

    return tuple(registrations), tuple(errors)


def validate_lookup_capability_registration(
    binding: dict[str, Any] | None,
) -> tuple[LookupCapabilityRegistrationError, ...]:
    if not isinstance(binding, dict):
        return (
            _error(
                agent="",
                binding_id="",
                field="binding",
                message="binding must be an object.",
            ),
        )

    return tuple(
        _error(
            agent="",
            binding_id="",
            field=error.field,
            message=error.message,
        )
        for error in validate_lookup_capability_policies(binding)
    )


def _manifest_paths(
    *,
    root: Path,
    agents: tuple[str, ...] | None,
) -> list[tuple[str, Path]]:
    agents_dir = root / "agents"
    if agents is not None:
        names = list(agents)
    elif agents_dir.exists():
        names = [
            path.name
            for path in agents_dir.iterdir()
            if path.is_dir() and path.name != "shared"
        ]
    else:
        names = []

    return [
        (
            name,
            agents_dir / name / "bindings" / "capabilities.json",
        )
        for name in sorted(name for name in names if isinstance(name, str))
    ]


def _read_binding_manifest(
    *,
    agent_name: str,
    root: Path,
    manifest_path: Path,
) -> dict[str, Any] | LookupCapabilityRegistrationError:
    manifest = get_binding_manifest(agent_name, root=root)
    if isinstance(manifest, BindingResolutionError):
        return _error(
            agent=agent_name,
            binding_id="",
            field="manifest",
            message=manifest.message,
            manifest_path=manifest.raw_manifest_path or manifest_path,
        )

    return manifest


def _has_lookup_policy(binding: dict[str, Any]) -> bool:
    return any(section in binding for section in LOOKUP_POLICY_SECTIONS)


def _registration_from_binding(
    *,
    agent: str,
    binding_id: str,
    binding: dict[str, Any],
    manifest_path: Path,
) -> LookupCapabilityRegistration | None:
    request_policy = binding.get("lookup_request_policy")
    render_policy = binding.get("lookup_context_render_policy")
    injection_policy = binding.get("lookup_context_injection_policy")
    if (
        not isinstance(request_policy, dict)
        or not isinstance(render_policy, dict)
        or not isinstance(injection_policy, dict)
    ):
        return None

    shared_capability = binding.get("shared_capability")
    compatibility = normalize_lookup_capability_compatibility(
        binding.get("lookup_capability_compatibility")
    )
    lookup_type = request_policy.get("lookup_type")
    source_scopes = request_policy.get("allowed_source_scopes")
    render_modes = render_policy.get("render_modes")
    resources = binding.get("resources", [])
    governance = normalize_lookup_governance_policy(
        binding.get("lookup_capability_governance")
    )
    execution_policy = normalize_lookup_execution_policy(
        binding.get("lookup_execution_policy")
    )

    if (
        not _non_empty_string(shared_capability)
        or compatibility is None
        or not _non_empty_string(lookup_type)
        or not _string_list(source_scopes)
        or not _string_list(render_modes)
        or not isinstance(resources, list)
        or governance is None
        or execution_policy is None
        or any(not _non_empty_string(resource) for resource in resources)
    ):
        return None

    return LookupCapabilityRegistration(
        agent=agent,
        binding_id=binding_id,
        shared_capability=shared_capability.strip(),
        capability_type="lookup_context_pipeline",
        contract_version=compatibility.contract_version,
        min_runtime_version=compatibility.min_runtime_version,
        max_runtime_version=compatibility.max_runtime_version,
        required_features=compatibility.required_features,
        supported_lookup_types=(lookup_type.strip(),),
        source_scopes=tuple(scope.strip() for scope in source_scopes),
        render_modes=tuple(mode.strip() for mode in render_modes),
        injection_enabled=injection_policy.get("allowed") is True,
        governance_state=governance.state,
        timeout_ms=execution_policy.timeout_ms,
        cancellation_behavior=execution_policy.cancellation_behavior,
        max_concurrent_lookups=execution_policy.max_concurrent_lookups,
        adapter_owners=tuple(resource.strip() for resource in resources),
        manifest_path=manifest_path,
    )


def _registration_errors(
    *,
    agent: str,
    binding_id: str,
    manifest_path: Path,
    validation_errors: list[LookupPolicyValidationError],
) -> list[LookupCapabilityRegistrationError]:
    return [
        _error(
            agent=agent,
            binding_id=binding_id,
            field=validation_error.field,
            message=validation_error.message,
            manifest_path=manifest_path,
        )
        for validation_error in validation_errors
    ]


def _error(
    *,
    agent: str,
    binding_id: str,
    field: str,
    message: str,
    manifest_path: Path | None = None,
) -> LookupCapabilityRegistrationError:
    return LookupCapabilityRegistrationError(
        agent=agent,
        binding_id=binding_id,
        field=field,
        message=message,
        manifest_path=manifest_path,
    )


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_non_empty_string(item) for item in value)
    )


__all__ = [
    "LookupCapabilityRegistration",
    "LookupCapabilityRegistrationError",
    "ResolvedLookupCapability",
    "audit_lookup_capability_registrations",
    "discover_lookup_capabilities",
    "resolve_lookup_capability",
    "validate_lookup_capability_registration",
]
