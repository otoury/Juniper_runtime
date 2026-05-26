import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.source_ingestion_registry import (  # noqa: E402
    SourceIngestionDeclaration,
)
from runtime.ingestion.source_execution import (  # noqa: E402
    FETCH_STATUS_FAILED,
    FETCH_STATUS_FETCHED,
    FETCH_STATUS_SKIPPED,
    fetch_declared_rss_sources,
    fetch_declared_rss_source,
)


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Fixture Feed</title>
    <item>
      <title>First item</title>
      <link>https://example.com/first</link>
      <pubDate>Mon, 18 May 2026 08:00:00 GMT</pubDate>
      <description>ARTICLE BODY SHOULD NOT SURFACE</description>
    </item>
    <item>
      <title>Second item</title>
      <link>https://example.com/second</link>
      <pubDate>Mon, 18 May 2026 08:05:00 GMT</pubDate>
      <content>RAW CONTENT SHOULD NOT SURFACE</content>
    </item>
  </channel>
</rss>
"""


def declaration(governance_state="audit_only", source_type="rss_feed"):
    return SourceIngestionDeclaration(
        source_id="neutral_example_rss",
        contract_id="source_ingestion_rss_feed",
        source_type=source_type,
        url="https://example.com/feed.xml",
        owning_agent="neutral_agent",
        governance_state=governance_state,
        refresh_policy={"type": "manual"},
        source_category={
            "category": "test_feed",
            "topic_tags": ["test"],
        },
        priority_policy={
            "level": "normal",
            "rationale": "Fixture declaration for execution tests.",
        },
        provenance_policy={
            "citation_required": True,
            "source_url_required": True,
            "attribution_required": True,
            "prose_only_output_allowed": False,
        },
        provenance_audit={"required": True},
        content_safety={
            "raw_content_storage_allowed": False,
            "prompt_injection_surface_allowed": False,
            "summary_generation_allowed": False,
        },
        storage_policy={
            "memory_write_allowed": False,
            "article_storage_allowed": False,
            "metadata_storage_allowed": True,
        },
        manifest_path=ROOT / "agents/alexis/source_feeds.json",
        raw_data={},
    )


def fixture_fetch(_url, _timeout_seconds, _max_feed_bytes):
    return RSS_FIXTURE


def test_disabled_sources_do_not_fetch():
    called = {"value": False}

    def fetch_fn(_url, _timeout_seconds, _max_feed_bytes):
        called["value"] = True
        return RSS_FIXTURE

    result = fetch_declared_rss_source(
        declaration("disabled"),
        fetch_fn=fetch_fn,
        write_audit=False,
        write_items=False,
        now=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
    )

    assert called["value"] is False
    assert result.fetch_status == FETCH_STATUS_SKIPPED
    assert result.fetch_performed is False
    assert result.skipped_reasons == ("governance_disabled",)
    assert result.entries == ()


def test_audit_only_sources_fetch_metadata_safely():
    result = fetch_declared_rss_source(
        declaration("audit_only"),
        fetch_fn=fixture_fetch,
        write_audit=False,
        write_items=False,
        now=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
    )
    trace = result.to_trace()
    serialized = json.dumps(trace, sort_keys=True)

    assert result.fetch_status == FETCH_STATUS_FETCHED
    assert result.fetch_performed is True
    assert result.entry_count == 2
    assert trace["entries"][0] == {
        "title": "First item",
        "link": "https://example.com/first",
        "published": "Mon, 18 May 2026 08:00:00 GMT",
    }
    assert "ARTICLE BODY SHOULD NOT SURFACE" not in serialized
    assert "RAW CONTENT SHOULD NOT SURFACE" not in serialized


def test_enabled_sources_fetch_normalized_metadata_only():
    result = fetch_declared_rss_source(
        declaration("enabled"),
        fetch_fn=fixture_fetch,
        write_audit=False,
        write_items=False,
        max_entries=1,
    )
    trace = result.to_trace()

    assert result.fetch_status == FETCH_STATUS_FETCHED
    assert result.governance_state == "enabled"
    assert result.entry_count == 1
    assert list(trace["entries"][0]) == ["title", "link", "published"]


def test_malformed_feeds_fail_closed():
    result = fetch_declared_rss_source(
        declaration("enabled"),
        fetch_fn=lambda _url, _timeout, _max_bytes: b"not xml",
        write_audit=False,
        write_items=False,
    )

    assert result.fetch_status == FETCH_STATUS_FAILED
    assert result.fetch_performed is False
    assert result.entry_count == 0
    assert result.skipped_reasons == ("malformed_feed",)


def test_oversized_responses_fail_closed():
    result = fetch_declared_rss_source(
        declaration("enabled"),
        fetch_fn=lambda _url, _timeout, _max_bytes: b"x" * 11,
        max_feed_bytes=10,
        write_audit=False,
        write_items=False,
    )

    assert result.fetch_status == FETCH_STATUS_FAILED
    assert result.skipped_reasons == ("feed_response_too_large",)
    assert result.entries == ()


def test_timeout_cases_fail_closed():
    def timeout_fetch(_url, _timeout, _max_bytes):
        raise TimeoutError("timeout")

    result = fetch_declared_rss_source(
        declaration("enabled"),
        fetch_fn=timeout_fetch,
        write_audit=False,
        write_items=False,
    )

    assert result.fetch_status == FETCH_STATUS_FAILED
    assert result.skipped_reasons == ("fetch_timeout",)
    assert result.entries == ()


def test_unsupported_source_type_fails_closed():
    result = fetch_declared_rss_source(
        declaration("enabled", source_type="web_page"),
        fetch_fn=fixture_fetch,
        write_audit=False,
        write_items=False,
    )

    assert result.fetch_status == FETCH_STATUS_FAILED
    assert result.fetch_performed is False
    assert result.skipped_reasons == ("unsupported_source_type",)


def test_batch_fetch_uses_same_governed_execution_path():
    results = fetch_declared_rss_sources(
        (
            declaration("disabled"),
            declaration("audit_only"),
        ),
        fetch_fn=fixture_fetch,
        write_audit=False,
        write_items=False,
    )

    assert len(results) == 2
    assert results[0].fetch_status == FETCH_STATUS_SKIPPED
    assert results[0].fetch_performed is False
    assert results[1].fetch_status == FETCH_STATUS_FETCHED
    assert results[1].entry_count == 2


def test_no_article_body_retrieval_or_semantic_processing_exists():
    source = (ROOT / "runtime/ingestion/source_execution.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "feedparser",
        "openai",
        "embedding",
        "summar",
        "persist_conversation_memory",
        "telegram",
        "BeautifulSoup",
        "readability",
        "article_body",
    )

    assert all(term not in source for term in forbidden)


def main():
    test_disabled_sources_do_not_fetch()
    test_audit_only_sources_fetch_metadata_safely()
    test_enabled_sources_fetch_normalized_metadata_only()
    test_malformed_feeds_fail_closed()
    test_oversized_responses_fail_closed()
    test_timeout_cases_fail_closed()
    test_unsupported_source_type_fails_closed()
    test_batch_fetch_uses_same_governed_execution_path()
    test_no_article_body_retrieval_or_semantic_processing_exists()
    print("PASS source ingestion execution")


if __name__ == "__main__":
    main()
