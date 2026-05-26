import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.request_runner as request_runner  # noqa: E402
from agents.alexis import AlexisAgent  # noqa: E402
from agents.alexis.workflows.news_summary_workflow import (  # noqa: E402
    NEWS_SUMMARY_WORKFLOW_ID,
    is_news_summary_request,
    maybe_run_news_summary_workflow,
)
from agents.alexis.workflows.rss_corpus_synthesis import (  # noqa: E402
    render_rss_corpus_briefing,
    synthesize_rss_corpus_briefing,
)
from agents.alexis.workflows.newsroom_rendering import (  # noqa: E402
    RSS_MORE_NOTICE,
    RSS_TELEGRAM_SAFE_MAX_CHARS,
)
from agents.alexis.workflows.rss_brief_transform import (  # noqa: E402
    maybe_transform_active_rss_brief,
)
from runtime.artifacts.insufficient_coverage import (  # noqa: E402
    INSUFFICIENT_COVERAGE_RESULT_ARTIFACT,
    build_insufficient_coverage_result,
    render_insufficient_coverage_result,
    validate_insufficient_coverage_result,
)
from runtime.artifacts.summary import validate_summary_artifact  # noqa: E402
from runtime.ingestion.source_item_store import (  # noqa: E402
    FRESHNESS_STATUS_INSUFFICIENT_COVERAGE,
    INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED,
    INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY,
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE,
    INSUFFICIENCY_REASON_STALE_ITEMS,
    INSUFFICIENCY_REASON_STALE_SOURCES,
    append_source_items,
    evaluate_source_item_freshness,
    source_item_from_fetch_entry,
)
from runtime.workflows.rss_cloud_escalation import (  # noqa: E402
    RSS_CLOUD_ESCALATION_RESULT_ARTIFACT,
    validate_rss_cloud_escalation_result,
)


def seed_items(store_path, count=3):
    items = []
    for index in range(count):
        hour = 8 + index
        items.append(
            source_item_from_fetch_entry(
                source_id=f"alexis_source_{index}",
                owning_agent="alexis",
                governance_state="audit_only",
                manifest_path="agents/alexis/source_feeds.json",
                title=f"Cached briefing headline {index}",
                link=f"https://example.com/{index}",
                published=f"2026-05-18T{hour:02d}:00:00+00:00",
                fetched_at=f"2026-05-18T{hour:02d}:01:00+00:00",
            )
        )
    append_source_items(tuple(items), store_path=store_path)


def test_news_summary_request_recognizer_is_explicit():
    assert is_news_summary_request("Summarize the latest news")
    assert is_news_summary_request("Give me a news briefing")
    assert is_news_summary_request("What's happening today?")
    assert is_news_summary_request("What topics are trending in the news?")
    assert is_news_summary_request("Brief me on business")
    assert not is_news_summary_request("fetch today news")


def test_alexis_news_summary_workflow_returns_source_grounded_artifact():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=2)
        result = maybe_run_news_summary_workflow(
            text="Summarize the latest news",
            store_path=store_path,
            generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
        )

    assert result is not None
    assert result.workflow_id == NEWS_SUMMARY_WORKFLOW_ID
    assert result.cache_hit is True
    assert result.cache_authorization["provider"] == "rss_metadata_cache"
    assert result.cache_authorization["dry_run"] is False
    assert result.cache_authorization["cloud_dry_run"] is False
    assert result.cache_authorization["workflow_dry_run"] is False
    assert result.cache_authorization["authorization"] == "local_cache_authorized"
    assert result.cache_authorization["authorization_status"] == (
        "local_cache_authorized"
    )
    assert result.cache_authorization["dry_run_forced_by"] == []
    assert result.cache_authorization["external_call_performed"] is False
    assert result.cache_authorization["cost_incurred"] is False
    assert result.artifact is not None
    assert validate_summary_artifact(result.artifact)
    assert result.artifact["artifact_type"] == "summary"
    assert result.artifact["summary_kind"] == "latest_news_briefing"
    assert result.artifact["cache_authorization"]["dry_run"] is False
    assert result.artifact["tone"] == "newsroom"
    assert result.artifact["summary_blocks"][0]["source_id"] == "alexis_source_1"
    assert result.artifact["summary_blocks"][0]["source_ref_id"] == (
        result.artifact["source_refs"][0]["source_ref_id"]
    )
    assert result.artifact["summary_blocks"][0]["citation_id"] == (
        result.artifact["citations"][0]["citation_id"]
    )
    assert result.artifact["summary_blocks"][0]["provenance"] == "rss_metadata"
    assert result.cloud_escalation_artifact is None
    assert "Cached briefing headline 1" in result.response


