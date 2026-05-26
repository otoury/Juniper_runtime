from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from runtime.artifacts.insufficient_coverage import (
    build_insufficient_coverage_result,
)
from runtime.artifacts.summary import build_summary_artifact
from runtime.execution_classes import (
    EXECUTION_CLASS_LOCAL_CACHE_READ,
    EXECUTION_CLASS_LOCAL_CACHE_SYNTHESIS,
    evaluate_execution_class_dry_run,
)
from runtime.ingestion.source_item_store import (
    FRESHNESS_STATUS_ADEQUATE,
    FRESHNESS_STATUS_FETCH_HEALTH_FAILED,
    FRESHNESS_STATUS_STALE,
    SOURCE_ITEM_STORE_PATH,
    SourceFreshnessEvaluationResult,
    SourceFreshnessPolicy,
    evaluate_latest_source_item_freshness,
)
from runtime.workflows.rss_adequacy import materialize_rss_coverage_adequacy
from runtime.workflows.rss_cloud_escalation import (
    materialize_rss_cloud_escalation,
)
from agents.alexis.workflows.latest_news_retrieval_diagnostics import (
    build_latest_news_retrieval_diagnostics,
)
from ..topic_normalization import (
    apply_topic_normalization_metadata,
    normalize_alexis_rss_topic_focus,
    retrieval_metadata_with_topic_normalization,
)
from .rss_corpus_synthesis import (
    render_rss_corpus_briefing,
    synthesize_rss_corpus_briefing,
)
from .newsroom_rendering import (
    render_rss_insufficient_coverage_newsroom,
    render_rss_stale_cache_newsroom,
    render_rss_summary_newsroom,
)
from .latest_news_tavily_fallback import run_latest_news_tavily_fallback_pilot


LATEST_NEWS_WORKFLOW_ID = "alexis_latest_news"
EMPTY_CACHE_RESPONSE = (
    "No cached news items available. Run the RSS ingestion workflow first."
)
DEFAULT_MAX_ITEMS = 5
DEFAULT_FRESHNESS_POLICY = SourceFreshnessPolicy(
    max_item_age=timedelta(days=3),
    max_fetch_age=timedelta(days=3),
    minimum_fresh_items=1,
    minimum_source_count=1,
)


