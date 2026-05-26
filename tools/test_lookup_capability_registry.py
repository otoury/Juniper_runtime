import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.lookup_capability_registry import (  # noqa: E402
    audit_lookup_capability_registrations,
    discover_lookup_capabilities,
    resolve_lookup_capability,
    validate_lookup_capability_registration,
)
from runtime.lookup.execution import execute_lookup_request  # noqa: E402


def generic_binding():
    return {
        "shared_capability": "summarize_entity",
        "skills": [],
        "resources": ["directory_adapter"],
        "lookup_capability_compatibility": {
            "contract_version": 1,
            "min_runtime_version": 1,
            "max_runtime_version": 1,
            "required_features": [
                "exact_entity_lookup",
                "bounded_context_materialization",
            ],
        },
        "lookup_request_policy": {
            "enabled": True,
            "lookup_type": "exact_entity_lookup",
            "entity_type": "person",
            "source_scope": "directory_scope",
            "allowed_source_scopes": ["directory_scope"],
            "required_planner_fields": ["entity_name"],
            "optional_planner_fields": ["workflow_topic"],
        },
        "lookup_context_materialization_policy": {
            "enabled": True,
            "context_type": "bounded_lookup_result",
            "allowed_fields": ["display_name", "role"],
            "max_fields": 2,
        },
        "lookup_context_render_policy": {
            "allowed": True,
            "render_modes": ["structured_fact_block"],
            "max_packets": 1,
            "require_successful_retrieval": True,
            "allowed_context_types": ["bounded_lookup_result"],
            "allowed_lookup_types": ["exact_entity_lookup"],
            "allowed_source_scopes": ["directory_scope"],
            "allowed_entity_types": ["person"],
            "field_order": ["display_name", "role"],
            "field_labels": {
                "display_name": "Display name",
                "role": "Role",
            },
        },
        "lookup_context_injection_policy": {
            "allowed": True,
            "require_render_decision": True,
            "require_rendered_context": True,
            "allowed_content_types": ["lookup_context_block"],
            "allowed_render_modes": ["structured_fact_block"],
            "max_blocks": 1,
            "max_facts_per_block": 2,
            "max_total_characters": 600,
            "truncation_mode": "drop_tail",
        },
    }


def write_manifest(root, agent_name, bindings):
    path = (
        Path(root)
        / "agents"
        / agent_name
        / "capabilities"
        / "bindings.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"bindings": bindings}, indent=2),
        encoding="utf-8",
    )
    return path


def test_alexis_lookup_capability_is_discoverable():
    registrations = discover_lookup_capabilities(root=ROOT, agents=("alexis",))
    metadata = [registration.to_metadata() for registration in registrations]
    by_capability = {
        item["shared_capability"]: item
        for item in metadata
    }

    assert len(metadata) == 2
    assert set(by_capability) == {"draft_email", "discover_entities"}
    exact = by_capability["draft_email"]
    assert exact["agent"] == "alexis"
    assert exact["capability_type"] == "lookup_context_pipeline"
    assert exact["contract_version"] == 1
    assert exact["min_runtime_version"] == 1
    assert exact["max_runtime_version"] == 1
    assert "exact_entity_lookup" in exact["required_features"]
    assert exact["supported_lookup_types"] == ["exact_entity_lookup"]
    assert exact["render_modes"] == ["structured_fact_block"]
    assert exact["injection_enabled"] is True
    assert exact["governance_state"] == "enabled"
    assert exact["timeout_ms"] == 3000
    assert exact["cancellation_behavior"] == "fail_closed"
    assert exact["max_concurrent_lookups"] == 4


def test_alexis_bounded_entity_search_capability_is_discoverable():
    registrations = discover_lookup_capabilities(root=ROOT, agents=("alexis",))
    metadata = [
        registration.to_metadata()
        for registration in registrations
        if registration.shared_capability == "discover_entities"
    ]

    assert len(metadata) == 1
    bounded = metadata[0]
    assert bounded["agent"] == "alexis"
    assert bounded["binding_id"] == "bounded_guest_search"
    assert bounded["supported_lookup_types"] == ["bounded_entity_search"]
    assert bounded["source_scopes"] == ["alexis_guest_canonical_csv"]
    assert bounded["adapter_owners"] == ["guest_db"]
    assert bounded["governance_state"] == "audit_only"
    assert bounded["injection_enabled"] is True