def test_news_summary_only_uses_cached_metadata_items():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=1)
        result = maybe_run_news_summary_workflow(
            text="Give me a news briefing",
            store_path=store_path,
        )

    assert result is not None
    serialized = json.dumps({"artifact": result.artifact, "response": result.response})
    assert "Cached briefing headline 0" in serialized
    assert "article body" not in serialized.lower()
    assert "raw feed" not in serialized.lower()
    assert "model output" not in serialized.lower()


def test_rss_brief_transform_preserves_source_refs_without_execution():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                source_item_from_fetch_entry(
                    source_id="alexis_source_0",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Central bank signals rate shift",
                    link="https://example.com/rates",
                    published="2026-05-18T08:00:00+00:00",
                    fetched_at="2026-05-18T08:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_source_1",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Diplomatic talks resume in Geneva",
                    link="https://example.com/geneva",
                    published="2026-05-18T09:00:00+00:00",
                    fetched_at="2026-05-18T09:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_source_2",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Technology shares lead market rally",
                    link="https://example.com/tech",
                    published="2026-05-18T10:00:00+00:00",
                    fetched_at="2026-05-18T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_source_3",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Energy ministers agree supply plan",
                    link="https://example.com/energy",
                    published="2026-05-18T11:00:00+00:00",
                    fetched_at="2026-05-18T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_news_summary_workflow(
            text="Summarize the latest news",
            store_path=store_path,
        )

    assert result is not None
    assert result.artifact is not None
    transformed = maybe_transform_active_rss_brief(
        text="Give me the top 3",
        active_artifact=result.artifact,
    )

    assert transformed is not None
    assert transformed.cache_hit is True
    assert transformed.transform_type == "top_items"
    assert transformed.artifact is not None
    assert validate_summary_artifact(transformed.artifact)
    assert transformed.artifact["artifact_type"] == "summary"
    assert transformed.artifact["summary_kind"] == "latest_news_briefing"
    assert len(transformed.artifact["summary_blocks"]) == 3
    assert len(transformed.artifact["story_clusters"]) == 3
    assert transformed.artifact["source_refs"]
    assert transformed.artifact["transform_metadata"]["model_used"] is False
    assert transformed.artifact["transform_metadata"]["search_api_executed"] is False
    assert transformed.artifact["transform_metadata"]["article_body_fetched"] is False
    assert "Top RSS stories:" in transformed.response
    assert "source_refs" not in transformed.response
    assert "artifact_type" not in transformed.response


def test_rss_brief_transform_without_active_brief_fails_closed():
    result = maybe_transform_active_rss_brief(
        text="Make it shorter",
        active_artifact=None,
    )

    assert result is not None
    assert result.cache_hit is False
    assert result.artifact is None
    assert "Ask for the latest news or name a topic first" in result.response


