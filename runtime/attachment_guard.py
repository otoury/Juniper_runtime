from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from runtime.governance.boundary_terms import SEMANTIC_AUTHORITY_FIELDS
from runtime.governance.validator_support import (
    matching_paths,
    safe_string,
    unique_values,
    validator_lineage,
)

ATTACHMENT_GUARD_VERSION = "stage165_attachment_guard_v1"

SEMANTIC_ATTACHMENT_TARGETS = frozenset(
    {
        "planner_prompt",
        "runtime_messages",
        "runtime_semantic_context",
        "semantic_planning_metadata",
        "active_artifact_context",
    }
)

LOOKUP_CONTEXT_TARGETS = frozenset({"lookup_context_block"})

FORBIDDEN_ATTACHMENT_FIELDS = frozenset(
    {
        "diagnostic_type",
        "governance",
        "governance_policy",
        "governance_state",
        "hidden_context_injection_performed",
        "planner_semantic_authority",
        "raw_database_path",
        "raw_lookup_results",
        "retrieval_diagnostics",
        "retrieval_policy",
        "runtime_diagnostics",
        "semantic_reinterpretation_performed",
        "trust_lineage",
        "visibility_type",
        "workflow_state_mutation_performed",
    }
)
SEMANTIC_MUTATION_FIELDS = SEMANTIC_AUTHORITY_FIELDS

RETRIEVAL_ARTIFACT_TYPES = frozenset(
    {
        "external_discovery_result_set",
        "external_search_result_set",
        "search_api_result_set",
    }
)

DISALLOWED_SEMANTIC_SOURCES = frozenset(
    {"diagnostic", "governance", "retrieval", "visibility"}
)


@dataclass(frozen=True)
class AttachmentValidation:
    allowed: bool
    attachment_path: str
    source_substrate: str | None
    target: str | None
    attachment_type: str | None
    blocked_fields: list[str]
    skipped_reasons: list[str]

    def to_record(self) -> dict[str, Any]:
        return {
            "guard_id": ATTACHMENT_GUARD_VERSION,
            "allowed": self.allowed,
            "attachment_path": self.attachment_path,
            "source_substrate": self.source_substrate,
            "target": self.target,
            "attachment_type": self.attachment_type,
            "explicit_attachment_required": True,
            "bounded_attachment_required": True,
            "provenance_required": True,
            "hidden_attachment_inheritance_allowed": False,
            "semantic_mutation_allowed": False,
            "blocked_fields": list(self.blocked_fields),
            "skipped_reasons": list(self.skipped_reasons),
            "validator_lineage": validator_lineage(
                owner="runtime.attachment_guard",
                validator="validate_attachment_path",
                contract_id=ATTACHMENT_GUARD_VERSION,
                source=self.attachment_path,
            ),
        }


class AttachmentValidationError(ValueError):
    def __init__(self, validation: AttachmentValidation):
        self.validation = validation
        suffix = ""
        if "retrieval_artifact_cannot_attach_as_active_context" in (
            validation.skipped_reasons
        ):
            suffix = "; retrieval artifact cannot provide semantic grounding"
        super().__init__(
            "Attachment path failed closed: "
            + ", ".join(validation.skipped_reasons)
            + suffix
        )


def validate_attachment_path(
    *,
    payload: Mapping[str, Any] | None,
    source_substrate: str,
    target: str,
    attachment_type: str,
    provenance: Mapping[str, Any] | None,
    attachment_path: str,
) -> AttachmentValidation:
    source = _safe_string(source_substrate)
    target_id = _safe_string(target)
    attachment_id = _safe_string(attachment_type)
    blocked: list[str] = []
    reasons: list[str] = []

    if not isinstance(payload, Mapping):
        blocked.append("payload")
        reasons.append("attachment_payload_missing")

    if source is None:
        blocked.append("source_substrate")
        reasons.append("source_substrate_missing")

    if target_id is None:
        blocked.append("target")
        reasons.append("attachment_target_missing")

    if attachment_id is None:
        blocked.append("attachment_type")
        reasons.append("attachment_type_missing")

    provenance_errors = _provenance_errors(
        provenance,
        source_substrate=source,
        attachment_type=attachment_id,
    )
    blocked.extend(provenance_errors)
    if provenance_errors:
        reasons.append("attachment_provenance_invalid")

    if (
        source in DISALLOWED_SEMANTIC_SOURCES
        and target_id in SEMANTIC_ATTACHMENT_TARGETS
    ):
        blocked.append("source_substrate")
        reasons.append("substrate_source_not_semantic_attachment_authority")

    if source == "retrieval" and target_id not in LOOKUP_CONTEXT_TARGETS:
        blocked.append("target")
        reasons.append("retrieval_attachment_target_not_lookup_context")

    if isinstance(payload, Mapping):
        leakage = detect_hidden_attachment_leakage(payload)
        blocked.extend(leakage)
        if leakage:
            reasons.append("hidden_attachment_leakage_detected")

    return AttachmentValidation(
        allowed=not blocked,
        attachment_path=attachment_path,
        source_substrate=source,
        target=target_id,
        attachment_type=attachment_id,
        blocked_fields=_unique(blocked),
        skipped_reasons=_unique(reasons),
    )


