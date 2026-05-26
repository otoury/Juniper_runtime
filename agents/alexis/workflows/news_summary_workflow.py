from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from runtime.artifacts.insufficient_coverage import (
    build_insufficient_coverage_result,
)
from runtime.artifacts.summary import (
    build_summary_artifact,
)
from runtime.ingestion.source_item_store import (
    FRESHNESS_STATUS_ADEQUATE,
    SOURCE_ITEM_STORE_PATH,
    SourceFreshnessPolicy,
    evaluate_latest_source_item_freshness,
)
from runtime.workflows.rss_adequacy import materialize_rss_coverage_adequacy
from runtime.workflows.rss_cloud_escalation import (
    materialize_rss_cloud_escalation,
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
    render_rss_summary_newsroom,
)


NEWS_SUMMARY_WORKFLOW_ID = "alexis_latest_news_briefing"
SUMMARY_KIND = "latest_news_briefing"
SUMMARY_TONE = "newsroom"
SUMMARY_PROVENANCE = "rss_metadata"
DEFAULT_MAX_SUMMARY_ITEMS = 5
NEWS_SUMMARY_EMPTY_CACHE_MESSAGE = (
    "No cached news items available. Run the RSS ingestion workflow first."
)
DEFAULT_FRESHNESS_POLICY = SourceFreshnessPolicy(
    max_item_age=timedelta(days=3),
    max_fetch_age=timedelta(days=3),
    minimum_fresh_items=1,
    minimum_source_count=1,
)


