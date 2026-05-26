from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.artifacts.insufficient_coverage import (
    INSUFFICIENT_COVERAGE_RESULT_ARTIFACT,
)
from runtime.ingestion.source_audit import SOURCE_INGESTION_AUDIT_LOG_PATH
from runtime.ingestion.source_item_store import SOURCE_ITEM_STORE_PATH
from runtime.workflows.rss_cache_introspection import (
    build_rss_cache_introspection,
    validate_rss_cache_introspection,
)
from tools.source_ingestion_diagnostics import build_source_ingestion_diagnostics

from .newsroom_rendering import render_rss_cache_introspection_newsroom


RSS_CACHE_INTROSPECTION_WORKFLOW_ID = "alexis_rss_cache_introspection"


@dataclass(frozen=True)
class AlexisRssCacheIntrospectionResult:
    workflow_id: str
    response: str
    artifact: dict[str, Any]

    def to_event_payload(self) -> dict[str, Any]:
        counts = self.artifact.get("source_counts")
        coverage = self.artifact.get("coverage")
        feeds = self.artifact.get("feeds")
        provenance = self.artifact.get("provenance")
        if not isinstance(counts, dict):
            counts = {}
        if not isinstance(coverage, dict):
            coverage = {}
        if not isinstance(feeds, dict):
            feeds = {}
        if not isinstance(provenance, dict):
            provenance = {}
        return {
            "workflow_id": self.workflow_id,
            "provider": "rss_metadata_cache",
            "execution_mode": "cache_only",
            "artifact_type": self.artifact.get("artifact_type"),
            "source_counts": dict(counts),
            "strong_topic_count": len(coverage.get("strong_topics", [])),
            "weak_topic_count": len(coverage.get("weak_topics", [])),
            "missing_topic_count": len(coverage.get("missing_topics", [])),
            "disabled_feed_count": len(feeds.get("disabled", [])),
            "failed_feed_count": len(feeds.get("failed", [])),
            "too_large_feed_count": len(feeds.get("too_large", [])),
            "external_call_performed": False,
            "search_api_executed": False,
            "cloud_call_performed": False,
            "cloud_web_fallback_triggered": False,
            "model_called": False,
            "article_body_fetched": False,
            "delivery_performed": False,
            "memory_write_performed": False,
            "provenance": dict(provenance),
        }


def maybe_run_rss_cache_introspection_workflow(
    *,
    text: str,
    active_artifact: dict[str, Any] | None = None,
    audit_path: str | Path | None = None,
    item_store_path: str | Path | None = None,
) -> AlexisRssCacheIntrospectionResult | None:
    if not is_rss_cache_introspection_request(text):
        return None

    diagnostics = build_source_ingestion_diagnostics(
        agent="alexis",
        audit_path=(
            audit_path
            or os.getenv("JUNIPER_SOURCE_INGESTION_AUDIT_PATH")
            or SOURCE_INGESTION_AUDIT_LOG_PATH
        ),
        item_store_path=(
            item_store_path
            or os.getenv("JUNIPER_SOURCE_ITEM_STORE_PATH")
            or SOURCE_ITEM_STORE_PATH
        ),
    )
    recent_insufficiency = _recent_insufficiency_artifact(active_artifact)
    artifact = build_rss_cache_introspection(
        diagnostics=diagnostics,
        workflow_id=RSS_CACHE_INTROSPECTION_WORKFLOW_ID,
        recent_insufficiency=recent_insufficiency,
        requested_topic=_extract_diagnosis_topic(text),
    )
    if not validate_rss_cache_introspection(artifact):
        return None
    return AlexisRssCacheIntrospectionResult(
        workflow_id=RSS_CACHE_INTROSPECTION_WORKFLOW_ID,
        response=render_rss_cache_introspection_newsroom(artifact),
        artifact=artifact,
    )


def is_rss_cache_introspection_request(text: str) -> bool:
    normalized = _normalize_request(text)
    if not normalized:
        return False
    if "rss" not in normalized and "local cache" not in normalized:
        return normalized.startswith("why didnt ") or normalized.startswith(
            "why didn't "
        )
    return any(
        phrase in normalized
        for phrase in (
            "missing from the local rss cache",
            "missing from local rss cache",
            "coverage is weak in rss",
            "weak in rss",
            "rss cache diagnosis",
            "diagnose rss cache",
            "local rss cache",
        )
    )


def _recent_insufficiency_artifact(
    active_artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(active_artifact, dict):
        return None
    if active_artifact.get("artifact_type") != INSUFFICIENT_COVERAGE_RESULT_ARTIFACT:
        return None
    provenance = active_artifact.get("provenance")
    if isinstance(provenance, dict) and provenance.get("kind") == "rss_metadata":
        return active_artifact
    return None


def _extract_diagnosis_topic(text: str) -> str | None:
    normalized = _normalize_request(text)
    prefixes = (
        "why didnt ",
        "why didn't ",
        "why did not ",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            remainder = normalized[len(prefix):].strip()
            for suffix in (" work", " match", " hit", " show up"):
                if remainder.endswith(suffix):
                    remainder = remainder[: -len(suffix)].strip()
                    break
            if _valid_topic(remainder):
                return remainder
    return None


def _normalize_request(text: str) -> str:
    if not isinstance(text, str):
        return ""
    lowered = text.casefold().replace("’", "'").replace(",", " ")
    return " ".join(
        token.strip("?.!;:'\"")
        for token in lowered.split()
        if token.strip("?.!;:'\"")
    )


def _valid_topic(value: str) -> bool:
    return bool(value) and len(value) <= 80 and len(value.split()) <= 8


__all__ = [
    "AlexisRssCacheIntrospectionResult",
    "RSS_CACHE_INTROSPECTION_WORKFLOW_ID",
    "is_rss_cache_introspection_request",
    "maybe_run_rss_cache_introspection_workflow",
]