@dataclass(frozen=True)
class AlexisLatestNewsWorkflowResult:
    workflow_id: str
    response: str
    artifact: dict[str, Any] | None
    cache_path: str
    max_items: int
    item_count: int
    cache_hit: bool
    freshness_status: str
    source_refs: tuple[dict[str, str], ...]
    retrieval_metadata: dict[str, Any]
    adequacy_artifact: dict[str, Any]
    cache_authorization: dict[str, Any]
    cloud_escalation_artifact: dict[str, Any] | None = None
    tavily_fallback_pilot: dict[str, Any] | None = None

    def to_event_payload(self) -> dict[str, Any]:
        fallback_pilot = (
            self.tavily_fallback_pilot
            if isinstance(self.tavily_fallback_pilot, dict)
            else {}
        )
        fallback_diagnostics = (
            fallback_pilot.get("diagnostics")
            if isinstance(fallback_pilot.get("diagnostics"), dict)
            else {}
        )
        fallback_receipt = (
            fallback_pilot.get("execution_receipt")
            if isinstance(fallback_pilot.get("execution_receipt"), dict)
            else None
        )
        diagnostics = build_latest_news_retrieval_diagnostics(
            adequacy_artifact=self.adequacy_artifact,
            result_artifact=self.artifact,
            execution_receipt_refs=(
                [fallback_receipt["receipt_ref"]]
                if fallback_receipt is not None
                and isinstance(fallback_receipt.get("receipt_ref"), str)
                else None
            ),
        )
        if fallback_diagnostics:
            diagnostics["tavily_fallback_pilot"] = dict(fallback_diagnostics)
        return {
            "workflow_id": self.workflow_id,
            "provider": "rss_metadata_cache",
            "cache_path": self.cache_path,
            "max_items": self.max_items,
            "item_count": self.item_count,
            "cache_hit": self.cache_hit,
            "execution_mode": "cache_only",
            "dry_run": self.cache_authorization.get("dry_run"),
            "execution_class": self.cache_authorization.get("execution_class"),
            "dry_run_effect": self.cache_authorization.get("dry_run_effect"),
            "execution_class_allowed": self.cache_authorization.get(
                "execution_class_allowed"
            ),
            "execution_class_reason": self.cache_authorization.get(
                "execution_class_reason"
            ),
            "cloud_dry_run": self.cache_authorization.get("cloud_dry_run"),
            "workflow_dry_run": self.cache_authorization.get("workflow_dry_run"),
            "authorization": self.cache_authorization.get("authorization"),
            "authorization_status": self.cache_authorization.get("authorization"),
            "dry_run_forced_by": self.cache_authorization.get("dry_run_forced_by"),
            "external_call_performed": False,
            "cost_incurred": False,
            "freshness_status": self.freshness_status,
            "source_refs": list(self.source_refs),
            "retrieval_metadata": dict(self.retrieval_metadata),
            "topic_entity_focus": self.retrieval_metadata.get(
                "topic_entity_focus"
            ),
            "candidate_count": self.retrieval_metadata.get(
                "candidate_item_count"
            ),
            "matched_count": self.retrieval_metadata.get(
                "topic_matched_item_count"
            ),
            "source_count": self._source_count(),
            "adequacy_artifact_type": self.adequacy_artifact.get("artifact_type"),
            "adequacy_outcome": self.adequacy_artifact.get("outcome"),
            "adequacy": dict(self.adequacy_artifact),
            "fallback_eligibility": dict(
                self.adequacy_artifact.get("fallback_eligibility", {})
            ),
            "external_live_retrieval_governance": dict(
                self.adequacy_artifact.get(
                    "external_live_retrieval_governance",
                    {},
                )
            ),
            "external_search_handoff": dict(
                self.adequacy_artifact.get("external_search_handoff", {})
            ),
            "artifact_type": (
                self.artifact.get("artifact_type")
                if isinstance(self.artifact, dict)
                else None
            ),
            "insufficiency_reason": (
                self.artifact.get("reason")
                if isinstance(self.artifact, dict)
                else None
            ),
            "fallback_provider_type": self._fallback_value(
                "fallback_provider_type"
            ),
            "fallback_provider_id": self._fallback_value("fallback_provider_id"),
            "fallback_live_allowed": self._fallback_value("live_allowed"),
            "fallback_dry_run": self._fallback_value("dry_run"),
            "cloud_web_fallback_triggered": False,
            "fallback_execution_status": (
                self.adequacy_artifact.get("fallback_eligibility", {}).get(
                    "execution_status"
                )
                if isinstance(
                    self.adequacy_artifact.get("fallback_eligibility"),
                    dict,
                )
                else None
            ),
            "external_live_retrieval_status": (
                self.adequacy_artifact.get(
                    "external_live_retrieval_governance",
                    {},
                ).get("status")
                if isinstance(
                    self.adequacy_artifact.get(
                        "external_live_retrieval_governance"
                    ),
                    dict,
                )
                else None
            ),
            "external_live_retrieval_allowed": (
                self.adequacy_artifact.get(
                    "external_live_retrieval_governance",
                    {},
                ).get("live_allowed")
                if isinstance(
                    self.adequacy_artifact.get(
                        "external_live_retrieval_governance"
                    ),
                    dict,
                )
                else False
            ),
            "external_search_handoff_status": (
                self.adequacy_artifact.get("external_search_handoff", {}).get(
                    "status"
                )
                if isinstance(
                    self.adequacy_artifact.get("external_search_handoff"),
                    dict,
                )
                else None
            ),
            "external_search_handoff_eligible": (
                self.adequacy_artifact.get("external_search_handoff", {}).get(
                    "handoff_eligible"
                )
                if isinstance(
                    self.adequacy_artifact.get("external_search_handoff"),
                    dict,
                )
                else False
            ),
            "external_search_handoff_reason_codes": (
                list(
                    self.adequacy_artifact.get("external_search_handoff", {}).get(
                        "reason_codes",
                        [],
                    )
                )
                if isinstance(
                    self.adequacy_artifact.get("external_search_handoff"),
                    dict,
                )
                else []
            ),
            "cloud_escalation": (
                dict(self.cloud_escalation_artifact)
                if isinstance(self.cloud_escalation_artifact, dict)
                else None
            ),
            "cloud_escalation_status": (
                self.cloud_escalation_artifact.get("status")
                if isinstance(self.cloud_escalation_artifact, dict)
                else None
            ),
            "cloud_escalation_execution_allowed": (
                self.cloud_escalation_artifact.get("execution_allowed")
                if isinstance(self.cloud_escalation_artifact, dict)
                else False
            ),
            "tavily_fallback_pilot": (
                dict(self.tavily_fallback_pilot)
                if isinstance(self.tavily_fallback_pilot, dict)
                else None
            ),
            "retrieval_diagnostics": diagnostics,
        }

    def _source_count(self) -> int:
        metrics = (
            self.artifact.get("metrics")
            if isinstance(self.artifact, dict)
            else None
        )
        if isinstance(metrics, dict) and isinstance(metrics.get("source_count"), int):
            return metrics["source_count"]
        source_ids = {
            item.get("source_id")
            for item in self.retrieval_metadata.get("fresh_items", [])
            if isinstance(item, dict) and isinstance(item.get("source_id"), str)
        }
        return len(source_ids)

    def _fallback_value(self, key: str) -> Any:
        fallback = self.adequacy_artifact.get("fallback_eligibility")
        if isinstance(fallback, dict):
            return fallback.get(key)
        return None


