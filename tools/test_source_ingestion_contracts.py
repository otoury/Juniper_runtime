import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.source_ingestion_registry import (  # noqa: E402
    audit_agent_source_ingestion_declarations,
    audit_source_ingestion_declarations,
    audit_source_ingestion_declarations_from_path,
    load_source_ingestion_contracts,
    load_source_ingestion_declarations,
    validate_source_ingestion_declaration,
    validate_source_ingestion_readiness,
)


def valid_declaration():
    return {
        "source_id": "neutral_bbc_world_rss",
        "contract_id": "source_ingestion_rss_feed",
        "source_type": "rss_feed",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "owning_agent": "neutral_agent",
        "governance_state": "audit_only",
        "refresh_policy": {
            "type": "manual",
        },
        "source_category": {
            "category": "global_news",
            "topic_tags": ["world", "breaking_news"],
        },
        "priority_policy": {
            "level": "normal",
            "rationale": "Production-like source declaration for contract validation.",
        },
        "provenance_policy": {
            "citation_required": True,
            "source_url_required": True,
            "attribution_required": True,
            "prose_only_output_allowed": False,
        },
        "provenance_audit": {
            "required": True,
        },
        "content_safety": {
            "raw_content_storage_allowed": False,
            "prompt_injection_surface_allowed": False,
            "summary_generation_allowed": False,
        },
        "storage_policy": {
            "memory_write_allowed": False,
            "article_storage_allowed": False,
            "metadata_storage_allowed": True,
        },
    }


def write_registry(root, declarations):
    source = ROOT / "agents/shared/semantics/source_ingestion_contracts.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["source_declarations"] = declarations
    path = Path(root) / "agents/shared/semantics/source_ingestion_contracts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_alexis_manifest(root, declarations):
    path = Path(root) / "agents/alexis/source_feeds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "agent": "alexis",
                "source_declarations": declarations,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def raw_alexis_sources():
    data = json.loads(
        (ROOT / "agents/alexis/source_feeds.json").read_text(encoding="utf-8")
    )
    return data["source_declarations"]


def test_valid_rss_source_contract_loads():
    contracts = load_source_ingestion_contracts(root=ROOT)

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.id == "source_ingestion_rss_feed"
    assert contract.source_type == "rss_feed"
    assert set(contract.governance_states) == {
        "enabled",
        "disabled",
        "audit_only",
    }


def test_valid_rss_source_declaration_loads():
    with TemporaryDirectory() as tmp:
        write_registry(tmp, [valid_declaration()])
        declarations, errors = audit_source_ingestion_declarations(root=tmp)

    assert errors == ()
    assert len(declarations) == 1
    metadata = declarations[0].to_metadata()
    assert metadata["source_id"] == "neutral_bbc_world_rss"
    assert metadata["source_type"] == "rss_feed"
    assert metadata["url"] == "https://feeds.bbci.co.uk/news/world/rss.xml"
    assert metadata["owning_agent"] == "neutral_agent"
    assert metadata["governance_state"] == "audit_only"
    assert metadata["source_category"]["category"] == "global_news"
    assert metadata["source_category"]["topic_tags"] == [
        "world",
        "breaking_news",
    ]
    assert metadata["priority_policy"]["level"] == "normal"
    assert metadata["provenance_policy"]["citation_required"] is True
    assert metadata["storage_policy"]["memory_write_allowed"] is False
    assert metadata["storage_policy"]["metadata_storage_allowed"] is True


def test_missing_url_and_source_id_fail_closed():
    missing_url = valid_declaration()
    del missing_url["url"]
    missing_source_id = valid_declaration()
    del missing_source_id["source_id"]

    url_errors = validate_source_ingestion_declaration(missing_url)
    source_errors = validate_source_ingestion_declaration(missing_source_id)

    assert any(error.field == "url" for error in url_errors)
    assert any(error.field == "source_id" for error in source_errors)


def test_unknown_source_type_fails_closed():
    declaration = valid_declaration()
    declaration["source_type"] = "web_page"

    errors = validate_source_ingestion_declaration(declaration)

    assert errors
    assert any(error.field == "source_type" for error in errors)


def test_unknown_governance_state_fails_closed():
    declaration = valid_declaration()
    declaration["governance_state"] = "shadow"

    errors = validate_source_ingestion_declaration(declaration)

    assert errors
    assert any(error.field == "governance_state" for error in errors)


