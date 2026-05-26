from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime.ingestion.source_item_store import SourceFreshnessEvaluationResult
from runtime.policies.rss_cloud_fallback_eligibility import (
    evaluate_rss_cloud_fallback_eligibility,
    validate_rss_cloud_fallback_eligibility,
)
from runtime.policies.rss_external_live_retrieval import (
    evaluate_rss_external_live_retrieval_governance,
    validate_rss_external_live_retrieval_governance,
)
from runtime.workflows.rss_external_search_handoff import (
    build_rss_external_search_handoff,
    validate_rss_external_search_handoff,
)


RSS_COVERAGE_ADEQUACY_ARTIFACT = "rss_coverage_adequacy"
RSS_ADEQUACY_ARTIFACT = RSS_COVERAGE_ADEQUACY_ARTIFACT
OUTCOME_ADEQUATE = "adequate"
OUTCOME_INADEQUATE = "inadequate"
OUTCOME_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RssCoverageAdequacyMaterialization:
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


def materialize_rss_coverage_adequacy(
    *,
    evaluation: SourceFreshnessEvaluationResult | None,
    workflow_id: str,
    source_scope: str = "rss_metadata_cache",
    generated_at: datetime | None = None,
) -> RssCoverageAdequacyMaterialization:
    if evaluation is None:
        return _unknown(
            workflow_id=workflow_id,
            source_scope=source_scope,
            generated_at=generated_at,
            skipped_reasons=("freshness_evaluation_missing",),
        )

    adequate = evaluation.adequate
    outcome = OUTCOME_ADEQUATE if adequate else OUTCOME_INADEQUATE
    artifact = _artifact(
        adequate=adequate,
        outcome=outcome,
        evaluation=evaluation,
        workflow_id=workflow_id,
        source_scope=source_scope,
        generated_at=generated_at,
        skipped_reasons=(),
    )
    return RssCoverageAdequacyMaterialization(
        artifact=artifact,
        materialized=True,
        transition_outcome="success" if adequate else "inadequate",
        skipped_reasons=(),
        audit_summary=_audit_summary(
            artifact=artifact,
            materialized=True,
            skipped_reasons=(),
        ),
    )


def materialize_rss_adequacy(
    *,
    evaluation: SourceFreshnessEvaluationResult | None,
    workflow_id: str,
    source_scope: str = "rss_metadata_cache",
    generated_at: datetime | None = None,
) -> RssCoverageAdequacyMaterialization:
    return materialize_rss_coverage_adequacy(
        evaluation=evaluation,
        workflow_id=workflow_id,
        source_scope=source_scope,
        generated_at=generated_at,
    )