def maybe_run_latest_news_workflow(
    *,
    text: str,
    store_path: str | Path | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    include_links: bool = True,
    freshness_policy: SourceFreshnessPolicy | dict[str, Any] = DEFAULT_FRESHNESS_POLICY,
    now: datetime | None = None,
    topic_entity_focus: dict[str, Any] | None = None,
    workflow_dry_run: bool = False,
    tavily_fallback_operator_live: bool = False,
    tavily_fallback_provider: Any = None,
    tavily_fallback_root: str | Path | None = None,
    tavily_fallback_environ: dict[str, str] | None = None,
) -> AlexisLatestNewsWorkflowResult | None:
    if not is_latest_news_request(text):
        return None

    resolved_store_path = Path(
        store_path
        or os.getenv("JUNIPER_SOURCE_ITEM_STORE_PATH")
        or SOURCE_ITEM_STORE_PATH
    )
    request_topic = extract_latest_news_topic_focus(text)
    effective_topic_entity_focus = (
        topic_entity_focus
        or ({"topics": [request_topic], "entities": []} if request_topic else None)
    )
    topic_normalization = normalize_alexis_rss_topic_focus(
        effective_topic_entity_focus
    )
    evaluation = evaluate_latest_source_item_freshness(
        store_path=resolved_store_path,
        policy=freshness_policy,
        max_items=max_items,
        owning_agent="alexis",
        now=now,
        topic_entity_focus=topic_normalization.matching_focus,
    )
    cache_hit = evaluation.status == FRESHNESS_STATUS_ADEQUATE
    adequacy = materialize_rss_coverage_adequacy(
        evaluation=evaluation,
        workflow_id=LATEST_NEWS_WORKFLOW_ID,
    )
    apply_topic_normalization_metadata(adequacy.artifact, topic_normalization)
    artifact = None
    if cache_hit:
        source_items = tuple(item.to_record() for item in evaluation.fresh_items)
        artifact = synthesize_rss_corpus_briefing(
            source_items=evaluation.fresh_items,
            summary_kind="latest_news_briefing",
            generated_at=_latest_generated_at(evaluation),
            max_clusters=max_items,
            topic_focus=topic_normalization.matching_focus,
        ) or build_summary_artifact(
            source_items=source_items,
            summary_kind="latest_news_briefing",
            tone="newsroom",
            provenance="rss_metadata",
            max_items=max_items,
            summary_text_builder=_latest_news_summary_text,
        )
        if artifact is not None:
            artifact["cache_authorization"] = _local_cache_authorization(
                cache_hit=True,
                workflow_dry_run=workflow_dry_run,
            )
            apply_topic_normalization_metadata(artifact, topic_normalization)
        response = (
            render_rss_corpus_briefing(artifact, title="Latest news briefing:")
            if isinstance(artifact, dict)
            and artifact.get("synthesis_kind") == "rss_corpus_synthesis"
            else render_rss_summary_newsroom(
                artifact,
                title="Latest news briefing:",
                empty_message=EMPTY_CACHE_RESPONSE,
            )
        )
    else:
        artifact = build_insufficient_coverage_result(
            evaluation=evaluation,
            workflow_id=LATEST_NEWS_WORKFLOW_ID,
        )
        tavily_fallback_pilot = (
            run_latest_news_tavily_fallback_pilot(
                adequacy_artifact=adequacy.artifact,
                operator_live_fallback=tavily_fallback_operator_live,
                provider=tavily_fallback_provider,
                root=tavily_fallback_root,
                environ=tavily_fallback_environ,
            )
            if tavily_fallback_operator_live
            else None
        )
        if artifact is not None:
            artifact["fallback_eligibility"] = dict(
                adequacy.artifact.get("fallback_eligibility", {})
            )
            artifact["external_live_retrieval_governance"] = dict(
                adequacy.artifact.get("external_live_retrieval_governance", {})
            )
            artifact["external_search_handoff"] = dict(
                adequacy.artifact.get("external_search_handoff", {})
            )
            if tavily_fallback_pilot is not None:
                artifact["tavily_fallback_pilot"] = {
                    "diagnostics": dict(tavily_fallback_pilot["diagnostics"]),
                    "result_artifact_ref": (
                        tavily_fallback_pilot.get("result_artifact", {}) or {}
                    ).get("search_id"),
                    "execution_receipt_ref": (
                        tavily_fallback_pilot.get("execution_receipt", {}) or {}
                    ).get("receipt_ref"),
                }
            apply_topic_normalization_metadata(artifact, topic_normalization)
        cloud_escalation = materialize_rss_cloud_escalation(
            adequacy_artifact=adequacy.artifact,
            workflow_id=LATEST_NEWS_WORKFLOW_ID,
            request_query=text,
            agent_id="alexis",
            channel="runtime",
            request_source="runtime",
            cloud_dry_run=True,
        ).artifact
        response = (
            render_rss_stale_cache_newsroom(artifact)
            if _is_readable_stale_cache(evaluation)
            else render_rss_insufficient_coverage_newsroom(artifact)
        )
    if cache_hit:
        cloud_escalation = None
        tavily_fallback_pilot = None
    return AlexisLatestNewsWorkflowResult(
        workflow_id=LATEST_NEWS_WORKFLOW_ID,
        response=response,
        artifact=artifact,
        cache_path=str(resolved_store_path),
        max_items=max_items,
        item_count=len(evaluation.fresh_items) if cache_hit else 0,
        cache_hit=cache_hit,
        freshness_status=evaluation.status,
        source_refs=evaluation.source_refs,
        retrieval_metadata=retrieval_metadata_with_topic_normalization(
            evaluation.to_record(),
            topic_normalization,
        ),
        adequacy_artifact=adequacy.artifact,
        cache_authorization=_local_cache_authorization(
            cache_hit=cache_hit,
            workflow_dry_run=workflow_dry_run,
        ),
        cloud_escalation_artifact=cloud_escalation,
        tavily_fallback_pilot=tavily_fallback_pilot,
    )