def assert_attachment_path_allowed(
    *,
    payload: Mapping[str, Any] | None,
    source_substrate: str,
    target: str,
    attachment_type: str,
    provenance: Mapping[str, Any] | None,
    attachment_path: str,
) -> AttachmentValidation:
    validation = validate_attachment_path(
        payload=payload,
        source_substrate=source_substrate,
        target=target,
        attachment_type=attachment_type,
        provenance=provenance,
        attachment_path=attachment_path,
    )
    if validation.allowed is not True:
        raise AttachmentValidationError(validation)
    return validation


def validate_active_artifact_attachment(
    artifact: Mapping[str, Any] | None,
) -> AttachmentValidation:
    if artifact is None:
        return AttachmentValidation(
            allowed=True,
            attachment_path="active_artifact_context",
            source_substrate="artifact",
            target="active_artifact_context",
            attachment_type="active_artifact",
            blocked_fields=[],
            skipped_reasons=[],
        )

    provenance = {
        "attachment_id": artifact.get("artifact_id"),
        "source_substrate": "artifact",
        "attachment_type": "active_artifact",
        "attachment_scope": "active_artifact_context",
        "explicit_attachment": True,
        "bounded": True,
        "request_id": artifact.get("request_id"),
    }
    validation = validate_attachment_path(
        payload=artifact,
        source_substrate="artifact",
        target="active_artifact_context",
        attachment_type="active_artifact",
        provenance=provenance,
        attachment_path="active_artifact_context",
    )

    artifact_type = artifact.get("artifact_type")
    if isinstance(artifact_type, str) and artifact_type in RETRIEVAL_ARTIFACT_TYPES:
        return AttachmentValidation(
            allowed=False,
            attachment_path=validation.attachment_path,
            source_substrate=validation.source_substrate,
            target=validation.target,
            attachment_type=validation.attachment_type,
            blocked_fields=_unique(
                [*validation.blocked_fields, "artifact_type"]
            ),
            skipped_reasons=_unique(
                [
                    *validation.skipped_reasons,
                    "retrieval_artifact_cannot_attach_as_active_context",
                ]
            ),
        )

    return validation


def build_lookup_attachment_provenance(
    *,
    block_count: int,
    first_block_provenance: Mapping[str, Any] | None,
) -> dict[str, Any]:
    lookup_id = (
        first_block_provenance.get("lookup_id")
        if isinstance(first_block_provenance, Mapping)
        else None
    )
    return {
        "attachment_id": lookup_id,
        "source_substrate": "retrieval",
        "attachment_type": "lookup_context_block",
        "attachment_scope": "bounded_lookup_context",
        "explicit_attachment": True,
        "bounded": True,
        "block_count": block_count,
    }


def detect_hidden_attachment_leakage(payload: Any) -> list[str]:
    return _matching_paths(
        payload,
        FORBIDDEN_ATTACHMENT_FIELDS | SEMANTIC_MUTATION_FIELDS,
    )


def _provenance_errors(
    provenance: Mapping[str, Any] | None,
    *,
    source_substrate: str | None,
    attachment_type: str | None,
) -> list[str]:
    if not isinstance(provenance, Mapping):
        return ["provenance"]

    blocked: list[str] = []
    for key in (
        "attachment_id",
        "source_substrate",
        "attachment_type",
        "attachment_scope",
    ):
        if not _safe_string(provenance.get(key)):
            blocked.append(f"provenance.{key}")

    if provenance.get("explicit_attachment") is not True:
        blocked.append("provenance.explicit_attachment")
    if provenance.get("bounded") is not True:
        blocked.append("provenance.bounded")
    if provenance.get("hidden_attachment_inheritance_performed") is True:
        blocked.append("provenance.hidden_attachment_inheritance_performed")
    if provenance.get("semantic_mutation_performed") is True:
        blocked.append("provenance.semantic_mutation_performed")
    if (
        source_substrate is not None
        and provenance.get("source_substrate") != source_substrate
    ):
        blocked.append("provenance.source_substrate")
    if (
        attachment_type is not None
        and provenance.get("attachment_type") != attachment_type
    ):
        blocked.append("provenance.attachment_type")

    return blocked


def _matching_paths(
    value: Any,
    fields: frozenset[str],
    *,
    prefix: str = "",
) -> list[str]:
    return matching_paths(value, fields, prefix=prefix)


def _unique(values: Sequence[str]) -> list[str]:
    return unique_values(values)


def _safe_string(value: Any) -> str | None:
    return safe_string(value)


__all__ = [
    "ATTACHMENT_GUARD_VERSION",
    "AttachmentValidation",
    "AttachmentValidationError",
    "assert_attachment_path_allowed",
    "build_lookup_attachment_provenance",
    "detect_hidden_attachment_leakage",
    "validate_active_artifact_attachment",
    "validate_attachment_path",
]