def test_hidden_autonomous_memory_write_fields_are_rejected():
    declaration = valid_declaration()
    declaration["autonomous_source_creation"] = True
    declaration["refresh_policy"]["background_retrieval"] = True
    declaration["content_safety"]["hidden_prompt"] = "inject"
    declaration["storage_policy"]["memory_write"] = True

    errors = validate_source_ingestion_declaration(declaration)
    fields = {error.field for error in errors}

    assert "autonomous_source_creation" in fields
    assert "refresh_policy.background_retrieval" in fields
    assert "content_safety.hidden_prompt" in fields
    assert "storage_policy.memory_write" in fields


def test_storage_and_content_policy_are_fail_closed():
    declaration = valid_declaration()
    declaration["storage_policy"]["memory_write_allowed"] = True
    declaration["content_safety"]["summary_generation_allowed"] = True

    errors = validate_source_ingestion_declaration(declaration)

    assert any(
        error.field == "storage_policy.memory_write_allowed"
        for error in errors
    )
    assert any(
        error.field == "content_safety.summary_generation_allowed"
        for error in errors
    )


def test_metadata_storage_policy_requires_boolean():
    declaration = valid_declaration()
    declaration["storage_policy"]["metadata_storage_allowed"] = "yes"

    errors = validate_source_ingestion_declaration(declaration)

    assert any(
        error.field == "storage_policy.metadata_storage_allowed"
        for error in errors
    )


def test_production_like_feed_declarations_pass_readiness_validation():
    errors = validate_source_ingestion_readiness(valid_declaration())

    assert errors == []


def test_placeholder_example_feeds_fail_readiness_validation():
    declaration = valid_declaration()
    declaration["source_id"] = "neutral_example_rss"
    declaration["url"] = "https://example.com/feed.xml"

    errors = validate_source_ingestion_readiness(declaration)
    fields = {error.field for error in errors}

    assert "source_id" in fields
    assert "url" in fields


def test_questionable_nyt_feed_declaration_fails_readiness_validation():
    declaration = valid_declaration()
    declaration["source_id"] = "alexis_nyt_example_rss"
    declaration["url"] = "https://example.com/nyt/rss.xml"
    declaration["owning_agent"] = "alexis"
    declaration["source_category"] = {
        "category": "world",
        "topic_tags": ["nyt", "world", "analysis", "secondary_source"],
    }

    errors = validate_source_ingestion_readiness(declaration)
    fields = {error.field for error in errors}

    assert "source_id" in fields
    assert "url" in fields


