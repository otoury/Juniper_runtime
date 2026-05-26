from __future__ import annotations

from typing import Any, Mapping, Sequence


RETRIEVAL_TRUST_DECOUPLING_CONTRACT_ID = "retrieval_trust_decoupling_v1"
RETRIEVAL_AUTHORITY_ISOLATION_DIAGNOSTIC_TYPE = (
    "retrieval_authority_isolation_diagnostic"
)

PROHIBITED_INFLUENCE_PATHS = frozenset(
    {
        "provider_success_to_trust",
        "provider_success_to_approval",
        "retrieval_history_to_trust",
        "retrieval_history_to_approval",
        "retrieval_receipt_to_trust",
        "retrieval_receipt_to_approval",
        "retrieval_lineage_to_trust",
        "retrieval_lineage_to_approval",
        "retrieval_score_to_trust",
        "retrieval_score_to_approval",
        "hidden_reputation_to_trust",
        "hidden_reputation_to_approval",
        "memory_write_to_trust",
        "memory_write_to_approval",
        "hidden_autonomy_to_trust",
        "hidden_autonomy_to_approval",
    }
)

RETRIEVAL_AUTHORITY_FIELDS = frozenset(
    {
        "adapter_id",
        "citations",
        "lookup_execution_id",
        "lookup_id",
        "lookup_lineage",
        "lookup_lineage_id",
        "lookup_request_id",
        "lookup_status",
        "provider_authorization",
        "provider_call_implemented",
        "provider_id",
        "provider_metadata",
        "provider_result_id",
        "provider_success",
        "raw_provider_payload",
        "receipt_ref",
        "receipt_refs",
        "records_returned",
        "retrieval_executed",
        "retrieval_history",
        "retrieval_lineage",
        "retrieval_lineage_id",
        "retrieval_provenance",
        "retrieval_receipt",
        "retrieval_receipts",
        "retrieval_status",
        "search_api_called",
        "semantic_match_score",
        "source_refs",
    }
)

TRUST_AUTHORITY_FIELDS = frozenset(
    {
        "explicit_governance_decision",
        "explicit_operator_verification",
        "explicit_verification_present",
        "governance_state",
        "operator_attestation",
        "operator_id",
        "requested_trust_state",
        "trust_lineage",
        "trust_state",
        "verification_receipt",
        "verified_by",
    }
)

PROHIBITED_TRUST_PROVENANCE_FIELDS = frozenset(
    {
        "autonomy_escalation_allowed",
        "implicit_trust_delta",
        "memory_write_allowed",
        "memory_write_performed",
        "memory_writes_allowed",
        "provider_reputation",
        "provider_score",
        "provider_success_count",
        "reputation",
        "reputation_score",
        "retrieval_based_trust_score",
        "retrieval_score",
        "silent_trust_promotion",
        "trust_accumulation",
        "trust_delta",
        "trust_score",
    }
)


def retrieval_trust_decoupling_policy() -> dict[str, Any]:
    return {
        "policy_id": RETRIEVAL_TRUST_DECOUPLING_CONTRACT_ID,
        "retrieval_informational_only": True,
        "retrieval_provenance_bearing_only": True,
        "trust_progression_operator_governance_driven": True,
        "retrieval_success_alters_trust": False,
        "retrieval_failure_alters_trust": False,
        "provider_success_trust_accumulation_allowed": False,
        "retrieval_based_trust_scoring_allowed": False,
        "hidden_reputation_systems_allowed": False,
        "memory_writes_allowed": False,
        "hidden_autonomy_escalation_allowed": False,
        "prohibited_influence_paths": sorted(PROHIBITED_INFLUENCE_PATHS),
        "allowed_trust_authority_fields": sorted(TRUST_AUTHORITY_FIELDS),
        "retrieval_authority_fields": sorted(RETRIEVAL_AUTHORITY_FIELDS),
        "prohibited_trust_provenance_fields": sorted(
            PROHIBITED_TRUST_PROVENANCE_FIELDS
        ),
    }


