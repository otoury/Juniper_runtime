from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from runtime.contracts.guest_candidate_merge_receipt import (
    validate_guest_candidate_merge_receipt,
)


GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
DB_SOURCE_SCOPE = "db"
WEB_SOURCE_SCOPE = "web"
DB_SOURCE_SCOPE_ALIASES = frozenset({DB_SOURCE_SCOPE, "guest_db"})
USER_SOURCE_SCOPE = "user"
MANUAL_OPERATOR_SOURCE_SCOPE = "manual_operator"
ALLOWED_SOURCE_SCOPES = (
    frozenset({WEB_SOURCE_SCOPE, USER_SOURCE_SCOPE, MANUAL_OPERATOR_SOURCE_SCOPE})
    | DB_SOURCE_SCOPE_ALIASES
)
LOCAL_DB_ORIGIN = "local_db"
EXTERNAL_PUBLIC_SOURCE_ORIGIN = "external_public_source"
USER_SUPPLIED_ORIGIN = "user_supplied"
MANUAL_OPERATOR_VERIFIED_ORIGIN = "manual_operator_verified"
ALLOWED_CANDIDATE_ORIGINS = frozenset(
    {
        LOCAL_DB_ORIGIN,
        EXTERNAL_PUBLIC_SOURCE_ORIGIN,
        USER_SUPPLIED_ORIGIN,
        MANUAL_OPERATOR_VERIFIED_ORIGIN,
    }
)
VERIFIED_CONTACT_STATE = "verified"
PUBLIC_SOURCE_OBSERVED_CONTACT_STATE = "public_source_observed"
POSSIBLE_UNVERIFIED_CONTACT_STATE = "possible_unverified"
BLOCKED_PRIVATE_CONTACT_STATE = "blocked_private"
MISSING_CONTACT_STATE = "missing"
ALLOWED_CONTACT_VERIFICATION_STATES = frozenset(
    {
        VERIFIED_CONTACT_STATE,
        PUBLIC_SOURCE_OBSERVED_CONTACT_STATE,
        POSSIBLE_UNVERIFIED_CONTACT_STATE,
        BLOCKED_PRIVATE_CONTACT_STATE,
        MISSING_CONTACT_STATE,
    }
)
DEFAULT_MAX_MERGED_CANDIDATES = 50
DEFAULT_MAX_MERGE_RECEIPTS = 100
MERGE_POLICY_ID = "declared_identity_structural_guest_candidate_merge_v1"
IDENTITY_FIELDS = ("candidate_id", "email", "canonical_name")
ENRICHMENT_BOOLEAN_FIELDS = ("has_email_contact", "has_video_presence")
ENRICHMENT_REF_FIELDS = ("email_refs", "video_presence_refs")
ENRICHMENT_SIGNAL_FIELDS = ("on_air_suitability_signals",)
ENRICHMENT_CONFIDENCE_FIELD = "contact_confidence"
ENRICHMENT_METADATA_FIELDS = (
    "has_email_contact",
    "email_refs",
    "has_video_presence",
    "video_presence_refs",
    ENRICHMENT_CONFIDENCE_FIELD,
    "on_air_suitability_signals",
)
SEMANTIC_METADATA_FIELDS = (
    "semantic_match_score",
    "semantic_match_reasons",
    "matched_terms",
)


