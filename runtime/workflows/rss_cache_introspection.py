from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


RSS_CACHE_INTROSPECTION_ARTIFACT = "rss_cache_introspection"


def build_rss_cache_introspection(
    *,
    diagnostics: Mapping[str, Any],
    workflow_id: str,
    recent_insufficiency: Mapping[str, Any] | None = None,
    requested_topic: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    declared_feeds = _safe_list(diagnostics.get("declared_feeds"))
    disabled_feeds = [
        _feed_summary(feed)
        for feed in declared_feeds
        if feed.get("governance_state") == "disabled"
    ]
    active_feeds = [
        feed for feed in declared_feeds
        if feed.get("governance_state") in {"enabled", "audit_only"}
    ]
    item_store = _safe_mapping(diagnostics.get("source_item_store"))
    recent_audit = _safe_mapping(diagnostics.get("recent_audit"))
    latest_source_ids = _safe_string_list(item_store.get("latest_source_ids"))
    source_item_counts = _safe_mapping(item_store.get("source_item_counts"))
    latest_source_counts = _source_counts(latest_source_ids, source_item_counts)
    failed_feeds = _audit_status_feeds(
        recent_audit,
        statuses={"failed", "error", "fetch_failed"},
    )
    too_large_feeds = _audit_reason_feeds(
        recent_audit,
        reason_tokens=("too_large", "oversize", "over_limit", "max_size"),
    )
    strong_topics = _topic_coverage(
        active_feeds,
        latest_source_counts,
        minimum_sources=1,
    )
    weak_topics = _weak_topics(
        active_feeds,
        latest_source_counts,
        strong_topics=strong_topics,
    )
    missing_topics = _missing_topics(
        requested_topic=requested_topic,
        recent_insufficiency=recent_insufficiency,
        strong_topics=strong_topics,
        weak_topics=weak_topics,
    )
    source_counts = {
        "declared": _safe_int(diagnostics.get("discovered_source_count")),
        "active": len(active_feeds),
        "disabled": len(disabled_feeds),
        "cached_items": _safe_int(item_store.get("item_count")),
        "latest_items": _safe_int(item_store.get("latest_item_count")),
        "latest_sources": len(latest_source_counts),
        "recent_audit_records": _safe_int(recent_audit.get("record_count")),
        "recent_entries": _safe_int(recent_audit.get("aggregate_entry_count")),
    }
    artifact = {
        "artifact_type": RSS_CACHE_INTROSPECTION_ARTIFACT,
        "workflow_id": _safe_text(workflow_id, limit=120),
        "generated_at": _timestamp(generated_at),
        "diagnostic_type": _safe_text(
            diagnostics.get("diagnostic_type"),
            limit=120,
        ),
        "agent": _safe_text(diagnostics.get("agent"), limit=80),
        "coverage": {
            "strong_topics": strong_topics[:8],
            "weak_topics": weak_topics[:8],
            "missing_topics": missing_topics[:8],
        },
        "feeds": {
            "disabled": disabled_feeds[:10],
            "failed": failed_feeds[:10],
            "too_large": too_large_feeds[:10],
        },
        "source_counts": source_counts,
        "recent_insufficiency": _insufficiency_summary(recent_insufficiency),
        "suggested_next_step": _suggested_next_step(
            missing_topics=missing_topics,
            weak_topics=weak_topics,
            disabled_feeds=disabled_feeds,
            failed_feeds=failed_feeds,
            too_large_feeds=too_large_feeds,
            source_counts=source_counts,
            recent_insufficiency=recent_insufficiency,
        ),
        "provenance": {
            "kind": "rss_cache_diagnostics",
            "execution_mode": "cache_only",
            "diagnostics_source": "source_ingestion_diagnostics",
            "recent_insufficiency_attached": isinstance(
                recent_insufficiency,
                Mapping,
            ),
            "web_search_executed": False,
            "cloud_web_fallback_triggered": False,
            "model_called": False,
            "article_body_fetched": False,
            "delivery_performed": False,
            "memory_write_performed": False,
        },
    }
    return artifact


def validate_rss_cache_introspection(artifact: Mapping[str, Any]) -> bool:
    if not isinstance(artifact, Mapping):
        return False
    if artifact.get("artifact_type") != RSS_CACHE_INTROSPECTION_ARTIFACT:
        return False
    if not _safe_text(artifact.get("workflow_id"), limit=120):
        return False
    coverage = artifact.get("coverage")
    feeds = artifact.get("feeds")
    source_counts = artifact.get("source_counts")
    provenance = artifact.get("provenance")
    if not all(
        isinstance(value, Mapping)
        for value in (coverage, feeds, source_counts, provenance)
    ):
        return False
    for key in ("strong_topics", "weak_topics", "missing_topics"):
        if not isinstance(coverage.get(key), list):
            return False
    for key in ("disabled", "failed", "too_large"):
        if not isinstance(feeds.get(key), list):
            return False
    for key in (
        "declared",
        "active",
        "disabled",
        "cached_items",
        "latest_items",
        "latest_sources",
        "recent_audit_records",
        "recent_entries",
    ):
        value = source_counts.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    return (
        provenance.get("execution_mode") == "cache_only"
        and provenance.get("web_search_executed") is False
        and provenance.get("cloud_web_fallback_triggered") is False
        and provenance.get("model_called") is False
        and provenance.get("article_body_fetched") is False
        and provenance.get("delivery_performed") is False
        and provenance.get("memory_write_performed") is False
    )


def _topic_coverage(
    feeds: list[Mapping[str, Any]],
    latest_source_counts: Mapping[str, int],
    *,
    minimum_sources: int,
) -> list[dict[str, Any]]:
    topic_sources: dict[str, set[str]] = {}
    topic_items: Counter[str] = Counter()
    for feed in feeds:
        source_id = _safe_text(feed.get("source_id"), limit=200)
        if not source_id:
            continue
        item_count = _safe_int(latest_source_counts.get(source_id))
        if item_count <= 0:
            continue
        for topic in _feed_topics(feed):
            topic_sources.setdefault(topic, set()).add(source_id)
            topic_items[topic] += item_count
    rows = [
        {
            "topic": topic,
            "source_count": len(sources),
            "latest_item_count": topic_items[topic],
        }
        for topic, sources in topic_sources.items()
        if len(sources) >= minimum_sources
    ]
    return sorted(
        rows,
        key=lambda row: (
            row["source_count"],
            row["latest_item_count"],
            row["topic"],
        ),
        reverse=True,
    )


def _weak_topics(
    feeds: list[Mapping[str, Any]],
    latest_source_counts: Mapping[str, int],
    *,
    strong_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    strong = {
        _safe_text(row.get("topic"), limit=80)
        for row in strong_topics
        if isinstance(row, Mapping)
    }
    declared_topics: dict[str, set[str]] = {}
    for feed in feeds:
        source_id = _safe_text(feed.get("source_id"), limit=200)
        if not source_id:
            continue
        for topic in _feed_topics(feed):
            declared_topics.setdefault(topic, set()).add(source_id)
    rows = []
    for topic, sources in declared_topics.items():
        if topic in strong:
            continue
        item_count = sum(_safe_int(latest_source_counts.get(source)) for source in sources)
        rows.append(
            {
                "topic": topic,
                "declared_source_count": len(sources),
                "latest_item_count": item_count,
            }
        )
    return sorted(rows, key=lambda row: (row["latest_item_count"], row["topic"]))


def _missing_topics(
    *,
    requested_topic: str | None,
    recent_insufficiency: Mapping[str, Any] | None,
    strong_topics: list[dict[str, Any]],
    weak_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    known = {
        _safe_text(row.get("topic"), limit=80)
        for row in (*strong_topics, *weak_topics)
        if isinstance(row, Mapping)
    }
    topics: list[str] = []
    explicit_topic = _safe_text(requested_topic, limit=80).casefold()
    if explicit_topic:
        topics.append(explicit_topic)
    if isinstance(recent_insufficiency, Mapping):
        focus = recent_insufficiency.get("topic_entity_focus")
        if isinstance(focus, Mapping):
            for key in ("topics", "entities"):
                for term in _safe_string_list(focus.get(key)):
                    topics.append(term.casefold())
    rows = []
    seen: set[str] = set()
    for topic in topics:
        normalized = " ".join(topic.split())
        if not normalized or normalized in seen or normalized in known:
            continue
        seen.add(normalized)
        rows.append({"topic": normalized, "reason": "no_recent_rss_topic_match"})
    return rows


def _suggested_next_step(
    *,
    missing_topics: list[dict[str, Any]],
    weak_topics: list[dict[str, Any]],
    disabled_feeds: list[dict[str, Any]],
    failed_feeds: list[dict[str, Any]],
    too_large_feeds: list[dict[str, Any]],
    source_counts: Mapping[str, int],
    recent_insufficiency: Mapping[str, Any] | None,
) -> str:
    if missing_topics:
        topic = _safe_text(missing_topics[0].get("topic"), limit=80)
        return f"Add or enable a declared RSS source that covers {topic}."
    if weak_topics:
        topic = _safe_text(weak_topics[0].get("topic"), limit=80)
        return f"Refresh or broaden RSS sources for {topic}."
    if failed_feeds:
        return "Check the failed feed declarations and rerun RSS ingestion."
    if too_large_feeds:
        return "Adjust feed size limits or disable the oversized feed."
    if source_counts.get("latest_items", 0) == 0:
        return "Run the RSS ingestion workflow to repopulate the local metadata cache."
    if disabled_feeds:
        return "Review disabled feeds that could improve source diversity."
    if isinstance(recent_insufficiency, Mapping):
        return "Retry the RSS request after the relevant source coverage is refreshed."
    return "No immediate RSS cache repair is indicated by local diagnostics."


def _insufficiency_summary(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    metrics = _safe_mapping(value.get("metrics"))
    return {
        "reason": _safe_text(value.get("reason"), limit=120),
        "reason_label": _safe_text(value.get("reason_label"), limit=120),
        "topic_entity_focus": _safe_focus(value.get("topic_entity_focus")),
        "metrics": {
            "candidate_item_count": _safe_int(metrics.get("candidate_item_count")),
            "topic_matched_item_count": _safe_int(
                metrics.get("topic_matched_item_count")
            ),
            "fresh_item_count": _safe_int(metrics.get("fresh_item_count")),
            "source_count": _safe_int(metrics.get("source_count")),
            "stale_item_count": _safe_int(metrics.get("stale_item_count")),
        },
    }


def _source_counts(
    latest_source_ids: list[str],
    source_item_counts: Mapping[str, Any],
) -> dict[str, int]:
    counts = {
        source_id: _safe_int(count)
        for source_id, count in source_item_counts.items()
        if isinstance(source_id, str)
    }
    if counts:
        return counts
    return dict(Counter(latest_source_ids))


def _audit_status_feeds(
    recent_audit: Mapping[str, Any],
    *,
    statuses: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for record in _safe_list(recent_audit.get("recent_records")):
        status = _safe_text(record.get("fetch_status"), limit=80).casefold()
        if status in statuses:
            rows.append(_audit_feed_summary(record))
    return rows


def _audit_reason_feeds(
    recent_audit: Mapping[str, Any],
    *,
    reason_tokens: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = []
    for record in _safe_list(recent_audit.get("recent_records")):
        reasons = _safe_string_list(record.get("skipped_reasons"))
        if any(
            token in reason.casefold()
            for token in reason_tokens
            for reason in reasons
        ):
            rows.append(_audit_feed_summary(record))
    return rows


def _audit_feed_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": _safe_text(record.get("source_id"), limit=200),
        "fetch_status": _safe_text(record.get("fetch_status"), limit=80),
        "skipped_reasons": _safe_string_list(record.get("skipped_reasons"))[:5],
        "entry_count": _safe_int(record.get("entry_count")),
    }


def _feed_summary(feed: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": _safe_text(feed.get("source_id"), limit=200),
        "category": _safe_text(feed.get("category"), limit=80),
        "topic_tags": _safe_string_list(feed.get("topic_tags"))[:8],
        "governance_state": _safe_text(feed.get("governance_state"), limit=80),
        "readiness_status": _safe_text(feed.get("readiness_status"), limit=120),
    }


def _feed_topics(feed: Mapping[str, Any]) -> tuple[str, ...]:
    topics = []
    category = _safe_text(feed.get("category"), limit=80).casefold()
    if category:
        topics.append(category)
    for tag in _safe_string_list(feed.get("topic_tags")):
        normalized = tag.casefold()
        if normalized and normalized not in topics:
            topics.append(normalized)
    return tuple(topics)


def _safe_focus(value: Any) -> dict[str, list[str]] | None:
    if not isinstance(value, Mapping):
        return None
    focus = {
        "topics": _safe_string_list(value.get("topics"))[:10],
        "entities": _safe_string_list(value.get("entities"))[:10],
    }
    return focus if focus["topics"] or focus["entities"] else None


def _safe_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        " ".join(item.split())[:200]
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


__all__ = [
    "RSS_CACHE_INTROSPECTION_ARTIFACT",
    "build_rss_cache_introspection",
    "validate_rss_cache_introspection",
]
