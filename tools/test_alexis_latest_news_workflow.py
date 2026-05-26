import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime.request_runner as request_runner  # noqa: E402
from agents.alexis import AlexisAgent  # noqa: E402
from agents.alexis.workflows.latest_news_workflow import (  # noqa: E402
    extract_latest_news_topic_focus,
    is_latest_news_request,
    maybe_run_latest_news_workflow,
)
from agents.alexis.workflows.rss_cache_introspection_workflow import (  # noqa: E402
    maybe_run_rss_cache_introspection_workflow,
)
from agents.alexis.topic_normalization import (  # noqa: E402
    normalize_alexis_rss_topic_focus,
)
from runtime.artifacts.insufficient_coverage import (  # noqa: E402
    INSUFFICIENT_COVERAGE_RESULT_ARTIFACT,
    validate_insufficient_coverage_result,
)
from runtime.ingestion.source_item_store import (  # noqa: E402
    FRESHNESS_STATUS_INSUFFICIENT_COVERAGE,
    FRESHNESS_STATUS_STALE,
    INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE,
    INSUFFICIENCY_REASON_STALE_ITEMS,
    INSUFFICIENCY_REASON_STALE_SOURCES,
    append_source_items,
    source_item_from_fetch_entry,
)
from runtime.conversation_continuity import (  # noqa: E402
    ConversationContinuity,
    ConversationTurn,
)
from runtime.workflows.rss_adequacy import (  # noqa: E402
    RSS_COVERAGE_ADEQUACY_ARTIFACT,
    validate_rss_coverage_adequacy,
)
from runtime.workflows.rss_cloud_escalation import (  # noqa: E402
    RSS_CLOUD_ESCALATION_RESULT_ARTIFACT,
    validate_rss_cloud_escalation_result,
)
from runtime.workflows.rss_cache_introspection import (  # noqa: E402
    RSS_CACHE_INTROSPECTION_ARTIFACT,
    validate_rss_cache_introspection,
)
from runtime.policies.rss_cloud_fallback_eligibility import (  # noqa: E402
    FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    FALLBACK_TIER_RSS_FIRST,
    FALLBACK_TIER_SEARCH_API,
    evaluate_premium_cloud_web_deep_fallback_eligibility,
    load_rss_cloud_fallback_eligibility_policy,
    RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT,
    validate_premium_cloud_web_deep_fallback_eligibility,
    validate_rss_cloud_fallback_eligibility,
)


def seed_items(store_path):
    older = source_item_from_fetch_entry(
        source_id="alexis_source_a",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Older cached headline",
        link="https://example.com/older",
        published="2026-05-21T08:00:00+00:00",
        fetched_at="2026-05-21T08:01:00+00:00",
    )
    newer = source_item_from_fetch_entry(
        source_id="alexis_source_b",
        owning_agent="alexis",
        governance_state="audit_only",
        manifest_path="agents/alexis/source_feeds.json",
        title="Newer cached headline",
        link="https://example.com/newer",
        published="2026-05-21T09:00:00+00:00",
        fetched_at="2026-05-21T09:01:00+00:00",
    )
    append_source_items((older, newer), store_path=store_path)


def test_request_recognizer_is_explicit_and_bounded():
    assert is_latest_news_request("Alexis, what are the latest news?")
    assert is_latest_news_request("What's the latest news?")
    assert is_latest_news_request("latest news")
    assert is_latest_news_request("What’s the latest news on Iran?")
    assert is_latest_news_request("What’s the latest on Trump?")
    assert not is_latest_news_request("please fetch news now")
    assert extract_latest_news_topic_focus("What’s the latest on Trump?") == "trump"
    assert (
        extract_latest_news_topic_focus(
            "What’s the latest on this sprawling noisy sentence "
            "with too many extra words?"
        )
        is None
    )


def test_alexis_latest_news_workflow_returns_bounded_cached_items():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        result = maybe_run_latest_news_workflow(
            text="Alexis, what are the latest news?",
            store_path=store_path,
            max_items=1,
        )

    assert result is not None
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
    assert result.artifact["artifact_type"] == "summary"
    assert result.artifact["summary_kind"] == "latest_news_briefing"
    assert result.artifact["cache_authorization"]["dry_run"] is False
    assert result.item_count == 1
    assert result.adequacy_artifact["artifact_type"] == (
        RSS_COVERAGE_ADEQUACY_ARTIFACT
    )
    assert result.adequacy_artifact["adequate"] is True
    assert result.adequacy_artifact["outcome"] == "adequate"
    assert validate_rss_coverage_adequacy(result.adequacy_artifact)
    fallback_eligibility = result.adequacy_artifact["fallback_eligibility"]
    assert validate_rss_cloud_fallback_eligibility(fallback_eligibility)
    assert fallback_eligibility["artifact_type"] == (
        RSS_CLOUD_FALLBACK_ELIGIBILITY_ARTIFACT
    )
    assert fallback_eligibility["eligible"] is False
    assert fallback_eligibility["reason"] == "rss_coverage_adequate"
    assert fallback_eligibility["eligibility_reason"] == "rss_coverage_adequate"
    assert fallback_eligibility["execution_status"] == "dry_run_ineligible"
    assert fallback_eligibility["fallback_provider_type"] == "search_api"
    assert fallback_eligibility["fallback_provider_id"] == "search_api"
    assert fallback_eligibility["fallback_order"] == [
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    ]
    premium_tier = fallback_eligibility["fallback_tiers"][2]
    assert premium_tier["tier_id"] == FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM
    assert premium_tier["active_by_default"] is False
    assert premium_tier["execution_allowed"] is False
    assert premium_tier["premium"] is True
    assert premium_tier["requires_prior_inadequacy"] == [
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
    ]
    assert fallback_eligibility["dry_run"] is True
    assert fallback_eligibility["dry_run_allowed"] is True
    assert fallback_eligibility["live_allowed"] is False
    assert fallback_eligibility["external_call_performed"] is False
    assert fallback_eligibility["cost_incurred"] is False
    assert fallback_eligibility["cloud_web_fallback_triggered"] is False
    assert result.cloud_escalation_artifact is None
    assert "Latest news briefing:" in result.response
    assert "Newer cached headline" in result.response
    assert "Fresh RSS item" in result.response
    assert "Fresh through May 21, 2026, 09:00 UTC" in result.response
    assert "<i>S1 - May 21, 2026, 09:00 UTC</i>" in result.response
    assert "artifact_type" not in result.response
    assert "source_refs" not in result.response
    assert "retrieval_metadata" not in result.response
    assert len(
        [line for line in result.response.splitlines() if line.startswith("- ")]
    ) <= 5
    assert result.artifact["synthesis_kind"] == "rss_corpus_synthesis"


