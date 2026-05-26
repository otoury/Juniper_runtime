from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from runtime.artifacts.summary import validate_summary_artifact
from semantics.transforms import resolve_transform_type

from .newsroom_rendering import render_rss_summary_newsroom
from .rss_corpus_synthesis import (
    RSS_CORPUS_SYNTHESIS_KIND,
    render_rss_corpus_briefing,
)


RSS_BRIEF_TRANSFORM_WORKFLOW_ID = "alexis_rss_brief_transform"
SUPPORTED_RSS_BRIEF_TRANSFORMS = {
    "punchy",
    "shorten",
    "tighten",
    "top_items",
}


@dataclass(frozen=True)
class AlexisRssBriefTransformResult:
    workflow_id: str
    response: str
    artifact: dict[str, Any] | None
    cache_hit: bool
    transform_type: str | None
    source_refs: tuple[dict[str, str], ...]

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "provider": "session_active_rss_brief",
            "cache_hit": self.cache_hit,
            "execution_mode": "session_artifact_transform",
            "transform_type": self.transform_type,
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
            "source_refs": list(self.source_refs),
            "external_call_performed": False,
            "search_api_executed": False,
            "cloud_call_performed": False,
            "article_body_fetched": False,
            "delivery_performed": False,
            "cost_incurred": False,
        }


def maybe_transform_active_rss_brief(
    *,
    text: str,
    active_artifact: Mapping[str, Any] | None,
) -> AlexisRssBriefTransformResult | None:
    transform_type = resolve_rss_brief_transform_type(text)
    if transform_type is None:
        return None

    if not _is_rss_news_brief_artifact(active_artifact):
        return AlexisRssBriefTransformResult(
            workflow_id=RSS_BRIEF_TRANSFORM_WORKFLOW_ID,
            response=(
                "I need an active RSS news briefing to transform. "
                "Ask for the latest news or name a topic first."
            ),
            artifact=None,
            cache_hit=False,
            transform_type=transform_type,
            source_refs=(),
        )

    transformed = transform_rss_news_brief_artifact(
        active_artifact,
        transform_type=transform_type,
        item_limit=_transform_item_limit(text, transform_type=transform_type),
    )
    response = render_transformed_rss_news_brief(
        transformed,
        transform_type=transform_type,
    )
    return AlexisRssBriefTransformResult(
        workflow_id=RSS_BRIEF_TRANSFORM_WORKFLOW_ID,
        response=response,
        artifact=transformed,
        cache_hit=True,
        transform_type=transform_type,
        source_refs=tuple(
            source
            for source in transformed.get("source_refs", [])
            if isinstance(source, dict)
        ),
    )


def resolve_rss_brief_transform_type(text: str) -> str | None:
    normalized = _normalized_text(text)
    if not normalized:
        return None
    if _extract_top_item_limit(normalized) is not None:
        return "top_items"
    transform_type = resolve_transform_type(normalized)
    if transform_type in {"shorten", "tighten", "punchy"}:
        return transform_type
    return None


def transform_rss_news_brief_artifact(
    artifact: Mapping[str, Any],
    *,
    transform_type: str,
    item_limit: int,
) -> dict[str, Any]:
    transformed = deepcopy(dict(artifact))
    bounded_limit = _bounded_item_limit(item_limit)

    transformed["max_items"] = min(
        _safe_int(transformed.get("max_items"), default=bounded_limit),
        bounded_limit,
    )
    transformed["transform_metadata"] = {
        "workflow_id": RSS_BRIEF_TRANSFORM_WORKFLOW_ID,
        "transform_type": transform_type,
        "preserves_artifact_type": True,
        "source_refs_preserved": True,
        "original_source_refs": deepcopy(transformed.get("source_refs", [])),
        "original_citations": deepcopy(transformed.get("citations", [])),
        "model_used": False,
        "cloud_call_performed": False,
        "search_api_executed": False,
        "article_body_fetched": False,
        "delivery_performed": False,
    }

    _trim_list_field(transformed, "source_items", bounded_limit)
    _trim_list_field(transformed, "summary_blocks", bounded_limit)
    _trim_referenced_sources(transformed)
    if transformed.get("synthesis_kind") == RSS_CORPUS_SYNTHESIS_KIND:
        _trim_list_field(transformed, "story_clusters", bounded_limit)

    if transform_type == "punchy":
        _apply_punchy_summary_blocks(transformed)

    if not validate_summary_artifact(transformed):
        return deepcopy(dict(artifact))
    return transformed