def build_retrieval_authority_isolation_diagnostic(
    *,
    retrieval_payload: Mapping[str, Any] | None = None,
    trust_payload: Mapping[str, Any] | None = None,
    approval_payload: Mapping[str, Any] | None = None,
    source: str = "retrieval_trust_decoupling",
) -> dict[str, Any]:
    retrieval_paths = _retrieval_authority_paths(retrieval_payload)
    trust_paths = _retrieval_authority_paths(trust_payload)
    trust_prohibited = _prohibited_trust_provenance_paths(trust_payload)
    approval_paths = _retrieval_authority_paths(approval_payload)
    approval_prohibited = _prohibited_trust_provenance_paths(approval_payload)
    blocked = _unique(
        [
            *[f"trust.{path}" for path in trust_paths],
            *[f"trust.{path}" for path in trust_prohibited],
            *[f"approval.{path}" for path in approval_paths],
            *[f"approval.{path}" for path in approval_prohibited],
        ]
    )
    return {
        "contract_id": RETRIEVAL_TRUST_DECOUPLING_CONTRACT_ID,
        "diagnostic_type": RETRIEVAL_AUTHORITY_ISOLATION_DIAGNOSTIC_TYPE,
        "source": _safe_string(source) or "retrieval_trust_decoupling",
        "allowed": not blocked,
        "observational_only": True,
        "hidden_context_injection_performed": False,
        "planner_semantic_authority": False,
        "retrieval_informational_only": True,
        "retrieval_authority_isolated": not blocked,
        "trust_progression_authority": "operator_governance_only",
        "approval_semantics_authority": "approval_policy_only",
        "retrieval_success_altered_trust": False,
        "provider_success_trust_accumulation_performed": False,
        "retrieval_based_trust_scoring_performed": False,
        "hidden_reputation_system_used": False,
        "memory_write_performed": False,
        "hidden_autonomy_escalation_performed": False,
        "retrieval_authority_fields_observed": retrieval_paths,
        "blocked_fields": blocked,
        "prohibited_influence_paths": sorted(PROHIBITED_INFLUENCE_PATHS),
        "skipped_reasons": (
            ["retrieval_authority_isolation_violation"] if blocked else []
        ),
    }


def validate_retrieval_trust_decoupling(
    *,
    retrieval_payload: Mapping[str, Any] | None = None,
    trust_payload: Mapping[str, Any] | None = None,
    approval_payload: Mapping[str, Any] | None = None,
) -> bool:
    return (
        build_retrieval_authority_isolation_diagnostic(
            retrieval_payload=retrieval_payload,
            trust_payload=trust_payload,
            approval_payload=approval_payload,
        )["allowed"]
        is True
    )


def trust_provenance_is_retrieval_isolated(value: Mapping[str, Any] | None) -> bool:
    if not isinstance(value, Mapping):
        return True
    return not (
        _retrieval_authority_paths(value)
        or _prohibited_trust_provenance_paths(value)
    )


def trust_provenance_blocked_paths(value: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    return _unique(
        [
            *_retrieval_authority_paths(value),
            *_prohibited_trust_provenance_paths(value),
        ]
    )


def _retrieval_authority_paths(value: Any, *, prefix: str = "") -> list[str]:
    return _matching_paths(value, RETRIEVAL_AUTHORITY_FIELDS, prefix=prefix)


def _prohibited_trust_provenance_paths(
    value: Any,
    *,
    prefix: str = "",
) -> list[str]:
    return _matching_paths(value, PROHIBITED_TRUST_PROVENANCE_FIELDS, prefix=prefix)


def _matching_paths(
    value: Any,
    fields: frozenset[str],
    *,
    prefix: str = "",
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            if key in fields:
                paths.append(path)
            paths.extend(_matching_paths(item, fields, prefix=path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            paths.extend(_matching_paths(item, fields, prefix=f"{prefix}[{index}]"))
    return paths


def _unique(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = _safe_string(value)
        if text and text not in seen:
            seen.append(text)
    return seen


def _safe_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "PROHIBITED_INFLUENCE_PATHS",
    "PROHIBITED_TRUST_PROVENANCE_FIELDS",
    "RETRIEVAL_AUTHORITY_FIELDS",
    "RETRIEVAL_AUTHORITY_ISOLATION_DIAGNOSTIC_TYPE",
    "RETRIEVAL_TRUST_DECOUPLING_CONTRACT_ID",
    "TRUST_AUTHORITY_FIELDS",
    "build_retrieval_authority_isolation_diagnostic",
    "retrieval_trust_decoupling_policy",
    "trust_provenance_blocked_paths",
    "trust_provenance_is_retrieval_isolated",
    "validate_retrieval_trust_decoupling",
]