def test_alexis_latest_news_workflow_accepts_topic_focus():
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
                    published="2026-05-21T10:00:00+00:00",
                    fetched_at="2026-05-21T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-21T11:00:00+00:00",
                    fetched_at="2026-05-21T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_latest_news_workflow(
            text="Alexis, what are the latest news?",
            store_path=store_path,
            max_items=5,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result is not None
    assert result.cache_hit is True
    assert result.item_count == 1
    assert "Iran nuclear talks resume" in result.response
    assert "European markets close higher" not in result.response


def test_alexis_latest_news_topic_aliases_feed_adequacy_not_routing():
    normalization = normalize_alexis_rss_topic_focus(
        {"topics": ["Iran"], "entities": []}
    )
    assert normalization.requested_record() == {
        "topics": ["iran"],
        "entities": [],
    }
    assert "tehran" in normalization.matching_record()["topics"]
    assert normalization.provenance["matching_boundary"] == (
        "cluster_relevance_and_rss_adequacy_only"
    )
    assert normalization.provenance["search_api_called"] is False
    assert is_latest_news_request("Can you discuss Tehran?") is False

    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        append_source_items(
            (
                source_item_from_fetch_entry(
                    source_id="alexis_world_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="Tehran signals movement on nuclear talks",
                    link="https://example.com/tehran",
                    published="2026-05-21T10:00:00+00:00",
                    fetched_at="2026-05-21T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-21T11:00:00+00:00",
                    fetched_at="2026-05-21T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_latest_news_workflow(
            text="Alexis, what are the latest news?",
            store_path=store_path,
            max_items=5,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result is not None
    assert result.cache_hit is True
    assert result.item_count == 1
    assert "Tehran signals movement on nuclear talks" in result.response
    assert "European markets close higher" not in result.response
    assert result.retrieval_metadata["topic_entity_focus"] == {
        "topics": ["iran"],
        "entities": [],
    }
    topic_normalization = result.retrieval_metadata["topic_normalization"]
    assert topic_normalization["matched_family_ids"] == ["iran"]
    assert "tehran" in topic_normalization["matching_focus"]["topics"]
    assert result.adequacy_artifact["topic_entity_focus"] == {
        "topics": ["iran"],
        "entities": [],
    }
    assert result.adequacy_artifact["provenance"]["web_search_executed"] is False
    assert result.cloud_escalation_artifact is None


def test_alexis_latest_news_workflow_extracts_topic_from_request():
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
                    published="2026-05-21T10:00:00+00:00",
                    fetched_at="2026-05-21T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-21T11:00:00+00:00",
                    fetched_at="2026-05-21T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        result = maybe_run_latest_news_workflow(
            text="What’s the latest news on Iran?",
            store_path=store_path,
            max_items=5,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result is not None
    assert result.cache_hit is True
    assert result.artifact is not None
    assert result.artifact["artifact_type"] == "summary"
    assert "Iran nuclear talks resume" in result.response
    assert "European markets close higher" not in result.response


def test_alexis_latest_news_workflow_compacts_latest_on_topic_focus():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        result = maybe_run_latest_news_workflow(
            text="What’s the latest on Trump?",
            store_path=store_path,
            max_items=5,
        )

    assert result is not None
    assert result.cache_hit is False
    assert result.freshness_status == FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
    assert result.retrieval_metadata["topic_entity_focus"] == {
        "topics": ["trump"],
        "entities": [],
    }
    assert result.artifact is not None
    assert validate_insufficient_coverage_result(result.artifact)
    assert result.artifact["topic_entity_focus"] == {
        "topics": ["trump"],
        "entities": [],
    }
    assert result.artifact["reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert "<b>Topic focus</b>" in result.response
    assert "trump." in result.response
    assert "What’s the latest on Trump" not in result.response


def test_alexis_latest_news_topic_focus_fails_closed_when_inadequate():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        result = maybe_run_latest_news_workflow(
            text="Alexis, what are the latest news?",
            store_path=store_path,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result is not None
    assert result.cache_hit is False
    assert result.item_count == 0
    assert result.freshness_status == FRESHNESS_STATUS_INSUFFICIENT_COVERAGE
    assert result.artifact is not None
    assert validate_insufficient_coverage_result(result.artifact)
    assert result.adequacy_artifact["adequate"] is False
    assert result.adequacy_artifact["outcome"] == "inadequate"
    assert result.adequacy_artifact["insufficiency_reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert validate_rss_coverage_adequacy(result.adequacy_artifact)
    fallback_eligibility = result.adequacy_artifact["fallback_eligibility"]
    assert validate_rss_cloud_fallback_eligibility(fallback_eligibility)
    assert fallback_eligibility["eligible"] is True
    assert fallback_eligibility["reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert fallback_eligibility["eligibility_reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert fallback_eligibility["execution_status"] == "dry_run_eligible"
    assert fallback_eligibility["fallback_provider_type"] == "search_api"
    assert fallback_eligibility["fallback_provider_id"] == "search_api"
    assert fallback_eligibility["fallback_order"] == [
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    ]
    assert fallback_eligibility["dry_run"] is True
    assert fallback_eligibility["dry_run_allowed"] is True
    assert fallback_eligibility["live_allowed"] is False
    assert fallback_eligibility["execution_allowed"] is False
    assert fallback_eligibility["provider_execution_allowed"] is False
    assert fallback_eligibility["external_call_performed"] is False
    assert fallback_eligibility["cost_incurred"] is False
    assert fallback_eligibility["cloud_web_fallback_triggered"] is False
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
    assert "fallback_provider_type_not_cloud_ai" in result.cloud_escalation_artifact[
        "skipped_reasons"
    ]
    assert result.artifact["artifact_type"] == INSUFFICIENT_COVERAGE_RESULT_ARTIFACT
    assert result.artifact["reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert result.artifact["topic_entity_focus"] == {
        "topics": ["iran"],
        "entities": [],
    }
    assert result.artifact["metrics"]["candidate_item_count"] == 2
    assert result.artifact["metrics"]["topic_matched_item_count"] == 0
    assert result.artifact["fallback_eligibility"]["fallback_provider_type"] == (
        "search_api"
    )
    assert result.artifact["fallback_eligibility"]["fallback_provider_id"] == (
        "search_api"
    )
    assert result.artifact["fallback_eligibility"]["live_allowed"] is False
    assert result.artifact["fallback_eligibility"]["dry_run"] is True
    assert "insufficient topic coverage" in result.response
    assert "<b>Topic focus</b>" in result.response
    assert "iran." in result.response
    assert "0 fresh / 2 candidate; 0 topic matches" in result.response
    assert "search_api; live=no; dry_run=yes." in result.response


def test_latest_news_premium_fallback_requires_rss_and_search_api_inadequacy():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        result = maybe_run_latest_news_workflow(
            text="Alexis, what are the latest news?",
            store_path=store_path,
            topic_entity_focus={"topics": ["Iran"], "entities": []},
        )

    assert result is not None
    assert result.adequacy_artifact["outcome"] == "inadequate"
    without_search_api = evaluate_premium_cloud_web_deep_fallback_eligibility(
        rss_adequacy_artifact=result.adequacy_artifact,
        search_api_adequacy_artifact=None,
    )

    assert validate_premium_cloud_web_deep_fallback_eligibility(
        without_search_api
    )
    assert without_search_api["eligible"] is False
    assert without_search_api["prior_inadequacy_satisfied"] is False
    assert without_search_api["rss_inadequate"] is True
    assert without_search_api["search_api_inadequate"] is False
    assert "search_api_inadequacy_required" in without_search_api["skipped_reasons"]
    assert without_search_api["active_by_default"] is False
    assert without_search_api["execution_allowed"] is False
    assert without_search_api["external_call_performed"] is False
    assert without_search_api["cost_incurred"] is False

    search_api_inadequacy = {
        "artifact_type": "search_api_coverage_adequacy",
        "outcome": "inadequate",
        "adequate": False,
        "source_refs": [],
    }
    with_search_api = evaluate_premium_cloud_web_deep_fallback_eligibility(
        rss_adequacy_artifact=result.adequacy_artifact,
        search_api_adequacy_artifact=search_api_inadequacy,
    )

    assert validate_premium_cloud_web_deep_fallback_eligibility(with_search_api)
    assert with_search_api["eligible"] is True
    assert with_search_api["prior_inadequacy_satisfied"] is True
    assert with_search_api["requires_prior_inadequacy"] == [
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
    ]
    assert with_search_api["provider"]["provider_id"] == (
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM
    )
    assert with_search_api["explicit_governance_required"] is True
    assert with_search_api["source_fidelity_required"] is True
    assert with_search_api["source_refs_required"] is True
    assert with_search_api["citations_required"] is True
    assert with_search_api["cost_awareness_required"] is True
    assert with_search_api["source_normalization_required_before_summary"] is True
    assert with_search_api["execution_allowed"] is False
    assert with_search_api["external_call_performed"] is False
    assert with_search_api["cost_incurred"] is False


def test_fallback_policy_declares_premium_order_without_activation():
    policy = load_rss_cloud_fallback_eligibility_policy(ROOT)

    assert policy.fallback_order == (
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
        FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM,
    )
    tiers = {tier.tier_id: tier for tier in policy.fallback_tiers}
    assert tiers[FALLBACK_TIER_SEARCH_API].requires_prior_inadequacy == (
        FALLBACK_TIER_RSS_FIRST,
    )
    premium = tiers[FALLBACK_TIER_CLOUD_WEB_DEEP_PREMIUM]
    assert premium.requires_prior_inadequacy == (
        FALLBACK_TIER_RSS_FIRST,
        FALLBACK_TIER_SEARCH_API,
    )
    assert premium.active_by_default is False
    assert premium.execution_allowed is False
    assert premium.premium is True
    assert premium.metadata["provider_capability"] == "cloud_web_deep"
    assert premium.metadata["explicit_governance_required"] is True
    assert premium.metadata["source_fidelity_required"] is True
    assert premium.metadata["source_refs_required"] is True
    assert premium.metadata["citations_required"] is True
    assert premium.metadata["cost_awareness_required"] is True


def test_empty_cache_returns_fail_closed_no_data_response():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        result = maybe_run_latest_news_workflow(
            text="Alexis, what are the latest news?",
            store_path=store_path,
        )

    assert result is not None
    assert result.cache_hit is False
    assert result.item_count == 0
    assert result.artifact is not None
    assert validate_insufficient_coverage_result(result.artifact)
    assert result.artifact["reason"] == INSUFFICIENCY_REASON_STALE_SOURCES
    assert "stale sources" in result.response


def test_latest_news_stale_readable_cache_returns_update_needed_response():
    previous = os.environ.get("CLOUD_DRY_RUN")
    os.environ["CLOUD_DRY_RUN"] = "true"
    try:
        with TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "source_items.jsonl"
            append_source_items(
                (
                    source_item_from_fetch_entry(
                        source_id="alexis_stale_source",
                        owning_agent="alexis",
                        governance_state="audit_only",
                        manifest_path="agents/alexis/source_feeds.json",
                        title="Old cached headline",
                        link="https://example.com/old",
                        published="2026-05-10T08:00:00+00:00",
                        fetched_at="2026-05-21T08:01:00+00:00",
                    ),
                ),
                store_path=store_path,
            )
            result = maybe_run_latest_news_workflow(
                text="What's the latest news?",
                store_path=store_path,
                now=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
            )
    finally:
        if previous is None:
            os.environ.pop("CLOUD_DRY_RUN", None)
        else:
            os.environ["CLOUD_DRY_RUN"] = previous

    assert result is not None
    assert result.cache_hit is False
    assert result.freshness_status == FRESHNESS_STATUS_STALE
    assert result.artifact is not None
    assert validate_insufficient_coverage_result(result.artifact)
    assert result.artifact["reason"] == INSUFFICIENCY_REASON_STALE_ITEMS
    assert result.tavily_fallback_pilot is None
    assert result.cloud_escalation_artifact is not None
    assert result.cloud_escalation_artifact["execution_allowed"] is False
    assert "Latest news briefing:" in result.response
    assert "RSS cache stale - stale items." in result.response
    assert "Fresh through May 10, 2026, 08:00 UTC" in result.response
    assert "Run the RSS ingestion workflow" in result.response
    assert "explicit governed Tavily authorization is required" in result.response
    assert "Cloud/web lookup is currently disabled" not in result.response
    assert "artifact_type" not in result.response
    assert "source_refs" not in result.response
    assert "retrieval_metadata" not in result.response
    assert "raw_provider_payload" not in result.response


def test_runtime_latest_news_request_does_not_trigger_fetch_or_model_path():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        request_runner.session_active_artifacts.clear()
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Alexis, what are the latest news?",
            )
        finally:
            _restore_runtime_blockers(originals)
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert "Newer cached headline" in response
    assert captured["events"][-1]["event_type"] == (
        "agent_local_workflow_completed"
    )
    assert captured["events"][-1]["payload"]["execution_mode"] == "cache_only"
    gate_event = next(
        event
        for event in captured["events"]
        if event["event_type"] == "rss_first_routing_gate_decision"
    )
    assert gate_event["payload"]["applicable"] is True
    assert gate_event["payload"]["ready"] is True
    assert gate_event["payload"]["source_manifest_ready"] is True
    assert gate_event["payload"]["provider"] == "rss_metadata_cache"
    assert gate_event["payload"]["dry_run"] is False
    assert gate_event["payload"]["cloud_dry_run"] is False
    assert gate_event["payload"]["workflow_dry_run"] is False
    assert gate_event["payload"]["authorization"] == "local_cache_authorized"
    assert gate_event["payload"]["authorization_status"] == "local_cache_authorized"
    assert gate_event["payload"]["dry_run_forced_by"] == []
    assert gate_event["payload"]["external_call_performed"] is False
    assert gate_event["payload"]["cost_incurred"] is False
    assert gate_event["payload"]["adequacy_artifact_type"] == (
        RSS_COVERAGE_ADEQUACY_ARTIFACT
    )
    assert gate_event["payload"]["adequacy_outcome"] == "adequate"
    assert gate_event["payload"]["adequacy"]["provenance"][
        "cloud_web_fallback_triggered"
    ] is False
    assert gate_event["payload"]["fallback_eligibility"]["eligible"] is False
    assert gate_event["payload"]["fallback_eligibility"][
        "fallback_provider_type"
    ] == "search_api"
    assert gate_event["payload"]["fallback_eligibility"][
        "fallback_provider_id"
    ] == "search_api"
    assert gate_event["payload"]["fallback_execution_status"] == (
        "dry_run_ineligible"
    )
    assert gate_event["payload"]["cloud_escalation"] is None
    diagnostics = gate_event["payload"]["retrieval_diagnostics"]
    assert diagnostics["diagnostic_type"] == "latest_news_retrieval_decision"
    assert diagnostics["rss_adequacy"]["outcome"] == "adequate"
    assert diagnostics["handoff"]["eligible"] is False
    assert diagnostics["provider_authorization"]["authorization_status"] == (
        "audit_only"
    )
    assert diagnostics["execution_disabled_state"]["execution_disabled"] is True
    assert diagnostics["retrieval_executed"] is False
    assert diagnostics["external_call_performed"] is False


def test_runtime_rss_brief_followup_transforms_session_artifact_without_model():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        request_runner.session_active_artifacts.clear()
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            first_response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Alexis, what are the latest news?",
            )
            second_response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Make it punchier",
            )
        finally:
            _restore_runtime_blockers(originals)
            request_runner.session_active_artifacts.clear()
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert "Latest news briefing:" in first_response
    assert "Punchier RSS brief:" in second_response
    assert "Newer cached headline" in second_response
    assert "artifact_type" not in second_response
    assert "source_refs" not in second_response
    transform_event = captured["events"][-1]
    assert transform_event["event_type"] == "agent_local_workflow_completed"
    assert transform_event["payload"]["workflow_id"] == "alexis_rss_brief_transform"
    assert transform_event["payload"]["execution_mode"] == (
        "session_artifact_transform"
    )
    assert transform_event["payload"]["transform_type"] == "punchy"
    assert transform_event["payload"]["external_call_performed"] is False
    assert transform_event["payload"]["search_api_executed"] is False
    assert transform_event["payload"]["cloud_call_performed"] is False
    assert transform_event["payload"]["article_body_fetched"] is False


def test_runtime_tighter_brief_attaches_session_rss_artifact_without_model():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        request_runner.session_active_artifacts.clear()
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Alexis, what are the latest news?",
            )
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Give me a tighter brief",
            )
        finally:
            _restore_runtime_blockers(originals)
            request_runner.session_active_artifacts.clear()
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert "Tighter RSS brief:" in response
    assert "Newer cached headline" in response
    transform_event = captured["events"][-1]
    assert transform_event["event_type"] == "agent_local_workflow_completed"
    assert transform_event["payload"]["workflow_id"] == "alexis_rss_brief_transform"
    assert transform_event["payload"]["provider"] == "session_active_rss_brief"
    assert transform_event["payload"]["execution_mode"] == (
        "session_artifact_transform"
    )
    assert transform_event["payload"]["transform_type"] == "tighten"
    assert transform_event["payload"]["artifact_type"] == "summary"
    assert transform_event["payload"]["summary_kind"] == "latest_news_briefing"
    assert transform_event["payload"]["external_call_performed"] is False
    assert transform_event["payload"]["search_api_executed"] is False
    assert transform_event["payload"]["cloud_call_performed"] is False
    assert transform_event["payload"]["article_body_fetched"] is False


def test_runtime_rss_brief_followup_without_session_artifact_fails_closed():
    with TemporaryDirectory() as tmp:
        result = AlexisAgent(
            workspace_path=str(Path(tmp) / "workspace")
        ).handle_local_artifact_transform_request(
            text="Make it shorter",
            active_artifact=None,
        )

    assert result is not None
    assert "I need an active RSS news briefing to transform" in result.response
    assert result.workflow_id == "alexis_rss_brief_transform"
    assert result.cache_hit is False


def test_runtime_topic_latest_news_short_circuits_to_rss_without_cloud_web():
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
                    published="2026-05-21T10:00:00+00:00",
                    fetched_at="2026-05-21T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-21T11:00:00+00:00",
                    fetched_at="2026-05-21T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="What’s the latest news on Iran?",
            )
        finally:
            _restore_runtime_blockers(originals)
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert "Iran nuclear talks resume" in response
    assert "European markets close higher" not in response
    gate_event = next(
        event
        for event in captured["events"]
        if event["event_type"] == "rss_first_routing_gate_decision"
    )
    assert gate_event["payload"]["applicable"] is True
    assert gate_event["payload"]["ready"] is True
    assert gate_event["payload"]["provider"] == "rss_metadata_cache"
    assert gate_event["payload"]["dry_run"] is False
    assert gate_event["payload"]["authorization"] == "local_cache_authorized"
    assert gate_event["payload"]["authorization_status"] == "local_cache_authorized"
    assert gate_event["payload"]["dry_run_forced_by"] == []
    assert gate_event["payload"]["external_call_performed"] is False
    assert gate_event["payload"]["artifact_type"] == "summary"
    assert gate_event["payload"]["fallback_execution_status"] == (
        "dry_run_ineligible"
    )
    assert captured["events"][-1]["event_type"] == (
        "agent_local_workflow_completed"
    )


def test_runtime_rss_first_gate_fails_closed_when_cache_not_ready():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        captured = {"events": []}
        originals = _install_rss_gate_failure_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="Alexis, what are the latest news?",
            )
        finally:
            _restore_runtime_blockers(originals)
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    gate_event = next(
        event
        for event in captured["events"]
        if event["event_type"] == "rss_first_routing_gate_decision"
    )
    assert gate_event["payload"]["applicable"] is True
    assert gate_event["payload"]["ready"] is False
    assert gate_event["payload"]["provider"] == "rss_metadata_cache"
    assert gate_event["payload"]["dry_run"] is False
    assert gate_event["payload"]["execution_class"] == "local_cache_read"
    assert gate_event["payload"]["dry_run_effect"] == "not_applicable"
    assert gate_event["payload"]["authorization"] == "insufficient_coverage"
    assert gate_event["payload"]["external_call_performed"] is False
    assert gate_event["payload"]["cost_incurred"] is False
    assert gate_event["payload"]["cache_hit"] is False
    assert gate_event["payload"]["adequacy_outcome"] == "inadequate"
    assert gate_event["payload"]["adequacy"]["adequate"] is False
    assert gate_event["payload"]["fallback_eligibility"]["eligible"] is True
    assert gate_event["payload"]["fallback_eligibility"][
        "fallback_provider_type"
    ] == "search_api"
    assert gate_event["payload"]["fallback_eligibility"][
        "fallback_provider_id"
    ] == "search_api"
    assert gate_event["payload"]["fallback_provider_type"] == "search_api"
    assert gate_event["payload"]["fallback_provider_id"] == "search_api"
    assert gate_event["payload"]["fallback_live_allowed"] is False
    assert gate_event["payload"]["fallback_dry_run"] is True
    diagnostics = gate_event["payload"]["retrieval_diagnostics"]
    assert diagnostics["diagnostic_type"] == "latest_news_retrieval_decision"
    assert diagnostics["rss_adequacy"]["outcome"] == "inadequate"
    assert diagnostics["handoff"]["eligible"] is False
    assert diagnostics["provider_authorization"]["authorization_status"] == (
        "audit_only"
    )
    assert diagnostics["execution_disabled_state"]["execution_disabled"] is True
    assert diagnostics["retrieval_executed"] is False
    assert gate_event["payload"]["fallback_execution_status"] == (
        "dry_run_eligible"
    )
    assert gate_event["payload"]["cloud_escalation"]["artifact_type"] == (
        RSS_CLOUD_ESCALATION_RESULT_ARTIFACT
    )
    assert gate_event["payload"]["cloud_escalation_status"] == "not_eligible"
    assert gate_event["payload"]["cloud_escalation_execution_allowed"] is False
    assert "RSS cache readiness failed" in gate_event["payload"]["reason"]
    assert any(
        event["event_type"] == "agent_local_workflow_completed"
        for event in captured["events"]
    )
    assert "stale sources" in response