def test_alexis_lookup_capability_resolves_through_registry():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="draft_email",
        root=ROOT,
    )

    assert hasattr(resolved, "registration")
    assert resolved.registration.agent == "alexis"
    assert resolved.registration.shared_capability == "draft_email"
    assert resolved.compatibility.contract_version == 1
    assert resolved.compatibility.min_runtime_version == 1
    assert resolved.compatibility.max_runtime_version == 1
    assert resolved.registration.supported_lookup_types == (
        "exact_entity_lookup",
    )
    assert resolved.policy_section("lookup_request_policy")[
        "lookup_type"
    ] == "exact_entity_lookup"


def test_alexis_bounded_entity_search_binding_validates():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="discover_entities",
        root=ROOT,
    )

    assert hasattr(resolved, "registration")
    assert resolved.registration.binding_id == "bounded_guest_search"
    assert resolved.registration.supported_lookup_types == (
        "bounded_entity_search",
    )
    request_policy = resolved.policy_section("lookup_request_policy")
    assert request_policy["lookup_type"] == "bounded_entity_search"
    assert request_policy["entity_type"] == "guest"
    assert request_policy["source_scope"] == "alexis_guest_canonical_csv"
    assert request_policy["execution_status"] == "implemented"
    assert request_policy["max_results"] == 5
    materialization_policy = resolved.policy_section(
        "lookup_context_materialization_policy"
    )
    assert materialization_policy["allowed_fields"] == [
        "display_name",
        "title",
        "expertise",
        "public_booking_notes",
        "known_contact_channels",
    ]


def test_bounded_entity_search_execution_fails_closed_not_implemented():
    resolved = resolve_lookup_capability(
        agent="alexis",
        shared_capability="discover_entities",
        root=ROOT,
    )
    result = execute_lookup_request(
        agent=object(),
        lookup_request={
            "lookup_type": "bounded_entity_search",
            "lookup_id": "bounded-search-execution-attempt",
            "search_topic": "healthcare reform",
            "entity_type": "guest",
            "source_scope": "alexis_guest_canonical_csv",
            "max_results": 5,
        },
        lookup_capability=resolved,
        require_lookup_capability=True,
    )

    assert result.retrieval_executed is False
    assert result.payloads == []
    assert result.skipped_reasons == (
        "lookup_capability_audit_only",
    )


def test_generic_non_alexis_lookup_capability_validates():
    with TemporaryDirectory() as tmp:
        write_manifest(
            tmp,
            "neutral_agent",
            {"summarize_entity": generic_binding()},
        )

        registrations, errors = audit_lookup_capability_registrations(
            root=tmp,
        )

    assert errors == ()
    assert len(registrations) == 1
    metadata = registrations[0].to_metadata()
    assert metadata == {
        "agent": "neutral_agent",
        "binding_id": "summarize_entity",
        "shared_capability": "summarize_entity",
        "capability_type": "lookup_context_pipeline",
        "retrieval_concept": "retrieval",
        "retrieval_specialization": "lookup",
        "retrieval_scope": "bounded",
        "retrieval_authority": (
            "planner_declared_runtime_orchestrated_agent_bound"
        ),
        "retrieval_types": ["exact_entity_lookup"],
        "contract_version": 1,
        "min_runtime_version": 1,
        "max_runtime_version": 1,
        "required_features": [
            "exact_entity_lookup",
            "bounded_context_materialization",
        ],
        "supported_lookup_types": ["exact_entity_lookup"],
        "source_scopes": ["directory_scope"],
        "render_modes": ["structured_fact_block"],
        "injection_enabled": True,
        "governance_state": "enabled",
        "timeout_ms": 3000,
        "cancellation_behavior": "fail_closed",
        "max_concurrent_lookups": 1,
        "adapter_owners": ["directory_adapter"],
    }


