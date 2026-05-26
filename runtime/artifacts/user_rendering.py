from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from runtime.artifacts.insufficient_coverage import (
    INSUFFICIENT_COVERAGE_RESULT_ARTIFACT,
    render_insufficient_coverage_result,
)


RAW_RENDER_KEYS = {
    "artifact_type",
    "candidate_count",
    "citations",
    "contact_items",
    "external_ids",
    "fetched_at",
    "item_id",
    "max_items",
    "max_words",
    "metrics",
    "mismatch_flags",
    "provider_metadata",
    "provenance",
    "raw_provider_payload",
    "raw_results",
    "source_id",
    "source_items",
    "source_provenance",
    "source_refs",
    "source_types",
    "retrieval_metadata",
    "summary_blocks",
    "summary_kind",
}

MAX_RENDERED_LINES = 14


def render_artifact_for_user(
    *,
    artifact_type: str | None,
    payload: Any,
) -> str | None:
    if not isinstance(payload, Mapping):
        return None

    if artifact_type in {"sourced_contact_result", "contact_discovery_result"}:
        return _render_sourced_contact_result(payload)

    if artifact_type in {"summary", "sourced_summary"}:
        return _render_sourced_summary(payload)

    if artifact_type == "external_discovery_result_set":
        return _render_external_discovery_result_set(payload)

    if artifact_type == INSUFFICIENT_COVERAGE_RESULT_ARTIFACT:
        return render_insufficient_coverage_result(payload)

    return None


def clone_payload(payload: Any) -> Any:
    return deepcopy(payload)


def contains_raw_render_key(text: str) -> bool:
    lowered = text.lower()
    return any(f"{key}:" in lowered or f'"{key}"' in lowered for key in RAW_RENDER_KEYS)


def _render_sourced_contact_result(payload: Mapping[str, Any]) -> str | None:
    lines: list[str] = []

    note = _mismatch_note(payload.get("mismatch_flags"))
    if note:
        lines.append(note)

    contacts = _first_sequence(
        payload,
        ("contacts", "contact_items", "items", "results", "sourced_contacts"),
    )

    if contacts:
        if lines:
            lines.append("")
        lines.append("Sourced booking contacts:")
        source_refs_by_id = _source_refs_by_id(payload.get("source_refs"))
        for item in contacts[:5]:
            lines.extend(_render_contact_item_lines(item, source_refs_by_id))

    if len(lines) == 1 and note:
        lines.append("I could not verify a public booking or press contact from the available sources.")

    if not lines:
        fallback = _safe_text(
            payload.get("assistant_response")
            or payload.get("summary")
            or payload.get("content")
            or payload.get("text"),
            limit=900,
        )
        if fallback:
            return _compact_lines([fallback])
        return None

    return _compact_lines(lines)


def _render_sourced_summary(payload: Mapping[str, Any]) -> str | None:
    blocks = _first_sequence(payload, ("summary_blocks", "blocks", "items", "results"))
    if not blocks:
        return None

    title = "Summary:"
    if payload.get("summary_kind") == "latest_news_briefing":
        title = "Latest news briefing:"

    generated_at = _safe_text(payload.get("generated_at"), limit=80)
    lines = [title]
    if generated_at:
        lines.append(f"Updated: {generated_at}")

    for block in blocks[:5]:
        if not isinstance(block, Mapping):
            continue
        headline = _safe_text(
            block.get("headline") or block.get("title") or block.get("name"),
            limit=180,
        )
        summary = _safe_text(block.get("summary") or block.get("description"), limit=220)
        source = _source_label(block)
        published = _safe_text(block.get("published") or block.get("timestamp"), limit=80)
        if not headline and not summary:
            continue
        line = _headline_summary_line(headline=headline, summary=summary)
        refs = _source_ref_text(source=source, published=published)
        if refs:
            line = f"{line} ({refs})"
        lines.append(f"- {line}")

    return _compact_lines(lines)


