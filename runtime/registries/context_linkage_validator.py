from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from runtime.registries.context_injection_binding_registry import (
    ContextInjectionContract,
    ContextInjectionRegistryError,
    load_context_injection_registry,
)
from runtime.registries.resource_binding_registry import (
    ContextSourceContract,
    get_context_source_contract,
)


@dataclass(frozen=True)
class ContextLinkageValidationError:
    error_code: str
    message: str
    injection_id: str
    source_contract_id: str | None = None
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextInjectionSourceLinkage:
    injection_id: str
    source_contract_id: str
    valid: bool
    injection_shared_capabilities: list[str]
    source_allowed_capabilities: list[str]
    injection_requires_provenance: bool
    source_requires_provenance: bool | None
    injection_max_tokens: int
    source_max_injection_tokens: int | None
    errors: list[ContextLinkageValidationError]


def _missing_source_linkage(
    injection: ContextInjectionContract,
) -> ContextInjectionSourceLinkage:
    error = ContextLinkageValidationError(
        error_code="missing_source_contract",
        message="Context injection source_contract_id does not resolve.",
        injection_id=injection.id,
        source_contract_id=injection.source_contract_id,
    )

    return ContextInjectionSourceLinkage(
        injection_id=injection.id,
        source_contract_id=injection.source_contract_id,
        valid=False,
        injection_shared_capabilities=list(injection.shared_capability_scope),
        source_allowed_capabilities=[],
        injection_requires_provenance=injection.requires_provenance_validation,
        source_requires_provenance=None,
        injection_max_tokens=injection.max_tokens,
        source_max_injection_tokens=None,
        errors=[error],
    )


def _validate_linkage(
    injection: ContextInjectionContract,
    source: ContextSourceContract,
) -> ContextInjectionSourceLinkage:
    errors: list[ContextLinkageValidationError] = []
    injection_capabilities = set(injection.shared_capability_scope)
    source_capabilities = set(source.allowed_shared_capabilities)
    missing_capabilities = sorted(injection_capabilities - source_capabilities)

    if missing_capabilities:
        errors.append(
            ContextLinkageValidationError(
                error_code="capability_scope_mismatch",
                message=(
                    "Context injection capability scope is not covered "
                    "by the source contract."
                ),
                injection_id=injection.id,
                source_contract_id=source.id,
                details=missing_capabilities,
            )
        )

    if (
        source.requires_provenance_validation
        and not injection.requires_provenance_validation
    ):
        errors.append(
            ContextLinkageValidationError(
                error_code="provenance_requirement_mismatch",
                message=(
                    "Context source requires provenance validation, "
                    "but the injection contract does not."
                ),
                injection_id=injection.id,
                source_contract_id=source.id,
            )
        )

    if injection.max_tokens > source.max_injection_tokens:
        errors.append(
            ContextLinkageValidationError(
                error_code="source_token_budget_exceeded",
                message=(
                    "Context injection max_tokens exceeds the linked "
                    "source max_injection_tokens."
                ),
                injection_id=injection.id,
                source_contract_id=source.id,
                details=[
                    f"injection_max_tokens={injection.max_tokens}",
                    f"source_max_injection_tokens={source.max_injection_tokens}",
                ],
            )
        )

    return ContextInjectionSourceLinkage(
        injection_id=injection.id,
        source_contract_id=source.id,
        valid=not errors,
        injection_shared_capabilities=list(injection.shared_capability_scope),
        source_allowed_capabilities=list(source.allowed_shared_capabilities),
        injection_requires_provenance=(
            injection.requires_provenance_validation
        ),
        source_requires_provenance=source.requires_provenance_validation,
        injection_max_tokens=injection.max_tokens,
        source_max_injection_tokens=source.max_injection_tokens,
        errors=errors,
    )


def validate_context_injection_source_linkages(
    root: str | Path | None = None,
) -> list[ContextInjectionSourceLinkage]:
    try:
        injections = load_context_injection_registry(root)
    except ContextInjectionRegistryError as exc:
        return [
            ContextInjectionSourceLinkage(
                injection_id="<registry>",
                source_contract_id="<unknown>",
                valid=False,
                injection_shared_capabilities=[],
                source_allowed_capabilities=[],
                injection_requires_provenance=False,
                source_requires_provenance=None,
                injection_max_tokens=0,
                source_max_injection_tokens=None,
                errors=[
                    ContextLinkageValidationError(
                        error_code="injection_registry_invalid",
                        message=str(exc),
                        injection_id="<registry>",
                    )
                ],
            )
        ]

    linkages: list[ContextInjectionSourceLinkage] = []

    for injection in injections:
        source = get_context_source_contract(
            injection.source_contract_id,
            root=root,
        )

        if source is None:
            linkages.append(_missing_source_linkage(injection))
            continue

        linkages.append(
            _validate_linkage(
                injection,
                source,
            )
        )

    return linkages


def context_linkage_errors(
    root: str | Path | None = None,
) -> list[ContextLinkageValidationError]:
    errors: list[ContextLinkageValidationError] = []

    for linkage in validate_context_injection_source_linkages(root):
        errors.extend(linkage.errors)

    return errors


__all__ = [
    "ContextInjectionSourceLinkage",
    "ContextLinkageValidationError",
    "context_linkage_errors",
    "validate_context_injection_source_linkages",
]