def test_malformed_lookup_capability_fails_closed():
    bad = generic_binding()
    bad["lookup_request_policy"] = {
        **bad["lookup_request_policy"],
        "lookup_type": "semantic_search",
    }

    errors = validate_lookup_capability_registration(bad)

    assert errors
    assert any(error.field == "lookup_request_policy.lookup_type" for error in errors)


def test_malformed_governance_fails_closed():
    bad = generic_binding()
    bad["lookup_capability_governance"] = {"state": "shadow_mode"}

    errors = validate_lookup_capability_registration(bad)

    assert errors
    assert any(error.field == "lookup_capability_governance" for error in errors)


def test_malformed_execution_policy_fails_closed():
    bad = generic_binding()
    bad["lookup_execution_policy"] = {
        "timeout_ms": 0,
        "cancellation_behavior": "fail_closed",
    }

    errors = validate_lookup_capability_registration(bad)

    assert errors
    assert any(error.field == "lookup_execution_policy.policy" for error in errors)


def test_unsupported_contract_version_fails_closed():
    bad = generic_binding()
    bad["lookup_capability_compatibility"] = {
        **bad["lookup_capability_compatibility"],
        "contract_version": 99,
    }

    errors = validate_lookup_capability_registration(bad)

    assert errors
    assert any(
        error.field == "lookup_capability_compatibility.policy"
        for error in errors
    )


def test_unsupported_runtime_range_fails_closed():
    bad = generic_binding()
    bad["lookup_capability_compatibility"] = {
        **bad["lookup_capability_compatibility"],
        "min_runtime_version": 2,
        "max_runtime_version": 3,
    }

    errors = validate_lookup_capability_registration(bad)

    assert errors
    assert any(
        error.field == "lookup_capability_compatibility.policy"
        for error in errors
    )


def test_unknown_required_feature_fails_closed():
    bad = generic_binding()
    bad["lookup_capability_compatibility"] = {
        **bad["lookup_capability_compatibility"],
        "required_features": ["semantic_search"],
    }

    errors = validate_lookup_capability_registration(bad)

    assert errors
    assert any(
        error.field == "lookup_capability_compatibility.policy"
        for error in errors
    )


def test_discovery_does_not_return_malformed_registrations():
    bad = generic_binding()
    del bad["lookup_context_injection_policy"]

    with TemporaryDirectory() as tmp:
        write_manifest(tmp, "neutral_agent", {"summarize_entity": bad})
        registrations, errors = audit_lookup_capability_registrations(
            root=tmp,
        )

    assert registrations == ()
    assert errors
    assert any("lookup_context_injection_policy" in error.field for error in errors)


def test_missing_lookup_capability_resolution_fails_closed():
    error = resolve_lookup_capability(
        agent="alexis",
        shared_capability="producer_note",
        root=ROOT,
    )

    assert error.field == "lookup_capability"
    assert "not found" in error.message


def test_registry_code_remains_domain_neutral():
    source = (
        ROOT
        / "runtime"
        / "registries"
        / "lookup_capability_registry.py"
    ).read_text(encoding="utf-8")

    forbidden = ("guest", "booking", "alexis_guest", "guest_db")
    lowered = source.lower()
    assert all(term not in lowered for term in forbidden)


def main():
    test_alexis_lookup_capability_is_discoverable()
    test_alexis_bounded_entity_search_capability_is_discoverable()
    test_alexis_lookup_capability_resolves_through_registry()
    test_alexis_bounded_entity_search_binding_validates()
    test_bounded_entity_search_execution_fails_closed_not_implemented()
    test_generic_non_alexis_lookup_capability_validates()
    test_malformed_lookup_capability_fails_closed()
    test_malformed_governance_fails_closed()
    test_malformed_execution_policy_fails_closed()
    test_unsupported_contract_version_fails_closed()
    test_unsupported_runtime_range_fails_closed()
    test_unknown_required_feature_fails_closed()
    test_discovery_does_not_return_malformed_registrations()
    test_missing_lookup_capability_resolution_fails_closed()
    test_registry_code_remains_domain_neutral()
    print("PASS lookup capability registry")


if __name__ == "__main__":
    main()