def test_rss_corpus_synthesis_collapses_cross_posted_duplicates():
    item_a = source_item_from_fetch_entry(
        source_id="alexis_nyt_world_rss",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Ukraine talks resume in Geneva",
        link="https://www.nytimes.com/2026/05/18/world/ukraine-talks.html",
        published="2026-05-18T10:00:00+00:00",
        fetched_at="2026-05-18T10:01:00+00:00",
    )
    item_b = source_item_from_fetch_entry(
        source_id="alexis_nyt_politics_rss",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Ukraine talks resume in Geneva",
        link="https://www.nytimes.com/2026/05/18/us/politics/ukraine-talks.html",
        published="2026-05-18T10:05:00+00:00",
        fetched_at="2026-05-18T10:06:00+00:00",
    )

    artifact = synthesize_rss_corpus_briefing(
        source_items=(item_a, item_b),
        summary_kind="latest_news_briefing",
        generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
    )

    assert artifact is not None
    assert validate_summary_artifact(artifact)
    assert artifact["synthesis_kind"] == "rss_corpus_synthesis"
    assert len(artifact["story_clusters"]) == 1
    cluster = artifact["story_clusters"][0]
    assert cluster["source_count"] == 2
    assert {source["source_id"] for source in cluster["source_refs"]} == {
        "alexis_nyt_world_rss",
        "alexis_nyt_politics_rss",
    }
    rendered = render_rss_corpus_briefing(artifact)
    assert rendered.count("Ukraine talks resume in Geneva") == 1
    assert "2 sources in RSS cache" in rendered
    assert "<b>Ukraine talks resume in Geneva</b>" in rendered
    assert "<i>S1, S2 - May 18, 2026, 10:05 UTC</i>" in rendered
    assert "Fresh through May 18, 2026, 10:05 UTC" in rendered
    assert "story_clusters" not in rendered
    assert "source_refs" not in rendered
    assert "artifact_type" not in rendered
    assert len([line for line in rendered.splitlines() if line.startswith("- ")]) <= 5


def test_rss_cluster_ranking_prefers_fresh_multi_source_cluster():
    single_source = source_item_from_fetch_entry(
        source_id="alexis_ap_top_news_rss",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Fresh single source headline",
        link="https://example.com/single",
        published="2026-05-18T11:00:00+00:00",
        fetched_at="2026-05-18T11:01:00+00:00",
    )
    multi_a = source_item_from_fetch_entry(
        source_id="alexis_ap_top_news_rss",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Markets rally after central bank decision",
        link="https://example.com/markets-a",
        published="2026-05-18T10:00:00+00:00",
        fetched_at="2026-05-18T10:01:00+00:00",
    )
    multi_b = source_item_from_fetch_entry(
        source_id="alexis_bbc_business_news_rss",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Markets rally after central bank decision",
        link="https://example.com/markets-b",
        published="2026-05-18T10:05:00+00:00",
        fetched_at="2026-05-18T10:06:00+00:00",
    )

    artifact = synthesize_rss_corpus_briefing(
        source_items=(single_source, multi_a, multi_b),
        summary_kind="latest_news_briefing",
    )

    assert artifact is not None
    assert artifact["story_clusters"][0]["representative_headline"] == (
        "Markets rally after central bank decision"
    )
    assert artifact["story_clusters"][0]["source_count"] == 2


def test_business_briefing_uses_rss_corpus_synthesis():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                source_item_from_fetch_entry(
                    source_id="alexis_bbc_business_news_rss",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Markets rise as business confidence improves",
                    link="https://example.com/business",
                    published="2026-05-18T10:00:00+00:00",
                    fetched_at="2026-05-18T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_ap_top_news_rss",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Sports league announces schedule",
                    link="https://example.com/sports",
                    published="2026-05-18T11:00:00+00:00",
                    fetched_at="2026-05-18T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_news_summary_workflow(
            text="Brief me on business",
            store_path=store_path,
            generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
        )

    assert result is not None
    assert result.cache_hit is True
    assert result.artifact is not None
    assert result.artifact["synthesis_kind"] == "rss_corpus_synthesis"
    assert result.artifact["synthesis_metadata"]["category_focus"] == "business"
    assert "Markets rise as business confidence improves" in result.response
    assert "Sports league announces schedule" not in result.response
    assert result.cache_authorization["external_call_performed"] is False


def test_runtime_trending_topics_uses_rss_synthesis_without_model_path():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=2)
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="What topics are trending in the news?",
            )
        finally:
            _restore_runtime_blockers(originals)
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert "Latest news briefing:" in response
    assert "Fresh RSS item" in response
    assert captured["events"][-1]["event_type"] == "agent_local_workflow_completed"
    assert captured["events"][-1]["payload"]["provider"] == "rss_metadata_cache"
    assert captured["events"][-1]["payload"]["cloud_web_fallback_triggered"] is False