def test_runtime_topic_latest_news_insufficient_reports_fallback_handoff():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="What’s the latest news on Iran?",
            )
        finally:
            _restore_runtime_blockers(originals)
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    gate_event = next(
        event
        for event in captured["events"]
        if event["event_type"] == "rss_first_routing_gate_decision"
    )
    assert gate_event["payload"]["applicable"] is True
    assert gate_event["payload"]["ready"] is False
    assert gate_event["payload"]["provider"] == "rss_metadata_cache"
    assert gate_event["payload"]["dry_run"] is False
    assert gate_event["payload"]["execution_class"] == "local_cache_read"
    assert gate_event["payload"]["dry_run_effect"] == "not_applicable"
    assert gate_event["payload"]["authorization"] == "insufficient_coverage"
    assert gate_event["payload"]["insufficiency_reason"] == (
        INSUFFICIENCY_REASON_INSUFFICIENT_TOPIC_COVERAGE
    )
    assert gate_event["payload"]["topic_entity_focus"] == {
        "topics": ["iran"],
        "entities": [],
    }
    assert gate_event["payload"]["candidate_count"] == 2
    assert gate_event["payload"]["matched_count"] == 0
    assert gate_event["payload"]["fallback_provider_type"] == "search_api"
    assert gate_event["payload"]["fallback_provider_id"] == "search_api"
    assert gate_event["payload"]["fallback_live_allowed"] is False
    assert gate_event["payload"]["fallback_dry_run"] is True
    assert "insufficient topic coverage" in response
    assert "<b>Topic focus</b>" in response
    assert "iran." in response
    assert "search_api; live=no; dry_run=yes." in response


