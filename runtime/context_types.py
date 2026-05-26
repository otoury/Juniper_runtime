from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from runtime.registries.resource_binding_registry import (
    get_context_source_contract,
)


ALLOWED_RENDERING_POLICIES = {
    "inline_notice",
    "bounded_context_block",
    "cite_only",
    "hidden_from_prompt",
}


@dataclass(frozen=True)
class ContextTypeValidationError:
    error_code: str
    message: str
    field: str


@dataclass(frozen=True)
class ResolvedContextProvenance:
    source_contract_id: str
    retrieval_executed: bool
    attribution: str
    generated_at: str | None = None


@dataclass(frozen=True)
class ResolvedContextItem:
    id: str
    source_contract_id: str
    content: str
    content_type: str
    provenance: ResolvedContextProvenance
    estimated_tokens: int
    trust_level: str
    rendering_policy: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _non_empty_string_error(
    item: ResolvedContextItem,
    field_name: str,
) -> ContextTypeValidationError | None:
    value = getattr(item, field_name)

    if isinstance(value, str) and value.strip():
        return None

    return ContextTypeValidationError(
        error_code="invalid_resolved_context_item",
        message=f"{field_name} must be a non-empty string.",
        field=field_name,
    )


def validate_resolved_context_item(
    item: ResolvedContextItem,
) -> list[ContextTypeValidationError]:
    errors: list[ContextTypeValidationError] = []

    for field_name in (
        "id",
        "source_contract_id",
        "content",
        "content_type",
        "trust_level",
        "rendering_policy",
    ):
        error = _non_empty_string_error(
            item,
            field_name,
        )

        if error is not None:
            errors.append(error)

    errors.extend(
        validate_resolved_context_provenance(item.provenance)
    )
    errors.extend(
        validate_context_item_source_contract(item)
    )

    rendering_policy_error = validate_rendering_policy(
        item.rendering_policy
    )

    if rendering_policy_error is not None:
        errors.append(rendering_policy_error)

    if (
        not isinstance(item.estimated_tokens, int)
        or isinstance(item.estimated_tokens, bool)
        or item.estimated_tokens < 0
    ):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_resolved_context_item",
                message="estimated_tokens must be a non-negative integer.",
                field="estimated_tokens",
            )
        )

    if not isinstance(item.metadata, dict):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_resolved_context_item",
                message="metadata must be an object.",
                field="metadata",
            )
        )

    return errors


def validate_context_item_source_contract(
    item: ResolvedContextItem,
    *,
    require_declared_source: bool = False,
    root: str | Path | None = None,
) -> list[ContextTypeValidationError]:
    errors: list[ContextTypeValidationError] = []
    provenance = item.provenance

    if not isinstance(provenance, ResolvedContextProvenance):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_context_item_source_contract",
                message=(
                    "Resolved context item provenance must be typed "
                    "before source contract validation."
                ),
                field="provenance",
            )
        )
        return errors

    if item.source_contract_id != provenance.source_contract_id:
        errors.append(
            ContextTypeValidationError(
                error_code="context_source_contract_mismatch",
                message=(
                    "Resolved context item source_contract_id must match "
                    "provenance.source_contract_id."
                ),
                field="source_contract_id",
            )
        )

    if require_declared_source and not get_context_source_contract(
        item.source_contract_id,
        root=root,
    ):
        errors.append(
            ContextTypeValidationError(
                error_code="context_source_contract_not_declared",
                message=(
                    "Resolved context item source_contract_id must resolve "
                    "to a declared context source contract."
                ),
                field="source_contract_id",
            )
        )

    return errors


def validate_resolved_context_provenance(
    provenance: ResolvedContextProvenance,
) -> list[ContextTypeValidationError]:
    errors: list[ContextTypeValidationError] = []

    if not isinstance(provenance, ResolvedContextProvenance):
        return [
            ContextTypeValidationError(
                error_code="invalid_resolved_context_provenance",
                message="provenance must be a ResolvedContextProvenance.",
                field="provenance",
            )
        ]

    if (
        not isinstance(provenance.source_contract_id, str)
        or not provenance.source_contract_id.strip()
    ):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_resolved_context_provenance",
                message="source_contract_id must be a non-empty string.",
                field="provenance.source_contract_id",
            )
        )

    if not isinstance(provenance.retrieval_executed, bool):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_resolved_context_provenance",
                message="retrieval_executed must be a boolean.",
                field="provenance.retrieval_executed",
            )
        )

    if (
        not isinstance(provenance.attribution, str)
        or not provenance.attribution.strip()
    ):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_resolved_context_provenance",
                message="attribution must be a non-empty string.",
                field="provenance.attribution",
            )
        )

    if (
        provenance.generated_at is not None
        and not isinstance(provenance.generated_at, str)
    ):
        errors.append(
            ContextTypeValidationError(
                error_code="invalid_resolved_context_provenance",
                message="generated_at must be a string when provided.",
                field="provenance.generated_at",
            )
        )

    return errors


def validate_rendering_policy(
    policy: str,
) -> ContextTypeValidationError | None:
    if not isinstance(policy, str) or not policy.strip():
        return ContextTypeValidationError(
            error_code="invalid_rendering_policy",
            message="rendering_policy must be a non-empty string.",
            field="rendering_policy",
        )

    if policy.strip() not in ALLOWED_RENDERING_POLICIES:
        return ContextTypeValidationError(
            error_code="invalid_rendering_policy",
            message=(
                "rendering_policy must be one of: "
                f"{sorted(ALLOWED_RENDERING_POLICIES)}"
            ),
            field="rendering_policy",
        )

    return None


def resolved_context_item_dict(
    item: ResolvedContextItem,
) -> dict[str, Any]:
    return asdict(item)


__all__ = [
    "ALLOWED_RENDERING_POLICIES",
    "ContextTypeValidationError",
    "ResolvedContextItem",
    "ResolvedContextProvenance",
    "resolved_context_item_dict",
    "validate_context_item_source_contract",
    "validate_rendering_policy",
    "validate_resolved_context_provenance",
    "validate_resolved_context_item",
]
