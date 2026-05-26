from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from runtime.ingestion.source_item_store import (
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED,
    INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY,
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE,
    INSUFFICIENCY_REASON_STALE_ITEMS,
    INSUFFICIENCY_REASON_STALE_SOURCES,
    SourceFreshnessEvaluationResult,
)


INSUFFICIENT_COVERAGE_RESULT_ARTIFACT = "insufficient_coverage_result"
ALLOWED_INSUFFICIENCY_REASONS = {
    INSUFFICIENCY_REASON_STALE_SOURCES,
    INSUFFICIENCY_REASON_STALE_ITEMS,
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE,
    INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY,
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED,
}

_REASON_LABELS = {
    INSUFFICIENCY_REASON_STALE_SOURCES: "stale sources",
    INSUFFICIENCY_REASON_STALE_ITEMS: "stale items",
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE: (
        "insufficient topic coverage"
    ),
    INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY: (
        "insufficient source diversity"
    ),
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED: "fetch health failed",
}

_REASON_MESSAGES = {
    INSUFFICIENCY_REASON_STALE_SOURCES: (
        "No usable cached RSS source items are available."
    ),
    INSUFFICIENCY_REASON_STALE_ITEMS: (
        "Cached items are older than the freshness policy allows."
    ),
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE: (
        "Cached RSS metadata does not cover the requested topic."
    ),
    INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY: (
        "Fresh cached items do not span enough distinct sources."
    ),
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED: (
        "Cached source fetches are outside the freshness policy."
    ),
}


def build_insufficient_coverage_result(
    *,
    evaluation: SourceFreshnessEvaluationResult,
    workflow_id: str,
    source_scope: str = "rss_metadata_cache",
    generated_at: datetime | None = None,
) -> dict[str, Any] | None:
    reason = _safe_reason(evaluation.insufficiency_reason)
    if reason is None:
        return None

    retrieval_metadata = evaluation.to_record()
    artifact = {
        "artifact_type": INSUFFICIENT_COVERAGE_RESULT_ARTIFACT,
        "coverage_status": "insufficient",
        "reason": reason,
        "reason_label": _REASON_LABELS[reason],
        "message": _REASON_MESSAGES[reason],
        "workflow_id": _safe_text(workflow_id, limit=120),
        "source_scope": _safe_text(source_scope, limit=120),
        "generated_at": _timestamp(generated_at),
        "evaluated_at": _safe_text(evaluation.evaluated_at, limit=100),
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
        "provenance": {
            "kind": "rss_metadata",
            "execution_mode": "cache_only",
            "cloud_web_fallback_triggered": False,
        },
        "retrieval_metadata": retrieval_metadata,
    }
    return artifact if validate_insufficient_coverage_result(artifact) else None


def validate_insufficient_coverage_result(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != INSUFFICIENT_COVERAGE_RESULT_ARTIFACT:
        return False
    if artifact.get("coverage_status") != "insufficient":
        return False
    if _safe_reason(artifact.get("reason")) is None:
        return False
    for field in (
        "reason_label",
        "message",
        "workflow_id",
        "source_scope",
        "generated_at",
        "evaluated_at",
    ):
        if not _safe_text(artifact.get(field), limit=500):
            return False

    metrics = artifact.get("metrics")
    policy = artifact.get("policy")
    provenance = artifact.get("provenance")
    retrieval_metadata = artifact.get("retrieval_metadata")
    source_refs = artifact.get("source_refs")
    if not isinstance(metrics, Mapping):
        return False
    if not isinstance(policy, Mapping):
        return False
    if not isinstance(provenance, Mapping):
        return False
    if not isinstance(retrieval_metadata, Mapping):
        return False
    if not isinstance(source_refs, list):
        return False
    if provenance.get("kind") != "rss_metadata":
        return False
    if provenance.get("execution_mode") != "cache_only":
        return False
    if provenance.get("cloud_web_fallback_triggered") is not False:
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
    return retrieval_metadata.get("insufficiency_reason") == artifact.get(
        "reason"
    )


def render_insufficient_coverage_result(
    artifact: Mapping[str, Any] | None,
    *,
    title: str = "Latest news coverage:",
) -> str:
    if not isinstance(artifact, Mapping):
        return "Latest news coverage is insufficient."
    reason = _safe_reason(artifact.get("reason"))
    label = _REASON_LABELS.get(reason, "insufficient coverage")
    message = _safe_text(artifact.get("message"), limit=220)
    metrics = artifact.get("metrics")
    topic_focus = artifact.get("topic_entity_focus")
    fallback = artifact.get("fallback_eligibility")
    metric_line = ""
    if isinstance(metrics, Mapping):
        metric_line = (
            f"Candidate items: {metrics.get('candidate_item_count', 0)}; "
            f"topic matches: {metrics.get('topic_matched_item_count', 0)}; "
            f"fresh items: {metrics.get('fresh_item_count', 0)}; "
            f"sources: {metrics.get('source_count', 0)}; "
            f"stale items: {metrics.get('stale_item_count', 0)}."
        )
    topic_line = _topic_focus_line(topic_focus)
    fallback_line = _fallback_line(fallback)
    lines = [f"{title} insufficient - {label}."]
    if message:
        lines.append(message)
    if topic_line:
        lines.append(topic_line)
    if metric_line:
        lines.append(metric_line)
    if fallback_line:
        lines.append(fallback_line)
    else:
        lines.append("Cloud fallback was not run.")
        lines.append(
            "I can check broader web sources if a governed fallback is enabled."
        )
    return "\n".join(lines)


def _topic_focus_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    topics = value.get("topics")
    entities = value.get("entities")
    terms = []
    for collection in (topics, entities):
        if not isinstance(collection, (list, tuple)):
            continue
        for item in collection:
            text = _safe_text(item, limit=80)
            if text and text not in terms:
                terms.append(text)
    if not terms:
        return ""
    return f"Topic focus: {', '.join(terms[:5])}."


def _fallback_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    provider_type = _safe_text(value.get("fallback_provider_type"), limit=80)
    provider_id = _safe_text(value.get("fallback_provider_id"), limit=120)
    live_allowed = value.get("live_allowed")
    dry_run = value.get("dry_run")
    if not provider_type and not provider_id:
        return ""
    label = provider_id or provider_type
    live_text = "enabled" if live_allowed is True else "not enabled"
    dry_run_text = "true" if dry_run is True else "false"
    return (
        f"Fallback prepared: {provider_type or 'provider'}={label}; "
        f"live fallback {live_text}; dry_run={dry_run_text}. "
        "I can check broader web sources if enabled."
    )


def _safe_reason(value: Any) -> str | None:
    if isinstance(value, str) and value in ALLOWED_INSUFFICIENCY_REASONS:
        return value
    return None


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
    "ALLOWED_INSUFFICIENCY_REASONS",
    "INSUFFICIENT_COVERAGE_RESULT_ARTIFACT",
    "build_insufficient_coverage_result",
    "render_insufficient_coverage_result",
    "validate_insufficient_coverage_result",
]
