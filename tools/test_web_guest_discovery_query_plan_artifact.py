import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.artifacts.web_guest_discovery_query_plan import (  # noqa: E402
    ALLOWED_PREFERRED_SIGNALS,
    WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT,
    build_web_guest_discovery_query_plan,
    preferred_signal_metadata,
    validate_web_guest_discovery_query_plan,
)
from runtime.registries.artifacts import (  # noqa: E402
    get_artifact_config,
    load_artifact_registry,
)


def _valid_plan():
    return build_web_guest_discovery_query_plan(
        discovery_intent="Find outside experts for a segment.",
        topic_entity_focus={
            "topics": ["AI regulation"],
            "entities": ["Federal Trade Commission"],
        },
        preferred_guest_traits=[
            "credible on air",
            "policy expertise",
        ],
        preferred_signals=[
            "has_email_contact",
            "has_video_presence",
        ],
        max_queries=6,
    )


def test_query_plan_artifact_is_registered():
    load_artifact_registry.cache_clear()
    config = get_artifact_config(WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT)

    assert config["semantic_class"] == "booking_research_plan"
    assert config["bounded"] is True
    assert config["persist_as_artifact"] is True
    assert config["formatting_constraints"]["provider_execution_allowed"] is False
    assert (
        config["formatting_constraints"]["generated_search_queries_allowed"]
        is False
    )


def test_query_plan_artifact_validates():
    plan = _valid_plan()

    assert plan["artifact_type"] == WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT
    assert validate_web_guest_discovery_query_plan(plan) == ()


def test_preferred_signal_metadata_validates():
    metadata = [
        preferred_signal_metadata("has_email_contact"),
        preferred_signal_metadata("has_video_presence"),
    ]
    plan = _valid_plan()
    plan["preferred_signals"] = metadata

    assert {item["signal_id"] for item in metadata} == set(
        ALLOWED_PREFERRED_SIGNALS
    )
    assert all(item["metadata_only"] is True for item in metadata)
    assert all(item["execution_required"] is False for item in metadata)
    assert validate_web_guest_discovery_query_plan(plan) == ()


def test_invalid_preferred_signal_metadata_fails_closed():
    plan = _valid_plan()
    plan["preferred_signals"] = [
        {
            "signal_id": "has_recent_publication",
            "metadata_only": False,
            "execution_required": True,
        }
    ]

    errors = validate_web_guest_discovery_query_plan(plan)
    codes = {error.error_code for error in errors}

    assert "unsupported_preferred_signal" in codes
    assert "preferred_signal_not_metadata_only" in codes
    assert "preferred_signal_requires_execution" in codes


def test_no_execution_or_generated_queries_are_allowed():
    plan = _valid_plan()
    plan["search_queries"] = ["AI regulation expert email"]
    plan["provenance"]["web_search_executed"] = True
    plan["provenance"]["cloud_model_called"] = True
    plan["provenance"]["generated_search_queries"] = True

    errors = validate_web_guest_discovery_query_plan(plan)
    fields = {error.field for error in errors}

    assert "search_queries" in fields
    assert "provenance.web_search_executed" in fields
    assert "provenance.cloud_model_called" in fields
    assert "provenance.generated_search_queries" in fields


def test_query_plan_module_has_no_provider_execution_paths():
    source = (
        ROOT / "runtime/artifacts/web_guest_discovery_query_plan.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    forbidden = (
        "requests",
        "urllib",
        "selenium",
        "playwright",
        "beautifulsoup",
        "openai",
        "anthropic",
        "browser.search",
        "webbrowser",
        "google",
        "bing",
        "duckduckgo",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
    )

    assert all(term not in lowered for term in forbidden)


def main():
    test_query_plan_artifact_is_registered()
    test_query_plan_artifact_validates()
    test_preferred_signal_metadata_validates()
    test_invalid_preferred_signal_metadata_fails_closed()
    test_no_execution_or_generated_queries_are_allowed()
    test_query_plan_module_has_no_provider_execution_paths()
    print("PASS web guest discovery query plan artifact")


if __name__ == "__main__":
    main()