def test_news_summary_accepts_topic_focus_and_rejects_off_topic_items():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                source_item_from_fetch_entry(
                    source_id="alexis_iran_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Iran nuclear talks resume",
                    link="https://example.com/iran",
                    published="2026-05-18T10:00:00+00:00",
                    fetched_at="2026-05-18T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-18T11:00:00+00:00",
                    fetched_at="2026-05-18T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_news_summary_workflow(
            text="Summarize the latest news",
            store_path=store_path,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
            generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
        )

    assert result is not None
    assert result.cache_hit is True
    assert result.artifact is not None
    serialized = json.dumps({"artifact": result.artifact, "response": result.response})
    assert "Iran nuclear talks resume" in serialized
    assert "European markets close higher" not in serialized


def test_news_summary_topic_aliases_support_foreign_affairs_adequacy():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                source_item_from_fetch_entry(
                    source_id="alexis_world_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Hostages talks continue after ceasefire proposal",
                    link="https://example.com/hostages",
                    published="2026-05-18T10:00:00+00:00",
                    fetched_at="2026-05-18T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-18T11:00:00+00:00",
                    fetched_at="2026-05-18T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_news_summary_workflow(
            text="Summarize the latest news",
            store_path=store_path,
            topic_entity_focus={"topics": ["Israel/Gaza"], "entities": []},
            generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
        )

    assert result is not None
    assert result.cache_hit is True
    serialized = json.dumps({"artifact": result.artifact, "response": result.response})
    assert "Hostages talks continue after ceasefire proposal" in serialized
    assert "European markets close higher" not in serialized
    assert result.retrieval_metadata["topic_entity_focus"] == {
        "topics": ["israel gaza"],
        "entities": [],
    }
    normalization = result.retrieval_metadata["topic_normalization"]
    assert normalization["matched_family_ids"] == ["israel_gaza"]
    assert "hostages" in normalization["matching_focus"]["topics"]
    assert result.adequacy_artifact["topic_entity_focus"] == {
        "topics": ["israel gaza"],
        "entities": [],
    }
    assert result.adequacy_artifact["provenance"]["web_search_executed"] is False
    assert result.cloud_escalation_artifact is None


