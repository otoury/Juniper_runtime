import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.artifacts.summary import (  # noqa: E402
    build_summary_artifact,
    render_summary_artifact,
    validate_summary_artifact,
)


def source_items(count=6):
    return tuple(
        {
            "item_id": f"item_{index}",
            "source_id": f"source_{index}",
            "title": f"Cached item {index}",
            "link": f"https://example.com/{index}",
            "published": f"2026-05-18T{8 + index:02d}:00:00+00:00",
            "fetched_at": f"2026-05-18T{8 + index:02d}:01:00+00:00",
            "provenance": "fixture_metadata",
        }
        for index in range(count)
    )


def test_generic_summary_artifact_shape_validates():
    artifact = build_summary_artifact(
        source_items=source_items(2),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
        max_words=None,
        max_items=2,
        generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
    )

    assert artifact is not None
    assert validate_summary_artifact(artifact)
    assert artifact["artifact_type"] == "summary"
    assert artifact["summary_kind"] == "operator_briefing"
    assert artifact["tone"] == "neutral"
    assert artifact["max_words"] is None
    assert artifact["max_items"] == 2
    assert artifact["provenance"] == "fixture_metadata"
    assert artifact["generated_at"] == "2026-05-18T12:00:00+00:00"
    assert len(artifact["source_items"]) == 2
    assert len(artifact["source_refs"]) == 2
    assert len(artifact["citations"]) == 2
    assert len(artifact["summary_blocks"]) == 2
    assert artifact["source_items"][0]["source_ref_id"].startswith("rss_")
    assert artifact["source_refs"][0]["source_label"] == "S1"
    assert artifact["summary_blocks"][0]["source_ref_id"] == (
        artifact["source_refs"][0]["source_ref_id"]
    )
    assert artifact["summary_blocks"][0]["citation_id"] == (
        artifact["citations"][0]["citation_id"]
    )


def test_summary_artifact_enforces_bounded_item_limit():
    artifact = build_summary_artifact(
        source_items=source_items(8),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
        max_items=99,
    )

    assert artifact is not None
    assert len(artifact["summary_blocks"]) == 5
    assert len(artifact["source_items"]) == 5
    assert artifact["max_items"] == 5


def test_summary_artifact_supports_custom_block_text():
    artifact = build_summary_artifact(
        source_items=source_items(1),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
        summary_text_builder=lambda item: f"Custom: {item['title']}",
    )
    rendered = render_summary_artifact(artifact, title="Briefing:")

    assert artifact is not None
    assert artifact["summary_blocks"][0]["summary"] == "Custom: Cached item 0"
    assert rendered.splitlines()[0] == "Briefing:"


def test_summary_artifact_preserves_mixed_source_provenance():
    artifact = build_summary_artifact(
        source_items=(
            {
                "item_id": "rss_item_1",
                "source_ref_id": "rss_ref_1",
                "source_id": "rss_source",
                "source_type": "rss_feed",
                "title": "RSS headline",
                "link": "https://example.com/rss",
                "published": "2026-05-18T08:00:00+00:00",
                "fetched_at": "2026-05-18T08:01:00+00:00",
                "provenance": {
                    "kind": "rss_metadata",
                    "owning_agent": "alexis",
                },
            },
            {
                "provider_result_id": "web_result_1",
                "source_ref_id": "web_ref_1",
                "source_id": "cloud_web_source",
                "source_type": "web_page",
                "title": "Cloud web headline",
                "source_url": "https://example.com/web",
                "published": "2026-05-18T09:00:00+00:00",
                "provenance": {
                    "provider_id": "cloud_web_ai",
                    "adapter_id": "fixture",
                },
            },
        ),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="mixed_source_metadata",
        max_items=2,
    )

    assert artifact is not None
    assert validate_summary_artifact(artifact)
    assert artifact["provenance"] == "mixed_source_metadata"
    assert artifact["source_provenance"] == ["cloud_web_ai", "rss_metadata"]
    assert artifact["source_types"] == ["rss_feed", "web_page"]
    assert artifact["source_items"][0]["provenance"] == "rss_metadata"
    assert artifact["source_items"][1]["provenance"] == "cloud_web_ai"
    assert artifact["source_items"][1]["link"] == "https://example.com/web"
    assert artifact["source_items"][1]["item_id"]
    assert artifact["summary_blocks"][1]["source_type"] == "web_page"


def test_summary_artifact_requires_source_grounding():
    artifact = build_summary_artifact(
        source_items=({"item_id": "", "source_id": "source", "title": "Title"},),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
    )

    assert artifact is None


def test_invalid_artifact_missing_grounding_fails_validation():
    artifact = {
        "artifact_type": "summary",
        "summary_kind": "operator_briefing",
        "tone": "neutral",
        "max_words": None,
        "max_items": 5,
        "generated_at": "2026-05-18T12:00:00+00:00",
        "source_items": [],
        "summary_blocks": [],
        "provenance": "fixture_metadata",
    }

    assert validate_summary_artifact(artifact) is False


def test_summary_artifact_missing_source_refs_fails_validation():
    artifact = build_summary_artifact(
        source_items=source_items(1),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
    )

    assert artifact is not None
    artifact.pop("source_refs")

    assert validate_summary_artifact(artifact) is False


def test_summary_artifact_missing_citations_fails_validation():
    artifact = build_summary_artifact(
        source_items=source_items(1),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
    )

    assert artifact is not None
    artifact["citations"] = []

    assert validate_summary_artifact(artifact) is False


def test_rendered_summary_uses_compact_source_labels():
    artifact = build_summary_artifact(
        source_items=source_items(1),
        summary_kind="operator_briefing",
        tone="neutral",
        provenance="fixture_metadata",
        generated_at=datetime(2026, 5, 18, 12, tzinfo=timezone.utc),
    )
    rendered = render_summary_artifact(artifact)

    assert "(S1; 2026-05-18T08:00:00+00:00)" in rendered
    assert "source_refs" not in rendered
    assert "citations" not in rendered


def test_summary_runtime_has_no_domain_specific_module_names():
    runtime_paths = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "runtime").rglob("*.py")
    ]
    forbidden = ("news_summary", "latest_news", "newsroom")

    assert all(
        all(term not in path for term in forbidden)
        for path in runtime_paths
    )


def test_summary_artifact_has_no_fetch_model_memory_or_delivery_behavior():
    source = (ROOT / "runtime/artifacts/summary.py").read_text(encoding="utf-8")
    serialized = json.dumps({"source": source}).lower()
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

    assert all(term not in serialized for term in forbidden)


def main():
    test_generic_summary_artifact_shape_validates()
    test_summary_artifact_enforces_bounded_item_limit()
    test_summary_artifact_supports_custom_block_text()
    test_summary_artifact_preserves_mixed_source_provenance()
    test_summary_artifact_requires_source_grounding()
    test_invalid_artifact_missing_grounding_fails_validation()
    test_summary_artifact_missing_source_refs_fails_validation()
    test_summary_artifact_missing_citations_fails_validation()
    test_rendered_summary_uses_compact_source_labels()
    test_summary_runtime_has_no_domain_specific_module_names()
    test_summary_artifact_has_no_fetch_model_memory_or_delivery_behavior()
    print("PASS summary artifact")


if __name__ == "__main__":
    main()
