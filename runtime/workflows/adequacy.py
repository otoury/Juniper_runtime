from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime.workflows.declarations import WorkflowStepDeclaration


GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
GUEST_CANDIDATE_ADEQUACY_ARTIFACT = "guest_candidate_adequacy"
GUEST_DB_ADEQUACY_ARTIFACT = "guest_db_adequacy"
OUTCOME_ADEQUATE = "adequate"
OUTCOME_INADEQUATE = "inadequate"
OUTCOME_UNKNOWN = "unknown"
DEFAULT_FUTURE_SIGNALS = (
    "has_email_contact",
    "email_refs",
    "has_video_presence",
    "video_presence_refs",
    "contact_confidence",
    "on_air_suitability_signals",
)
DEFAULT_REQUIRED_CONTACT_FIELDS = ("email_contact",)
DEFAULT_MAX_FRESHNESS_AGE_DAYS = 180
ADEQUACY_REASON_LOCAL_EXACT = "local_exact_match"
ADEQUACY_REASON_LOCAL_PARTIAL = "local_partial_match_sufficient"
ADEQUACY_REASON_CONTACTS = "contact_fields_sufficient"
ADEQUACY_REASON_FRESH = "freshness_current"
ADEQUACY_REASON_BOOKING = "booking_suitable"
INADEQUACY_REASON_USER_WEB = "user_requested_web"
INADEQUACY_REASON_NO_CANDIDATES = "no_local_candidates"
INADEQUACY_REASON_AMBIGUOUS = "ambiguous_local_candidates"
INADEQUACY_REASON_MISSING_EMAIL = "missing_email_contact"
INADEQUACY_REASON_MISSING_PHONE = "missing_phone_contact"
INADEQUACY_REASON_FRESHNESS_UNKNOWN = "freshness_unknown"
INADEQUACY_REASON_FRESHNESS_STALE = "freshness_stale"
INADEQUACY_REASON_BOOKING_RESTRICTED = "booking_restricted"
INADEQUACY_REASON_BOOKING_UNKNOWN = "booking_suitability_unknown"


@dataclass(frozen=True)
class GuestCandidateAdequacyMaterialization:
    artifact: dict[str, Any]
    materialized: bool
    transition_outcome: str | None
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact.get("artifact_type"),
            "materialized": self.materialized,
            "transition_outcome": self.transition_outcome,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


@dataclass(frozen=True)
class GuestDbAdequacyMaterialization:
    artifact: dict[str, Any]
    materialized: bool
    transition_outcome: str | None
    skipped_reasons: tuple[str, ...]
    audit_summary: dict[str, Any]

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact.get("artifact_type"),
            "materialized": self.materialized,
            "transition_outcome": self.transition_outcome,
            "skipped_reasons": list(self.skipped_reasons),
            "audit_summary": dict(self.audit_summary),
        }


def materialize_guest_candidate_adequacy(
    *,
    candidate_artifact: dict[str, Any] | None,
    step: WorkflowStepDeclaration | None = None,
    min_required_candidates: int | None = None,
) -> GuestCandidateAdequacyMaterialization:
    required_minimum = _min_required_candidates(
        explicit=min_required_candidates,
        step=step,
    )
    required_signals = _required_signals(step)
    future_signals = _future_signals(step)

    if not isinstance(candidate_artifact, dict):
        return _unknown(
            min_required_candidates=required_minimum,
            required_signals=required_signals,
            future_signals=future_signals,
            skipped_reasons=("candidate_artifact_missing",),
        )

    if candidate_artifact.get("artifact_type") != GUEST_CANDIDATE_LIST_ARTIFACT:
        return _unknown(
            min_required_candidates=required_minimum,
            required_signals=required_signals,
            future_signals=future_signals,
            skipped_reasons=("unexpected_candidate_artifact_type",),
        )

    candidates = candidate_artifact.get("candidates")
    candidate_count = candidate_artifact.get("candidate_count")
    if not isinstance(candidates, list):
        return _unknown(
            min_required_candidates=required_minimum,
            required_signals=required_signals,
            future_signals=future_signals,
            skipped_reasons=("candidate_list_missing",),
        )

    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
        candidate_count = len(candidates)

    if candidate_count < 0:
        return _unknown(
            min_required_candidates=required_minimum,
            required_signals=required_signals,
            future_signals=future_signals,
            skipped_reasons=("candidate_count_invalid",),
        )

    adequate = candidate_count >= required_minimum
    outcome = OUTCOME_ADEQUATE if adequate else OUTCOME_INADEQUATE
    artifact = _artifact(
        adequate=adequate,
        outcome=outcome,
        candidate_count=candidate_count,
        min_required_candidates=required_minimum,
        required_signals=required_signals,
        missing_signals=(),
        future_signals=future_signals,
        skipped_reasons=(),
        input_provenance=_input_provenance(candidate_artifact),
    )
    return GuestCandidateAdequacyMaterialization(
        artifact=artifact,
        materialized=True,
        transition_outcome=(
            "success" if outcome == OUTCOME_ADEQUATE else "inadequate"
        ),
        skipped_reasons=(),
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=True,
            skipped_reasons=(),
        ),
    )


