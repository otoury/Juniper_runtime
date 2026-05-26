from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from html import escape, unescape
from typing import Any

from runtime.operator_rendering import (
    format_operator_timestamp,
    render_latest_news_operator_status,
)
from runtime.ingestion.source_item_store import (
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED,
    INSUFFICIENCY_REASON_STALE_ITEMS,
)

RSS_TELEGRAM_SAFE_MAX_CHARS = 3200
RSS_DEFAULT_CLUSTER_LIMIT = 5
RSS_HEADLINE_MAX_CHARS = 180
RSS_DETAIL_MAX_CHARS = 220
RSS_MORE_NOTICE = "Ask for more if you want the full source list."
TELEGRAM_HTML_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|s|code|pre|a)(?:\s+[^>]*)?>"
)


def render_rss_summary_newsroom(
    artifact: Mapping[str, Any] | None,
    *,
    title: str = "Latest news briefing:",
    empty_message: str = "No cached RSS items are available to brief.",
    max_chars: int = RSS_TELEGRAM_SAFE_MAX_CHARS,
    max_blocks: int = RSS_DEFAULT_CLUSTER_LIMIT,
) -> str:
    if not isinstance(artifact, Mapping):
        return empty_message
    blocks = artifact.get("summary_blocks")
    if not isinstance(blocks, list) or not blocks:
        return empty_message

    source_labels = _source_labels_by_ref(artifact.get("source_refs"))
    freshness = _freshness_from_blocks(blocks) or _safe_text(
        artifact.get("generated_at"),
        limit=100,
    )
    lines = [_lead_line(title=title, freshness=freshness)]

    displayed = 0
    block_limit = _bounded_count(
        max_blocks,
        fallback=RSS_DEFAULT_CLUSTER_LIMIT,
    )
    for block in blocks[:block_limit]:
        if not isinstance(block, Mapping):
            continue
        headline = _safe_text(
            block.get("headline") or block.get("title"),
            limit=RSS_HEADLINE_MAX_CHARS,
        )
        if not headline:
            continue
        why = _why_from_summary_block(block)
        refs = _summary_block_refs(block, source_labels)
        line = f"- <b>{telegram_safe_text(headline)}</b>"
        if why:
            line = f"{line}\n  {telegram_safe_text(why)}"
        if refs:
            line = f"{line}\n  <i>{telegram_safe_text(refs)}</i>"
        lines.append(line)
        displayed += 1

    if len(lines) <= 1:
        return empty_message
    omitted = _has_more_renderable_blocks(blocks, displayed)
    return budget_rss_newsroom_lines(
        lines,
        max_chars=max_chars,
        append_more_notice=omitted,
    )


def render_rss_insufficient_coverage_newsroom(
    artifact: Mapping[str, Any] | None,
    *,
    title: str = "Latest news coverage:",
    max_chars: int = RSS_TELEGRAM_SAFE_MAX_CHARS,
) -> str:
    if not isinstance(artifact, Mapping):
        return f"{title} not enough fresh RSS coverage."

    label = _safe_text(artifact.get("reason_label"), limit=140) or (
        "insufficient coverage"
    )
    message = _safe_text(artifact.get("message"), limit=140)
    freshness = _safe_text(artifact.get("evaluated_at"), limit=100) or _safe_text(
        artifact.get("generated_at"),
        limit=100,
    )
    metrics = artifact.get("metrics")
    fallback = artifact.get("fallback_eligibility")
    topic_line = _topic_focus_line(artifact.get("topic_entity_focus"))

    lines = [
        _lead_line(
            title=title,
            freshness=freshness,
            suffix=f"not enough fresh RSS coverage - {label}.",
        )
    ]
    if message:
        lines.append(f"- <b>Coverage gap</b>\n  {telegram_safe_text(message)}")
    if topic_line:
        lines.append(f"- <b>Topic focus</b>\n  {telegram_safe_text(topic_line)}")
    metric_line = _metric_line(metrics)
    if metric_line:
        lines.append(f"- <b>RSS cache</b>\n  {telegram_safe_text(metric_line)}")
    fallback_line = _short_fallback_line(fallback)
    lines.append(
        f"- <b>Fallback</b>\n  {telegram_safe_text(fallback_line or 'Not run.')}"
    )
    return budget_rss_newsroom_lines(lines[:5], max_chars=max_chars)


