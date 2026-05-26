from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.workflows.declarations import WorkflowStepDeclaration


GUEST_CANDIDATE_LIST_ARTIFACT = "guest_candidate_list"
RANKED_GUEST_CANDIDATE_LIST_ARTIFACT = "ranked_guest_candidate_list"
DEFAULT_RANKING_POLICY_ID = "deterministic_guest_enrichment_score_v1"
DEFAULT_REASON_CODES = (
    "video_presence_present",
    "video_presence_absent",
    "email_contact_present",
    "email_contact_absent",
    "contact_confidence_present",
    "contact_confidence_absent",
    "on_air_suitability_signals_present",
    "on_air_suitability_signals_absent",
    "semantic_match_score_present",
    "semantic_match_score_absent",
    "stable_input_order",
)
ENRICHMENT_SCORE_COMPONENTS = (
    {
        "signal": "video_presence",
        "max_points": 51,
        "source": "has_video_presence|video_presence_refs",
    },
    {
        "signal": "email_contact",
        "max_points": 24,
        "source": "has_email_contact|email|email_refs",
    },
    {
        "signal": "contact_confidence",
        "max_points": 10,
        "source": "contact_confidence",
    },
    {
        "signal": "on_air_suitability_signals",
        "max_points": 10,
        "source": "on_air_suitability_signals",
    },
    {
        "signal": "semantic_match_score",
        "max_points": 5,
        "source": "semantic_match_score",
    },
)


@dataclass(frozen=True)
class GuestCandidateRankingMaterialization:
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


def materialize_guest_candidate_ranking(
    *,
    candidate_artifact: dict[str, Any] | None,
    step: WorkflowStepDeclaration | None = None,
    input_artifact_ref: str | None = None,
) -> GuestCandidateRankingMaterialization:
    ranking_policy = _ranking_policy(step)
    safe_ref = _optional_string(input_artifact_ref)

    if not isinstance(candidate_artifact, dict):
        return _closed(
            ranking_policy=ranking_policy,
            input_artifact_ref=safe_ref,
            skipped_reasons=("candidate_artifact_missing",),
        )

    if candidate_artifact.get("artifact_type") != GUEST_CANDIDATE_LIST_ARTIFACT:
        return _closed(
            ranking_policy=ranking_policy,
            input_artifact_ref=safe_ref,
            skipped_reasons=("unexpected_candidate_artifact_type",),
        )

    candidates = candidate_artifact.get("candidates")
    if not isinstance(candidates, list):
        return _closed(
            ranking_policy=ranking_policy,
            input_artifact_ref=safe_ref,
            skipped_reasons=("candidate_list_missing",),
        )

    if safe_ref is None:
        safe_ref = _artifact_ref(candidate_artifact)

    ranked = sorted(
        (
            _candidate_record(candidate=candidate, original_index=index)
            for index, candidate in enumerate(candidates)
            if isinstance(candidate, dict)
        ),
        key=lambda record: (
            -record["enrichment_score"],
            record["original_index"],
        ),
    )
    skipped_reasons = tuple(
        "candidate_not_object"
        for candidate in candidates
        if not isinstance(candidate, dict)
    )

    ranked_candidates = [
        _ranked_candidate(
            record=record,
            rank=index + 1,
            ranking_policy=ranking_policy,
        )
        for index, record in enumerate(ranked)
    ]
    artifact = _artifact(
        ranked_candidates=ranked_candidates,
        ranking_policy=ranking_policy,
        input_artifact_ref=safe_ref,
        skipped_reasons=skipped_reasons,
        ranking_executed=True,
    )
    return GuestCandidateRankingMaterialization(
        artifact=artifact,
        materialized=True,
        transition_outcome="success",
        skipped_reasons=skipped_reasons,
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=True,
            skipped_reasons=skipped_reasons,
        ),
    )


