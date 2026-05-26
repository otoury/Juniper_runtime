import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.source_ingestion_registry import (  # noqa: E402
    SourceIngestionDeclaration,
)
from runtime.ingestion.source_execution import fetch_declared_rss_source  # noqa: E402
from runtime.ingestion.source_item_store import (  # noqa: E402
    FRESHNESS_STATUS_ADEQUATE,
    FRESHNESS_STATUS_FETCH_HEALTH_FAILED,
    FRESHNESS_STATUS_INSUFFICIENT_COVERAGE,
    FRESHNESS_STATUS_STALE,
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED,
    INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY,
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE,
    INSUFFICIENCY_REASON_STALE_ITEMS,
    INSUFFICIENCY_REASON_STALE_SOURCES,
    append_source_items,
    evaluate_latest_source_item_freshness,
    latest_source_items,
    load_source_items,
    rss_source_ref_id,
    source_item_from_fetch_entry,
    source_item_id,
)


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Later headline</title>
      <link>https://example.com/later</link>
      <pubDate>Mon, 18 May 2026 09:00:00 GMT</pubDate>
      <description>ARTICLE BODY MUST NOT STORE</description>
    </item>
    <item>
      <title>Earlier headline</title>
      <link>https://example.com/earlier</link>
      <pubDate>Mon, 18 May 2026 08:00:00 GMT</pubDate>
      <summary>SUMMARY MUST NOT STORE</summary>
    </item>
  </channel>
