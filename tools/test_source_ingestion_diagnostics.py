import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.source_ingestion_diagnostics import (  # noqa: E402
    build_source_ingestion_diagnostics,
)
from runtime.ingestion.source_item_store import (  # noqa: E402
    append_source_items,
    source_item_from_fetch_entry,
)


RAW_MARKERS = (
    "Unsafe article title",
    "https://example.com/article",
    "RAW FEED BODY",
    "ARTICLE BODY",
    "prompt text",
    "model output",
    "embedding vector",
    "memory state",
    "telegram payload",
    "article_title",
    "article_link",
    "raw_feed_body",
    "article_body",
    "prompt",
    "model_output",
    "embeddings",
    "memory_state",
    "telegram_payload",
)


def write_audit(path):
    records = [
        {
            "timestamp": "2026-05-18T08:00:00+00:00",
            "source_id": "alexis_bbc_world_news_rss",
            "source_type": "rss_feed",
            "owning_agent": "alexis",
            "governance_state": "disabled",
            "fetch_status": "skipped",
            "fetch_performed": False,
            "duration_ms": 0,
            "entry_count": 0,
            "skipped_reasons": ["governance_disabled"],
            "article_title": "Unsafe article title",
            "article_link": "https://example.com/article",
            "raw_feed_body": "RAW FEED BODY",
            "article_body": "ARTICLE BODY",
            "prompt": "prompt text",
            "model_output": "model output",
            "embeddings": "embedding vector",
            "memory_state": "memory state",
            "telegram_payload": "telegram payload",
        },
        {
            "timestamp": "2026-05-18T08:01:00+00:00",
            "source_id": "alexis_bbc_business_news_rss",
            "source_type": "rss_feed",
            "owning_agent": "alexis",
            "governance_state": "audit_only",
            "fetch_status": "fetched",
            "fetch_performed": True,
            "duration_ms": 5,
            "entry_count": 3,
            "skipped_reasons": [],
        },
    ]
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def test_diagnostics_command_outputs_content_safe_summary():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        item_store_path = Path(tmp) / "source_items.jsonl"
        write_audit(audit_path)
        output = subprocess.check_output(
            [
                sys.executable,
                str(ROOT / "tools/source_ingestion_diagnostics.py"),
                "--agent",
                "alexis",
                "--audit-path",
                str(audit_path),
                "--item-store-path",
                str(item_store_path),
                "--json",
            ],
            text=True,
            cwd=ROOT,
        )

    payload = json.loads(output)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["diagnostic_type"] == "source_ingestion_status"
    assert payload["agent"] == "alexis"
    assert payload["discovered_source_count"] == 17
    assert payload["governance_counts"] == {
        "audit_only": 15,
        "disabled": 2,
    }
    assert payload["source_type_counts"] == {"rss_feed": 17}
    declared_ids = {
        source["source_id"]
        for source in payload["declared_feeds"]
    }
    assert {
        "alexis_nyt_world_rss",
        "alexis_nyt_us_rss",
        "alexis_nyt_politics_rss",
        "alexis_foreign_affairs_rss",
        "alexis_foreign_policy_rss",
        "alexis_chatham_house_rss",
        "alexis_ecfr_rss",
        "alexis_sipri_rss",
        "alexis_war_on_the_rocks_rss",
    }.issubset(declared_ids)
    assert payload["recent_audit"]["last_fetch_time"] == (
        "2026-05-18T08:01:00+00:00"
    )
    assert "empty_source_item_cache" in payload["warnings"]
    assert payload["recent_audit"]["record_count"] == 2
    assert payload["recent_audit"]["recent_fetch_status_counts"] == {
        "fetched": 1,
        "skipped": 1,
    }
    assert payload["recent_audit"]["aggregate_entry_count"] == 3
    assert payload["fetch_performed"] is False
    for marker in RAW_MARKERS:
        assert marker not in serialized


def test_text_diagnostics_show_counts_only():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        item_store_path = Path(tmp) / "source_items.jsonl"
        write_audit(audit_path)
        output = subprocess.check_output(
            [
                sys.executable,
                str(ROOT / "tools/source_ingestion_diagnostics.py"),
                "--audit-path",
                str(audit_path),
                "--item-store-path",
                str(item_store_path),
            ],
            text=True,
            cwd=ROOT,
        )

    assert "Source ingestion diagnostics" in output
    assert "discovered_source_count: 17" in output
    assert "audit_record_count: 2" in output
    assert "aggregate_entry_count: 3" in output
    assert "last_fetch_time: 2026-05-18T08:01:00+00:00" in output
    assert "warnings:" in output
    for marker in RAW_MARKERS:
        assert marker not in output


def test_audit_summaries_are_metadata_only():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        item_store_path = Path(tmp) / "source_items.jsonl"
        write_audit(audit_path)
        payload = build_source_ingestion_diagnostics(
            audit_path=audit_path,
            item_store_path=item_store_path,
        )

    recent = payload["recent_audit"]["recent_records"]
    assert set(recent[0]) == {
        "duration_ms",
        "entry_count",
        "fetch_performed",
        "fetch_status",
        "governance_state",
        "owning_agent",
        "skipped_reasons",
        "source_id",
        "source_type",
        "timestamp",
    }
    assert "article_title" not in recent[0]
    assert "raw_feed_body" not in recent[0]


def test_diagnostics_include_safe_source_item_counts():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        item_store_path = Path(tmp) / "source_items.jsonl"
        write_audit(audit_path)
        append_source_items(
            (
                source_item_from_fetch_entry(
                    source_id="alexis_bbc_business_news_rss",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Business headline",
                    link="https://example.com/business",
                    published="2026-05-18T08:00:00+00:00",
                    fetched_at="2026-05-18T08:01:00+00:00",
                ),
            ),
            store_path=item_store_path,
        )
        payload = build_source_ingestion_diagnostics(
            audit_path=audit_path,
            item_store_path=item_store_path,
        )

    assert payload["source_item_store"]["source_item_counts"] == {
        "alexis_bbc_business_news_rss": 1,
    }


def test_no_execution_behavior_changes_or_fetch_imports():
    source = (
        ROOT / "tools/source_ingestion_diagnostics.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "fetch_declared_rss_source",
        "fetch_declared_rss_sources",
        "execute_scheduled_workflow_manually",
        "urlopen",
        "requests",
        "feedparser",
        "openai",
        "persist_conversation_memory",
        "telegram",
        "threading",
        "asyncio",
    )
    lowered = source.lower()

    assert all(term not in lowered for term in forbidden)


def main():
    test_diagnostics_command_outputs_content_safe_summary()
    test_text_diagnostics_show_counts_only()
    test_audit_summaries_are_metadata_only()
    test_diagnostics_include_safe_source_item_counts()
    test_no_execution_behavior_changes_or_fetch_imports()
    print("PASS source ingestion diagnostics")


if __name__ == "__main__":
    main()
