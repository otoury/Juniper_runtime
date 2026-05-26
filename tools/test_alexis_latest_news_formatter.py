import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.tools.latest_news import (  # noqa: E402
    format_latest_news_for_alexis,
    latest_news_items_for_alexis,
)
from runtime.ingestion.source_item_store import (  # noqa: E402
    append_source_items,
    source_item_from_fetch_entry,
)


def seed_items(store_path):
    first = source_item_from_fetch_entry(
        source_id="source_a",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="First headline",
        link="https://example.com/first",
        published="2026-05-18T08:00:00+00:00",
        fetched_at="2026-05-18T08:01:00+00:00",
    )
    second = source_item_from_fetch_entry(
        source_id="source_b",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Second headline",
        link="https://example.com/second",
        published="2026-05-18T09:00:00+00:00",
        fetched_at="2026-05-18T09:01:00+00:00",
    )
    other_agent = source_item_from_fetch_entry(
        source_id="source_c",
        owning_agent="other",
        governance_state="audit_only",
        manifest_path="agents/other/source_feeds.json",
        title="Other headline",
        link="https://example.com/other",
        published="2026-05-18T10:00:00+00:00",
        fetched_at="2026-05-18T10:01:00+00:00",
    )
    append_source_items((first, second, other_agent), store_path=store_path)


def test_latest_news_formatter_returns_bounded_source_grounded_items():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        items = latest_news_items_for_alexis(store_path=store_path, max_items=1)

    assert items == [
        {
            "headline": "Second headline",
            "source_id": "source_b",
            "published": "2026-05-18T09:00:00+00:00",
            "provenance": "rss_metadata",
            "link": "https://example.com/second",
        }
    ]


def test_latest_news_formatter_text_is_deterministic():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        first = format_latest_news_for_alexis(
            store_path=store_path,
            max_items=2,
        )
        second = format_latest_news_for_alexis(
            store_path=store_path,
            max_items=2,
        )

    assert first == second
    assert first.splitlines() == [
        "Latest news:",
        (
            "- Second headline (source source_b; "
            "2026-05-18T09:00:00+00:00) "
            "https://example.com/second"
        ),
        (
            "- First headline (source source_a; "
            "2026-05-18T08:00:00+00:00) "
            "https://example.com/first"
        ),
    ]


def test_latest_news_formatter_can_omit_links():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        items = latest_news_items_for_alexis(
            store_path=store_path,
            max_items=1,
            include_links=False,
        )
        text = format_latest_news_for_alexis(
            store_path=store_path,
            max_items=1,
            include_links=False,
        )

    assert "link" not in items[0]
    assert "https://example.com" not in text


def test_latest_news_formatter_empty_state():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        text = format_latest_news_for_alexis(store_path=store_path)

    assert text == "Latest news: no source metadata items available."


def test_formatter_has_no_summarization_model_memory_or_delivery_behavior():
    source = (ROOT / "agents/alexis/tools/latest_news.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "openai",
        "embedding",
        "summarize",
        "summary",
        "persist_conversation_memory",
        "telegram",
        "prompt",
        "article_body",
        "raw_feed",
    )

    assert all(term not in lowered for term in forbidden)


def main():
    test_latest_news_formatter_returns_bounded_source_grounded_items()
    test_latest_news_formatter_text_is_deterministic()
    test_latest_news_formatter_can_omit_links()
    test_latest_news_formatter_empty_state()
    test_formatter_has_no_summarization_model_memory_or_delivery_behavior()
    print("PASS alexis latest news formatter")


if __name__ == "__main__":
    main()