def _render_external_discovery_result_set(payload: Mapping[str, Any]) -> str | None:
    results = _first_sequence(payload, ("raw_results", "results", "items"))
    source_refs = _first_sequence(payload, ("source_refs", "citations"))
    citation_by_index = _citation_labels(source_refs)

    lines = ["External discovery results:"]
    if results:
        for index, item in enumerate(results[:5], start=1):
            rendered = _render_discovery_item(item, citation_by_index.get(index))
            if rendered:
                lines.append(f"- {rendered}")

    if len(lines) == 1:
        for source in source_refs[:5]:
            rendered = _render_source_ref(source)
            if rendered:
                lines.append(f"- {rendered}")

    return _compact_lines(lines) if len(lines) > 1 else None


def _mismatch_note(value: Any) -> str:
    flags = _as_sequence(value)
    if not flags:
        return ""

    first = flags[0]
    if isinstance(first, Mapping):
        requested = _safe_text(
            first.get("requested")
            or first.get("requested_state")
            or first.get("requested_office")
            or first.get("claimed_value")
            or first.get("input_value"),
            limit=120,
        )
        actual = _safe_text(
            first.get("actual")
            or first.get("actual_state")
            or first.get("matched_state")
            or first.get("canonical_value")
            or first.get("resolved_value"),
            limit=120,
        )
        entity = _safe_text(
            first.get("entity")
            or first.get("resolved_entity")
            or first.get("canonical_entity")
            or first.get("name"),
            limit=160,
        )
        role = _safe_text(first.get("role") or first.get("title"), limit=120)
        if entity and actual and requested:
            subject = f"{role} {entity}".strip() if role else entity
            return f"Note: I'm reading this as {subject} of {actual}, not {requested}."
        if actual and requested:
            return f"Note: I found a possible mismatch: {actual}, not {requested}."
        message = _safe_text(
            first.get("message") or first.get("note") or first.get("reason"),
            limit=220,
        )
        if message:
            return f"Note: {message}"

    rendered = _humanize_flag(first)
    return f"Note: {rendered}" if rendered else ""


def _render_contact_item_lines(
    item: Any,
    source_refs_by_id: Mapping[str, str],
) -> list[str]:
    if not isinstance(item, Mapping):
        rendered = _safe_text(item, limit=280)
        return [f"- {rendered}"] if rendered else []

    name = _safe_text(item.get("name") or item.get("office") or item.get("label"), limit=120)
    role = _safe_text(item.get("role") or item.get("title") or item.get("type"), limit=120)
    lead = ", ".join(part for part in (name, role) if part)
    contact_parts = _contact_parts(item)
    sources = _contact_sources(item, source_refs_by_id)
    note = _safe_text(
        item.get("note")
        or item.get("notes")
        or item.get("rationale")
        or item.get("verification_note"),
        limit=220,
    )

    if not lead and contact_parts:
        lead = contact_parts[0]
        contact_parts = contact_parts[1:]
    if not lead and sources:
        lead = sources[0]
        sources = sources[1:]
    if not lead:
        return []

    lines = [f"- {lead}"]
    if contact_parts:
        lines.append(f"  Contact: {'; '.join(contact_parts)}")
    if note:
        lines.append(f"  Note: {note}")
    if sources:
        lines.append(f"  Sources: {'; '.join(sources)}")
    return lines


def _contact_parts(item: Mapping[str, Any]) -> list[str]:
    labeled_keys = (
        ("booking_email", "booking email"),
        ("press_email", "press email"),
        ("email", "email"),
        ("phone", "phone"),
        ("booking_url", "booking page"),
        ("press_url", "press page"),
        ("contact_url", "contact page"),
        ("url", "url"),
    )
    parts: list[str] = []
    seen: set[str] = set()
    for key, label in labeled_keys:
        value = _safe_text(item.get(key), limit=200)
        if not value or value in seen:
            continue
        seen.add(value)
        parts.append(f"{label}: {value}")
    return parts


