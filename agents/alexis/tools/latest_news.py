from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.ingestion.source_item_store import (
    SOURCE_ITEM_STORE_PATH,
    SourceItem,
    latest_source_items,
)


def latest_news_records_for_alexis(
    items: tuple[SourceItem, ...],
    *,
    include_links: bool = True,
) -> list[dict[str, Any]]:
    formatted = []
    for item in items:
        record = {
            "headline": item.title,
            "source_id": item.source_id,
            "published": item.published,
            "provenance": item.provenance.get("kind", "rss_metadata"),
        }
        if include_links:
            record["link"] = item.link
        formatted.append(record)
    return formatted


def latest_news_items_for_alexis(
    *,
    store_path: str | Path = SOURCE_ITEM_STORE_PATH,
    max_items: int = 5,
    source_id: str | None = None,
    include_links: bool = True,
) -> list[dict[str, Any]]:
    items = latest_source_items(
        store_path=store_path,
        max_items=max_items,
        owning_agent="alexis",
        source_id=source_id,
    )
    return latest_news_records_for_alexis(items, include_links=include_links)


def format_latest_news_records_for_alexis(
    items: list[dict[str, Any]],
    *,
    include_links: bool = True,
    empty_message: str = "Latest news: no source metadata items available.",
) -> str:
    if not items:
        return empty_message

    lines = ["Latest news:"]
    for item in items:
        line = (
            f"- {item['headline']} "
            f"(source {item['source_id']}; {item['published']})"
        )
        if include_links and item.get("link"):
            line = f"{line} {item['link']}"
        lines.append(line)
    return "\n".join(lines)


def format_latest_news_for_alexis(
    *,
    store_path: str | Path = SOURCE_ITEM_STORE_PATH,
    max_items: int = 5,
    source_id: str | None = None,
    include_links: bool = True,
    empty_message: str = "Latest news: no source metadata items available.",
) -> str:
    items = latest_news_items_for_alexis(
        store_path=store_path,
        max_items=max_items,
        source_id=source_id,
        include_links=include_links,
    )
    return format_latest_news_records_for_alexis(
        items,
        include_links=include_links,
        empty_message=empty_message,
    )


__all__ = [
    "format_latest_news_records_for_alexis",
    "format_latest_news_for_alexis",
    "latest_news_items_for_alexis",
    "latest_news_records_for_alexis",
]