def render_rss_stale_cache_newsroom(
    artifact: Mapping[str, Any] | None,
    *,
    title: str = "Latest news briefing:",
    max_chars: int = RSS_TELEGRAM_SAFE_MAX_CHARS,
) -> str:
    if not isinstance(artifact, Mapping):
        return (
            f"{title} RSS cache is stale. Run RSS ingestion before treating "
            "cached items as latest."
        )

    latest_cached = _latest_source_ref_timestamp(artifact.get("source_refs"))
    freshness = latest_cached or _safe_text(artifact.get("evaluated_at"), limit=100)
    reason = _safe_text(artifact.get("reason_label"), limit=120) or "stale RSS cache"
    message = _safe_text(artifact.get("message"), limit=180)
    metric_line = _metric_line(artifact.get("metrics"))
    fallback_line = _stale_cache_fallback_line(artifact)
    update_line = (
        "Run the RSS ingestion workflow to refresh the cache before treating "
        "this as latest."
    )

    lines = [
        _lead_line(
            title=title,
            freshness=freshness,
            suffix=f"RSS cache stale - {reason}.",
        )
    ]
    if message:
        lines.append(f"- <b>Freshness</b>\n  {telegram_safe_text(message)}")
    if metric_line:
        lines.append(f"- <b>RSS cache</b>\n  {telegram_safe_text(metric_line)}")
    lines.append(f"- <b>Update needed</b>\n  {telegram_safe_text(update_line)}")
    lines.append(f"- <b>Fallback</b>\n  {telegram_safe_text(fallback_line)}")
    return budget_rss_newsroom_lines(lines[:5], max_chars=max_chars)


def render_rss_cache_introspection_newsroom(
    artifact: Mapping[str, Any] | None,
    *,
    title: str = "RSS cache diagnosis:",
) -> str:
    if not isinstance(artifact, Mapping):
        return f"{title} local RSS diagnostics are unavailable."

    coverage = artifact.get("coverage")
    feeds = artifact.get("feeds")
    counts = artifact.get("source_counts")
    insufficiency = artifact.get("recent_insufficiency")
    if not isinstance(coverage, Mapping):
        coverage = {}
    if not isinstance(feeds, Mapping):
        feeds = {}
    if not isinstance(counts, Mapping):
        counts = {}

    lines = [
        _lead_line(
            title=title,
            freshness=_safe_text(artifact.get("generated_at"), limit=100),
            suffix="local RSS metadata only.",
        )
    ]
    source_line = _source_counts_line(counts)
    if source_line:
        lines.append(f"- <b>Source counts</b>\n  {telegram_safe_text(source_line)}")
    strong = _topic_rows(coverage.get("strong_topics"), label="topic")
    if strong:
        lines.append(f"- <b>Strong coverage</b>\n  {telegram_safe_text(strong)}")
    weak = _topic_rows(coverage.get("weak_topics"), label="topic")
    missing = _topic_rows(coverage.get("missing_topics"), label="topic")
    if weak or missing:
        lines.append(
            "- <b>Weak or missing</b>\n  "
            f"{telegram_safe_text(', '.join(part for part in (weak, missing) if part))}"
        )
    disabled = _feed_rows(feeds.get("disabled"))
    if disabled:
        lines.append(f"- <b>Disabled feeds</b>\n  {telegram_safe_text(disabled)}")
    failed = _feed_rows(feeds.get("failed"))
    too_large = _feed_rows(feeds.get("too_large"))
    if failed or too_large:
        lines.append(
            "- <b>Failed or too-large</b>\n  "
            f"{telegram_safe_text(', '.join(part for part in (failed, too_large) if part))}"
        )
    recent_line = _recent_insufficiency_line(insufficiency)
    if recent_line:
        lines.append(
            f"- <b>Recent insufficiency</b>\n  {telegram_safe_text(recent_line)}"
        )
    next_step = _safe_text(artifact.get("suggested_next_step"), limit=220)
    if next_step:
        lines.append(f"- <b>Next step</b>\n  {telegram_safe_text(next_step)}")
    return "\n\n".join(lines[:8])