def validate_rss_coverage_adequacy(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != RSS_COVERAGE_ADEQUACY_ARTIFACT:
        return False
    if artifact.get("result_type") != RSS_COVERAGE_ADEQUACY_ARTIFACT:
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
    for field in ("workflow_id", "source_scope", "generated_at"):
        if not _safe_text(artifact.get(field), limit=500):
            return False

    metrics = artifact.get("metrics")
    policy = artifact.get("policy")
    provenance = artifact.get("provenance")
    source_refs = artifact.get("source_refs")
    if not isinstance(metrics, Mapping):
        return False
    if not isinstance(policy, Mapping):
        return False
    if not isinstance(provenance, Mapping):
        return False
    if not isinstance(source_refs, list):
        return False
    if provenance.get("kind") != "rss_metadata":
        return False
    if provenance.get("execution_mode") != "cache_only":
        return False
    if provenance.get("web_search_executed") is not False:
        return False
    if provenance.get("cloud_web_fallback_triggered") is not False:
        return False
    if provenance.get("delivery_performed") is not False:
        return False
    if not validate_rss_cloud_fallback_eligibility(
        artifact.get("fallback_eligibility")
    ):
        return False
    if not validate_rss_external_live_retrieval_governance(
        artifact.get("external_live_retrieval_governance")
    ):
        return False
    if not validate_rss_external_search_handoff(
        artifact.get("external_search_handoff")
    ):
        return False
    for key in (
        "fresh_item_count",
        "candidate_item_count",
        "topic_matched_item_count",
        "source_count",
        "invalid_item_count",
        "stale_item_count",
    ):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    return True


def _unknown(
    *,
    workflow_id: str,
    source_scope: str,
    generated_at: datetime | None,
    skipped_reasons: tuple[str, ...],
) -> RssCoverageAdequacyMaterialization:
    artifact = {
        "artifact_type": RSS_COVERAGE_ADEQUACY_ARTIFACT,
        "result_type": RSS_COVERAGE_ADEQUACY_ARTIFACT,
        "adequate": None,
        "outcome": OUTCOME_UNKNOWN,
        "workflow_id": _safe_text(workflow_id, limit=120),
        "source_scope": _safe_text(source_scope, limit=120),
        "generated_at": _timestamp(generated_at),
        "evaluated_at": None,
        "insufficiency_reason": None,
        "metrics": _empty_metrics(),
        "policy": {},
        "topic_entity_focus": None,
        "source_refs": [],
        "provenance": _provenance(skipped_reasons=skipped_reasons),
    }
    artifact["fallback_eligibility"] = evaluate_rss_cloud_fallback_eligibility(
        artifact
    )
    artifact["external_live_retrieval_governance"] = (
        evaluate_rss_external_live_retrieval_governance(
            adequacy_artifact=artifact,
            fallback_eligibility=artifact["fallback_eligibility"],
        )
    )
    artifact["external_search_handoff"] = build_rss_external_search_handoff(
        adequacy_artifact=artifact
    )
    return RssCoverageAdequacyMaterialization(
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
    adequate: bool,
    outcome: str,
    evaluation: SourceFreshnessEvaluationResult,
    workflow_id: str,
    source_scope: str,
    generated_at: datetime | None,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    retrieval_metadata = evaluation.to_record()
    artifact = {
        "artifact_type": RSS_COVERAGE_ADEQUACY_ARTIFACT,
        "result_type": RSS_COVERAGE_ADEQUACY_ARTIFACT,
        "adequate": adequate,
        "outcome": outcome,
        "workflow_id": _safe_text(workflow_id, limit=120),
        "source_scope": _safe_text(source_scope, limit=120),
        "generated_at": _timestamp(generated_at),
        "evaluated_at": _safe_text(evaluation.evaluated_at, limit=100),
        "insufficiency_reason": evaluation.insufficiency_reason,
        "metrics": {
            "fresh_item_count": len(evaluation.fresh_items),
            "candidate_item_count": evaluation.candidate_item_count,
            "topic_matched_item_count": evaluation.topic_matched_item_count,
            "source_count": len(
                {item.source_id for item in evaluation.fresh_items}
            ),
            "invalid_item_count": evaluation.invalid_item_count,
            "stale_item_count": evaluation.stale_item_count,
        },
        "policy": evaluation.policy.to_record(),
        "topic_entity_focus": retrieval_metadata.get("topic_entity_focus"),
        "source_refs": list(evaluation.source_refs),
        "provenance": _provenance(skipped_reasons=skipped_reasons),
        "retrieval_metadata": retrieval_metadata,
    }
    artifact["fallback_eligibility"] = evaluate_rss_cloud_fallback_eligibility(
        artifact
    )
    artifact["external_live_retrieval_governance"] = (
        evaluate_rss_external_live_retrieval_governance(
            adequacy_artifact=artifact,
            fallback_eligibility=artifact["fallback_eligibility"],
        )
    )
    artifact["external_search_handoff"] = build_rss_external_search_handoff(
        adequacy_artifact=artifact
    )
    return artifact


def _provenance(*, skipped_reasons: tuple[str, ...]) -> dict[str, Any]:
    return {
        "kind": "rss_metadata",
        "assessment_materialized": True,
        "assessment_rule": "source freshness evaluation result",
        "execution_mode": "cache_only",
        "web_search_executed": False,
        "cloud_web_fallback_triggered": False,
        "delivery_performed": False,
        "draft_generated": False,
        "fallback_eligibility_evaluated": True,
        "skipped_reasons": list(skipped_reasons),
    }


def _empty_metrics() -> dict[str, int]:
    return {
        "fresh_item_count": 0,
        "candidate_item_count": 0,
        "topic_matched_item_count": 0,
        "source_count": 0,
        "invalid_item_count": 0,
        "stale_item_count": 0,
    }


def _audit_summary(
    *,
    artifact: Mapping[str, Any],
    materialized: bool,
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    metrics = artifact.get("metrics")
    fallback_eligibility = artifact.get("fallback_eligibility")
    live_governance = artifact.get("external_live_retrieval_governance")
    external_search_handoff = artifact.get("external_search_handoff")
    return {
        "artifact_type": artifact.get("artifact_type"),
        "outcome": artifact.get("outcome"),
        "adequate": artifact.get("adequate"),
        "workflow_id": artifact.get("workflow_id"),
        "source_scope": artifact.get("source_scope"),
        "insufficiency_reason": artifact.get("insufficiency_reason"),
        "metrics": dict(metrics) if isinstance(metrics, Mapping) else {},
        "materialized": materialized,
        "skipped_reasons": list(skipped_reasons),
        "fallback_eligible": (
            fallback_eligibility.get("eligible")
            if isinstance(fallback_eligibility, Mapping)
            else None
        ),
        "fallback_eligibility_reason": (
            fallback_eligibility.get("eligibility_reason")
            if isinstance(fallback_eligibility, Mapping)
            else None
        ),
        "fallback_execution_status": (
            fallback_eligibility.get("execution_status")
            if isinstance(fallback_eligibility, Mapping)
            else None
        ),
        "fallback_provider_id": (
            fallback_eligibility.get("fallback_provider_id")
            if isinstance(fallback_eligibility, Mapping)
            else None
        ),
        "fallback_provider_type": (
            fallback_eligibility.get("fallback_provider_type")
            if isinstance(fallback_eligibility, Mapping)
            else None
        ),
        "external_live_retrieval_status": (
            live_governance.get("status")
            if isinstance(live_governance, Mapping)
            else None
        ),
        "external_live_retrieval_allowed": (
            live_governance.get("live_allowed")
            if isinstance(live_governance, Mapping)
            else None
        ),
        "external_search_handoff_status": (
            external_search_handoff.get("status")
            if isinstance(external_search_handoff, Mapping)
            else None
        ),
        "external_search_handoff_eligible": (
            external_search_handoff.get("handoff_eligible")
            if isinstance(external_search_handoff, Mapping)
            else None
        ),
        "external_search_handoff_reason_codes": (
            list(external_search_handoff.get("reason_codes", []))
            if isinstance(external_search_handoff, Mapping)
            else []
        ),
    }


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


__all__ = [
    "OUTCOME_ADEQUATE",
    "OUTCOME_INADEQUATE",
    "OUTCOME_UNKNOWN",
    "RSS_ADEQUACY_ARTIFACT",
    "RSS_COVERAGE_ADEQUACY_ARTIFACT",
    "RssCoverageAdequacyMaterialization",
    "materialize_rss_adequacy",
    "materialize_rss_coverage_adequacy",
    "validate_rss_coverage_adequacy",
]