def test_news_summary_topic_focus_fails_closed_when_coverage_missing():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=2)
        result = maybe_run_news_summary_workflow(
            text="Summarize the latest news",
            store_path=store_path,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result is not None
    assert result.cache_hit is False
    assert result.cache_authorization["dry_run"] is True
    assert result.cache_authorization["authorization"] == "insufficient_coverage"
    assert result.cache_authorization["external_call_performed"] is False
    assert result.artifact is not None
    assert validate_insufficient_coverage_result(result.artifact)
    assert result.artifact["artifact_type"] == INSUFFICIENT_COVERAGE_RESULT_ARTIFACT
    assert result.artifact["reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert result.item_count == 0
    assert result.freshness_status == FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
    assert result.cloud_escalation_artifact is not None
    assert validate_rss_cloud_escalation_result(result.cloud_escalation_artifact)
    assert result.cloud_escalation_artifact["artifact_type"] == (
        RSS_CLOUD_ESCALATION_RESULT_ARTIFACT
    )
    assert result.cloud_escalation_artifact["eligible"] is False
    assert result.cloud_escalation_artifact["status"] == "not_eligible"
    assert result.cloud_escalation_artifact["execution_allowed"] is False
    assert result.cloud_escalation_artifact["external_call_performed"] is False
    assert result.cloud_escalation_artifact["delivery_performed"] is False
    fallback_eligibility = result.adequacy_artifact["fallback_eligibility"]
    assert fallback_eligibility["eligible"] is True
    assert fallback_eligibility["fallback_provider_type"] == "search_api"
    assert fallback_eligibility["fallback_provider_id"] == "search_api"
    assert fallback_eligibility["dry_run"] is True
    assert fallback_eligibility["live_allowed"] is False
    assert "insufficient topic coverage" in result.response
    assert "<b>Topic focus</b>" in result.response
    assert "iran." in result.response
    assert "search_api prepared; live not enabled" in result.response


def test_news_summary_bounded_item_limit_enforced():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=8)
        result = maybe_run_news_summary_workflow(
            text="What's happening today?",
            store_path=store_path,
            max_items=99,
        )

    assert result is not None
    assert result.artifact is not None
    assert len(result.artifact["summary_blocks"]) == 5
    assert result.item_count == 5


def test_rss_briefing_rendering_is_telegram_safe_and_preserves_artifact_sources():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        long_title = " ".join(["Extended newsroom headline"] * 18)
        append_source_items(
            tuple(
                source_item_from_fetch_entry(
                    source_id=f"alexis_source_{index}",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title=f"{long_title} {index}",
                    link=f"https://example.com/long-{index}",
                    published=f"2026-05-18T{8 + index:02d}:00:00+00:00",
                    fetched_at=f"2026-05-18T{8 + index:02d}:01:00+00:00",
                )
                for index in range(6)
            ),
            store_path=store_path,
        )
        result = maybe_run_news_summary_workflow(
            text="What's happening today?",
            store_path=store_path,
            max_items=6,
            generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
        )

    assert result is not None
    assert result.artifact is not None
    assert len(result.response) <= RSS_TELEGRAM_SAFE_MAX_CHARS
    assert len([line for line in result.response.splitlines() if line.startswith("- ")]) <= 5
    assert RSS_MORE_NOTICE in result.response
    assert len(result.artifact["source_refs"]) > 5


def test_news_summary_cache_path_respects_global_forced_dry_run():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=2)
        previous = os.environ.get("CLOUD_DRY_RUN")
        os.environ["CLOUD_DRY_RUN"] = "true"
        try:
            result = maybe_run_news_summary_workflow(
                text="Give me a news briefing",
                store_path=store_path,
                generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
            )
        finally:
            if previous is None:
                os.environ.pop("CLOUD_DRY_RUN", None)
            else:
                os.environ["CLOUD_DRY_RUN"] = previous

    assert result is not None
    assert result.cache_hit is True
    assert result.cache_authorization["provider"] == "rss_metadata_cache"
    assert result.cache_authorization["dry_run"] is True
    assert result.cache_authorization["cloud_dry_run"] is True
    assert result.cache_authorization["workflow_dry_run"] is False
    assert result.cache_authorization["authorization"] == "dry_run_forced"
    assert result.cache_authorization["dry_run_forced_by"] == ["cloud_dry_run"]
    assert result.cache_authorization["external_call_performed"] is False


def test_news_summary_cache_path_respects_explicit_workflow_dry_run():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=2)
        previous = os.environ.get("CLOUD_DRY_RUN")
        os.environ["CLOUD_DRY_RUN"] = "false"
        try:
            result = maybe_run_news_summary_workflow(
                text="Give me a news briefing",
                store_path=store_path,
                generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
                workflow_dry_run=True,
            )
        finally:
            if previous is None:
                os.environ.pop("CLOUD_DRY_RUN", None)
            else:
                os.environ["CLOUD_DRY_RUN"] = previous

    assert result is not None
    assert result.cache_hit is True
    assert result.cache_authorization["provider"] == "rss_metadata_cache"
    assert result.cache_authorization["dry_run"] is True
    assert result.cache_authorization["cloud_dry_run"] is False
    assert result.cache_authorization["workflow_dry_run"] is True
    assert result.cache_authorization["authorization"] == "dry_run_forced"
    assert result.cache_authorization["dry_run_forced_by"] == ["workflow_dry_run"]
    assert result.cache_authorization["external_call_performed"] is False