def _lead_line(*, title: str, freshness: str, suffix: str | None = None) -> str:
    normalized = title.strip() or "Latest news briefing:"
    if not normalized.endswith(":"):
        normalized = f"{normalized}:"
    display_title = telegram_safe_text(normalized)
    if suffix:
        lead = f"<b>{display_title}</b>\n{telegram_safe_text(suffix)}"
    else:
        lead = f"<b>{display_title}</b>\nConcise RSS newsroom brief."
    if freshness:
        operator_lines = render_latest_news_operator_status(freshness=freshness)
        if operator_lines:
            lead = f"{lead}\n{telegram_safe_text(operator_lines[0])}"
    return lead


def _why_from_summary_block(block: Mapping[str, Any]) -> str:
    summary = _safe_text(block.get("summary"), limit=RSS_DETAIL_MAX_CHARS)
    if summary and not summary.lower().startswith("cached rss metadata headline"):
        return summary
    source_metadata = block.get("source_metadata")
    source_count = ""
    if isinstance(source_metadata, Mapping):
        source_count = _safe_text(source_metadata.get("source_count"), limit=20)
    if source_count and source_count != "1":
        return f"{source_count} RSS sources."
    return "Fresh RSS item."


def _summary_block_refs(
    block: Mapping[str, Any],
    source_labels: Mapping[str, str],
) -> str:
    source_ref_id = _safe_text(block.get("source_ref_id"), limit=100)
    label = source_labels.get(source_ref_id) or _safe_text(
        block.get("source_label"),
        limit=40,
    )
    published = display_newsroom_timestamp(
        _safe_text(block.get("published"), limit=100)
    )
    return " - ".join(part for part in (label, published) if part)


def _source_labels_by_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    labels: dict[str, str] = {}
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            continue
        source_ref_id = _safe_text(item.get("source_ref_id"), limit=100)
        label = _safe_text(item.get("source_label"), limit=40) or f"S{index}"
        if source_ref_id:
            labels[source_ref_id] = label
    return labels


def _freshness_from_blocks(blocks: list[Any]) -> str:
    values = [
        _safe_text(block.get("published"), limit=100)
        for block in blocks
        if isinstance(block, Mapping)
    ]
    return max((value for value in values if value), default="")


def _topic_focus_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    terms: list[str] = []
    for key in ("topics", "entities"):
        raw_terms = value.get(key)
        if not isinstance(raw_terms, (list, tuple)):
            continue
        for term in raw_terms:
            text = _safe_text(term, limit=80)
            if text and text not in terms:
                terms.append(text)
    if not terms:
        return ""
    return f"{', '.join(terms[:5])}."


def _metric_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    candidate = value.get("candidate_item_count", 0)
    matched = value.get("topic_matched_item_count", 0)
    fresh = value.get("fresh_item_count", 0)
    sources = value.get("source_count", 0)
    stale = value.get("stale_item_count", 0)
    return (
        f"{fresh} fresh / {candidate} candidate; {matched} topic matches; "
        f"{sources} sources; {stale} stale."
    )


def _source_counts_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    return (
        f"declared {value.get('declared', 0)}, active {value.get('active', 0)}, "
        f"disabled {value.get('disabled', 0)}, cached items {value.get('cached_items', 0)}, "
        f"latest items {value.get('latest_items', 0)}, latest sources {value.get('latest_sources', 0)}."
    )


