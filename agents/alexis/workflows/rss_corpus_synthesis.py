from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from runtime.artifacts.summary import build_summary_artifact
from runtime.ingestion.source_item_store import SourceItem
from .rss_citation_attachment import build_rss_story_cluster_citation_attachment
from .newsroom_rendering import (
    RSS_DEFAULT_CLUSTER_LIMIT,
    RSS_DETAIL_MAX_CHARS,
    RSS_HEADLINE_MAX_CHARS,
    RSS_TELEGRAM_SAFE_MAX_CHARS,
    budget_rss_newsroom_lines,
    display_newsroom_timestamp,
    render_rss_summary_newsroom,
    telegram_safe_text,
)


DEFAULT_SOURCE_MANIFEST = Path(__file__).resolve().parents[1] / "source_feeds.json"
RSS_CORPUS_SYNTHESIS_KIND = "rss_corpus_synthesis"
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "latest",
    "news",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "with",
}
SOURCE_PRIORITY = {
    "critical": 50,
    "high": 40,
    "normal": 25,
    "low": 10,
}


@dataclass(frozen=True)
class SourceDeclarationMetadata:
    source_id: str
    category: str
    topic_tags: tuple[str, ...]
    priority_level: str
    source_role: str

    @property
    def priority_score(self) -> int:
        score = SOURCE_PRIORITY.get(self.priority_level, 20)
        if self.source_role == "secondary_analysis":
            score -= 3
        return score


@dataclass(frozen=True)
class SynthesizedCluster:
    cluster_id: str
    representative_item: SourceItem
    contributing_items: tuple[SourceItem, ...]
    source_count: int
    latest_published: str
    source_refs: tuple[dict[str, str], ...]
    topic_hints: tuple[str, ...]
    rank_score: int


def synthesize_rss_corpus_briefing(
    *,
    source_items: tuple[SourceItem, ...],
    summary_kind: str,
    generated_at: datetime | None = None,
    max_clusters: int = 5,
    topic_focus: dict[str, Any] | None = None,
    category_focus: str | None = None,
    source_manifest_path: str | Path = DEFAULT_SOURCE_MANIFEST,
) -> dict[str, Any] | None:
    metadata = load_source_declaration_metadata(source_manifest_path)
    filtered_items = _filter_items(
        source_items,
        metadata=metadata,
        topic_focus=topic_focus,
        category_focus=category_focus,
    )
    clusters = synthesize_rss_story_clusters(
        filtered_items,
        metadata=metadata,
        topic_focus=topic_focus,
        category_focus=category_focus,
        max_clusters=max_clusters,
    )
    if not clusters:
        return None

    representative_records = tuple(
        _representative_record(cluster) for cluster in clusters
    )
    artifact = build_summary_artifact(
        source_items=representative_records,
        summary_kind=summary_kind,
        tone="newsroom",
        provenance="rss_metadata",
        generated_at=generated_at,
        max_items=max_clusters,
        summary_text_builder=_synthesis_summary_text,
    )
    if artifact is None:
        return None

    cluster_records = [_cluster_record(cluster) for cluster in clusters]
    artifact["synthesis_kind"] = RSS_CORPUS_SYNTHESIS_KIND
    artifact["story_clusters"] = cluster_records
    artifact["citation_attachments"] = [
        build_rss_story_cluster_citation_attachment(
            cluster_id=cluster["cluster_id"],
            source_refs=cluster["source_refs"],
            citations=cluster["citations"],
            artifact_type=artifact["artifact_type"],
            synthesis_kind=RSS_CORPUS_SYNTHESIS_KIND,
        )
        for cluster in cluster_records
    ]
    artifact["synthesis_metadata"] = {
        "dedupe_strategy": "canonical_title_domain_path_tokens",
        "cluster_strategy": "deterministic_headline_token_overlap",
        "ranking_signals": [
            "freshness",
            "source_count",
            "source_priority",
            "topic_or_category_relevance",
        ],
        "model_used": False,
        "cloud_call_performed": False,
        "search_api_executed": False,
        "article_body_fetched": False,
        "category_focus": category_focus or "",
        "topic_focus": _focus_terms(topic_focus),
    }
    return artifact