def _latest_news_summary_text(item: dict[str, str]) -> str:
    return f"Cached RSS metadata headline: {item.get('title', '')}"


def _is_readable_stale_cache(
    evaluation: SourceFreshnessEvaluationResult,
) -> bool:
    return (
        evaluation.status in {
            FRESHNESS_STATUS_STALE,
            FRESHNESS_STATUS_FETCH_HEALTH_FAILED,
        }
        and evaluation.candidate_item_count > 0
        and evaluation.stale_item_count > 0
        and bool(evaluation.source_refs)
    )


def _coerce_datetime(value: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_generated_at(
    evaluation: SourceFreshnessEvaluationResult,
) -> datetime | None:
    candidates = [
        _coerce_datetime(item.published) or _coerce_datetime(item.fetched_at)
        for item in evaluation.fresh_items
    ]
    parsed = [item for item in candidates if item is not None]
    if not parsed:
        return _coerce_datetime(evaluation.evaluated_at)
    return max(parsed)


def _local_cache_authorization(
    *,
    cache_hit: bool,
    workflow_dry_run: bool = False,
) -> dict[str, Any]:
    cloud_dry_run = _global_dry_run_forced()
    explicit_workflow_dry_run = bool(workflow_dry_run)
    forced_dry_run = cloud_dry_run or explicit_workflow_dry_run
    execution_class = (
        EXECUTION_CLASS_LOCAL_CACHE_SYNTHESIS
        if cache_hit
        else EXECUTION_CLASS_LOCAL_CACHE_READ
    )
    dry_run_decision = evaluate_execution_class_dry_run(
        execution_class,
        dry_run=forced_dry_run,
    )
    if cache_hit and dry_run_decision.allowed:
        status = "local_cache_authorized"
    else:
        status = "insufficient_coverage"
    dry_run = False if dry_run_decision.allowed else forced_dry_run

    return {
        "provider": "rss_metadata_cache",
        "dry_run": dry_run,
        "execution_class": dry_run_decision.execution_class,
        "dry_run_effect": dry_run_decision.dry_run_effect,
        "execution_class_allowed": dry_run_decision.allowed,
        "execution_class_reason": dry_run_decision.reason,
        "cloud_dry_run": cloud_dry_run,
        "workflow_dry_run": explicit_workflow_dry_run,
        "authorization": status,
        "authorization_status": status,
        "dry_run_forced_by": _dry_run_forced_by(
            cloud_dry_run=cloud_dry_run,
            workflow_dry_run=explicit_workflow_dry_run,
        ),
        "external_call_performed": False,
        "cost_incurred": False,
        "authorization_basis": (
            "fresh_local_cache_metadata"
            if status == "local_cache_authorized"
            else status
        ),
    }


def _dry_run_forced_by(*, cloud_dry_run: bool, workflow_dry_run: bool) -> list[str]:
    reasons: list[str] = []
    if cloud_dry_run:
        reasons.append("cloud_dry_run")
    if workflow_dry_run:
        reasons.append("workflow_dry_run")
    return reasons


def _global_dry_run_forced() -> bool:
    return os.getenv("CLOUD_DRY_RUN", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_latest_news_request(text: str) -> bool:
    normalized = _normalize_request(text)
    if not normalized:
        return False
    if normalized in {
        "alexis latest news",
        "alexis what are the latest news",
        "alexis what's the latest news",
        "alexis whats the latest news",
        "latest news",
        "what are the latest news",
        "what is the latest news",
        "what's the latest news",
        "whats the latest news",
        "show latest news",
        "show me latest news",
    }:
        return True
    return extract_latest_news_topic_focus(text) is not None


def extract_latest_news_topic_focus(text: str) -> str | None:
    normalized = _normalize_request(text)
    if not normalized:
        return None

    prefixes = (
        "alexis what is the latest news on ",
        "alexis what's the latest news on ",
        "alexis whats the latest news on ",
        "what is the latest news on ",
        "what's the latest news on ",
        "whats the latest news on ",
        "alexis what is the latest on ",
        "alexis what's the latest on ",
        "alexis whats the latest on ",
        "what is the latest on ",
        "what's the latest on ",
        "whats the latest on ",
        "alexis what is latest on ",
        "alexis what's latest on ",
        "alexis whats latest on ",
        "what is latest on ",
        "what's latest on ",
        "whats latest on ",
        "alexis what are the latest news on ",
        "what are the latest news on ",
        "alexis latest news on ",
        "latest news on ",
        "alexis latest on ",
        "latest on ",
        "give me the latest on ",
        "alexis give me the latest on ",
        "show me latest news on ",
        "show latest news on ",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            topic = normalized[len(prefix) :].strip()
            if _valid_topic_focus(topic):
                return topic
    return None


def _normalize_request(text: str) -> str:
    if not isinstance(text, str):
        return ""
    lowered = (
        text.lower()
        .replace(",", " ")
        .replace("’", "'")
        .replace("`", "'")
    )
    return " ".join(
        token.strip("?.!;:'\"")
        for token in lowered.split()
        if token.strip("?.!;:'\"")
    )


def _valid_topic_focus(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    if len(value.split()) > 8:
        return False
    return value not in {"it", "that", "this", "these", "those"}


__all__ = [
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_FRESHNESS_POLICY",
    "EMPTY_CACHE_RESPONSE",
    "LATEST_NEWS_WORKFLOW_ID",
    "AlexisLatestNewsWorkflowResult",
    "extract_latest_news_topic_focus",
    "is_latest_news_request",
    "maybe_run_latest_news_workflow",
]
