from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from runtime.registries.summary_contracts import (
    SummaryContract,
    get_summary_contract,
)


SummaryTextBuilder = Callable[[dict[str, Any]], str]


def build_summary_artifact(
    *,
    source_items: tuple[dict[str, str], ...],
    summary_kind: str,
    tone: str,
    provenance: str,
    generated_at: datetime | None = None,
    max_words: int | None = None,
    max_items: int | None = None,
    contract: SummaryContract | None = None,
    summary_text_builder: SummaryTextBuilder | None = None,
) -> dict[str, Any] | None:
    summary_contract = contract or get_summary_contract()
    if summary_contract is None:
        return None
    if not _safe_text(summary_kind, limit=100):
        return None
    if not _safe_text(tone, limit=100):
        return None
    if not _safe_text(provenance, limit=100):
        return None

    bounded_items = _bounded_item_count(max_items, contract_max=summary_contract.max_items)
    artifact_provenance = _safe_text(provenance, limit=100)
    records = tuple(
        _source_item_record(item, artifact_provenance=artifact_provenance)
        for item in source_items[:bounded_items]
    )
    records = tuple(item for item in records if item is not None)
    if not records:
        return None
    source_refs = tuple(
        _source_ref_record(item, index=index)
        for index, item in enumerate(records, start=1)
    )
    citations = tuple(
        _citation_record(item, index=index)
        for index, item in enumerate(
            records[: summary_contract.max_summary_blocks],
            start=1,
        )
    )

    effective_max_words = (
        max_words
        if isinstance(max_words, int) and not isinstance(max_words, bool) and max_words > 0
        else summary_contract.max_words
    )
    artifact = {
        "artifact_type": summary_contract.artifact_type,
        "summary_kind": _safe_text(summary_kind, limit=100),
        "tone": _safe_text(tone, limit=100),
        "max_words": effective_max_words,
        "max_items": bounded_items,
        "generated_at": _timestamp(generated_at),
        "source_items": list(records),
        "source_refs": list(source_refs),
        "citations": list(citations),
        "summary_blocks": [
            _summary_block(
                item,
                citation=citations[index],
                max_chars=summary_contract.max_summary_chars_per_block,
                summary_text_builder=summary_text_builder,
            )
            for index, item in enumerate(records[: summary_contract.max_summary_blocks])
        ],
        "provenance": artifact_provenance,
        "source_provenance": _source_provenance(records),
        "source_types": _source_types(records),
    }
    return artifact if validate_summary_artifact(artifact, summary_contract) else None


