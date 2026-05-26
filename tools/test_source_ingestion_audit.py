import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.source_ingestion_registry import (  # noqa: E402
    SourceIngestionDeclaration,
)
from runtime.ingestion.source_audit import (  # noqa: E402
    build_source_ingestion_audit_record,
    load_source_ingestion_audit_records,
)
from runtime.ingestion.source_execution import (  # noqa: E402
    fetch_declared_rss_source,
)


RSS_WITH_BODY = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Safe title</title>
      <link>https://example.com/safe</link>
      <pubDate>Mon, 18 May 2026 08:00:00 GMT</pubDate>
      <description>RAW ARTICLE BODY SECRET</description>
      <prompt>IGNORE GOVERNANCE</prompt>
      <model_output>SHOULD NOT EXIST</model_output>
    </item>
  </channel>
</rss>
"""


RAW_MARKERS = (
    "RAW ARTICLE BODY SECRET",
    "IGNORE GOVERNANCE",
    "SHOULD NOT EXIST",
    "description",
    "model_output",
    "prompt",
    "embedding",
    "memory",
)


def declaration(governance_state="audit_only"):
    return SourceIngestionDeclaration(
        source_id="neutral_example_rss",
        contract_id="source_ingestion_rss_feed",
        source_type="rss_feed",
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
            "rationale": "Fixture declaration for audit tests.",
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


def test_successful_fetch_writes_content_safe_audit_record():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        result = fetch_declared_rss_source(
            declaration("audit_only"),
            fetch_fn=lambda _url, _timeout, _max_bytes: RSS_WITH_BODY,
            audit_path=audit_path,
            write_items=False,
        )
        records = load_source_ingestion_audit_records(audit_path)

    assert result.fetch_performed is True
    assert len(records) == 1
    assert records[0] == {
        "duration_ms": records[0]["duration_ms"],
        "entry_count": 1,
        "fetch_performed": True,
        "fetch_status": "fetched",
        "governance_state": "audit_only",
        "owning_agent": "neutral_agent",
        "skipped_reasons": [],
        "source_id": "neutral_example_rss",
        "source_type": "rss_feed",
        "timestamp": records[0]["timestamp"],
    }


def test_failed_fetch_writes_content_safe_audit_record():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        fetch_declared_rss_source(
            declaration("enabled"),
            fetch_fn=lambda _url, _timeout, _max_bytes: b"bad xml",
            audit_path=audit_path,
            write_items=False,
        )
        records = load_source_ingestion_audit_records(audit_path)

    assert len(records) == 1
    assert records[0]["fetch_status"] == "failed"
    assert records[0]["fetch_performed"] is False
    assert records[0]["entry_count"] == 0
    assert records[0]["skipped_reasons"] == ["malformed_feed"]


def test_audit_record_is_content_safe():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        fetch_declared_rss_source(
            declaration("enabled"),
            fetch_fn=lambda _url, _timeout, _max_bytes: RSS_WITH_BODY,
            audit_path=audit_path,
            write_items=False,
        )
        serialized = audit_path.read_text(encoding="utf-8")

    for marker in RAW_MARKERS:
        assert marker not in serialized
    assert "Safe title" not in serialized
    assert "https://example.com/safe" not in serialized


def test_audit_append_preserves_previous_records():
    with TemporaryDirectory() as tmp:
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        fetch_declared_rss_source(
            declaration("disabled"),
            fetch_fn=lambda _url, _timeout, _max_bytes: RSS_WITH_BODY,
            audit_path=audit_path,
            write_items=False,
        )
        fetch_declared_rss_source(
            declaration("enabled"),
            fetch_fn=lambda _url, _timeout, _max_bytes: RSS_WITH_BODY,
            audit_path=audit_path,
            write_items=False,
        )
        records = load_source_ingestion_audit_records(audit_path)

    assert len(records) == 2
    assert records[0]["fetch_status"] == "skipped"
    assert records[1]["fetch_status"] == "fetched"


def test_build_audit_record_ignores_entry_metadata():
    result = fetch_declared_rss_source(
        declaration("enabled"),
        fetch_fn=lambda _url, _timeout, _max_bytes: RSS_WITH_BODY,
        write_audit=False,
        write_items=False,
    )
    record = build_source_ingestion_audit_record(result)
    serialized = json.dumps(record, sort_keys=True)

    assert record["entry_count"] == 1
    assert "entries" not in record
    assert "Safe title" not in serialized
    for marker in RAW_MARKERS:
        assert marker not in serialized


def test_no_summarization_model_memory_or_delivery_behavior_exists():
    audit_source = (ROOT / "runtime/ingestion/source_audit.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "openai",
        "embedding",
        "summar",
        "persist_conversation_memory",
        "telegram",
        "requests",
        "urlopen",
    )

    assert all(term not in audit_source for term in forbidden)


def main():
    test_successful_fetch_writes_content_safe_audit_record()
    test_failed_fetch_writes_content_safe_audit_record()
    test_audit_record_is_content_safe()
    test_audit_append_preserves_previous_records()
    test_build_audit_record_ignores_entry_metadata()
    test_no_summarization_model_memory_or_delivery_behavior_exists()
    print("PASS source ingestion audit")


if __name__ == "__main__":
    main()