def test_rss_cache_introspection_uses_local_diagnostics_and_insufficiency():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        seed_items(store_path)
        audit_path.write_text(
            "\n".join(
                json.dumps(record, sort_keys=True)
                for record in (
                    {
                        "timestamp": "2026-05-21T08:00:00+00:00",
                        "source_id": "alexis_ap_top_news_rss",
                        "source_type": "rss_feed",
                        "owning_agent": "alexis",
                        "governance_state": "audit_only",
                        "fetch_status": "failed",
                        "fetch_performed": True,
                        "duration_ms": 5,
                        "entry_count": 0,
                        "skipped_reasons": ["network_error"],
                    },
                    {
                        "timestamp": "2026-05-21T08:01:00+00:00",
                        "source_id": "alexis_cnn_top_stories_rss",
                        "source_type": "rss_feed",
                        "owning_agent": "alexis",
                        "governance_state": "audit_only",
                        "fetch_status": "skipped",
                        "fetch_performed": False,
                        "duration_ms": 0,
                        "entry_count": 0,
                        "skipped_reasons": ["feed_too_large"],
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        insufficient = maybe_run_latest_news_workflow(
            text="What’s the latest news on Iran?",
            store_path=store_path,
        )
        result = maybe_run_rss_cache_introspection_workflow(
            text="Why didn’t Iran work?",
            active_artifact=insufficient.artifact,
            audit_path=audit_path,
            item_store_path=store_path,
        )

    assert result is not None
    assert result.artifact["artifact_type"] == RSS_CACHE_INTROSPECTION_ARTIFACT
    assert validate_rss_cache_introspection(result.artifact)
    assert result.artifact["coverage"]["missing_topics"] == [
        {"topic": "iran", "reason": "no_recent_rss_topic_match"},
    ]
    assert result.artifact["feeds"]["failed"][0]["source_id"] == (
        "alexis_ap_top_news_rss"
    )
    assert result.artifact["feeds"]["too_large"][0]["source_id"] == (
        "alexis_cnn_top_stories_rss"
    )
    assert result.artifact["provenance"]["web_search_executed"] is False
    assert result.artifact["provenance"]["model_called"] is False
    assert "RSS cache diagnosis:" in result.response
    assert "Weak or missing" in result.response
    assert "iran" in result.response
    assert "Next step" in result.response
    assert "source_refs" not in result.response
    assert "retrieval_metadata" not in result.response


def test_runtime_rss_cache_introspection_short_circuits_without_cloud_or_model():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        audit_path = Path(tmp) / "source_ingestion_audit.jsonl"
        seed_items(store_path)
        audit_path.write_text("", encoding="utf-8")
        previous_store = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        previous_audit = os.environ.get("JUNIPER_SOURCE_INGESTION_AUDIT_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        os.environ["JUNIPER_SOURCE_INGESTION_AUDIT_PATH"] = str(audit_path)
        request_runner.session_active_artifacts.clear()
        captured = {"events": []}
        originals = _install_runtime_blockers(captured)
        try:
            response = request_runner.run_request(
                source_bot="operator_smoke",
                agent=AlexisAgent(workspace_path=str(Path(tmp) / "workspace")),
                user_id="operator_smoke_user",
                text="What’s missing from the local RSS cache?",
            )
        finally:
            _restore_runtime_blockers(originals)
            request_runner.session_active_artifacts.clear()
            if previous_store is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous_store
            if previous_audit is None:
                os.environ.pop("JUNIPER_SOURCE_INGESTION_AUDIT_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_INGESTION_AUDIT_PATH"] = previous_audit

    assert "RSS cache diagnosis:" in response
    assert captured["events"][-1]["event_type"] == "agent_local_workflow_completed"
    assert captured["events"][-1]["payload"]["workflow_id"] == (
        "alexis_rss_cache_introspection"
    )
    assert captured["events"][-1]["payload"]["execution_mode"] == "cache_only"
    assert captured["events"][-1]["payload"]["external_call_performed"] is False
    assert captured["events"][-1]["payload"]["search_api_executed"] is False
    assert captured["events"][-1]["payload"]["cloud_call_performed"] is False
    assert captured["events"][-1]["payload"]["model_called"] is False


def test_rss_brief_followup_uses_prior_latest_news_context():
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
                    published="2026-05-21T10:00:00+00:00",
                    fetched_at="2026-05-21T10:01:00+00:00",
                ),
                source_item_from_fetch_entry(
                    source_id="alexis_markets_source",
                    owning_agent="alexis",
                    governance_state="audit_only",
                    manifest_path="agents/alexis/source_feeds.json",
                    title="European markets close higher",
                    link="https://example.com/markets",
                    published="2026-05-21T11:00:00+00:00",
                    fetched_at="2026-05-21T11:01:00+00:00",
                ),
            ),
            store_path=store_path,
        )
        previous = os.environ.get("JUNIPER_SOURCE_ITEM_STORE_PATH")
        os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = str(store_path)
        try:
            result = AlexisAgent(
                workspace_path=str(Path(tmp) / "workspace")
            ).handle_rss_first_workflow_request(
                text="Give me the brief",
                continuity=ConversationContinuity(
                    turns=(
                        ConversationTurn(
                            user_text="What’s the latest news on Iran?",
                            assistant_text="Latest news:\n1. Iran nuclear talks resume",
                        ),
                    )
                ),
            )
        finally:
            if previous is None:
                os.environ.pop("JUNIPER_SOURCE_ITEM_STORE_PATH", None)
            else:
                os.environ["JUNIPER_SOURCE_ITEM_STORE_PATH"] = previous

    assert result.applicable is True
    assert result.ready is True
    assert result.workflow_id == "alexis_latest_news_briefing"
    assert result.response is not None
    payload = result.to_event_payload()
    assert payload["provider"] == "rss_metadata_cache"
    assert payload["dry_run"] is False
    assert payload["authorization"] == "local_cache_authorized"
    assert payload["authorization_status"] == "local_cache_authorized"
    assert payload["dry_run_forced_by"] == []
    assert payload["external_call_performed"] is False
    assert "Iran nuclear talks resume" in result.response
    assert "European markets close higher" not in result.response


def test_rss_cache_path_respects_global_forced_dry_run():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous = os.environ.get("CLOUD_DRY_RUN")
        os.environ["CLOUD_DRY_RUN"] = "true"
        try:
            result = maybe_run_latest_news_workflow(
                text="Alexis, what are the latest news?",
                store_path=store_path,
            )
        finally:
            if previous is None:
                os.environ.pop("CLOUD_DRY_RUN", None)
            else:
                os.environ["CLOUD_DRY_RUN"] = previous

    assert result is not None
    assert result.cache_hit is True
    assert result.cache_authorization["provider"] == "rss_metadata_cache"
    assert result.cache_authorization["dry_run"] is False
    assert result.cache_authorization["dry_run_effect"] == (
        "allowed_local_free_execution"
    )
    assert result.cache_authorization["cloud_dry_run"] is True
    assert result.cache_authorization["workflow_dry_run"] is False
    assert result.cache_authorization["authorization"] == "local_cache_authorized"
    assert result.cache_authorization["dry_run_forced_by"] == ["cloud_dry_run"]
    assert result.cache_authorization["external_call_performed"] is False


def test_rss_cache_path_respects_explicit_workflow_dry_run():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous = os.environ.get("CLOUD_DRY_RUN")
        os.environ["CLOUD_DRY_RUN"] = "false"
        try:
            result = maybe_run_latest_news_workflow(
                text="Alexis, what are the latest news?",
                store_path=store_path,
                workflow_dry_run=True,
            )
        finally:
            if previous is None:
                os.environ.pop("CLOUD_DRY_RUN", None)
            else:
                os.environ["CLOUD_DRY_RUN"] = previous

    assert result is not None
    assert result.cache_hit is True
    assert result.cache_authorization["dry_run"] is False
    assert result.cache_authorization["dry_run_effect"] == (
        "allowed_local_free_execution"
    )
    assert result.cache_authorization["cloud_dry_run"] is False
    assert result.cache_authorization["workflow_dry_run"] is True
    assert result.cache_authorization["authorization"] == "local_cache_authorized"
    assert result.cache_authorization["dry_run_forced_by"] == ["workflow_dry_run"]
    assert result.cache_authorization["external_call_performed"] is False


def test_rss_cache_rendering_ignores_ingestion_source_plan_dry_run_env():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        previous_cloud = os.environ.get("CLOUD_DRY_RUN")
        previous_plan = os.environ.get("JUNIPER_SOURCE_PLAN_MODE")
        os.environ["CLOUD_DRY_RUN"] = "false"
        os.environ["JUNIPER_SOURCE_PLAN_MODE"] = "dry_run"
        try:
            result = maybe_run_latest_news_workflow(
                text="Alexis, what are the latest news?",
                store_path=store_path,
            )
        finally:
            if previous_cloud is None:
                os.environ.pop("CLOUD_DRY_RUN", None)
            else:
                os.environ["CLOUD_DRY_RUN"] = previous_cloud
            if previous_plan is None:
                os.environ.pop("JUNIPER_SOURCE_PLAN_MODE", None)
            else:
                os.environ["JUNIPER_SOURCE_PLAN_MODE"] = previous_plan

    assert result is not None
    assert result.cache_hit is True
    assert result.cache_authorization["dry_run"] is False
    assert result.cache_authorization["authorization"] == "local_cache_authorized"
    assert result.cache_authorization["dry_run_forced_by"] == []


def test_rss_brief_followup_without_context_does_not_force_rss():
    result = AlexisAgent(workspace_path=".").handle_rss_first_workflow_request(
        text="Give me the brief",
        continuity=ConversationContinuity(turns=()),
    )

    assert result.applicable is False
    assert result.ready is False


def test_workflow_output_is_deterministic_and_source_grounded():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        first = maybe_run_latest_news_workflow(
            text="what are the latest news",
            store_path=store_path,
            max_items=2,
        )
        second = maybe_run_latest_news_workflow(
            text="what are the latest news",
            store_path=store_path,
            max_items=2,
        )

    assert first is not None and second is not None
    assert first.response == second.response
    assert "Fresh RSS item" in first.response
    assert "<i>S1 - May 21, 2026, 09:00 UTC</i>" in first.response


def test_workflow_output_contains_no_forbidden_runtime_content():
    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        result = maybe_run_latest_news_workflow(
            text="latest news",
            store_path=store_path,
        )

    assert result is not None
    forbidden = (
        "ARTICLE BODY",
        "RAW CONTENT",
        "system:",
        "assistant:",
        "embedding",
        "persist_conversation_memory",
        "telegram",
    )
    assert all(term not in result.response for term in forbidden)


def test_operator_smoke_command_uses_same_cache_workflow():
    from tools.alexis_latest_news_smoke import run_latest_news_smoke

    with TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "source_items.jsonl"
        seed_items(store_path)
        output = run_latest_news_smoke(store_path=store_path, max_items=1)

    assert output["handled"] is True
    assert output["workflow_id"] == "alexis_latest_news"
    assert output["item_count"] == 1
    assert "Newer cached headline" in output["response"]


def test_no_live_fetch_or_hidden_runtime_paths_in_workflow_source():
    workflow_source = (
        ROOT / "agents/alexis/workflows/latest_news_workflow.py"
    ).read_text(encoding="utf-8")
    smoke_source = (ROOT / "tools/alexis_latest_news_smoke.py").read_text(
        encoding="utf-8"
    )
    combined = f"{workflow_source}\n{smoke_source}".lower()
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


def _install_rss_gate_failure_blockers(captured):
    originals = {
        "plan_request": request_runner.plan_request,
        "report_event": request_runner.report_event,
    }

    def fake_report_event(source_bot, event_type, payload, request_id=None):
        captured["events"].append(
            {
                "source_bot": source_bot,
                "event_type": event_type,
                "payload": payload,
                "request_id": request_id,
            }
        )

    def stop_after_gate(*_args, **_kwargs):
        raise RuntimeError("stop after RSS-first gate")

    request_runner.report_event = fake_report_event
    request_runner.plan_request = stop_after_gate
    return originals


def main():
    test_request_recognizer_is_explicit_and_bounded()
    test_alexis_latest_news_workflow_returns_bounded_cached_items()
    test_alexis_latest_news_workflow_accepts_topic_focus()
    test_alexis_latest_news_topic_aliases_feed_adequacy_not_routing()
    test_alexis_latest_news_workflow_extracts_topic_from_request()
    test_alexis_latest_news_workflow_compacts_latest_on_topic_focus()
    test_alexis_latest_news_topic_focus_fails_closed_when_inadequate()
    test_latest_news_premium_fallback_requires_rss_and_search_api_inadequacy()
    test_fallback_policy_declares_premium_order_without_activation()
    test_empty_cache_returns_fail_closed_no_data_response()
    test_latest_news_stale_readable_cache_returns_update_needed_response()
    test_runtime_latest_news_request_does_not_trigger_fetch_or_model_path()
    test_runtime_rss_brief_followup_transforms_session_artifact_without_model()
    test_runtime_tighter_brief_attaches_session_rss_artifact_without_model()
    test_runtime_rss_brief_followup_without_session_artifact_fails_closed()
    test_runtime_topic_latest_news_short_circuits_to_rss_without_cloud_web()
    test_runtime_rss_first_gate_fails_closed_when_cache_not_ready()
    test_runtime_topic_latest_news_insufficient_reports_fallback_handoff()
    test_rss_cache_introspection_uses_local_diagnostics_and_insufficiency()
    test_runtime_rss_cache_introspection_short_circuits_without_cloud_or_model()
    test_rss_brief_followup_uses_prior_latest_news_context()
    test_rss_cache_path_respects_global_forced_dry_run()
    test_rss_cache_path_respects_explicit_workflow_dry_run()
    test_rss_cache_rendering_ignores_ingestion_source_plan_dry_run_env()
    test_rss_brief_followup_without_context_does_not_force_rss()
    test_workflow_output_is_deterministic_and_source_grounded()
    test_workflow_output_contains_no_forbidden_runtime_content()
    test_operator_smoke_command_uses_same_cache_workflow()
    test_no_live_fetch_or_hidden_runtime_paths_in_workflow_source()
    print("PASS alexis latest news workflow")


if __name__ == "__main__":
    main()