def validate_summary_artifact(
    artifact: dict[str, Any],
    contract: SummaryContract | None = None,
) -> bool:
    summary_contract = contract or get_summary_contract()
    if summary_contract is None:
        return False
    if not isinstance(artifact, dict):
        return False
    if artifact.get("artifact_type") != summary_contract.artifact_type:
        return False
    for field in ("summary_kind", "tone", "generated_at", "provenance"):
        if not isinstance(artifact.get(field), str) or not artifact[field].strip():
            return False
    if not (
        artifact.get("max_words") is None
        or (
            isinstance(artifact.get("max_words"), int)
            and not isinstance(artifact.get("max_words"), bool)
            and artifact["max_words"] > 0
        )
    ):
        return False
    if not isinstance(artifact.get("max_items"), int):
        return False
    if artifact["max_items"] > summary_contract.max_items:
        return False

    source_items = artifact.get("source_items")
    source_refs = artifact.get("source_refs")
    citations = artifact.get("citations")
    blocks = artifact.get("summary_blocks")
    if not isinstance(source_items, list) or not source_items:
        return False
    if not isinstance(source_refs, list) or not source_refs:
        return False
    if not isinstance(citations, list) or not citations:
        return False
    if not isinstance(blocks, list) or not blocks:
        return False
    if len(source_items) > summary_contract.max_items:
        return False
    if len(blocks) > summary_contract.max_summary_blocks:
        return False

    item_ids = {
        item.get("item_id")
        for item in source_items
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    if len(item_ids) != len(source_items):
        return False
    source_ref_ids = {
        source.get("source_ref_id")
        for source in source_refs
        if isinstance(source, dict) and isinstance(source.get("source_ref_id"), str)
    }
    citation_ids = {
        citation.get("citation_id")
        for citation in citations
        if isinstance(citation, dict) and isinstance(citation.get("citation_id"), str)
    }
    if len(source_ref_ids) != len(source_refs):
        return False
    if len(citation_ids) != len(citations):
        return False

    for item in source_items:
        if not _valid_source_item_record(item, summary_contract):
            return False
        if item.get("source_ref_id") not in source_ref_ids:
            return False

    for source in source_refs:
        if not _valid_source_ref(source, item_ids, artifact):
            return False

    for citation in citations:
        if not _valid_citation(citation, item_ids, source_ref_ids, artifact):
            return False

    for block in blocks:
        if not _valid_summary_block(
            block,
            item_ids,
            source_ref_ids,
            citation_ids,
            artifact,
            summary_contract,
        ):
            return False
    return True


def render_summary_artifact(
    artifact: dict[str, Any] | None,
    *,
    title: str = "Summary:",
    empty_message: str = "No source items available to summarize.",
) -> str:
    if artifact is None:
        return empty_message
    blocks = artifact.get("summary_blocks")
    if not isinstance(blocks, list) or not blocks:
        return empty_message

    source_labels = _source_labels(artifact.get("source_refs"))
    lines = [title]
    generated_at = _safe_text(artifact.get("generated_at"), limit=100)
    if generated_at:
        lines.append(f"Updated: {generated_at}")

    for block in blocks[:5]:
        headline = _safe_text(block.get("headline"), limit=500)
        summary = _safe_text(block.get("summary"), limit=300)
        source_id = _safe_text(block.get("source_id"), limit=200)
        source_ref_id = _safe_text(block.get("source_ref_id"), limit=100)
        source_label = source_labels.get(source_ref_id, "")
        published = _safe_text(block.get("published"), limit=200)
        refs = "; ".join(
            part
            for part in (
                source_label or (f"source {source_id}" if source_id else ""),
                published,
            )
            if part
        )
        line = f"- {headline} - {summary}" if summary else f"- {headline}"
        if refs:
            line = f"{line} ({refs})"
        lines.append(line)
    return "\n".join(lines)


def _source_item_record(
    item: dict[str, Any],
    *,
    artifact_provenance: str,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    source_type = _safe_text(item.get("source_type"), limit=100) or "rss_feed"
    provenance_label = _source_provenance_label(
        item.get("provenance"),
        fallback=artifact_provenance,
    )
    item_id = _safe_text(item.get("item_id"), limit=128)
    source_id = _safe_text(
        item.get("source_id")
        or item.get("provider_result_id")
        or item.get("source")
        or item.get("source_name"),
        limit=200,
    )
    title = _safe_text(
        item.get("title")
        or item.get("headline")
        or item.get("raw_title")
        or item.get("name"),
        limit=500,
    )
    link = _safe_text(
        item.get("link")
        or item.get("url")
        or item.get("source_url")
        or item.get("raw_url"),
        limit=1000,
    )
    published = _safe_text(
        item.get("published") or item.get("published_at") or item.get("timestamp"),
        limit=200,
    )
    if not item_id and source_id and title and link:
        item_id = _derived_item_id(
            source_id=source_id,
            title=title,
            link=link,
            published=published,
        )
    record = {
        "item_id": item_id,
        "source_ref_id": _safe_source_ref_id(item),
        "source_id": source_id,
        "source_type": source_type,
        "title": title,
        "link": link,
        "published": published,
        "fetched_at": _safe_text(item.get("fetched_at"), limit=100),
        "provenance": provenance_label,
    }
    snippet = _safe_text(item.get("snippet"), limit=1000)
    if snippet:
        record["snippet"] = snippet
    provider_metadata = _safe_mapping(item.get("provider_metadata"))
    if provider_metadata:
        record["provider_metadata"] = provider_metadata
    source_metadata = _safe_mapping(item.get("source_metadata"))
    if source_metadata:
        record["source_metadata"] = source_metadata
    if not record["source_ref_id"]:
        record["source_ref_id"] = _derived_source_ref_id(
            source_type=source_type,
            source_id=source_id,
            item_id=item_id,
        )
    provenance_details = _safe_mapping(item.get("provenance"))
    if provenance_details:
        record["provenance_details"] = provenance_details
    if not all(
        record[field] for field in ("item_id", "source_ref_id", "source_id", "title")
    ):
        return None
    return record


def _source_ref_record(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_ref_id": item["source_ref_id"],
        "source_label": f"S{index}",
        "source_type": item["source_type"],
        "item_id": item["item_id"],
        "source_id": item["source_id"],
        "title": item["title"],
        "link": item["link"],
        "published": item["published"],
        "fetched_at": item["fetched_at"],
        "provenance": item["provenance"],
    }
    if item.get("snippet"):
        record["snippet"] = item["snippet"]
    if isinstance(item.get("provider_metadata"), dict):
        record["provider_metadata"] = dict(item["provider_metadata"])
    if isinstance(item.get("source_metadata"), dict):
        record["source_metadata"] = dict(item["source_metadata"])
    return record


def _citation_record(item: dict[str, str], *, index: int) -> dict[str, str]:
    return {
        "citation_id": f"citation_{item['source_ref_id']}",
        "source_ref_id": item["source_ref_id"],
        "source_label": f"S{index}",
        "item_id": item["item_id"],
        "source_id": item["source_id"],
        "published": item["published"],
        "provenance": item["provenance"],
        "source_type": item["source_type"],
    }


def _summary_block(
    item: dict[str, str],
    *,
    citation: dict[str, str],
    max_chars: int,
    summary_text_builder: SummaryTextBuilder | None,
) -> dict[str, str]:
    summary = (
        summary_text_builder(item)
        if summary_text_builder is not None
        else f"Cached metadata item: {item['title']}"
    )
    return {
        "item_id": item["item_id"],
        "headline": item["title"],
        "summary": _safe_text(summary, limit=max_chars),
        "source_id": item["source_id"],
        "source_type": item["source_type"],
        "source_ref_id": item["source_ref_id"],
        "source_label": citation["source_label"],
        "citation_id": citation["citation_id"],
        "published": item["published"],
        "provenance": item["provenance"],
    }


def _valid_source_item_record(
    item: Any,
    contract: SummaryContract,
) -> bool:
    if not isinstance(item, dict):
        return False
    for field in contract.required_source_item_fields:
        if not isinstance(item.get(field), str):
            return False
        if field in {
            "item_id",
            "source_ref_id",
            "source_id",
            "title",
            "provenance",
        } and not item[field]:
            return False
    return True


def _valid_source_ref(
    source: Any,
    item_ids: set[str],
    artifact: dict[str, Any],
) -> bool:
    if not isinstance(source, dict):
        return False
    required = (
        "source_ref_id",
        "source_label",
        "source_type",
        "item_id",
        "source_id",
        "title",
        "published",
        "fetched_at",
        "provenance",
    )
    if any(not isinstance(source.get(field), str) for field in required):
        return False
    non_empty = (
        "source_ref_id",
        "source_label",
        "item_id",
        "source_id",
        "title",
        "provenance",
    )
    if any(not source.get(field) for field in non_empty):
        return False
    if source.get("item_id") not in item_ids:
        return False
    return True


def _valid_citation(
    citation: Any,
    item_ids: set[str],
    source_ref_ids: set[str],
    artifact: dict[str, Any],
) -> bool:
    if not isinstance(citation, dict):
        return False
    required = (
        "citation_id",
        "source_ref_id",
        "source_label",
        "item_id",
        "source_id",
        "published",
        "provenance",
    )
    if any(not isinstance(citation.get(field), str) for field in required):
        return False
    non_empty = (
        "citation_id",
        "source_ref_id",
        "source_label",
        "item_id",
        "source_id",
        "provenance",
    )
    if any(not citation.get(field) for field in non_empty):
        return False
    if citation.get("item_id") not in item_ids:
        return False
    if citation.get("source_ref_id") not in source_ref_ids:
        return False
    return True


def _valid_summary_block(
    block: Any,
    item_ids: set[str],
    source_ref_ids: set[str],
    citation_ids: set[str],
    artifact: dict[str, Any],
    contract: SummaryContract,
) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("item_id") not in item_ids:
        return False
    if block.get("source_ref_id") not in source_ref_ids:
        return False
    if block.get("citation_id") not in citation_ids:
        return False
    required = (
        "headline",
        "summary",
        "source_id",
        "source_ref_id",
        "source_label",
        "citation_id",
        "published",
        "provenance",
    )
    if any(not isinstance(block.get(field), str) for field in required):
        return False
    if len(block.get("summary", "")) > contract.max_summary_chars_per_block:
        return False
    return True


def _safe_source_ref_id(item: Mapping[str, Any]) -> str:
    explicit = _safe_text(item.get("source_ref_id"), limit=64)
    if explicit:
        return explicit
    item_id = _safe_text(item.get("item_id"), limit=128)
    source_id = _safe_text(item.get("source_id"), limit=200)
    if not item_id or not source_id:
        return ""
    identity = f"rss_source_item|{source_id}|{item_id}"
    return f"rss_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _derived_item_id(
    *,
    source_id: str,
    title: str,
    link: str,
    published: str,
) -> str:
    identity = "|".join((source_id, link, title, published))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _derived_source_ref_id(
    *,
    source_type: str,
    source_id: str,
    item_id: str,
) -> str:
    if not source_id or not item_id:
        return ""
    identity = f"source_item|{source_type}|{source_id}|{item_id}"
    return f"src_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _source_provenance_label(value: Any, *, fallback: str) -> str:
    if isinstance(value, Mapping):
        return (
            _safe_text(value.get("kind"), limit=100)
            or _safe_text(value.get("provider_id"), limit=100)
            or _safe_text(value.get("provider"), limit=100)
            or fallback
        )
    return _safe_text(value, limit=100) or fallback


def _source_provenance(records: tuple[dict[str, Any], ...]) -> list[str]:
    values = sorted(
        {
            item["provenance"]
            for item in records
            if isinstance(item.get("provenance"), str) and item["provenance"]
        }
    )
    return values


def _source_types(records: tuple[dict[str, Any], ...]) -> list[str]:
    values = sorted(
        {
            item["source_type"]
            for item in records
            if isinstance(item.get("source_type"), str) and item["source_type"]
        }
    )
    return values


def _source_labels(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    labels: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        source_ref_id = _safe_text(item.get("source_ref_id"), limit=100)
        source_label = _safe_text(item.get("source_label"), limit=40)
        if source_ref_id and source_label:
            labels[source_ref_id] = source_label
    return labels


def _bounded_item_count(value: int | None, *, contract_max: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return contract_max
    return min(value, contract_max)


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: _safe_text(item, limit=500)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


__all__ = [
    "build_summary_artifact",
    "render_summary_artifact",
    "validate_summary_artifact",
]