@dataclass(frozen=True)
class AlexisNewsSummaryWorkflowResult:
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

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "provider": "rss_metadata_cache",
            "cache_path": self.cache_path,
            "max_items": self.max_items,
            "item_count": self.item_count,
            "cache_hit": self.cache_hit,
            "dry_run": self.cache_authorization.get("dry_run"),
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
            "artifact_type": (
                self.artifact.get("artifact_type")
                if isinstance(self.artifact, dict)
                else None
            ),
            "summary_kind": (
                self.artifact.get("summary_kind")
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
            "execution_mode": "cache_only",
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


def maybe_run_news_summary_workflow(
    *,
    text: str,
    store_path: str | Path | None = None,
    max_items: int = DEFAULT_MAX_SUMMARY_ITEMS,
    generated_at: datetime | None = None,
    freshness_policy: SourceFreshnessPolicy | dict[str, Any] = DEFAULT_FRESHNESS_POLICY,
    now: datetime | None = None,
    topic_entity_focus: dict[str, Any] | None = None,
    workflow_dry_run: bool = False,
) -> AlexisNewsSummaryWorkflowResult | None:
    if not is_news_summary_request(text):
        return None

    resolved_store_path = Path(
        store_path
        or os.getenv("JUNIPER_SOURCE_ITEM_STORE_PATH")
        or SOURCE_ITEM_STORE_PATH
    )
    category_focus = extract_news_summary_category_focus(text)
    effective_topic_entity_focus = topic_entity_focus or (
        {"topics": [category_focus], "entities": []} if category_focus else None
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
        workflow_id=NEWS_SUMMARY_WORKFLOW_ID,
    )
    apply_topic_normalization_metadata(adequacy.artifact, topic_normalization)
    artifact = None
    if cache_hit:
        source_items = tuple(item.to_record() for item in evaluation.fresh_items)
        artifact = synthesize_rss_corpus_briefing(
            source_items=evaluation.fresh_items,
            summary_kind=SUMMARY_KIND,
            generated_at=generated_at,
            max_clusters=max_items,
            topic_focus=topic_normalization.matching_focus,
            category_focus=category_focus,
        ) or build_summary_artifact(
            source_items=source_items,
            summary_kind=SUMMARY_KIND,
            tone=SUMMARY_TONE,
            provenance=SUMMARY_PROVENANCE,
            generated_at=generated_at,
            max_items=max_items,
            summary_text_builder=_newsroom_summary_text,
        )
        if artifact is not None:
            artifact["cache_authorization"] = _local_cache_authorization(
                cache_hit=True,
                workflow_dry_run=workflow_dry_run,
            )
            apply_topic_normalization_metadata(artifact, topic_normalization)
    if artifact is None and not cache_hit:
        artifact = build_insufficient_coverage_result(
            evaluation=evaluation,
            workflow_id=NEWS_SUMMARY_WORKFLOW_ID,
        )
        if artifact is not None:
            artifact["fallback_eligibility"] = dict(
                adequacy.artifact.get("fallback_eligibility", {})
            )
            artifact["external_live_retrieval_governance"] = dict(
                adequacy.artifact.get("external_live_retrieval_governance", {})
            )
            apply_topic_normalization_metadata(artifact, topic_normalization)
    cloud_escalation = None
    if not cache_hit:
        cloud_escalation = materialize_rss_cloud_escalation(
            adequacy_artifact=adequacy.artifact,
            workflow_id=NEWS_SUMMARY_WORKFLOW_ID,
            request_query=text,
            agent_id="alexis",
            channel="runtime",
            request_source="runtime",
            cloud_dry_run=True,
        ).artifact
    if isinstance(artifact, dict) and artifact.get("artifact_type") == "summary":
        response = (
            render_rss_corpus_briefing(
                artifact,
                title="Latest news briefing:",
                empty_message=NEWS_SUMMARY_EMPTY_CACHE_MESSAGE,
            )
            if artifact.get("synthesis_kind") == "rss_corpus_synthesis"
            else render_rss_summary_newsroom(
                artifact,
                title="Latest news briefing:",
                empty_message=NEWS_SUMMARY_EMPTY_CACHE_MESSAGE,
            )
        )
    else:
        response = render_rss_insufficient_coverage_newsroom(
            artifact,
            title="Latest news briefing coverage:",
        )
    blocks = artifact.get("summary_blocks", []) if isinstance(artifact, dict) else []
    item_count = len(blocks) if isinstance(blocks, list) else 0
    return AlexisNewsSummaryWorkflowResult(
        workflow_id=NEWS_SUMMARY_WORKFLOW_ID,
        response=response,
        artifact=artifact,
        cache_path=str(resolved_store_path),
        max_items=max_items,
        item_count=item_count,
        cache_hit=cache_hit and artifact is not None,
        freshness_status=evaluation.status,
        source_refs=evaluation.source_refs,
        retrieval_metadata=retrieval_metadata_with_topic_normalization(
            evaluation.to_record(),
            topic_normalization,
        ),
        adequacy_artifact=adequacy.artifact,
        cache_authorization=_local_cache_authorization(
            cache_hit=cache_hit and artifact is not None,
            workflow_dry_run=workflow_dry_run,
        ),
        cloud_escalation_artifact=cloud_escalation,
    )


def _newsroom_summary_text(item: dict[str, str]) -> str:
    return f"Cached RSS metadata headline: {item.get('title', '')}"


def _local_cache_authorization(
    *,
    cache_hit: bool,
    workflow_dry_run: bool = False,
) -> dict[str, Any]:
    cloud_dry_run = _global_dry_run_forced()
    explicit_workflow_dry_run = bool(workflow_dry_run)
    forced_dry_run = cloud_dry_run or explicit_workflow_dry_run
    if cache_hit and not forced_dry_run:
        status = "local_cache_authorized"
        dry_run = False
    elif forced_dry_run:
        status = "dry_run_forced"
        dry_run = True
    else:
        status = "insufficient_coverage"
        dry_run = True

    return {
        "provider": "rss_metadata_cache",
        "dry_run": dry_run,
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


def is_news_summary_request(text: str) -> bool:
    normalized = _normalize_request(text)
    if not normalized:
        return False
    if extract_news_summary_category_focus(text):
        return True
    return normalized in {
        "summarize the latest news",
        "alexis summarize the latest news",
        "give me a news briefing",
        "alexis give me a news briefing",
        "news briefing",
        "what topics are trending in the news",
        "what topics are trending",
        "trending news topics",
        "trending topics in the news",
        "what's happening today",
        "whats happening today",
        "alexis what's happening today",
        "alexis whats happening today",
    }


def extract_news_summary_category_focus(text: str) -> str | None:
    normalized = _normalize_request(text)
    if not normalized:
        return None
    prefixes = (
        "brief me on ",
        "alexis brief me on ",
        "give me a briefing on ",
        "alexis give me a briefing on ",
        "news briefing on ",
    )
    allowed_categories = {
        "business": "business",
        "markets": "business",
        "economy": "business",
        "business news": "business",
        "politics": "politics",
        "world": "world",
        "us": "us_news",
        "u s": "us_news",
        "us news": "us_news",
    }
    for prefix in prefixes:
        if normalized.startswith(prefix):
            value = normalized[len(prefix):].strip()
            return allowed_categories.get(value)
    return None


def _normalize_request(text: str) -> str:
    if not isinstance(text, str):
        return ""
    lowered = text.lower().replace(",", " ")
    return " ".join(
        token.strip("?.!;:")
        for token in lowered.split()
        if token.strip("?.!;:")
    )


__all__ = [
    "DEFAULT_MAX_SUMMARY_ITEMS",
    "DEFAULT_FRESHNESS_POLICY",
    "NEWS_SUMMARY_WORKFLOW_ID",
    "NEWS_SUMMARY_EMPTY_CACHE_MESSAGE",
    "AlexisNewsSummaryWorkflowResult",
    "extract_news_summary_category_focus",
    "is_news_summary_request",
    "maybe_run_news_summary_workflow",
]
