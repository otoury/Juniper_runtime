import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.scheduled_task_registry import (  # noqa: E402
    audit_scheduled_task_declarations_from_path,
)
from runtime.scheduling.workflow_audit import (  # noqa: E402
    load_scheduled_workflow_audit_records,
)
from runtime.scheduling.workflow_executor import (  # noqa: E402
    execute_scheduled_workflow_manually,
)
from runtime.scheduling.workflow_orchestration import (  # noqa: E402
    ScheduledWorkflowExecutionPlan,
    build_due_scheduled_workflow_plans,
)
from runtime.ingestion.source_audit import (  # noqa: E402
    load_source_ingestion_audit_records,
)
from runtime.ingestion.source_item_store import (  # noqa: E402
    append_source_items,
    source_item_from_fetch_entry,
)


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Safe title should remain transient</title>
      <link>https://example.com/transient</link>
      <pubDate>Mon, 18 May 2026 08:00:00 GMT</pubDate>
      <description>RAW ARTICLE BODY MUST NOT PERSIST</description>
    </item>
  </channel>
</rss>
"""
RAW_MARKERS = (
    "Safe title should remain transient",
    "https://example.com/transient",
    "RAW ARTICLE BODY MUST NOT PERSIST",
    "description",
    "prompt",
    "model_messages",
    "telegram",
    "embedding",
    "memory_state",
)


def raw_scheduled_declarations():
    data = json.loads(
        (ROOT / "agents/alexis/scheduled_tasks.json").read_text(
            encoding="utf-8"
        )
    )
    return data["task_declarations"]


def write_scheduled_manifest(root, declarations):
    path = Path(root) / "agents/alexis/scheduled_tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "agent": "alexis",
                "task_declarations": declarations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def enabled_rss_plan():
    declarations = raw_scheduled_declarations()
    for declaration in declarations:
        if declaration["id"] == "alexis_rss_feed_check":
            declaration["governance_state"] = "enabled"

    with TemporaryDirectory() as tmp:
        path = write_scheduled_manifest(tmp, declarations)
        loaded, errors = audit_scheduled_task_declarations_from_path(
            path,
            root=ROOT,
        )
        assert errors == ()
        plans = build_due_scheduled_workflow_plans(
            loaded,
            now=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
        )

    matches = [
        plan for plan in plans if plan.task_id == "alexis_rss_feed_check"
    ]
    assert len(matches) == 1
    return matches[0]


def disabled_rss_plan():
    return ScheduledWorkflowExecutionPlan(
        task_id="alexis_rss_feed_check",
        agent="alexis",
        workflow="alexis_rss_feed_check",
        binding_id="alexis_rss_feed_check",
        semantic_operation={
            "operation_type": "NEWS_INGESTION",
            "capability_id": "alexis_rss_feed_check",
            "produces_artifact": False,
            "external_side_effects_allowed": False,
            "memory_write_allowed": False,
            "requires_approval": False,
        },
        governance_state="disabled",
        schedule_type="interval",
        plan_mode="dry_run",
        dry_run=True,
        execution_allowed_by_governance=False,
        execution_performed=False,
        max_runtime_ms=30000,
        max_concurrent_runs=1,
        retry_policy="none",
        skipped_reasons=("governance_disabled",),
        manifest_path="test",
    )


def fixture_fetch(_url, _timeout_seconds, _max_feed_bytes):
    return RSS_FIXTURE


def seed_cached_rss_item(store_path):
    fetched_at = datetime.now(timezone.utc).isoformat()
    item = source_item_from_fetch_entry(
        source_id="stage195_cached_source",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path=str(ROOT / "agents/alexis/source_feeds.json"),
        title="Stage 195 cached RSS headline",
        link="https://example.com/stage195",
        published=fetched_at,
        fetched_at=fetched_at,
    )
    append_source_items((item,), store_path=store_path)


def test_disabled_scheduled_rss_workflow_does_not_execute():
    called = {"value": False}

    def fetch_fn(_url, _timeout, _max_bytes):
        called["value"] = True
        return RSS_FIXTURE

    result = execute_scheduled_workflow_manually(
        disabled_rss_plan(),
        source_fetch_fn=fetch_fn,
        write_audit=False,
    )

    assert called["value"] is False
    assert result.execution_performed is False
    assert result.execution_status == "skipped"
    assert result.skipped_reasons == ("governance_disabled",)


def test_enabled_scheduled_rss_dry_run_uses_cache_and_blocks_fetch():
    called = {"value": False}

    def fetch_fn(_url, _timeout_seconds, _max_feed_bytes):
        called["value"] = True
        return RSS_FIXTURE

    with TemporaryDirectory() as tmp:
        source_item_path = Path(tmp) / "source_items.jsonl"
        seed_cached_rss_item(source_item_path)
        result = execute_scheduled_workflow_manually(
            enabled_rss_plan(),
            source_fetch_fn=fetch_fn,
            source_item_store_path=source_item_path,
            write_audit=False,
        )
    serialized = json.dumps(result.to_trace(), sort_keys=True)

    assert called["value"] is False
    assert result.execution_performed is True
    assert result.execution_status == "executed"
    assert result.audit_summary["workflow"] == "alexis_rss_feed_check"
    assert result.audit_summary["source_count"] == 17
    assert result.audit_summary["fetched_count"] == 0
    assert result.audit_summary["skipped_count"] == 17
    assert result.audit_summary["total_entry_count"] == 0
    assert result.audit_summary["dry_run_plan"] is True
    assert result.audit_summary["local_cache_operation_allowed"] is True
    assert result.audit_summary["local_cache_synthesis_allowed"] is True
    assert result.audit_summary["external_network_fetch_blocked"] is True
    assert result.audit_summary["external_call_performed"] is False
    for marker in RAW_MARKERS:
        assert marker not in serialized


def test_scheduled_rss_dry_run_writes_no_source_ingestion_audit_records():
    with TemporaryDirectory() as tmp:
        source_audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        source_item_path = Path(tmp) / "source_items.jsonl"
        seed_cached_rss_item(source_item_path)
        execute_scheduled_workflow_manually(
            enabled_rss_plan(),
            source_fetch_fn=fixture_fetch,
            source_audit_path=source_audit_path,
            source_item_store_path=source_item_path,
            write_audit=False,
        )
        records = load_source_ingestion_audit_records(source_audit_path)

    assert records == ()


def test_scheduled_workflow_audit_summary_includes_safe_fetch_counts():
    with TemporaryDirectory() as tmp:
        scheduled_audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        source_audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        source_item_path = Path(tmp) / "source_items.jsonl"
        seed_cached_rss_item(source_item_path)
        execute_scheduled_workflow_manually(
            enabled_rss_plan(),
            audit_path=scheduled_audit_path,
            source_audit_path=source_audit_path,
            source_item_store_path=source_item_path,
            source_fetch_fn=fixture_fetch,
        )
        records = load_scheduled_workflow_audit_records(scheduled_audit_path)

    assert len(records) == 1
    summary = records[0]["audit_summary"]
    assert summary == {
        "execution_status": "success",
        "dry_run_plan": True,
        "external_call_performed": False,
        "external_network_fetch_blocked": True,
        "external_network_fetch_reason": "external_network_fetch_blocked_by_dry_run",
        "failed_count": 0,
        "fetch_status_counts": {
            "skipped": 17,
        },
        "fetched_count": 0,
        "local_cache_hit": True,
        "local_cache_item_count": 1,
        "local_cache_operation_allowed": True,
        "local_cache_read_allowed": True,
        "local_cache_synthesis_allowed": True,
        "skipped_count": 17,
        "skipped_reasons": ["external_network_fetch_blocked_by_dry_run"],
        "source_count": 17,
        "total_entry_count": 0,
        "workflow": "alexis_rss_feed_check",
    }


def test_no_article_titles_links_or_bodies_persist_in_audits():
    with TemporaryDirectory() as tmp:
        scheduled_audit_path = Path(tmp) / "scheduled_workflow_audit.jsonl"
        source_audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        source_item_path = Path(tmp) / "source_items.jsonl"
        seed_cached_rss_item(source_item_path)
        execute_scheduled_workflow_manually(
            enabled_rss_plan(),
            audit_path=scheduled_audit_path,
            source_audit_path=source_audit_path,
            source_item_store_path=source_item_path,
            source_fetch_fn=fixture_fetch,
        )
        serialized = (
            scheduled_audit_path.read_text(encoding="utf-8")
            + (
                source_audit_path.read_text(encoding="utf-8")
                if source_audit_path.exists()
                else ""
            )
        )

    for marker in RAW_MARKERS:
        assert marker not in serialized


def test_no_models_memory_delivery_prompt_or_article_fetches_exist():
    executor_source = (
        ROOT / "runtime/scheduling/workflow_executor.py"
    ).read_text(encoding="utf-8")
    lowered = executor_source.lower()
    forbidden = (
        "openai",
        "embedding",
        "summarize",
        "summarization",
        "persist_conversation_memory",
        "telegram",
        "hidden_prompt",
        "article_body",
        "readability",
        "beautifulsoup",
    )

    assert all(term not in lowered for term in forbidden)


def main():
    test_disabled_scheduled_rss_workflow_does_not_execute()
    test_enabled_scheduled_rss_dry_run_uses_cache_and_blocks_fetch()
    test_scheduled_rss_dry_run_writes_no_source_ingestion_audit_records()
    test_scheduled_workflow_audit_summary_includes_safe_fetch_counts()
    test_no_article_titles_links_or_bodies_persist_in_audits()
    test_no_models_memory_delivery_prompt_or_article_fetches_exist()
    print("PASS scheduled source ingestion workflow")


if __name__ == "__main__":
    main()