def materialize_guest_db_adequacy(
    *,
    candidate_artifact: dict[str, Any] | None,
    lookup_intent: dict[str, Any] | None = None,
    user_requested_web: bool = False,
    min_required_candidates: int = 1,
    required_contact_fields: tuple[str, ...] = DEFAULT_REQUIRED_CONTACT_FIELDS,
    require_current_freshness: bool = True,
    max_freshness_age_days: int = DEFAULT_MAX_FRESHNESS_AGE_DAYS,
    require_booking_suitability: bool = False,
    generated_at: datetime | None = None,
) -> GuestDbAdequacyMaterialization:
    if not isinstance(candidate_artifact, dict):
        return _guest_db_unknown(
            skipped_reasons=("candidate_artifact_missing",),
            min_required_candidates=min_required_candidates,
            required_contact_fields=required_contact_fields,
            user_requested_web=user_requested_web,
            generated_at=generated_at,
        )

    if candidate_artifact.get("artifact_type") != GUEST_CANDIDATE_LIST_ARTIFACT:
        return _guest_db_unknown(
            skipped_reasons=("unexpected_candidate_artifact_type",),
            min_required_candidates=min_required_candidates,
            required_contact_fields=required_contact_fields,
            user_requested_web=user_requested_web,
            generated_at=generated_at,
        )

    candidates = candidate_artifact.get("candidates")
    if not isinstance(candidates, list):
        return _guest_db_unknown(
            skipped_reasons=("candidate_list_missing",),
            min_required_candidates=min_required_candidates,
            required_contact_fields=required_contact_fields,
            user_requested_web=user_requested_web,
            generated_at=generated_at,
        )

    candidate_count = candidate_artifact.get("candidate_count")
    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
        candidate_count = len(candidates)
    if candidate_count < 0:
        return _guest_db_unknown(
            skipped_reasons=("candidate_count_invalid",),
            min_required_candidates=min_required_candidates,
            required_contact_fields=required_contact_fields,
            user_requested_web=user_requested_web,
            generated_at=generated_at,
        )

    assessment = _assess_guest_db_candidates(
        candidates=candidates,
        candidate_count=candidate_count,
        lookup_intent=lookup_intent,
        user_requested_web=user_requested_web,
        min_required_candidates=max(1, min_required_candidates),
        required_contact_fields=required_contact_fields,
        require_current_freshness=require_current_freshness,
        max_freshness_age_days=max(1, max_freshness_age_days),
        require_booking_suitability=require_booking_suitability,
        generated_at=generated_at,
    )
    artifact = _guest_db_artifact(
        assessment=assessment,
        candidate_artifact=candidate_artifact,
        generated_at=generated_at,
    )
    return GuestDbAdequacyMaterialization(
        artifact=artifact,
        materialized=True,
        transition_outcome=(
            "success" if artifact["outcome"] == OUTCOME_ADEQUATE else "inadequate"
        ),
        skipped_reasons=(),
        audit_summary=_guest_db_audit_summary(
            artifact=artifact,
            materialized=True,
            skipped_reasons=(),
        ),
    )