def test_empty_cache_fails_closed_cleanly():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        result = maybe_run_news_summary_workflow(
            text="Summarize the latest news",
            store_path=store_path,
        )

    assert result is not None
    assert result.cache_hit is False
    assert result.artifact is not None
    assert validate_insufficient_coverage_result(result.artifact)
    assert result.artifact["reason"] == INSUFFICIENCY_REASON_STALE_SOURCES
    assert "stale sources" in result.response


def test_each_insufficiency_reason_validates_and_renders():
    policy = {
        "max_item_age": 7200,
        "max_fetch_age": 7200,
        "minimum_fresh_items": 2,
        "minimum_source_count": 2,
    }
    now = datetime(2026, 5, 20, 10, tzinfo=timezone.utc)
    cases = {
        INSUFFICIENCY_REASON_STALE_SOURCES: (),
        INSUFFICIENCY_REASON_STALE_ITEMS: (
            source_item_from_fetch_entry(
                source_id="alexis_source_a",
                owning_agent="alexis",
                governance_state="audit_only",
                manifest_path="agents/alexis/source_feeds.json",
                title="Stale published item",
                link="https://example.com/stale-item",
                published="2026-05-17T10:00:00+00:00",
                fetched_at="2026-05-20T09:59:00+00:00",
            ),
        ),
        INSUFFICIENCY_REASON_FETCH_HEALTH_FAILED: (
            source_item_from_fetch_entry(
                source_id="alexis_source_a",
                owning_agent="alexis",
                governance_state="audit_only",
                manifest_path="agents/alexis/source_feeds.json",
                title="Stale source fetch",
                link="https://example.com/stale-source-fetch",
                published="2026-05-20T09:00:00+00:00",
                fetched_at="2026-05-17T09:00:00+00:00",
            ),
        ),
        INSUFFICIENCY_REASON_INSUFFICIENT_SOURCE_DIVERSITY: (
            source_item_from_fetch_entry(
                source_id="alexis_source_a",
                owning_agent="alexis",
                governance_state="audit_only",
                manifest_path="agents/alexis/source_feeds.json",
                title="Fresh one",
                link="https://example.com/fresh-one",
                published="2026-05-20T09:00:00+00:00",
                fetched_at="2026-05-20T09:01:00+00:00",
            ),
            source_item_from_fetch_entry(
                source_id="alexis_source_a",
                owning_agent="alexis",
                governance_state="audit_only",
                manifest_path="agents/alexis/source_feeds.json",
                title="Fresh two",
                link="https://example.com/fresh-two",
                published="2026-05-20T09:30:00+00:00",
                fetched_at="2026-05-20T09:31:00+00:00",
            ),
        ),
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE: (
            source_item_from_fetch_entry(
                source_id="alexis_source_a",
                owning_agent="alexis",
                governance_state="audit_only",
                manifest_path="agents/alexis/source_feeds.json",
                title="Markets close higher",
                link="https://example.com/markets",
                published="2026-05-20T09:00:00+00:00",
                fetched_at="2026-05-20T09:01:00+00:00",
            ),
        ),
    }

    for reason, items in cases.items():
        evaluation = evaluate_source_item_freshness(
            items,
            policy=policy,
            now=now,
            topic_entity_focus=(
                {"topics": ["Iran"], "entities": []}
                if reason == INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
                else None
            ),
            candidate_item_count=len(items),
            topic_matched_item_count=(
                0
                if reason == INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
                else len(items)
            ),
        )
        artifact = build_insufficient_coverage_result(
            evaluation=evaluation,
            workflow_id=NEWS_SUMMARY_WORKFLOW_ID,
            generated_at=now,
        )
        rendered = render_insufficient_coverage_result(artifact)

        assert artifact is not None
        assert artifact["reason"] == reason
        assert validate_insufficient_coverage_result(artifact)
        assert artifact["provenance"]["cloud_web_fallback_triggered"] is False
        assert artifact["retrieval_metadata"]["insufficiency_reason"] == reason
        assert artifact["source_refs"] == list(evaluation.source_refs)
        assert reason.replace("_", " ") in rendered
        assert "broader web sources" in rendered