def _candidate_record(
    *,
    candidate: dict[str, Any],
    original_index: int,
) -> dict[str, Any]:
    record = {
        "candidate": dict(candidate),
        "original_index": original_index,
        "has_email_contact": _has_email_contact(candidate),
        "has_video_presence": _has_video_presence(candidate),
        "contact_confidence": _unit_interval(candidate.get("contact_confidence")),
        "on_air_suitability_signal_count": len(
            _string_list(candidate.get("on_air_suitability_signals"))
        ),
        "semantic_match_score": _unit_interval(candidate.get("semantic_match_score")),
    }
    record["score_components"] = _score_components(record)
    record["enrichment_score"] = _score_total(record["score_components"])
    return record


def _ranked_candidate(
    *,
    record: dict[str, Any],
    rank: int,
    ranking_policy: dict[str, Any],
) -> dict[str, Any]:
    candidate = dict(record["candidate"])
    candidate["rank"] = rank
    candidate["original_index"] = record["original_index"]
    candidate["enrichment_score"] = record["enrichment_score"]
    candidate["enrichment_score_components"] = list(record["score_components"])
    candidate["rank_reason_codes"] = _candidate_reason_codes(record)
    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance = dict(provenance)
    provenance["ranking_executed"] = True
    provenance["ranking_policy_id"] = ranking_policy.get("policy_id")
    provenance["scoring_performed"] = True
    provenance["scoring_policy_id"] = ranking_policy.get("policy_id")
    provenance["selection_performed"] = False
    candidate["provenance"] = provenance
    return candidate


def _candidate_reason_codes(record: dict[str, Any]) -> list[str]:
    codes = [
        (
            "video_presence_present"
            if record["has_video_presence"]
            else "video_presence_absent"
        ),
        (
            "email_contact_present"
            if record["has_email_contact"]
            else "email_contact_absent"
        ),
        (
            "contact_confidence_present"
            if record["contact_confidence"] is not None
            else "contact_confidence_absent"
        ),
        (
            "on_air_suitability_signals_present"
            if record["on_air_suitability_signal_count"] > 0
            else "on_air_suitability_signals_absent"
        ),
        (
            "semantic_match_score_present"
            if record["semantic_match_score"] is not None
            else "semantic_match_score_absent"
        ),
        "stable_input_order",
    ]
    return codes


def _score_components(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "signal": "video_presence",
            "points": 51 if record["has_video_presence"] else 0,
            "max_points": 51,
        },
        {
            "signal": "email_contact",
            "points": 24 if record["has_email_contact"] else 0,
            "max_points": 24,
        },
        {
            "signal": "contact_confidence",
            "points": _scaled_points(record["contact_confidence"], max_points=10),
            "max_points": 10,
        },
        {
            "signal": "on_air_suitability_signals",
            "points": min(record["on_air_suitability_signal_count"], 2) * 5,
            "max_points": 10,
        },
        {
            "signal": "semantic_match_score",
            "points": _scaled_points(record["semantic_match_score"], max_points=5),
            "max_points": 5,
        },
    ]


def _score_total(components: list[dict[str, Any]]) -> float:
    total = sum(
        component["points"]
        for component in components
        if isinstance(component.get("points"), (int, float))
    )
    return round(total, 4)


def _scaled_points(value: float | None, *, max_points: int) -> float:
    if value is None:
        return 0
    return round(value * max_points, 4)


def _has_email_contact(candidate: dict[str, Any]) -> bool:
    if candidate.get("has_email_contact") is True:
        return True
    return _has_string(candidate.get("email")) or _has_string_list(
        candidate.get("email_refs")
    )


def _has_video_presence(candidate: dict[str, Any]) -> bool:
    if candidate.get("has_video_presence") is True:
        return True
    return _has_string_list(candidate.get("video_presence_refs"))