def validate_guest_db_adequacy(artifact: Any) -> bool:
    if not isinstance(artifact, dict):
        return False
    if artifact.get("artifact_type") != GUEST_DB_ADEQUACY_ARTIFACT:
        return False
    if artifact.get("result_type") != GUEST_DB_ADEQUACY_ARTIFACT:
        return False
    outcome = artifact.get("outcome")
    if outcome not in {OUTCOME_ADEQUATE, OUTCOME_INADEQUATE, OUTCOME_UNKNOWN}:
        return False
    adequate = artifact.get("adequate")
    if outcome == OUTCOME_ADEQUATE and adequate is not True:
        return False
    if outcome == OUTCOME_INADEQUATE and adequate is not False:
        return False
    if outcome == OUTCOME_UNKNOWN and adequate is not None:
        return False
    for key in (
        "reason_codes",
        "inadequacy_reason_codes",
        "missing_contact_fields",
        "booking_restrictions",
    ):
        if not isinstance(artifact.get(key), list):
            return False
    diagnostics = artifact.get("diagnostics")
    provenance = artifact.get("provenance")
    if not isinstance(diagnostics, dict) or not isinstance(provenance, dict):
        return False
    if diagnostics.get("content_safe") is not True:
        return False
    if provenance.get("web_search_executed") is not False:
        return False
    if provenance.get("external_discovery_executed") is not False:
        return False
    if provenance.get("memory_written") is not False:
        return False
    return True