def test_runtime_summary_request_does_not_trigger_fetch_model_or_memory():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path, count=2)
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Summarize the latest news",
            )
        finally:
            _restore_runtime_blockers(originals)
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert "Latest news briefing:" in response
    assert captured["events"][-1]["event_type"] == (
        "agent_local_workflow_completed"
    )
    assert captured["events"][-1]["payload"]["execution_mode"] == "cache_only"
    assert captured["events"][-1]["payload"]["artifact_type"] == "summary"
    assert captured["events"][-1]["payload"]["summary_kind"] == (
        "latest_news_briefing"
    )


def test_workflow_source_has_no_hidden_retrieval_or_delivery_paths():
    workflow_source = (
        ROOT / "agents/alexis/workflows/news_summary_workflow.py"
    ).read_text(encoding="utf-8")
    artifact_source = (ROOT / "runtime/artifacts/summary.py").read_text(
        encoding="utf-8"
    )
    combined = f"{workflow_source}\n{artifact_source}".lower()
    forbidden = (
        "urlopen",
        "fetch_declared_rss",
        "openai",
        "embedding",
        "persist_conversation_memory",
        "telegram",
        "article_body",
        "raw_feed",
    )

    assert all(term not in combined for term in forbidden)


def _install_runtime_blockers(captured):
    originals = {
        "execute_request": request_runner.execute_request,
        "load_session_memory": request_runner.load_session_memory,
        "build_context_packet": request_runner.build_context_packet,
        "persist_conversation_memory": request_runner.persist_conversation_memory,
        "persist_runtime_result": request_runner.persist_runtime_result,
        "report_event": request_runner.report_event,
        "report_memory_snapshot": request_runner.report_memory_snapshot,
        "plan_request": request_runner.plan_request,
    }

    def blocked(name):
        def _raise(*_args, **_kwargs):
            raise AssertionError(f"{name} must not be called")

        return _raise

    def fake_report_event(source_bot, event_type, payload, request_id=None):
        captured["events"].append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    request_runner.execute_request = blocked("execute_request")
    request_runner.load_session_memory = blocked("load_session_memory")
    request_runner.build_context_packet = blocked("build_context_packet")
    request_runner.persist_conversation_memory = blocked(
        "persist_conversation_memory"
    )
    request_runner.persist_runtime_result = blocked("persist_runtime_result")
    request_runner.report_event = fake_report_event
    request_runner.report_memory_snapshot = blocked("report_memory_snapshot")
    request_runner.plan_request = blocked("plan_request")
    return originals


def _restore_runtime_blockers(originals):
    for name, value in originals.items():
        setattr(request_runner, name, value)


def main():
    test_news_summary_request_recognizer_is_explicit()
    test_alexis_news_summary_workflow_returns_source_grounded_artifact()
    test_news_summary_only_uses_cached_metadata_items()
    test_rss_brief_transform_preserves_source_refs_without_execution()
    test_rss_brief_transform_without_active_brief_fails_closed()
    test_rss_corpus_synthesis_collapses_cross_posted_duplicates()
    test_rss_cluster_ranking_prefers_fresh_multi_source_cluster()
    test_business_briefing_uses_rss_corpus_synthesis()
    test_runtime_trending_topics_uses_rss_synthesis_without_model_path()
    test_news_summary_accepts_topic_focus_and_rejects_off_topic_items()
    test_news_summary_topic_aliases_support_foreign_affairs_adequacy()
    test_news_summary_topic_focus_fails_closed_when_coverage_missing()
    test_news_summary_bounded_item_limit_enforced()
    test_news_summary_cache_path_respects_global_forced_dry_run()
    test_news_summary_cache_path_respects_explicit_workflow_dry_run()
    test_empty_cache_fails_closed_cleanly()
    test_each_insufficiency_reason_validates_and_renders()
    test_runtime_summary_request_does_not_trigger_fetch_model_or_memory()
    test_workflow_source_has_no_hidden_retrieval_or_delivery_paths()
    print("PASS alexis news summary workflow")


if __name__ == "__main__":
    main()