</rss>
"""


def declaration(metadata_storage_allowed=True):
    return SourceIngestionDeclaration(
        source_id="alexis_bbc_business_news_rss",
        contract_id="source_ingestion_rss_feed",
        source_type="rss_feed",
        url="https://example.com/feed.xml",
        owning_agent="alexis",
        governance_state="audit_only",
        refresh_policy={"type": "manual"},
        source_category={
            "category": "business_news",
            "topic_tags": ["business", "markets"],
        },
        priority_policy={
            "domain": "newsroom",
            "level": "normal",
            "rationale": "Fixture declaration for item store tests.",
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
            "metadata_storage_allowed": metadata_storage_allowed,
        },
        manifest_path=ROOT / "agents/alexis/source_feeds.json",
        raw_data={},
    )


def fixture_fetch(_url, _timeout, _max_bytes):
    return RSS_FIXTURE


def test_rss_fetch_stores_metadata_items_when_policy_allows():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        result = fetch_declared_rss_source(
            declaration(metadata_storage_allowed=True),
            fetch_fn=fixture_fetch,
            write_audit=False,
            item_store_path=store_path,
        )
        items = load_source_items(store_path)

    assert result.entry_count == 2
    assert result.stored_item_count == 2
    assert len(items) == 2
    assert items[0].title == "Later headline"
    assert items[0].link == "https://example.com/later"
    assert items[0].provenance["kind"] == "rss_metadata"
    serialized = json.dumps([item.to_record() for item in items], sort_keys=True)
    assert "ARTICLE BODY MUST NOT STORE" not in serialized
    assert "SUMMARY MUST NOT STORE" not in serialized
    assert "summary" not in serialized.lower()
    assert "embedding" not in serialized.lower()
    assert "memory" not in serialized.lower()


def test_fetch_does_not_store_when_metadata_policy_forbids():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        result = fetch_declared_rss_source(
            declaration(metadata_storage_allowed=False),
            fetch_fn=fixture_fetch,
            write_audit=False,
            item_store_path=store_path,
        )
        items = load_source_items(store_path)

    assert result.entry_count == 2
    assert result.stored_item_count == 0
    assert items == ()


def test_item_ids_are_deterministic_and_content_safe():
    first = source_item_id(
        source_id="source",
        title="Headline",
        link="https://example.com/a",
        published="2026-05-18T08:00:00+00:00",
    )
    second = source_item_id(
        source_id="source",
        title="Headline",
        link="https://example.com/a",
        published="2026-05-18T08:00:00+00:00",
    )

    assert first == second
    assert "Headline" not in first
    assert "example.com" not in first
    assert len(first) == 64


def test_rss_source_ref_ids_are_stable_and_content_safe():
    item_id = source_item_id(
        source_id="source",
        title="Headline",
        link="https://example.com/a",
        published="2026-05-18T08:00:00+00:00",
    )
    first = rss_source_ref_id(source_id="source", item_id=item_id)
    second = rss_source_ref_id(source_id="source", item_id=item_id)

    assert first == second
    assert first.startswith("rss_")
    assert "Headline" not in first
    assert "example.com" not in first
    assert len(first) == 28


def test_duplicate_items_are_handled_deterministically():
    item = source_item_from_fetch_entry(
        source_id="source",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="manifest",
        title="Headline",
        link="https://example.com/a",
        published="2026-05-18T08:00:00+00:00",
        fetched_at="2026-05-18T08:01:00+00:00",
    )
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        first = append_source_items((item,), store_path=store_path)
        second = append_source_items((item,), store_path=store_path)
        loaded = load_source_items(store_path)

    assert first == (item,)
    assert second == ()
    assert loaded == (item,)


def test_latest_news_retrieval_is_sorted_bounded_and_filterable():
    older = source_item_from_fetch_entry(
        source_id="source_a",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="manifest",
        title="Older",
        link="https://example.com/old",
        published="2026-05-18T07:00:00+00:00",
        fetched_at="2026-05-18T07:10:00+00:00",
    )
    newer = source_item_from_fetch_entry(
        source_id="source_b",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="manifest",
        title="Newer",
        link="https://example.com/new",
        published="2026-05-18T09:00:00+00:00",
        fetched_at="2026-05-18T09:10:00+00:00",
    )
    fallback = source_item_from_fetch_entry(
        source_id="source_b",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="manifest",
        title="Fetched sort",
        link="https://example.com/fetched",
        published="",
        fetched_at="2026-05-18T10:00:00+00:00",
    )

    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items((older, newer, fallback), store_path=store_path)
        latest = latest_source_items(store_path=store_path, max_items=2)
        filtered = latest_source_items(
            store_path=store_path,
            max_items=10,
            source_id="source_a",
        )

    assert [item.title for item in latest] == ["Fetched sort", "Newer"]
    assert [item.title for item in filtered] == ["Older"]


def test_fresh_cache_satisfies_named_freshness_policy():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item("source_a", "Fresh A"),
                fresh_item("source_b", "Fresh B"),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(minimum_fresh_items=2, minimum_source_count=2),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_ADEQUATE
    assert result.adequate is True
    assert result.insufficiency_reason is None
    assert len(result.fresh_items) == 2
    assert {ref["source_id"] for ref in result.source_refs} == {
        "source_a",
        "source_b",
    }
    assert all(ref["source_ref_id"].startswith("rss_") for ref in result.source_refs)
    assert all(ref["source_type"] == "rss_feed" for ref in result.source_refs)
    assert result.source_refs[0]["provenance"] == "rss_metadata"


def test_stale_cache_fails_closed_with_typed_status():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item(
                    "source_a",
                    "Old A",
                    published="2026-05-17T10:00:00+00:00",
                    fetched_at="2026-05-17T10:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_FETCH_HEALTH_FAILED
    assert result.adequate is False
    assert result.fresh_items == ()
    assert result.insufficiency_reason == INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED


def test_stale_items_fail_closed_with_typed_reason():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item(
                    "source_a",
                    "Stale published item",
                    published="2026-05-17T10:00:00+00:00",
                    fetched_at="2026-05-20T09:59:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(max_fetch_age=7200),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_STALE
    assert result.adequate is False
    assert result.insufficiency_reason == INSUFFICIENCY_REASON_STALE_ITEMS


def test_empty_cache_fails_closed_with_insufficient_coverage():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
    assert result.adequate is False
    assert result.source_refs == ()
    assert result.insufficiency_reason == INSUFFICIENCY_REASON_STALE_SOURCES


def test_topic_aware_cache_retrieval_matches_normalized_focus():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item("source_a", "Iran nuclear talks resume"),
                fresh_item("source_b", "European markets close higher"),
                fresh_item("source_c", "Iran sanctions debate widens"),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(minimum_fresh_items=2),
            now=fixed_now(),
            max_items=5,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result.status == FRESHNESS_STATUS_ADEQUATE
    assert [item.title for item in result.fresh_items] == [
        "Iran sanctions debate widens",
        "Iran nuclear talks resume",
    ]
    assert result.candidate_item_count == 3
    assert result.topic_matched_item_count == 2
    assert result.topic_entity_focus == {"topics": ("iran",), "entities": ()}


def test_topic_aware_cache_retrieval_filters_before_latest_bound():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        newer_off_topic_items = tuple(
            fresh_item(
                f"source_{index}",
                f"General headline {index}",
                published=f"2026-05-20T09:{index:02d}:00+00:00",
                fetched_at=f"2026-05-20T09:{index:02d}:30+00:00",
            )
            for index in range(55)
        )
        append_source_items(
            newer_off_topic_items
            + (
                fresh_item(
                    "source_iran",
                    "Iran Threatens to Strike Beyond the Middle East",
                    published="2026-05-20T08:00:00+00:00",
                    fetched_at="2026-05-20T09:59:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(),
            now=fixed_now(),
            max_items=5,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result.status == FRESHNESS_STATUS_ADEQUATE
    assert [item.title for item in result.fresh_items] == [
        "Iran Threatens to Strike Beyond the Middle East"
    ]
    assert result.candidate_item_count == 56
    assert result.topic_matched_item_count == 1


def test_topic_aware_cache_retrieval_rejects_off_topic_items():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item("source_a", "Iran nuclear talks resume"),
                fresh_item("source_b", "European markets close higher"),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(),
            now=fixed_now(),
            max_items=5,
            topic_entity_focus={"topics": ["European markets"], "entities": []},
        )

    assert result.status == FRESHNESS_STATUS_ADEQUATE
    assert [item.title for item in result.fresh_items] == [
        "European markets close higher",
    ]
    assert all("Iran" not in item.title for item in result.fresh_items)


def test_topic_aware_cache_retrieval_fails_closed_when_coverage_missing():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item("source_a", "European markets close higher"),
                fresh_item("source_b", "US budget talks continue"),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(),
            now=fixed_now(),
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result.status == FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
    assert result.adequate is False
    assert result.fresh_items == ()
    assert result.source_refs == ()
    assert result.candidate_item_count == 2
    assert result.topic_matched_item_count == 0
    assert result.insufficiency_reason == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )


def test_insufficient_source_diversity_fails_closed():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item("source_a", "Fresh A"),
                fresh_item(
                    "source_a",
                    "Fresh B",
                    published="2026-05-20T09:30:00+00:00",
                    link="https://example.com/fresh-b",
                ),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(minimum_fresh_items=2, minimum_source_count=2),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
    assert result.adequate is False
    assert len(result.fresh_items) == 2
    assert result.insufficiency_reason == (
        INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY
    )


def test_recent_fetch_plus_fresh_items_passes():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item(
                    "source_a",
                    "Fresh fetched",
                    published="2026-05-20T09:00:00+00:00",
                    fetched_at="2026-05-20T09:59:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(max_fetch_age=120),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_ADEQUATE
    assert result.adequate is True


def test_invalid_timestamps_fail_closed_without_trace_loss():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                fresh_item(
                    "source_a",
                    "Invalid time",
                    published="not a timestamp",
                    fetched_at="also invalid",
                ),
            ),
            store_path=store_path,
        )
        result = evaluate_latest_source_item_freshness(
            store_path=store_path,
            policy=freshness_policy(),
            now=fixed_now(),
        )

    assert result.status == FRESHNESS_STATUS_FETCH_HEALTH_FAILED
    assert result.adequate is False
    assert result.invalid_item_count == 1
    assert result.fresh_items == ()
    assert result.insufficiency_reason == INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED


def test_store_module_has_no_semantic_processing_or_delivery_behavior():
    source = (ROOT / "runtime/ingestion/source_item_store.py").read_text(encoding="utf-8")
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


def fixed_now():
    return datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)


def freshness_policy(
    *,
    max_item_age=7200,
    max_fetch_age=7200,
    minimum_fresh_items=1,
    minimum_source_count=1,
):
    return {
        "max_item_age": max_item_age,
        "max_fetch_age": max_fetch_age,
        "minimum_fresh_items": minimum_fresh_items,
        "minimum_source_count": minimum_source_count,
    }


def fresh_item(
    source_id,
    title,
    *,
    published="2026-05-20T09:00:00+00:00",
    fetched_at="2026-05-20T09:01:00+00:00",
    link=None,
):
    return source_item_from_fetch_entry(
        source_id=source_id,
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="manifest",
        title=title,
        link=link or f"https://example.com/{title.lower().replace(' ', '-')}",
        published=published,
        fetched_at=fetched_at,
    )


def main():
    test_rss_fetch_stores_metadata_items_when_policy_allows()
    test_fetch_does_not_store_when_metadata_policy_forbids()
    test_item_ids_are_deterministic_and_content_safe()
    test_rss_source_ref_ids_are_stable_and_content_safe()
    test_duplicate_items_are_handled_deterministically()
    test_latest_news_retrieval_is_sorted_bounded_and_filterable()
    test_fresh_cache_satisfies_named_freshness_policy()
    test_stale_cache_fails_closed_with_typed_status()
    test_stale_items_fail_closed_with_typed_reason()
    test_empty_cache_fails_closed_with_insufficient_coverage()
    test_topic_aware_cache_retrieval_matches_normalized_focus()
    test_topic_aware_cache_retrieval_filters_before_latest_bound()
    test_topic_aware_cache_retrieval_rejects_off_topic_items()
    test_topic_aware_cache_retrieval_fails_closed_when_coverage_missing()
    test_insufficient_source_diversity_fails_closed()
    test_recent_fetch_plus_fresh_items_passes()
    test_invalid_timestamps_fail_closed_without_trace_loss()
    test_store_module_has_no_semantic_processing_or_delivery_behavior()
    print("PASS source item store")


if __name__ == "__main__":
    main()