def _unknown(
    *,
    min_required_candidates: int,
    required_signals: tuple[str, ...],
    future_signals: tuple[str, ...],
    skipped_reasons: tuple[str, ...],
) -> GuestCandidateAdequacyMaterialization:
    artifact = _artifact(
        adequate=None,
        outcome=OUTCOME_UNKNOWN,
        candidate_count=0,
        min_required_candidates=min_required_candidates,
        required_signals=required_signals,
        missing_signals=required_signals,
        future_signals=future_signals,
        skipped_reasons=skipped_reasons,
    )
    return GuestCandidateAdequacyMaterialization(
        artifact=artifact,
        materialized=False,
        transition_outcome="failure",
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _artifact(
    *,
    adequate: bool | None,
    outcome: str,
    candidate_count: int,
    min_required_candidates: int,
    required_signals: tuple[str, ...],
    missing_signals: tuple[str, ...],
    future_signals: tuple[str, ...],
    skipped_reasons: tuple[str, ...],
    input_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "assessment_materialized": True,
        "assessment_rule": "candidate_count >= min_required_candidates",
        "ranking_performed": False,
        "selection_performed": False,
        "web_search_executed": False,
        "draft_generated": False,
        "delivery_performed": False,
        "required_signals_scored": False,
        "skipped_reasons": list(skipped_reasons),
    }
    if input_provenance is not None:
        provenance["input_artifact_provenance"] = input_provenance
        provenance["semantic_retrieval_executed"] = bool(
            input_provenance.get("retrieval_boundary")
            == "runtime.semantic_retrieval"
            and input_provenance.get("retrieval_executed") is True
        )
        provenance["semantic_records_returned"] = input_provenance.get(
            "records_returned"
        )
        provenance["input_source_scope"] = input_provenance.get("source_scope")

    return {
        "artifact_type": GUEST_CANDIDATE_ADEQUACY_ARTIFACT,
        "result_type": GUEST_CANDIDATE_ADEQUACY_ARTIFACT,
        "adequate": adequate,
        "outcome": outcome,
        "candidate_count": candidate_count,
        "min_required_candidates": min_required_candidates,
        "required_signals": list(required_signals),
        "missing_signals": list(missing_signals),
        "future_enrichment_signals": list(future_signals),
        "provenance": provenance,
    }


def _guest_db_unknown(
    *,
    skipped_reasons: tuple[str, ...],
    min_required_candidates: int,
    required_contact_fields: tuple[str, ...],
    user_requested_web: bool,
    generated_at: datetime | None,
) -> GuestDbAdequacyMaterialization:
    assessment = {
        "adequate": None,
        "outcome": OUTCOME_UNKNOWN,
        "candidate_count": 0,
        "min_required_candidates": max(1, min_required_candidates),
        "match": _match_assessment(
            exact_match=False,
            partial_match=False,
            ambiguous=False,
            exact_match_count=0,
            partial_match_count=0,
        ),
        "missing_contact_fields": _string_tuple(required_contact_fields),
        "freshness": {
            "status": "unknown",
            "max_age_days": DEFAULT_MAX_FRESHNESS_AGE_DAYS,
            "current_count": 0,
            "unknown_count": 0,
            "stale_count": 0,
        },
        "booking": {
            "suitability": "unknown",
            "restrictions_present": False,
            "restrictions": [],
        },
        "user_requested_web": bool(user_requested_web),
        "reason_codes": (),
        "inadequacy_reason_codes": tuple(skipped_reasons),
    }
    artifact = _guest_db_artifact(
        assessment=assessment,
        candidate_artifact=None,
        generated_at=generated_at,
        skipped_reasons=skipped_reasons,
    )
    return GuestDbAdequacyMaterialization(
        artifact=artifact,
        materialized=False,
        transition_outcome="failure",
        skipped_reasons=skipped_reasons,
        audit_summary=_guest_db_audit_summary(
            artifact=artifact,
            materialized=False,
            skipped_reasons=skipped_reasons,
        ),
    )


def _assess_guest_db_candidates(
    *,
    candidates: list[Any],
    candidate_count: int,
    lookup_intent: dict[str, Any] | None,
    user_requested_web: bool,
    min_required_candidates: int,
    required_contact_fields: tuple[str, ...],
    require_current_freshness: bool,
    max_freshness_age_days: int,
    require_booking_suitability: bool,
    generated_at: datetime | None,
) -> dict[str, Any]:
    usable_candidates = [
        candidate for candidate in candidates if isinstance(candidate, dict)
    ]
    exact_count = sum(
        1
        for candidate in usable_candidates
        if _candidate_is_exact_match(candidate, lookup_intent)
    )
    partial_count = sum(
        1
        for candidate in usable_candidates
        if _candidate_is_partial_match(candidate, lookup_intent)
    )
    exact_match = exact_count == 1
    partial_match = partial_count > 0 or (candidate_count > 0 and exact_count == 0)
    ambiguous = candidate_count > 1 and exact_count != 1
    missing_contact_fields = _missing_contact_fields(
        candidates=usable_candidates,
        required_contact_fields=required_contact_fields,
    )
    freshness = _freshness_assessment(
        candidates=usable_candidates,
        max_freshness_age_days=max_freshness_age_days,
        generated_at=generated_at,
    )
    booking = _booking_assessment(usable_candidates)

    reason_codes: list[str] = []
    inadequacy: list[str] = []
    if user_requested_web:
        inadequacy.append(INADEQUACY_REASON_USER_WEB)
    if candidate_count < min_required_candidates:
        inadequacy.append(INADEQUACY_REASON_NO_CANDIDATES)
    if ambiguous:
        inadequacy.append(INADEQUACY_REASON_AMBIGUOUS)
    if missing_contact_fields:
        inadequacy.extend(_contact_reason(field) for field in missing_contact_fields)
    else:
        reason_codes.append(ADEQUACY_REASON_CONTACTS)
    if require_current_freshness and freshness["status"] == "unknown":
        inadequacy.append(INADEQUACY_REASON_FRESHNESS_UNKNOWN)
    if require_current_freshness and freshness["status"] == "stale":
        inadequacy.append(INADEQUACY_REASON_FRESHNESS_STALE)
    if freshness["status"] == "current":
        reason_codes.append(ADEQUACY_REASON_FRESH)
    if booking["suitability"] == "restricted":
        inadequacy.append(INADEQUACY_REASON_BOOKING_RESTRICTED)
    elif require_booking_suitability and booking["suitability"] == "unknown":
        inadequacy.append(INADEQUACY_REASON_BOOKING_UNKNOWN)
    elif booking["suitability"] == "suitable":
        reason_codes.append(ADEQUACY_REASON_BOOKING)
    if exact_match:
        reason_codes.append(ADEQUACY_REASON_LOCAL_EXACT)
    elif partial_match and candidate_count >= min_required_candidates:
        reason_codes.append(ADEQUACY_REASON_LOCAL_PARTIAL)

    adequate = not inadequacy
    return {
        "adequate": adequate,
        "outcome": OUTCOME_ADEQUATE if adequate else OUTCOME_INADEQUATE,
        "candidate_count": candidate_count,
        "min_required_candidates": min_required_candidates,
        "match": _match_assessment(
            exact_match=exact_match,
            partial_match=partial_match,
            ambiguous=ambiguous,
            exact_match_count=exact_count,
            partial_match_count=partial_count,
        ),
        "missing_contact_fields": tuple(missing_contact_fields),
        "freshness": freshness,
        "booking": booking,
        "user_requested_web": bool(user_requested_web),
        "reason_codes": tuple(_dedupe(reason_codes)),
        "inadequacy_reason_codes": tuple(_dedupe(inadequacy)),
    }


def _guest_db_artifact(
    *,
    assessment: dict[str, Any],
    candidate_artifact: dict[str, Any] | None,
    generated_at: datetime | None,
    skipped_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    provenance = _input_provenance(candidate_artifact or {})
    source_scope = None
    if isinstance(candidate_artifact, dict):
        source_scope = candidate_artifact.get("source_scope")
    if source_scope is None and isinstance(provenance, dict):
        source_scope = provenance.get("source_scope")
    return {
        "artifact_type": GUEST_DB_ADEQUACY_ARTIFACT,
        "result_type": GUEST_DB_ADEQUACY_ARTIFACT,
        "adequate": assessment["adequate"],
        "outcome": assessment["outcome"],
        "source_scope": _optional_string(source_scope) or "db",
        "generated_at": _timestamp(generated_at),
        "candidate_count": assessment["candidate_count"],
        "min_required_candidates": assessment["min_required_candidates"],
        "exact_match": assessment["match"]["exact_match"],
        "partial_match": assessment["match"]["partial_match"],
        "ambiguous": assessment["match"]["ambiguous"],
        "match": assessment["match"],
        "missing_contact_fields": list(assessment["missing_contact_fields"]),
        "freshness": dict(assessment["freshness"]),
        "booking_suitability": assessment["booking"]["suitability"],
        "booking_restrictions": list(assessment["booking"]["restrictions"]),
        "user_requested_web": assessment["user_requested_web"],
        "reason_codes": list(assessment["reason_codes"]),
        "inadequacy_reason_codes": list(
            assessment["inadequacy_reason_codes"]
        ),
        "diagnostics": _guest_db_diagnostics(assessment),
        "provenance": {
            "assessment_materialized": True,
            "assessment_boundary": "runtime.workflows.adequacy",
            "assessment_rule": "local guest db adequacy assessment",
            "input_artifact_type": (
                candidate_artifact.get("artifact_type")
                if isinstance(candidate_artifact, dict)
                else None
            ),
            "input_source_scope": source_scope,
            "semantic_retrieval_executed": bool(
                isinstance(provenance, dict)
                and provenance.get("retrieval_boundary")
                == "runtime.semantic_retrieval"
                and provenance.get("retrieval_executed") is True
            ),
            "retrieval_executed": bool(
                isinstance(provenance, dict)
                and provenance.get("retrieval_executed") is True
            ),
            "assessment_only": True,
            "planner_intent_reinterpreted": False,
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "external_adapter_called": False,
            "external_discovery_executed": False,
            "ranking_performed": False,
            "selection_performed": False,
            "draft_generated": False,
            "delivery_performed": False,
            "memory_written": False,
            "skipped_reasons": list(skipped_reasons),
        },
    }


def _guest_db_diagnostics(assessment: dict[str, Any]) -> dict[str, Any]:
    freshness = assessment["freshness"]
    booking = assessment["booking"]
    match = assessment["match"]
    return {
        "content_safe": True,
        "candidate_count": assessment["candidate_count"],
        "exact_match_count": match["exact_match_count"],
        "partial_match_count": match["partial_match_count"],
        "ambiguous": match["ambiguous"],
        "missing_contact_field_count": len(assessment["missing_contact_fields"]),
        "missing_contact_fields": list(assessment["missing_contact_fields"]),
        "freshness_status": freshness["status"],
        "freshness_unknown_count": freshness["unknown_count"],
        "freshness_stale_count": freshness["stale_count"],
        "booking_suitability": booking["suitability"],
        "booking_restriction_count": len(booking["restrictions"]),
        "user_requested_web": assessment["user_requested_web"],
        "reason_codes": list(assessment["reason_codes"]),
        "inadequacy_reason_codes": list(
            assessment["inadequacy_reason_codes"]
        ),
    }


def _match_assessment(
    *,
    exact_match: bool,
    partial_match: bool,
    ambiguous: bool,
    exact_match_count: int,
    partial_match_count: int,
) -> dict[str, Any]:
    return {
        "exact_match": exact_match,
        "partial_match": partial_match,
        "ambiguous": ambiguous,
        "exact_match_count": exact_match_count,
        "partial_match_count": partial_match_count,
    }


def _min_required_candidates(
    *,
    explicit: int | None,
    step: WorkflowStepDeclaration | None,
) -> int:
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return max(1, explicit)
    shape = _adequacy_shape(step)
    value = shape.get("min_required_candidates")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, value)
    return 1


def _required_signals(step: WorkflowStepDeclaration | None) -> tuple[str, ...]:
    shape = _adequacy_shape(step)
    return _string_tuple(shape.get("required_signals"))


def _future_signals(step: WorkflowStepDeclaration | None) -> tuple[str, ...]:
    if step is not None:
        values = _string_tuple(step.constraints.get("future_enrichment_signals"))
        if values:
            return values
    return DEFAULT_FUTURE_SIGNALS


def _adequacy_shape(step: WorkflowStepDeclaration | None) -> dict[str, Any]:
    if step is None:
        return {}
    shape = step.constraints.get("adequacy_result_shape")
    return shape if isinstance(shape, dict) else {}


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )


def _candidate_is_exact_match(
    candidate: dict[str, Any],
    lookup_intent: dict[str, Any] | None,
) -> bool:
    metadata = candidate.get("metadata")
    score = candidate.get("semantic_match_score")
    if not isinstance(score, (int, float)) and isinstance(metadata, dict):
        score = metadata.get("semantic_match_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return float(score) >= 1.0

    entity_name = _lookup_text(lookup_intent, "entity_name")
    display_name = _optional_string(candidate.get("display_name"))
    return bool(entity_name and display_name and entity_name == display_name)


def _candidate_is_partial_match(
    candidate: dict[str, Any],
    lookup_intent: dict[str, Any] | None,
) -> bool:
    if _candidate_is_exact_match(candidate, lookup_intent):
        return False
    score = candidate.get("semantic_match_score")
    metadata = candidate.get("metadata")
    if not isinstance(score, (int, float)) and isinstance(metadata, dict):
        score = metadata.get("semantic_match_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return 0 < float(score) < 1.0
    return bool(candidate.get("matched_terms"))


def _missing_contact_fields(
    *,
    candidates: list[dict[str, Any]],
    required_contact_fields: tuple[str, ...],
) -> tuple[str, ...]:
    missing: list[str] = []
    for field in _string_tuple(required_contact_fields):
        channel = _contact_channel(field)
        has_contact = any(
            _candidate_has_contact(candidate, channel)
            for candidate in candidates
        )
        if not has_contact:
            missing.append(field)
    return tuple(missing)


def _candidate_has_contact(candidate: dict[str, Any], channel: str) -> bool:
    channels = candidate.get("known_contact_channels")
    if isinstance(channels, list) and channel in channels:
        return True
    metadata = candidate.get("metadata")
    if isinstance(metadata, dict):
        channels = metadata.get("known_contact_channels")
        if isinstance(channels, list) and channel in channels:
            return True
    return False


def _contact_channel(field: str) -> str:
    if field.endswith("_contact"):
        return field[: -len("_contact")]
    return field


def _contact_reason(field: str) -> str:
    if _contact_channel(field) == "phone":
        return INADEQUACY_REASON_MISSING_PHONE
    return INADEQUACY_REASON_MISSING_EMAIL


def _freshness_assessment(
    *,
    candidates: list[dict[str, Any]],
    max_freshness_age_days: int,
    generated_at: datetime | None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    unknown = 0
    stale = 0
    current = 0
    for candidate in candidates:
        timestamp = _parse_timestamp(_candidate_source_updated_at(candidate))
        if timestamp is None:
            unknown += 1
            continue
        age_days = (now - timestamp).days
        if age_days > max_freshness_age_days:
            stale += 1
        else:
            current += 1
    status = "unknown"
    if stale:
        status = "stale"
    elif current and not unknown:
        status = "current"
    return {
        "status": status,
        "max_age_days": max_freshness_age_days,
        "current_count": current,
        "unknown_count": unknown,
        "stale_count": stale,
    }


def _candidate_source_updated_at(candidate: dict[str, Any]) -> str | None:
    provenance = candidate.get("provenance")
    if isinstance(provenance, dict):
        value = _optional_string(provenance.get("source_updated_at"))
        if value:
            return value
    metadata = candidate.get("metadata")
    if isinstance(metadata, dict):
        return _optional_string(metadata.get("source_updated_at"))
    return _optional_string(candidate.get("source_updated_at"))


def _booking_assessment(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    restrictions: list[str] = []
    suitability_known = False
    suitable = False
    for candidate in candidates:
        candidate_restrictions = _string_tuple(
            candidate.get("booking_restrictions")
        )
        restrictions.extend(candidate_restrictions)
        value = candidate.get("booking_suitability")
        if isinstance(value, bool):
            suitability_known = True
            suitable = suitable or value
        elif _optional_string(candidate.get("public_booking_notes")):
            suitability_known = True
            suitable = True

    if restrictions:
        status = "restricted"
    elif suitable:
        status = "suitable"
    elif suitability_known:
        status = "unsuitable"
    else:
        status = "unknown"
    return {
        "suitability": status,
        "restrictions_present": bool(restrictions),
        "restrictions": _dedupe(restrictions),
    }


def _lookup_text(value: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    return _optional_string(value.get(key))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _input_provenance(candidate_artifact: dict[str, Any]) -> dict[str, Any] | None:
    provenance = candidate_artifact.get("provenance")
    if isinstance(provenance, dict):
        return dict(provenance)
    return None


def _audit_summary(
    *,
    artifact: dict[str, Any],
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "artifact_type": artifact.get("artifact_type"),
        "outcome": artifact.get("outcome"),
        "candidate_count": artifact.get("candidate_count"),
        "min_required_candidates": artifact.get("min_required_candidates"),
        "materialized": materialized,
        "ranking_performed": False,
        "selection_performed": False,
        "web_search_executed": False,
        "delivery_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


def _guest_db_audit_summary(
    *,
    artifact: dict[str, Any],
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "artifact_type": artifact.get("artifact_type"),
        "outcome": artifact.get("outcome"),
        "adequate": artifact.get("adequate"),
        "candidate_count": artifact.get("candidate_count"),
        "exact_match": artifact.get("exact_match"),
        "partial_match": artifact.get("partial_match"),
        "ambiguous": artifact.get("ambiguous"),
        "reason_codes": list(artifact.get("reason_codes", [])),
        "inadequacy_reason_codes": list(
            artifact.get("inadequacy_reason_codes", [])
        ),
        "content_safe_diagnostics": True,
        "materialized": materialized,
        "web_search_executed": False,
        "external_discovery_executed": False,
        "memory_written": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "GUEST_CANDIDATE_ADEQUACY_ARTIFACT",
    "GUEST_CANDIDATE_LIST_ARTIFACT",
    "GUEST_DB_ADEQUACY_ARTIFACT",
    "GuestCandidateAdequacyMaterialization",
    "GuestDbAdequacyMaterialization",
    "materialize_guest_candidate_adequacy",
    "materialize_guest_db_adequacy",
    "validate_guest_db_adequacy",
]