def _contact_sources(
    item: Mapping[str, Any],
    source_refs_by_id: Mapping[str, str],
) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()

    for source_ref_id in _source_ref_ids(item):
        rendered = source_refs_by_id.get(source_ref_id)
        if rendered and rendered not in seen:
            seen.add(rendered)
            sources.append(rendered)

    for embedded_source in _as_sequence(item.get("source_refs")):
        rendered = _render_source_ref(embedded_source)
        if rendered and rendered not in seen:
            seen.add(rendered)
            sources.append(rendered)

    fallback = _source_label(item)
    if fallback and fallback not in seen:
        sources.append(fallback)

    return sources[:3]


def _source_ref_ids(item: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("source_ref_id", "source_id"):
        value = _safe_text(item.get(key), limit=120)
        if value:
            ids.append(value)
    for value in _as_sequence(item.get("source_ref_ids")):
        rendered = _safe_text(value, limit=120)
        if rendered:
            ids.append(rendered)
    return ids


def _render_discovery_item(item: Any, fallback_source: str | None) -> str:
    if not isinstance(item, Mapping):
        rendered = _safe_text(item, limit=260)
        return rendered

    headline = _safe_text(
        item.get("title") or item.get("headline") or item.get("name") or item.get("label"),
        limit=180,
    )
    summary = _safe_text(
        item.get("summary") or item.get("description") or item.get("snippet"),
        limit=220,
    )
    source = _source_label(item) or fallback_source or ""
    line = _headline_summary_line(headline=headline, summary=summary)
    if source:
        line = f"{line} ({source})"
    return line


def _render_source_ref(source: Any) -> str:
    if isinstance(source, Mapping):
        label = _source_label(source)
        title = _safe_text(source.get("title") or source.get("name"), limit=160)
        url = _safe_text(source.get("url") or source.get("link") or source.get("source_url"), limit=220)
        return " - ".join(part for part in (title, label, url) if part)
    return _safe_text(source, limit=220)


def _source_refs_by_id(value: Any) -> dict[str, str]:
    labels: dict[str, str] = {}
    for source in _as_sequence(value):
        if not isinstance(source, Mapping):
            continue
        rendered = _render_source_ref(source)
        if not rendered:
            continue
        for key in ("source_ref_id", "source_id", "id"):
            source_id = _safe_text(source.get(key), limit=120)
            if source_id:
                labels[source_id] = rendered
    return labels


def _citation_labels(source_refs: Sequence[Any]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for index, source in enumerate(source_refs, start=1):
        rendered = _render_source_ref(source)
        if rendered:
            labels[index] = rendered
    return labels


def _source_label(item: Mapping[str, Any]) -> str:
    label = _safe_text(
        item.get("source_label")
        or item.get("source")
        or item.get("source_name")
        or item.get("source_title")
        or item.get("citation")
        or item.get("source_ref"),
        limit=140,
    )
    if label:
        return label
    source_id = _safe_text(item.get("source_id"), limit=120)
    return f"source {source_id}" if source_id else ""


def _source_ref_text(*, source: str, published: str) -> str:
    parts = []
    if source:
        parts.append(source)
    if published:
        parts.append(published)
    return "; ".join(parts)


def _headline_summary_line(*, headline: str, summary: str) -> str:
    if headline and summary:
        return f"{headline} - {summary}"
    return headline or summary


def _first_sequence(payload: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        items = _as_sequence(value)
        if items:
            return items
    return []


def _as_sequence(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if value is None:
        return []
    return [value]


def _humanize_flag(value: Any) -> str:
    text = _safe_text(value, limit=220)
    if not text:
        return ""
    return text.replace("_", " ").strip().capitalize() + "."


def _compact_lines(lines: Sequence[str]) -> str:
    cleaned = [line.rstrip() for line in lines if isinstance(line, str) and line.strip()]
    return "\n".join(cleaned[:MAX_RENDERED_LINES]).strip()


def _safe_text(value: Any, *, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return " ".join(value.split())[:limit]


__all__ = [
    "RAW_RENDER_KEYS",
    "clone_payload",
    "contains_raw_render_key",
    "render_artifact_for_user",
]