@dataclass(frozen=True)
class GuestCandidateListMergeMaterialization:
    artifact: dict[str, Any]
    materialized: bool
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact.get("artifact_type"),
            "materialized": self.materialized,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_guest_candidate_list_merge(
    *,
    candidate_artifacts: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    artifact_refs: list[str] | tuple[str, ...] = (),
    max_merged_candidates: int = DEFAULT_MAX_MERGED_CANDIDATES,
    max_merge_receipts: int = DEFAULT_MAX_MERGE_RECEIPTS,
) -> GuestCandidateListMergeMaterialization:
    if not isinstance(candidate_artifacts, (list, tuple)):
        return _closed(skipped_reasons=("candidate_artifacts_missing",))

    safe_refs = _string_list(artifact_refs)
    candidate_limit = _positive_int_or_default(
        max_merged_candidates,
        DEFAULT_MAX_MERGED_CANDIDATES,
    )
    receipt_limit = _positive_int_or_default(
        max_merge_receipts,
        DEFAULT_MAX_MERGE_RECEIPTS,
    )
    occurrences: list[dict[str, Any]] = []
    skipped: list[str] = []

    for artifact_index, artifact in enumerate(candidate_artifacts):
        if not isinstance(artifact, dict):
            skipped.append("candidate_artifact_not_object")
            continue
        if artifact.get("artifact_type") != GUEST_CANDIDATE_LIST_ARTIFACT:
            skipped.append("unexpected_candidate_artifact_type")
            continue

        source_scope = _artifact_source_scope(artifact)
        if source_scope not in ALLOWED_SOURCE_SCOPES:
            skipped.append("unsupported_source_scope")
            continue

        candidates = artifact.get("candidates")
        if not isinstance(candidates, list):
            skipped.append("candidate_list_missing")
            continue

        artifact_ref = _artifact_ref_for_index(
            artifact_refs=safe_refs,
            artifact=artifact,
            artifact_index=artifact_index,
        )
        for candidate_index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                skipped.append("candidate_not_object")
                continue
            enrichment_errors = validate_guest_candidate_enrichment_metadata(
                candidate
            )
            if enrichment_errors:
                skipped.append("candidate_enrichment_metadata_invalid")
                continue
            origin = _candidate_origin(candidate, source_scope)
            if origin not in ALLOWED_CANDIDATE_ORIGINS:
                skipped.append("candidate_origin_invalid")
                continue
            contact_state = _contact_verification_state(candidate)
            if contact_state not in ALLOWED_CONTACT_VERIFICATION_STATES:
                skipped.append("contact_verification_state_invalid")
                continue
            occurrences.append(
                {
                    "candidate": _candidate_with_structural_metadata(
                        candidate=candidate,
                        origin=origin,
                        contact_verification_state=contact_state,
                    ),
                    "source_scope": source_scope,
                    "candidate_origin": origin,
                    "contact_verification_state": contact_state,
                    "artifact_ref": artifact_ref,
                    "artifact_index": artifact_index,
                    "candidate_index": candidate_index,
                    "provenance": _candidate_provenance(
                        artifact=artifact,
                        candidate=candidate,
                        artifact_ref=artifact_ref,
                        source_scope=source_scope,
                    ),
                    "identity_keys": _identity_keys(candidate),
                }
            )

    merged_candidates, duplicate_groups, merge_receipts = _merge_occurrences(
        occurrences,
        candidate_limit=candidate_limit,
        receipt_limit=receipt_limit,
    )
    source_scopes = _unique_strings(
        occurrence["source_scope"] for occurrence in occurrences
    )
    merged_refs = _unique_strings(
        occurrence["artifact_ref"] for occurrence in occurrences
    )
    artifact = _artifact(
        candidates=merged_candidates,
        source_scopes=source_scopes,
        merged_from_artifact_refs=merged_refs,
        duplicate_groups=duplicate_groups,
        merge_receipts=merge_receipts,
        skipped_reasons=tuple(skipped),
        bounds={
            "max_merged_candidates": candidate_limit,
            "max_merge_receipts": receipt_limit,
        },
    )
    return GuestCandidateListMergeMaterialization(
        artifact=artifact,
        materialized=True,
        skipped_reasons=tuple(skipped),
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=True,
            skipped_reasons=tuple(skipped),
        ),
    )


