import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.artifacts.external_discovery_result import (  # noqa: E402
    EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT,
    build_external_discovery_result_set,
    validate_external_discovery_result_set,
)
from runtime.registries.artifacts import (  # noqa: E402
    get_artifact_config,
    load_artifact_registry,
)


def _valid_result_set():
    return build_external_discovery_result_set(
        provider_metadata={
            "provider_id": "search_api",
            "provider_type": "search_api",
            "request_id": "provider-request-123",
            "rate_limit_remaining": 42,
        },
        raw_provider_payload={
            "items": [
                {
                    "id": "provider-result-1",
                    "title": "Example source title",
                    "url": "https://example.test/source",
                    "snippet": "Provider-supplied snippet.",
                }
            ],
            "provider_specific": {
                "ranking_score": 0.87,
                "page": 1,
            },
        },
        raw_results=[
            {
                "provider_result_id": "provider-result-1",
                "raw_title": "Example source title",
                "raw_url": "https://example.test/source",
                "raw_snippet": "Provider-supplied snippet.",
            }
        ],
        source_refs=[
            {
                "source_ref_id": "source-ref-1",
                "provider_result_id": "provider-result-1",
                "source_url": "https://example.test/source",
                "source_type": "web_page",
                "title": "Example source title",
            }
        ],
        citations=[
            {
                "citation_id": "citation-1",
                "source_ref_id": "source-ref-1",
                "provider_result_id": "provider-result-1",
                "source_url": "https://example.test/source",
                "quote": "Provider-supplied snippet.",
            }
        ],
    )


def test_external_discovery_result_artifact_is_registered():
    load_artifact_registry.cache_clear()
    config = get_artifact_config(EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT)

    assert config["semantic_class"] == "external_discovery_raw_result"
    assert config["bounded"] is True
    assert config["persist_as_artifact"] is True
    assert config["formatting_constraints"]["provider_execution_allowed"] is False
    assert config["formatting_constraints"]["normalization_allowed"] is False
    assert config["formatting_constraints"]["delivery_allowed"] is False


def test_raw_external_discovery_result_artifact_validates():
    artifact = _valid_result_set()

    assert artifact["artifact_type"] == EXTERNAL_DISCOVERY_RESULT_SET_ARTIFACT
    assert validate_external_discovery_result_set(artifact) == ()


def test_citations_and_source_refs_are_preserved():
    artifact = _valid_result_set()

    assert artifact["source_refs"] == [
        {
            "source_ref_id": "source-ref-1",
            "provider_result_id": "provider-result-1",
            "source_url": "https://example.test/source",
            "source_type": "web_page",
            "title": "Example source title",
        }
    ]
    assert artifact["citations"] == [
        {
            "citation_id": "citation-1",
            "source_ref_id": "source-ref-1",
            "provider_result_id": "provider-result-1",
            "source_url": "https://example.test/source",
            "quote": "Provider-supplied snippet.",
        }
    ]
    assert validate_external_discovery_result_set(artifact) == ()


def test_live_search_api_result_requires_source_refs():
    artifact = _valid_result_set()
    artifact["provider_metadata"].update(
        {
            "dry_run": False,
            "live_authorized": True,
            "provider_call_implemented": True,
            "external_call_performed": True,
            "execution_state": "live_adapter_executed",
        }
    )
    artifact["provenance"].update(
        {
            "dry_run": False,
            "live_authorized": True,
            "provider_call_implemented": True,
            "external_call_performed": True,
            "execution_state": "live_adapter_executed",
        }
    )
    artifact["source_refs"] = []

    errors = validate_external_discovery_result_set(artifact)

    assert "accepted_result_missing_source_ref" in {
        error.error_code for error in errors
    }


def test_provider_metadata_is_preserved():
    artifact = _valid_result_set()

    assert artifact["provider_metadata"] == {
        "provider_id": "search_api",
        "provider_type": "search_api",
        "request_id": "provider-request-123",
        "rate_limit_remaining": 42,
    }
    assert artifact["provenance"]["provider_id"] == "search_api"
    assert artifact["provenance"]["provider_type"] == "search_api"
    assert validate_external_discovery_result_set(artifact) == ()


def test_no_guest_candidate_normalization_occurs():
    artifact = _valid_result_set()

    assert artifact["artifact_type"] != "guest_candidate_list"
    assert "candidates" not in artifact
    assert "guest_candidate_list" not in artifact
    assert artifact["provenance"]["normalization_performed"] is False
    assert artifact["provenance"]["ranking_performed"] is False
    assert artifact["provenance"]["selection_performed"] is False

    artifact["candidates"] = []
    artifact["provenance"]["normalization_performed"] = True

    errors = validate_external_discovery_result_set(artifact)
    fields = {error.field for error in errors}

    assert "candidates" in fields
    assert "provenance.normalization_performed" in fields


def test_no_provider_execution_occurs():
    artifact = _valid_result_set()

    assert artifact["provenance"]["provider_execution_performed"] is False
    assert artifact["provenance"]["provider_executed"] is False
    assert artifact["provenance"]["web_search_executed"] is False
    assert artifact["provenance"]["search_api_called"] is False
    assert artifact["provenance"]["browser_api_called"] is False
    assert artifact["provenance"]["cloud_model_called"] is False
    assert artifact["provenance"]["external_adapter_called"] is False
    assert artifact["provenance"]["delivery_performed"] is False

    artifact["provenance"]["search_api_called"] = True

    errors = validate_external_discovery_result_set(artifact)

    assert "provenance.search_api_called" in {
        error.field
        for error in errors
    }


def test_external_discovery_result_module_has_no_execution_paths():
    source = (
        ROOT / "runtime" / "artifacts" / "external_discovery_result.py"
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
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
    )

    assert all(term not in lowered for term in forbidden)


def main():
    test_external_discovery_result_artifact_is_registered()
    test_raw_external_discovery_result_artifact_validates()
    test_citations_and_source_refs_are_preserved()
    test_live_search_api_result_requires_source_refs()
    test_provider_metadata_is_preserved()
    test_no_guest_candidate_normalization_occurs()
    test_no_provider_execution_occurs()
    test_external_discovery_result_module_has_no_execution_paths()
    print("PASS external discovery result artifact")


if __name__ == "__main__":
    main()