def render_transformed_rss_news_brief(
    artifact: Mapping[str, Any] | None,
    *,
    transform_type: str,
) -> str:
    title = _title_for_transform(transform_type)
    if (
        isinstance(artifact, Mapping)
        and artifact.get("synthesis_kind") == RSS_CORPUS_SYNTHESIS_KIND
    ):
        return render_rss_corpus_briefing(dict(artifact), title=title)
    return render_rss_summary_newsroom(artifact, title=title)


def _is_rss_news_brief_artifact(value: Mapping[str, Any] | None) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("artifact_type") == "summary"
        and value.get("summary_kind") == "latest_news_briefing"
        and value.get("provenance") == "rss_metadata"
    )


def _transform_item_limit(text: str, *, transform_type: str) -> int:
    explicit_limit = _extract_top_item_limit(_normalized_text(text))
    if explicit_limit is not None:
        return explicit_limit
    if transform_type in {"shorten", "tighten", "punchy"}:
        return 3
    return 5


def _extract_top_item_limit(normalized: str) -> int | None:
    tokens = normalized.split()
    for index, token in enumerate(tokens[:-1]):
        if token == "top" and tokens[index + 1].isdigit():
            return _bounded_item_limit(int(tokens[index + 1]))
    return None


def _bounded_item_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 3
    return min(max(value, 1), 5)


def _trim_list_field(artifact: dict[str, Any], field: str, limit: int) -> None:
    value = artifact.get(field)
    if isinstance(value, list):
        artifact[field] = value[:limit]


def _trim_referenced_sources(artifact: dict[str, Any]) -> None:
    item_ids = {
        item.get("item_id")
        for item in artifact.get("source_items", [])
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    source_ref_ids = {
        item.get("source_ref_id")
        for item in artifact.get("source_items", [])
        if isinstance(item, dict) and isinstance(item.get("source_ref_id"), str)
    }
    source_refs = artifact.get("source_refs")
    if isinstance(source_refs, list):
        artifact["source_refs"] = [
            source
            for source in source_refs
            if isinstance(source, dict) and source.get("item_id") in item_ids
        ]
    citations = artifact.get("citations")
    if isinstance(citations, list):
        artifact["citations"] = [
            citation
            for citation in citations
            if isinstance(citation, dict)
            and citation.get("item_id") in item_ids
            and citation.get("source_ref_id") in source_ref_ids
        ]


def _apply_punchy_summary_blocks(artifact: dict[str, Any]) -> None:
    blocks = artifact.get("summary_blocks")
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        headline = _safe_text(
            block.get("headline") or block.get("title"),
            limit=180,
        )
        if headline:
            block["summary"] = f"Watch this: {headline}"


def _title_for_transform(transform_type: str) -> str:
    if transform_type == "top_items":
        return "Top RSS stories:"
    if transform_type == "punchy":
        return "Punchier RSS brief:"
    return "Tighter RSS brief:"


def _normalized_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    lowered = text.lower().replace(",", " ")
    return " ".join(
        token.strip("?.!;:'\"")
        for token in lowered.split()
        if token.strip("?.!;:'\"")
    )


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_int(value: Any, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


__all__ = [
    "AlexisRssBriefTransformResult",
    "RSS_BRIEF_TRANSFORM_WORKFLOW_ID",
    "maybe_transform_active_rss_brief",
    "resolve_rss_brief_transform_type",
    "render_transformed_rss_news_brief",
    "transform_rss_news_brief_artifact",
]