def _merge_occurrences(
    occurrences: list[dict[str, Any]],
    *,
    candidate_limit: int,
    receipt_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    merged: list[dict[str, Any]] = []
    groups: list[list[dict[str, Any]]] = []
    key_to_group_index: dict[tuple[str, str], int] = {}

    for occurrence in occurrences:
        keys = occurrence["identity_keys"]
        matching_indexes = {
            key_to_group_index[key]
            for key in keys
            if key in key_to_group_index
        }
        if not matching_indexes:
            group_index = len(groups)
            groups.append([occurrence])
            for key in keys:
                key_to_group_index[key] = group_index
            continue

        group_index = min(matching_indexes)
        groups[group_index].append(occurrence)
        for other_index in sorted(matching_indexes - {group_index}):
            groups[group_index].extend(groups[other_index])
            groups[other_index] = []
        for index, group in enumerate(groups):
            for member in group:
                for key in member["identity_keys"]:
                    key_to_group_index[key] = index

    duplicate_groups: list[dict[str, Any]] = []
    merge_receipts: list[dict[str, Any]] = []
    for group_index, group in enumerate(group for group in groups if group):
        if len(merged) >= candidate_limit:
            break
        first = group[0]
        candidate = deepcopy(first["candidate"])
        lineage = [_lineage(member) for member in group]
        source_scopes = _unique_strings(member["source_scope"] for member in group)
        origins = _unique_strings(member["candidate_origin"] for member in group)
        artifact_refs = _unique_strings(member["artifact_ref"] for member in group)
        duplicate_evidence = [_duplicate_evidence(member) for member in group]
        receipt_ref = f"receipt:guest_candidate_merge:{group_index}"

        candidate["source_scope"] = first["source_scope"]
        candidate["source_scopes"] = source_scopes
        candidate["candidate_origins"] = origins
        candidate["source_lineage"] = lineage
        candidate["artifact_refs"] = artifact_refs
        candidate["duplicate_evidence"] = duplicate_evidence
        candidate["merge_receipt_refs"] = [receipt_ref]
        _preserve_selected_semantic_metadata(candidate)
        candidate["provenance"] = _merged_candidate_provenance(
            existing=candidate.get("provenance"),
            lineage=lineage,
            receipt_refs=[receipt_ref],
        )
        merged.append(candidate)

        if len(group) > 1:
            if len(merge_receipts) < receipt_limit:
                merge_receipts.append(
                    _guest_candidate_merge_receipt(
                        receipt_ref=receipt_ref,
                        group_index=group_index,
                        group=group,
                        selected_member=first,
                    )
                )
            duplicate_groups.append(
                {
                    "group_id": f"duplicate_group:{group_index}",
                    "identity_keys": _public_identity_keys(
                        key
                        for member in group
                        for key in member["identity_keys"]
                    ),
                    "candidate_indexes": [
                        member["candidate_index"] for member in group
                    ],
                    "source_scopes": source_scopes,
                    "candidate_origins": origins,
                    "artifact_refs": artifact_refs,
                    "evidence": duplicate_evidence,
                    "receipt_ref": receipt_ref,
                }
            )

    return merged, duplicate_groups, merge_receipts


def _artifact(
    *,
    candidates: list[dict[str, Any]],
    source_scopes: list[str],
    merged_from_artifact_refs: list[str],
    duplicate_groups: list[dict[str, Any]],
    merge_receipts: list[dict[str, Any]],
    skipped_reasons: tuple[str, ...],
    bounds: dict[str, int],
) -> dict[str, Any]:
    return {
        "artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "source_scopes": source_scopes,
        "merged_from_artifact_refs": merged_from_artifact_refs,
        "duplicate_groups": duplicate_groups,
        "guest_candidate_merge_receipts": merge_receipts,
        "merge_executed": True,
        "merge_policy": {
            "policy_id": MERGE_POLICY_ID,
            "merge_is_structural": True,
            "semantic_ranking_performed": False,
            "automatic_contact_promotion_allowed": False,
            "external_overwrites_local_db_allowed": False,
            "identity_fields": list(IDENTITY_FIELDS),
            "bounds": dict(bounds),
        },
        "provenance": {
            "merge_executed": True,
            "merge_boundary": "runtime.workflows.candidate_merge",
            "merge_policy_id": MERGE_POLICY_ID,
            "dedupe_fields": list(IDENTITY_FIELDS),
            "merge_is_structural": True,
            "candidate_semantics_mutated": False,
            "automatic_contact_promotion_performed": False,
            "external_overwrite_performed": False,
            "ranking_performed": False,
            "scoring_performed": False,
            "selection_performed": False,
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "cloud_model_called": False,
            "draft_generated": False,
            "notification_performed": False,
            "delivery_performed": False,
            "source_scopes": list(source_scopes),
            "merged_from_artifact_refs": list(merged_from_artifact_refs),
            "duplicate_group_count": len(duplicate_groups),
            "guest_candidate_merge_receipt_count": len(merge_receipts),
            "bounds": dict(bounds),
            "skipped_reasons": list(skipped_reasons),
        },
    }


def _closed(
    *,
    skipped_reasons: tuple[str, ...],
) -> GuestCandidateListMergeMaterialization:
    artifact = _artifact(
        candidates=[],
        source_scopes=[],
        merged_from_artifact_refs=[],
        duplicate_groups=[],
        merge_receipts=[],
        skipped_reasons=skipped_reasons,
        bounds={
            "max_merged_candidates": DEFAULT_MAX_MERGED_CANDIDATES,
            "max_merge_receipts": DEFAULT_MAX_MERGE_RECEIPTS,
        },
    )
    return GuestCandidateListMergeMaterialization(
        artifact=artifact,
        materialized=False,
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _artifact_source_scope(artifact: dict[str, Any]) -> str | None:
    direct = _optional_string(artifact.get("source_scope"))
    if direct is not None:
        return _normalize_source_scope(direct)
    provenance = artifact.get("provenance")
    if isinstance(provenance, dict):
        return _normalize_source_scope(_optional_string(provenance.get("source_scope")))
    return None


def _normalize_source_scope(value: str | None) -> str | None:
    if value in DB_SOURCE_SCOPE_ALIASES:
        return DB_SOURCE_SCOPE
    if value in {USER_SOURCE_SCOPE, USER_SUPPLIED_ORIGIN}:
        return USER_SOURCE_SCOPE
    if value in {MANUAL_OPERATOR_SOURCE_SCOPE, MANUAL_OPERATOR_VERIFIED_ORIGIN}:
        return MANUAL_OPERATOR_SOURCE_SCOPE
    return value


def _candidate_origin(candidate: dict[str, Any], source_scope: str) -> str:
    explicit = _optional_string(candidate.get("candidate_origin"))
    if explicit is not None:
        return explicit
    explicit = _optional_string(candidate.get("origin"))
    if explicit is not None:
        return explicit
    if source_scope == DB_SOURCE_SCOPE:
        return LOCAL_DB_ORIGIN
    if source_scope == WEB_SOURCE_SCOPE:
        return EXTERNAL_PUBLIC_SOURCE_ORIGIN
    if source_scope == USER_SOURCE_SCOPE:
        return USER_SUPPLIED_ORIGIN
    if source_scope == MANUAL_OPERATOR_SOURCE_SCOPE:
        return MANUAL_OPERATOR_VERIFIED_ORIGIN
    return source_scope


def _contact_verification_state(candidate: dict[str, Any]) -> str:
    explicit = _optional_string(candidate.get("contact_verification_state"))
    if explicit is not None:
        return explicit
    contact = candidate.get("contact")
    if isinstance(contact, dict):
        explicit = _optional_string(contact.get("verification_state"))
        if explicit is not None:
            return explicit
    return MISSING_CONTACT_STATE


def _candidate_with_structural_metadata(
    *,
    candidate: dict[str, Any],
    origin: str,
    contact_verification_state: str,
) -> dict[str, Any]:
    normalized = deepcopy(candidate)
    normalized["candidate_origin"] = origin
    normalized["contact_verification_state"] = contact_verification_state
    return normalized


def _identity_keys(candidate: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    keys: list[tuple[str, str]] = []
    for field in IDENTITY_FIELDS:
        value = _optional_string(candidate.get(field))
        if value is None:
            continue
        if field in {"email", "canonical_name"}:
            value = " ".join(value.lower().split())
        keys.append((field, value))
    return tuple(keys)


def _public_identity_keys(
    keys: Any,
) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    public: list[dict[str, str]] = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        public.append({"field": key[0], "value": key[1]})
    return public


def _candidate_provenance(
    *,
    artifact: dict[str, Any],
    candidate: dict[str, Any],
    artifact_ref: str,
    source_scope: str,
) -> dict[str, Any]:
    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    artifact_provenance = artifact.get("provenance")
    if not isinstance(artifact_provenance, dict):
        artifact_provenance = {}
    return {
        "candidate_provenance": dict(provenance),
        "artifact_provenance": dict(artifact_provenance),
        "artifact_ref": artifact_ref,
        "source_scope": source_scope,
    }


def _merged_candidate_provenance(
    *,
    existing: Any,
    lineage: list[dict[str, Any]],
    receipt_refs: list[str],
) -> dict[str, Any]:
    provenance = dict(existing) if isinstance(existing, dict) else {}
    provenance["merge_executed"] = True
    provenance["merge_policy_id"] = MERGE_POLICY_ID
    provenance["merge_is_structural"] = True
    provenance["candidate_semantics_mutated"] = False
    provenance["automatic_contact_promotion_performed"] = False
    provenance["external_overwrite_performed"] = False
    provenance["ranking_performed"] = False
    provenance["scoring_performed"] = False
    provenance["selection_performed"] = False
    provenance["source_lineage"] = list(lineage)
    provenance["merge_receipt_refs"] = list(receipt_refs)
    return provenance


def _lineage(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_scope": member["source_scope"],
        "candidate_origin": member["candidate_origin"],
        "contact_verification_state": member["contact_verification_state"],
        "artifact_ref": member["artifact_ref"],
        "artifact_index": member["artifact_index"],
        "candidate_index": member["candidate_index"],
        "provenance": dict(member["provenance"]),
    }


def _duplicate_evidence(member: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_scope": member["source_scope"],
        "candidate_origin": member["candidate_origin"],
        "contact_verification_state": member["contact_verification_state"],
        "artifact_ref": member["artifact_ref"],
        "candidate_index": member["candidate_index"],
        "identity_keys": _public_identity_keys(member["identity_keys"]),
    }


def _guest_candidate_merge_receipt(
    *,
    receipt_ref: str,
    group_index: int,
    group: list[dict[str, Any]],
    selected_member: dict[str, Any],
) -> dict[str, Any]:
    receipt = {
        "artifact_type": "guest_candidate_merge_receipt",
        "receipt_ref": receipt_ref,
        "merge_policy_id": MERGE_POLICY_ID,
        "merge_is_structural": True,
        "group_id": f"duplicate_group:{group_index}",
        "declared_identity_policy": {
            "identity_fields": list(IDENTITY_FIELDS),
            "hidden_dedup_inference_performed": False,
        },
        "selected_candidate_ref": _member_ref(selected_member),
        "candidate_refs": [_member_ref(member) for member in group],
        "candidate_origins": _unique_strings(
            member["candidate_origin"] for member in group
        ),
        "contact_verification_states": _unique_strings(
            member["contact_verification_state"] for member in group
        ),
        "identity_evidence": [_duplicate_evidence(member) for member in group],
        "provenance_refs": [
            {
                "artifact_ref": member["artifact_ref"],
                "source_scope": member["source_scope"],
                "candidate_origin": member["candidate_origin"],
                "candidate_index": member["candidate_index"],
            }
            for member in group
        ],
        "local_db_and_external_blended": False,
        "external_overwrote_local_db": False,
        "automatic_contact_promotion_performed": False,
        "source_weighting_heuristic_performed": False,
        "semantic_ranking_performed": False,
        "db_write_performed": False,
        "external_call_performed": False,
        "memory_write_performed": False,
    }
    errors = validate_guest_candidate_merge_receipt(receipt)
    if errors:
        details = ", ".join(
            f"{error.field}:{error.error_code}" for error in errors
        )
        raise ValueError(f"Invalid guest candidate merge receipt: {details}")
    return receipt


def _member_ref(member: dict[str, Any]) -> str:
    return (
        f"{member['artifact_ref']}#candidate:"
        f"{member['artifact_index']}:{member['candidate_index']}"
    )


def validate_guest_candidate_enrichment_metadata(
    candidate: dict[str, Any],
) -> tuple[str, ...]:
    if not isinstance(candidate, dict):
        return ("candidate_not_object",)

    errors: list[str] = []
    for field in ENRICHMENT_BOOLEAN_FIELDS:
        if field in candidate and not isinstance(candidate[field], bool):
            errors.append(f"{field}_not_boolean")

    for field in ENRICHMENT_REF_FIELDS:
        if field in candidate and not _is_string_list(candidate[field]):
            errors.append(f"{field}_not_string_list")

    if ENRICHMENT_CONFIDENCE_FIELD in candidate:
        confidence = candidate[ENRICHMENT_CONFIDENCE_FIELD]
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or confidence < 0
            or confidence > 1
        ):
            errors.append(f"{ENRICHMENT_CONFIDENCE_FIELD}_not_unit_interval")

    for field in ENRICHMENT_SIGNAL_FIELDS:
        if field in candidate and not _is_string_list(candidate[field]):
            errors.append(f"{field}_not_string_list")

    return tuple(errors)


def _merge_enrichment_metadata(
    candidate: dict[str, Any],
    group: list[dict[str, Any]],
) -> None:
    for field in ENRICHMENT_BOOLEAN_FIELDS:
        values = [
            member["candidate"].get(field)
            for member in group
            if field in member["candidate"]
        ]
        if any(value is True for value in values):
            candidate[field] = True
        elif any(value is False for value in values):
            candidate[field] = False

    for field in ENRICHMENT_REF_FIELDS + ENRICHMENT_SIGNAL_FIELDS:
        merged = _unique_strings(
            item
            for member in group
            for item in member["candidate"].get(field, [])
            if isinstance(member["candidate"].get(field), list)
        )
        if merged:
            candidate[field] = merged

    confidences = [
        member["candidate"].get(ENRICHMENT_CONFIDENCE_FIELD)
        for member in group
        if ENRICHMENT_CONFIDENCE_FIELD in member["candidate"]
    ]
    numeric_confidences = [
        value
        for value in confidences
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if numeric_confidences:
        candidate[ENRICHMENT_CONFIDENCE_FIELD] = max(numeric_confidences)


def _merge_semantic_metadata(
    candidate: dict[str, Any],
    group: list[dict[str, Any]],
) -> None:
    semantic_records = [
        member["candidate"]
        for member in group
        if _has_semantic_metadata(member["candidate"])
    ]
    if not semantic_records:
        return

    if "semantic_match_score" not in candidate:
        scores = [
            record.get("semantic_match_score")
            for record in semantic_records
            if isinstance(record.get("semantic_match_score"), (int, float))
            and not isinstance(record.get("semantic_match_score"), bool)
        ]
        if scores:
            candidate["semantic_match_score"] = max(scores)

    reasons = _unique_strings(
        reason
        for record in semantic_records
        for reason in record.get("semantic_match_reasons", [])
        if isinstance(record.get("semantic_match_reasons"), list)
    )
    if reasons and "semantic_match_reasons" not in candidate:
        candidate["semantic_match_reasons"] = reasons

    matched_terms = _unique_strings(
        term
        for record in semantic_records
        for term in record.get("matched_terms", [])
        if isinstance(record.get("matched_terms"), list)
    )
    if matched_terms and "matched_terms" not in candidate:
        candidate["matched_terms"] = matched_terms

    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    for field in SEMANTIC_METADATA_FIELDS:
        if field in candidate and field not in metadata:
            metadata[field] = candidate[field]
    if metadata:
        candidate["metadata"] = metadata


def _preserve_selected_semantic_metadata(candidate: dict[str, Any]) -> None:
    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    changed = False
    for field in SEMANTIC_METADATA_FIELDS:
        if field in candidate and field not in metadata:
            metadata[field] = candidate[field]
            changed = True
    if changed or metadata:
        candidate["metadata"] = metadata


def _has_semantic_metadata(candidate: dict[str, Any]) -> bool:
    return any(field in candidate for field in SEMANTIC_METADATA_FIELDS)


def _artifact_ref_for_index(
    *,
    artifact_refs: list[str],
    artifact: dict[str, Any],
    artifact_index: int,
) -> str:
    if artifact_index < len(artifact_refs):
        return artifact_refs[artifact_index]
    explicit = _optional_string(artifact.get("artifact_ref"))
    if explicit is not None:
        return explicit
    workflow_id = _optional_string(artifact.get("workflow_id"))
    step_id = _optional_string(artifact.get("step_id"))
    if workflow_id is not None or step_id is not None:
        return "artifact:guest_candidate_list:" + ":".join(
            item for item in (workflow_id, step_id) if item is not None
        )
    return f"artifact:guest_candidate_list:input:{artifact_index}"


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        clean = value.strip()
        if clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return _unique_strings(value)


def _positive_int_or_default(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _audit_summary(
    *,
    artifact: dict[str, Any],
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "artifact_type": artifact.get("artifact_type"),
        "candidate_count": artifact.get("candidate_count"),
        "source_scopes": list(artifact.get("source_scopes", [])),
        "duplicate_group_count": len(artifact.get("duplicate_groups", [])),
        "guest_candidate_merge_receipt_count": len(
            artifact.get("guest_candidate_merge_receipts", [])
        ),
        "materialized": materialized,
        "merge_executed": artifact.get("merge_executed") is True,
        "merge_policy_id": MERGE_POLICY_ID,
        "merge_is_structural": True,
        "ranking_performed": False,
        "scoring_performed": False,
        "selection_performed": False,
        "web_search_executed": False,
        "delivery_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "ALLOWED_CANDIDATE_ORIGINS",
    "ALLOWED_CONTACT_VERIFICATION_STATES",
    "ENRICHMENT_METADATA_FIELDS",
    "GUEST_CANDIDATE_LIST_ARTIFACT",
    "GuestCandidateListMergeMaterialization",
    "MERGE_POLICY_ID",
    "materialize_guest_candidate_list_merge",
    "validate_guest_candidate_enrichment_metadata",
]