def test_registry_validation_is_domain_neutral():
    source = (
        ROOT / "runtime/registries/source_ingestion_registry.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()

    forbidden = ("alexis", "guest", "booking", "business_news")
    assert all(term not in lowered for term in forbidden)


def test_no_network_fetching_occurs():
    declaration = valid_declaration()
    declaration["fetch_callable"] = "fetch_feed"

    with TemporaryDirectory() as tmp:
        write_registry(tmp, [declaration])
        declarations = load_source_ingestion_declarations(root=tmp)
        audited, errors = audit_source_ingestion_declarations(root=tmp)

    registry_source = (
        ROOT / "runtime/registries/source_ingestion_registry.py"
    ).read_text(encoding="utf-8")
    lowered = registry_source.lower()

    assert declarations == ()
    assert audited == ()
    assert errors
    assert any(error.field == "fetch_callable" for error in errors)
    assert "requests" not in lowered
    assert "urllib" not in lowered
    assert "feedparser" not in lowered
    assert "httpx" not in lowered


def test_alexis_source_declarations_validate():
    declarations, errors = audit_agent_source_ingestion_declarations(
        "alexis",
        root=ROOT,
    )

    assert errors == ()
    assert len(declarations) == 17
    assert {declaration.source_type for declaration in declarations} == {
        "rss_feed"
    }
    assert {declaration.owning_agent for declaration in declarations} == {
        "alexis"
    }
    assert {
        declaration.governance_state for declaration in declarations
    } == {"disabled", "audit_only"}
    assert {
        "alexis_ap_top_news_rss",
        "alexis_reuters_top_news_rss",
        "alexis_cnn_top_stories_rss",
        "alexis_axios_news_rss",
        "alexis_bbc_world_news_rss",
        "alexis_bbc_business_news_rss",
        "alexis_abc_news_top_stories_rss",
        "alexis_nyt_world_rss",
        "alexis_nyt_us_rss",
        "alexis_nyt_politics_rss",
        "alexis_newsnation_rss",
        "alexis_foreign_affairs_rss",
        "alexis_foreign_policy_rss",
        "alexis_chatham_house_rss",
        "alexis_ecfr_rss",
        "alexis_sipri_rss",
        "alexis_war_on_the_rocks_rss",
    } == {declaration.source_id for declaration in declarations}
    assert all(
        declaration.storage_policy["metadata_storage_allowed"] is True
        for declaration in declarations
    )
    assert all(
        declaration.storage_policy["memory_write_allowed"] is False
        for declaration in declarations
    )
    nyt_sources = {
        declaration.source_id: declaration
        for declaration in declarations
        if declaration.source_id.startswith("alexis_nyt_")
    }
    assert set(nyt_sources) == {
        "alexis_nyt_world_rss",
        "alexis_nyt_us_rss",
        "alexis_nyt_politics_rss",
    }
    foreign_affairs_sources = {
        declaration.source_id: declaration
        for declaration in declarations
        if declaration.source_category["category"]
        in {"foreign_affairs", "foreign_policy", "security_policy"}
    }
    assert {
        "alexis_foreign_affairs_rss",
        "alexis_foreign_policy_rss",
        "alexis_chatham_house_rss",
        "alexis_ecfr_rss",
        "alexis_sipri_rss",
        "alexis_war_on_the_rocks_rss",
    }.issubset(foreign_affairs_sources)
    assert all(
        "geopolitics" in declaration.source_category["topic_tags"]
        for declaration in foreign_affairs_sources.values()
    )
    assert all(
        declaration.governance_state == "audit_only"
        for declaration in foreign_affairs_sources.values()
    )
    assert all(
        declaration.governance_state == "audit_only"
        for declaration in nyt_sources.values()
    )
    assert all(
        declaration.provenance_policy["citation_required"] is True
        and declaration.provenance_policy["source_url_required"] is True
        and declaration.provenance_policy["attribution_required"] is True
        for declaration in nyt_sources.values()
    )
    assert all(
        declaration.content_safety["raw_content_storage_allowed"] is False
        and declaration.storage_policy["article_storage_allowed"] is False
        for declaration in nyt_sources.values()
    )
    assert all(
        declaration.priority_policy["level"] == "normal"
        and declaration.priority_policy["source_role"] == "secondary_analysis"
        for declaration in nyt_sources.values()
    )
    assert all(
        declaration.raw_data["readiness_check"]["status"] == "declared_official_rss"
        and declaration.raw_data["readiness_check"]["official_source"] is True
        for declaration in nyt_sources.values()
    )
    assert all(
        declaration.content_safety["summary_generation_allowed"] is False
        for declaration in declarations
    )
    assert all(declaration.source_category for declaration in declarations)
    assert all(declaration.priority_policy for declaration in declarations)
    assert all(declaration.provenance_policy for declaration in declarations)
    assert all(
        validate_source_ingestion_readiness(declaration.raw_data) == []
        for declaration in declarations
    )


def test_alexis_missing_url_fails_closed():
    declarations = raw_alexis_sources()
    del declarations[0]["url"]

    with TemporaryDirectory() as tmp:
        path = write_alexis_manifest(tmp, declarations)
        _loaded, errors = audit_source_ingestion_declarations_from_path(
            path,
            root=ROOT,
        )

    assert errors
    assert any(error.field == "url" for error in errors)


def main():
    test_valid_rss_source_contract_loads()
    test_valid_rss_source_declaration_loads()
    test_missing_url_and_source_id_fail_closed()
    test_unknown_source_type_fails_closed()
    test_unknown_governance_state_fails_closed()
    test_hidden_autonomous_memory_write_fields_are_rejected()
    test_storage_and_content_policy_are_fail_closed()
    test_metadata_storage_policy_requires_boolean()
    test_production_like_feed_declarations_pass_readiness_validation()
    test_placeholder_example_feeds_fail_readiness_validation()
    test_questionable_nyt_feed_declaration_fails_readiness_validation()
    test_registry_validation_is_domain_neutral()
    test_no_network_fetching_occurs()
    test_alexis_source_declarations_validate()
    test_alexis_missing_url_fails_closed()
    print("PASS source ingestion contracts")


if __name__ == "__main__":
    main()