def synthesize_rss_story_clusters(
    source_items: tuple[SourceItem, ...],
    *,
    metadata: dict[str, SourceDeclarationMetadata] | None = None,
    topic_focus: dict[str, Any] | None = None,
    category_focus: str | None = None,
    max_clusters: int = 5,
) -> tuple[SynthesizedCluster, ...]:
    source_metadata = metadata or {}
    deduped_groups = _dedupe_source_item_groups(source_items, source_metadata)
    clusters: list[list[SourceItem]] = []
    cluster_tokens: list[set[str]] = []
    for group in deduped_groups:
        item = _canonical_item(list(group), source_metadata)
        tokens = set(_headline_tokens(item.title))
        if not tokens:
            continue
        target_index = None
        for index, existing_tokens in enumerate(cluster_tokens):
            overlap = tokens & existing_tokens
            union = tokens | existing_tokens
            jaccard = len(overlap) / len(union) if union else 0
            if len(overlap) >= 4 and jaccard >= 0.65:
                target_index = index
                break
        if target_index is None:
            clusters.append(list(group))
            cluster_tokens.append(tokens)
        else:
            clusters[target_index].extend(group)
            cluster_tokens[target_index].update(tokens)

    built = tuple(
        _build_cluster(
            cluster,
            metadata=source_metadata,
            topic_focus=topic_focus,
            category_focus=category_focus,
        )
        for cluster in clusters
        if cluster
    )
    return tuple(
        sorted(
            built,
            key=lambda cluster: (
                cluster.rank_score,
                cluster.latest_published,
                cluster.cluster_id,
            ),
            reverse=True,
        )[: _bounded_max(max_clusters)]
    )


def render_rss_corpus_briefing(
    artifact: dict[str, Any] | None,
    *,
    title: str = "Newsroom briefing:",
    empty_message: str = "No cached RSS items are available to brief.",
    max_chars: int = RSS_TELEGRAM_SAFE_MAX_CHARS,
    max_clusters: int = RSS_DEFAULT_CLUSTER_LIMIT,
) -> str:
    if not isinstance(artifact, dict):
        return empty_message
    clusters = artifact.get("story_clusters")
    if not isinstance(clusters, list) or not clusters:
        return render_rss_summary_newsroom(
            artifact,
            title=title,
            empty_message=empty_message,
            max_chars=max_chars,
            max_blocks=max_clusters,
        )

    freshness = _freshness_from_clusters(clusters) or _safe_text(
        artifact.get("generated_at"),
        limit=100,
    )
    display_title = title if title.endswith(":") else f"{title}:"
    lead = f"<b>{telegram_safe_text(display_title)}</b>\nConcise RSS newsroom brief."
    if freshness:
        lead = (
            f"{lead}\nFresh through "
            f"{telegram_safe_text(display_newsroom_timestamp(freshness))}."
        )
    lines = [lead]

    displayed = 0
    hidden_sources = False
    for cluster in clusters[:_bounded_render_count(max_clusters)]:
        if not isinstance(cluster, dict):
            continue
        headline = _safe_text(
            cluster.get("representative_headline"),
            limit=RSS_HEADLINE_MAX_CHARS,
        )
        if not headline:
            continue
        source_labels = _source_labels(cluster.get("source_refs"))
        hidden_sources = hidden_sources or _has_hidden_sources(
            cluster.get("source_refs"),
            shown_count=len(source_labels),
        )
        latest = _safe_text(cluster.get("latest_published"), limit=100)
        why = (
            ""
            f"{cluster.get('source_count', 1)} source"
            f"{'' if cluster.get('source_count') == 1 else 's'} "
            "in RSS cache."
        )
        if cluster.get("source_count") == 1:
            why = "Fresh RSS item."
        why = _safe_text(why, limit=RSS_DETAIL_MAX_CHARS)
        line = (
            f"- <b>{telegram_safe_text(headline)}</b>\n  "
            f"{telegram_safe_text(why)}"
        )
        if source_labels:
            refs = ", ".join(source_labels)
            if latest:
                refs = f"{refs} - {display_newsroom_timestamp(latest)}"
            line = f"{line}\n  <i>{telegram_safe_text(refs)}</i>"
        lines.append(line)
        displayed += 1
    return budget_rss_newsroom_lines(
        lines,
        max_chars=max_chars,
        append_more_notice=_has_more_clusters(clusters, displayed) or hidden_sources,
    )