def _ranking_policy(step: WorkflowStepDeclaration | None) -> dict[str, Any]:
    declared = {}
    if step is not None:
        value = step.constraints.get("ranking_policy")
        if isinstance(value, dict):
            declared = dict(value)

    return {
        "policy_id": _optional_string(declared.get("policy_id"))
        or DEFAULT_RANKING_POLICY_ID,
        "version": _optional_string(declared.get("version")) or "v1",
        "ordering": [
            {
                "signal": "enrichment_score",
                "highest_first": True,
                "components": list(ENRICHMENT_SCORE_COMPONENTS),
            },
            {
                "signal": "input_order",
                "stable": True,
            },
        ],
        "scoring": {
            "implemented": True,
            "score_field": "enrichment_score",
            "components": list(ENRICHMENT_SCORE_COMPONENTS),
            "max_score": 100,
        },
        "deterministic": True,
        "external_calls_allowed": False,
        "prose_explanations_allowed": False,
    }


def _artifact(
    *,
    ranked_candidates: list[dict[str, Any]],
    ranking_policy: dict[str, Any],
    input_artifact_ref: str | None,
    skipped_reasons: tuple[str, ...],
    ranking_executed: bool,
) -> dict[str, Any]:
    return {
        "artifact_type": RANKED_GUEST_CANDIDATE_LIST_ARTIFACT,
        "candidate_count": len(ranked_candidates),
        "ranked_candidates": ranked_candidates,
        "ranking_policy": ranking_policy,
        "rank_reason_codes": list(DEFAULT_REASON_CODES),
        "ranking_executed": ranking_executed,
        "provenance": {
            "ranking_executed": ranking_executed,
            "ranking_boundary": "runtime.workflows.ranking",
            "input_artifact_type": GUEST_CANDIDATE_LIST_ARTIFACT,
            "input_artifact_ref": input_artifact_ref,
            "deterministic": True,
            "scoring_performed": ranking_executed,
            "scoring_policy_id": (
                ranking_policy.get("policy_id") if ranking_executed else None
            ),
            "selection_performed": False,
            "web_search_executed": False,
            "browser_api_called": False,
            "search_api_called": False,
            "cloud_model_called": False,
            "external_adapter_called": False,
            "draft_generated": False,
            "notification_performed": False,
            "delivery_performed": False,
            "prose_explanation_generated": False,
            "skipped_reasons": list(skipped_reasons),
        },
    }


def _closed(
    *,
    ranking_policy: dict[str, Any],
    input_artifact_ref: str | None,
    skipped_reasons: tuple[str, ...],
) -> GuestCandidateRankingMaterialization:
    artifact = _artifact(
        ranked_candidates=[],
        ranking_policy=ranking_policy,
        input_artifact_ref=input_artifact_ref,
        skipped_reasons=skipped_reasons,
        ranking_executed=False,
    )
    return GuestCandidateRankingMaterialization(
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


def _artifact_ref(artifact: dict[str, Any]) -> str | None:
    explicit = _optional_string(artifact.get("artifact_ref"))
    if explicit is not None:
        return explicit
    workflow_id = _optional_string(artifact.get("workflow_id"))
    step_id = _optional_string(artifact.get("step_id"))
    if workflow_id is None and step_id is None:
        return None
    return "artifact:guest_candidate_list:" + ":".join(
        item for item in (workflow_id, step_id) if item is not None
    )


def _has_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_string_list(value: Any) -> bool:
    return isinstance(value, list) and any(_has_string(item) for item in value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if _has_string(item)]


def _unit_interval(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 1:
        return None
    return float(value)


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
        "materialized": materialized,
        "ranking_executed": artifact.get("ranking_executed") is True,
        "ranking_policy_id": artifact.get("ranking_policy", {}).get("policy_id"),
        "scoring_performed": artifact.get("provenance", {}).get(
            "scoring_performed"
        )
        is True,
        "selection_performed": False,
        "web_search_executed": False,
        "delivery_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "GUEST_CANDIDATE_LIST_ARTIFACT",
    "RANKED_GUEST_CANDIDATE_LIST_ARTIFACT",
    "GuestCandidateRankingMaterialization",
    "materialize_guest_candidate_ranking",
]