def _topic_rows(value: Any, *, label: str) -> str:
    if not isinstance(value, list):
        return ""
    rows = []
    for item in value[:5]:
        if not isinstance(item, Mapping):
            continue
        topic = _safe_text(item.get(label), limit=80)
        if not topic:
            continue
        source_count = item.get("source_count") or item.get("declared_source_count")
        latest_count = item.get("latest_item_count")
        if isinstance(source_count, int) and isinstance(latest_count, int):
            rows.append(f"{topic} ({source_count} sources, {latest_count} items)")
        else:
            rows.append(topic)
    return ", ".join(rows)


def _feed_rows(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    rows = []
    for item in value[:5]:
        if not isinstance(item, Mapping):
            continue
        source_id = _safe_text(item.get("source_id"), limit=80)
        if not source_id:
            continue
        status = _safe_text(
            item.get("fetch_status")
            or item.get("governance_state")
            or item.get("readiness_status"),
            limit=80,
        )
        rows.append(f"{source_id}{f' ({status})' if status else ''}")
    return ", ".join(rows)


def _recent_insufficiency_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    label = _safe_text(value.get("reason_label"), limit=100) or _safe_text(
        value.get("reason"),
        limit=100,
    )
    focus = _topic_focus_line(value.get("topic_entity_focus"))
    metrics = value.get("metrics")
    metric_line = _metric_line(metrics)
    parts = [part for part in (label, focus, metric_line) if part]
    return " ".join(parts)


def _fallback_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    provider_type = _safe_text(value.get("fallback_provider_type"), limit=80)
    provider_id = _safe_text(value.get("fallback_provider_id"), limit=120)
    if not provider_type and not provider_id:
        return ""
    label = provider_id or provider_type
    live_allowed = value.get("live_allowed")
    dry_run = value.get("dry_run")
    live_text = "enabled" if live_allowed is True else "not enabled"
    dry_run_text = "true" if dry_run is True else "false"
    return (
        f"Fallback prepared: {provider_type or 'provider'}={label}; "
        f"live fallback {live_text}; dry_run={dry_run_text}. "
        "I can check broader web sources if enabled."
    )


def _short_fallback_line(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    provider_type = _safe_text(value.get("fallback_provider_type"), limit=80)
    provider_id = _safe_text(value.get("fallback_provider_id"), limit=120)
    if not provider_type and not provider_id:
        return ""
    live_allowed = value.get("live_allowed") is True
    dry_run = value.get("dry_run") is True
    label = provider_id or provider_type
    lines = render_latest_news_operator_status(
        freshness=None,
        fallback={
            "fallback_provider_id": label,
            "live_allowed": live_allowed,
            "dry_run": dry_run,
        },
    )
    for line in lines:
        if line.startswith("Fallback: "):
            return line.removeprefix("Fallback: ")
    return (
        f"{label} prepared; live {'enabled' if live_allowed else 'not enabled'}; "
        f"dry_run={'true' if dry_run else 'false'}."
    )


def _stale_cache_fallback_line(artifact: Mapping[str, Any]) -> str:
    tavily = artifact.get("tavily_fallback_pilot")
    diagnostics = tavily.get("diagnostics") if isinstance(tavily, Mapping) else None
    if isinstance(diagnostics, Mapping):
        provider = _safe_text(diagnostics.get("provider_id"), limit=80) or "tavily"
        external_call = diagnostics.get("external_call_performed") is True
        execution = _safe_text(diagnostics.get("execution_state"), limit=80)
        if external_call:
            return f"{provider} fallback ran under explicit operator authorization."
        if diagnostics.get("operator_live_fallback") is True:
            return (
                f"{provider} fallback was explicitly requested but did not run"
                f"{f' ({execution})' if execution else ''}."
            )
    reason = _safe_text(artifact.get("reason"), limit=80)
    if reason in {
        INSUFFICIENCY_REASON_STALE_ITEMS,
        INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED,
    }:
        return "Not run; explicit governed Tavily authorization is required."
    fallback = _short_fallback_line(artifact.get("fallback_eligibility"))
    return fallback or "Not run."


def _latest_source_ref_timestamp(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    published_values = []
    fetched_values = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        published = _safe_text(item.get("published"), limit=100)
        fetched_at = _safe_text(item.get("fetched_at"), limit=100)
        if published:
            published_values.append(published)
        if fetched_at:
            fetched_values.append(fetched_at)
    return max(published_values, default="") or max(fetched_values, default="")


def budget_rss_newsroom_lines(
    lines: list[str],
    *,
    max_chars: int = RSS_TELEGRAM_SAFE_MAX_CHARS,
    append_more_notice: bool = False,
) -> str:
    budget = _bounded_char_budget(max_chars)
    notice = telegram_safe_text(RSS_MORE_NOTICE) if append_more_notice else ""
    notice_cost = len(notice) + (1 if notice else 0)
    selected: list[str] = []
    used = 0
    for line in lines:
        normalized = _safe_render_text(line, limit=budget)
        if not normalized:
            continue
        remaining = budget - used - notice_cost - (1 if selected else 0)
        if remaining <= 0:
            break
        if len(normalized) > remaining:
            normalized = _truncate_render_text(normalized, max_chars=remaining)
        if not normalized:
            break
        next_size = len(normalized) + (2 if selected else 0)
        if selected and used + next_size + notice_cost > budget:
            break
        selected.append(normalized)
        used += next_size
    if notice and notice not in selected:
        if selected:
            selected.append(notice)
        else:
            selected = [notice[:budget]]
    rendered = "\n\n".join(selected)
    if len(rendered) <= budget:
        return rendered
    return _truncate_text(rendered, max_chars=budget)


def _has_more_renderable_blocks(blocks: list[Any], displayed: int) -> bool:
    renderable = 0
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        headline = _safe_text(block.get("headline") or block.get("title"), limit=20)
        if headline:
            renderable += 1
    return renderable > displayed


def _bounded_count(value: int, *, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return min(max(value, 1), RSS_DEFAULT_CLUSTER_LIMIT)


def _bounded_char_budget(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return RSS_TELEGRAM_SAFE_MAX_CHARS
    return min(max(value, 500), RSS_TELEGRAM_SAFE_MAX_CHARS)


def _truncate_text(value: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    if max_chars <= 3:
        return "." * max_chars
    return f"{value[: max_chars - 3].rstrip()}..."


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_render_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    lines = [_normalize_render_line(part) for part in value.splitlines()]
    return "\n".join(part for part in lines if part)[:limit]


def _normalize_render_line(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    indent_width = min(len(value) - len(value.lstrip(" ")), 2)
    return f"{' ' * indent_width}{' '.join(stripped.split())}"


def _truncate_render_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    if TELEGRAM_HTML_TAG_RE.search(value):
        plain = TELEGRAM_HTML_TAG_RE.sub("", value)
        return telegram_safe_text(
            _truncate_text(unescape(plain), max_chars=max_chars)
        )
    return _truncate_text(value, max_chars=max_chars)


def display_newsroom_timestamp(value: str) -> str:
    text = _safe_text(value, limit=100)
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    month = parsed.strftime("%b")
    return f"{month} {parsed.day}, {parsed.year}, {parsed:%H:%M} UTC"


def display_operator_newsroom_timestamp(value: str) -> str:
    return format_operator_timestamp(value)


def telegram_safe_text(value: str) -> str:
    return escape(value, quote=False)


__all__ = [
    "RSS_DEFAULT_CLUSTER_LIMIT",
    "RSS_MORE_NOTICE",
    "RSS_TELEGRAM_SAFE_MAX_CHARS",
    "budget_rss_newsroom_lines",
    "display_newsroom_timestamp",
    "display_operator_newsroom_timestamp",
    "render_rss_cache_introspection_newsroom",
    "render_rss_insufficient_coverage_newsroom",
    "render_rss_stale_cache_newsroom",
    "render_rss_summary_newsroom",
    "telegram_safe_text",
]