def load_source_declaration_metadata(
    manifest_path: str | Path = DEFAULT_SOURCE_MANIFEST,
) -> dict[str, SourceDeclarationMetadata]:
    path = Path(manifest_path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    declarations = raw.get("source_declarations")
    if not isinstance(declarations, list):
        return {}
    metadata: dict[str, SourceDeclarationMetadata] = {}
    for declaration in declarations:
        if not isinstance(declaration, dict):
            continue
        source_id = _safe_text(declaration.get("source_id"), limit=200)
        if not source_id:
            continue
        source_category = declaration.get("source_category")
        priority_policy = declaration.get("priority_policy")
        category = ""
        tags: tuple[str, ...] = ()
        if isinstance(source_category, dict):
            category = _safe_text(source_category.get("category"), limit=100)
            raw_tags = source_category.get("topic_tags")
            if isinstance(raw_tags, list):
                tags = tuple(
                    _safe_text(tag, limit=80)
                    for tag in raw_tags
                    if _safe_text(tag, limit=80)
                )
        priority_level = ""
        source_role = ""
        if isinstance(priority_policy, dict):
            priority_level = _safe_text(priority_policy.get("level"), limit=50)
            source_role = _safe_text(priority_policy.get("source_role"), limit=100)
        metadata[source_id] = SourceDeclarationMetadata(
            source_id=source_id,
            category=category,
            topic_tags=tags,
            priority_level=priority_level,
            source_role=source_role,
        )
    return metadata


def _dedupe_source_item_groups(
    items: tuple[SourceItem, ...],
    metadata: dict[str, SourceDeclarationMetadata],
) -> tuple[tuple[SourceItem, ...], ...]:
    grouped: dict[str, list[SourceItem]] = {}
    for item in items:
        key = _dedupe_key(item)
        grouped.setdefault(key, []).append(item)
    groups = tuple(
        tuple(
            sorted(
                group,
                key=lambda item: (
                    _item_priority(item, metadata),
                    _published_key(item),
                    item.item_id,
                ),
                reverse=True,
            )
        )
        for group in grouped.values()
        if group
    )
    return tuple(
        sorted(
            groups,
            key=lambda group: (
                _published_key(_canonical_item(list(group), metadata)),
                _canonical_item(list(group), metadata).item_id,
            ),
            reverse=True,
        )
    )


def _build_cluster(
    items: list[SourceItem],
    *,
    metadata: dict[str, SourceDeclarationMetadata],
    topic_focus: dict[str, Any] | None,
    category_focus: str | None,
) -> SynthesizedCluster:
    ordered = tuple(
        sorted(
            items,
            key=lambda item: (
                _item_priority(item, metadata),
                _published_key(item),
                item.item_id,
            ),
            reverse=True,
        )
    )
    representative = ordered[0]
    source_refs = tuple(
        _source_ref(item, index=index)
        for index, item in enumerate(ordered, start=1)
    )
    source_count = len({item.source_id for item in ordered})
    latest_published = max((_published_key(item) for item in ordered), default="")
    topic_hints = _cluster_topic_hints(ordered, metadata)
    rank_score = (
        source_count * 100
        + max((_item_priority(item, metadata) for item in ordered), default=0)
        + _relevance_score(
            ordered,
            metadata=metadata,
            topic_focus=topic_focus,
            category_focus=category_focus,
        )
    )
    cluster_id = "rss_cluster_" + hashlib.sha256(
        "|".join(sorted(item.item_id for item in ordered)).encode("utf-8")
    ).hexdigest()[:16]
    return SynthesizedCluster(
        cluster_id=cluster_id,
        representative_item=representative,
        contributing_items=ordered,
        source_count=source_count,
        latest_published=latest_published,
        source_refs=source_refs,
        topic_hints=topic_hints,
        rank_score=rank_score,
    )


def _filter_items(
    items: tuple[SourceItem, ...],
    *,
    metadata: dict[str, SourceDeclarationMetadata],
    topic_focus: dict[str, Any] | None,
    category_focus: str | None,
) -> tuple[SourceItem, ...]:
    if not category_focus and not topic_focus:
        return items
    return tuple(
        item
        for item in items
        if _matches_category(item, metadata, category_focus)
        and _matches_topic_focus(item, topic_focus)
    )


def _matches_category(
    item: SourceItem,
    metadata: dict[str, SourceDeclarationMetadata],
    category_focus: str | None,
) -> bool:
    if not category_focus:
        return True
    focus_tokens = set(_headline_tokens(category_focus))
    source = metadata.get(item.source_id)
    source_terms = set(_headline_tokens(item.source_id))
    if source is not None:
        source_terms.update(_headline_tokens(source.category))
        for tag in source.topic_tags:
            source_terms.update(_headline_tokens(tag))
    title_terms = set(_headline_tokens(item.title))
    return bool(focus_tokens & (source_terms | title_terms))


def _matches_topic_focus(item: SourceItem, topic_focus: dict[str, Any] | None) -> bool:
    terms = set(_focus_terms(topic_focus))
    if not terms:
        return True
    haystack = set(_headline_tokens(" ".join((item.title, item.source_id, item.link))))
    return bool(terms & haystack)


def _relevance_score(
    items: tuple[SourceItem, ...],
    *,
    metadata: dict[str, SourceDeclarationMetadata],
    topic_focus: dict[str, Any] | None,
    category_focus: str | None,
) -> int:
    score = 0
    if category_focus:
        score += sum(
            20
            for item in items
            if _matches_category(item, metadata, category_focus)
        )
    if topic_focus:
        score += sum(20 for item in items if _matches_topic_focus(item, topic_focus))
    return score


def _representative_record(cluster: SynthesizedCluster) -> dict[str, Any]:
    item = cluster.representative_item
    return {
        "item_id": cluster.cluster_id,
        "source_ref_id": item.source_ref_id,
        "source_id": item.source_id,
        "source_type": "rss_feed",
        "title": item.title,
        "link": item.link,
        "published": cluster.latest_published or item.published,
        "fetched_at": item.fetched_at,
        "provenance": item.provenance,
        "source_metadata": {
            "cluster_id": cluster.cluster_id,
            "source_count": str(cluster.source_count),
        },
    }


def _cluster_record(cluster: SynthesizedCluster) -> dict[str, Any]:
    source_refs = list(cluster.source_refs)
    citations = [_cluster_citation(source) for source in source_refs]
    return {
        "cluster_id": cluster.cluster_id,
        "representative_headline": cluster.representative_item.title,
        "representative_item_id": cluster.representative_item.item_id,
        "contributing_items": [
            {
                "item_id": item.item_id,
                "source_ref_id": item.source_ref_id,
                "source_id": item.source_id,
                "title": item.title,
                "link": item.link,
                "published": item.published,
            }
            for item in cluster.contributing_items
        ],
        "source_count": cluster.source_count,
        "latest_published": cluster.latest_published,
        "source_refs": source_refs,
        "citation_ids": [
            citation["citation_id"]
            for citation in citations
            if citation.get("citation_id")
        ],
        "citations": citations,
        "topic_hints": list(cluster.topic_hints),
        "rank_score": cluster.rank_score,
    }


def _synthesis_summary_text(item: dict[str, Any]) -> str:
    return f"Fresh RSS metadata supports this headline: {item.get('title', '')}"


def _canonical_item(
    items: list[SourceItem],
    metadata: dict[str, SourceDeclarationMetadata],
) -> SourceItem:
    return sorted(
        items,
        key=lambda item: (
            _item_priority(item, metadata),
            _published_key(item),
            item.item_id,
        ),
        reverse=True,
    )[0]


def _dedupe_key(item: SourceItem) -> str:
    parsed = urlparse(item.link)
    path = parsed.path.rstrip("/")
    domain_path = f"{parsed.netloc.casefold()}{path.casefold()}"
    title_key = " ".join(_headline_tokens(item.title))
    if title_key:
        return f"title:{title_key}"
    if domain_path:
        return f"url:{domain_path}"
    return f"item:{item.item_id}"


def _cluster_topic_hints(
    items: tuple[SourceItem, ...],
    metadata: dict[str, SourceDeclarationMetadata],
) -> tuple[str, ...]:
    hints: list[str] = []
    seen: set[str] = set()
    for item in items:
        source = metadata.get(item.source_id)
        values = [item.source_id]
        if source is not None:
            values.extend((source.category, *source.topic_tags))
        for value in values:
            normalized = _safe_text(value, limit=100)
            if normalized and normalized not in seen:
                seen.add(normalized)
                hints.append(normalized)
    return tuple(hints[:12])


def _source_ref(item: SourceItem, *, index: int) -> dict[str, str]:
    return {
        "item_id": item.item_id,
        "source_ref_id": item.source_ref_id,
        "source_label": f"S{index}",
        "source_id": item.source_id,
        "source_type": "rss_feed",
        "title": item.title,
        "link": item.link,
        "published": item.published,
        "fetched_at": item.fetched_at,
        "provenance": item.provenance.get("kind", "rss_metadata"),
    }


def _cluster_citation(source_ref: dict[str, str]) -> dict[str, str]:
    return {
        "citation_id": f"citation_{source_ref['source_ref_id']}",
        "source_ref_id": source_ref["source_ref_id"],
        "source_label": source_ref["source_label"],
        "item_id": source_ref["item_id"],
        "source_id": source_ref["source_id"],
        "published": source_ref["published"],
        "provenance": source_ref["provenance"],
        "source_type": source_ref["source_type"],
    }


def _source_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for index, source in enumerate(value, start=1):
        if not isinstance(source, dict):
            continue
        label = _safe_text(source.get("source_label"), limit=40) or f"S{index}"
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels[:5]


def _has_hidden_sources(value: Any, *, shown_count: int) -> bool:
    if not isinstance(value, list):
        return False
    unique = {
        _safe_text(source.get("source_label"), limit=40) or f"S{index}"
        for index, source in enumerate(value, start=1)
        if isinstance(source, dict)
    }
    return len(unique) > shown_count


def _has_more_clusters(clusters: list[Any], displayed: int) -> bool:
    renderable = 0
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        headline = _safe_text(cluster.get("representative_headline"), limit=20)
        if headline:
            renderable += 1
    return renderable > displayed


def _bounded_render_count(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return RSS_DEFAULT_CLUSTER_LIMIT
    return min(max(value, 1), RSS_DEFAULT_CLUSTER_LIMIT)


def _freshness_from_clusters(value: list[Any]) -> str:
    timestamps = [
        _safe_text(cluster.get("latest_published"), limit=100)
        for cluster in value
        if isinstance(cluster, dict)
    ]
    return max((timestamp for timestamp in timestamps if timestamp), default="")


def _item_priority(
    item: SourceItem,
    metadata: dict[str, SourceDeclarationMetadata],
) -> int:
    source = metadata.get(item.source_id)
    return source.priority_score if source is not None else 20


def _published_key(item: SourceItem) -> str:
    return _iso_timestamp(item.published) or _iso_timestamp(item.fetched_at) or ""


def _iso_timestamp(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _focus_terms(value: dict[str, Any] | None) -> list[str]:
    if not isinstance(value, dict):
        return []
    terms: list[str] = []
    for key in ("topics", "entities"):
        raw_terms = value.get(key)
        if not isinstance(raw_terms, (list, tuple)):
            continue
        for term in raw_terms:
            for token in _headline_tokens(term):
                if token not in terms:
                    terms.append(token)
    return terms


def _headline_tokens(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    tokens: list[str] = []
    current: list[str] = []
    for char in value.casefold():
        if char.isalnum():
            current.append(char)
        elif current:
            token = "".join(current)
            if token not in STOPWORDS and (len(token) > 1 or token.isdigit()):
                tokens.append(token)
            current = []
    if current:
        token = "".join(current)
        if token not in STOPWORDS and (len(token) > 1 or token.isdigit()):
            tokens.append(token)
    return tuple(tokens)


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _bounded_max(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return 1
    return min(value, 10)


__all__ = [
    "RSS_CORPUS_SYNTHESIS_KIND",
    "load_source_declaration_metadata",
    "render_rss_corpus_briefing",
    "synthesize_rss_corpus_briefing",
    "synthesize_rss_story_clusters",
]
