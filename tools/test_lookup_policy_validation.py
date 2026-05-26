import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.lookup.context_budgeting import apply_lookup_context_budget  # noqa: E402
from runtime.lookup.context_injection import maybe_inject_lookup_context  # noqa: E402
from runtime.lookup.context_render_gate import (  # noqa: E402
    evaluate_lookup_context_render_gate,
)
from runtime.lookup.policy_validation import (  # noqa: E402
    LOOKUP_CAPABILITY_CONTRACTS_PATH,
    LOOKUP_EXECUTION_POLICY_PATH,
    LOOKUP_GOVERNANCE_STATES_PATH,
    LOOKUP_RENDER_CONTRACTS_PATH,
    LOOKUP_REQUEST_CONTRACTS_PATH,
    LOOKUP_RUNTIME_COMPATIBILITY_CONTRACTS_PATH,
    get_lookup_capability_contract,
    load_lookup_capability_contracts,
    validate_lookup_capability_policies,
    validate_lookup_capability_compatibility,
    validate_lookup_context_budget_policy,
    validate_lookup_context_injection_policy,
    validate_lookup_context_render_policy,
    validate_lookup_execution_policy,
)
from runtime.bindings import get_binding_manifest  # noqa: E402


def alexis_binding():
    data = get_binding_manifest("alexis", root=ROOT)
    assert isinstance(data, dict), data
    return data["bindings"]["draft_email"]


def alexis_bounded_search_binding():
    data = get_binding_manifest("alexis", root=ROOT)
    assert isinstance(data, dict), data
    return data["bindings"]["bounded_guest_search"]


def generic_binding():
    return {
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
            "entity_type": "entity",
            "source_scope": "bounded_source",
            "allowed_source_scopes": ["bounded_source"],
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
            "allowed_source_scopes": ["bounded_source"],
            "allowed_entity_types": ["entity"],
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
            "max_total_characters": 800,
            "truncation_mode": "drop_tail",
        },
    }


def rendered_context():
    return {
        "render_mode": "structured_fact_block",
        "content_type": "lookup_context_block",
        "blocks": [
            {
                "title": "Retrieved entity context",
                "facts": [
                    {
                        "label": "Display name",
                        "field": "display_name",
                        "value": "Example Entity",
                    }
                ],
                "provenance": {
                    "lookup_id": "lookup-001",
                    "retrieval_executed": True,
                    "records_returned": 1,
                },
            }
        ],
    }


def render_decision():
    return {
        "render_allowed": True,
        "render_mode": "structured_fact_block",
        "packet_ids": ["lookup-001"],
        "reasons": [],
    }


def packet():
    return {
        "context_type": "bounded_lookup_result",
        "lookup_type": "exact_entity_lookup",
        "entity_type": "entity",
        "source_scope": "bounded_source",
        "fields": {"display_name": "Example Entity"},
        "provenance": {
            "lookup_id": "lookup-001",
            "retrieval_executed": True,
            "records_returned": 1,
        },
    }


def error_fields(errors):
    return [error.field for error in errors]


def test_generic_lookup_capability_policy_validates_without_alexis():
    assert validate_lookup_capability_policies(generic_binding()) == []


def test_shared_lookup_capability_contract_manifest_loads():
    contract = get_lookup_capability_contract()

    assert contract is not None
    assert contract.id == "bounded_lookup_context_capability"
    assert contract.capability_type == "lookup_context_pipeline"
    assert contract.retrieval_concept == "retrieval"
    assert contract.retrieval_specialization == "lookup"
    assert contract.retrieval_scope == "bounded"
    assert contract.contract_version == 1
    assert contract.runtime_compatibility_version == 1
    assert "bounded_concurrency" in contract.supported_features
    assert "lookup_request_policy" in contract.required_policy_sections
    assert "exact_entity_lookup" in contract.lookup_types
    assert "structured_fact_block" in contract.render_modes
    assert "bounded_lookup_result" in contract.context_types
    assert "lookup_context_block" in contract.content_types
    assert "drop_tail" in contract.truncation_modes
    assert "enabled" in contract.governance_states
    assert "audit_only" in contract.governance_states
    assert "blocked" in contract.governance_states
    assert "fail_closed" in contract.cancellation_behaviors
    assert "source_scope" in contract.agent_owned_values
    assert "bounded_entity_search" in contract.lookup_types
    assert "bounded_entity_search" in contract.supported_features


def test_shared_lookup_contract_source_files_are_split_by_authority():
    assert not (
        ROOT / "agents/shared/semantics/lookup_capability_contracts.json"
    ).exists()

    paths = (
        LOOKUP_CAPABILITY_CONTRACTS_PATH,
        LOOKUP_RUNTIME_COMPATIBILITY_CONTRACTS_PATH,
        LOOKUP_RENDER_CONTRACTS_PATH,
        LOOKUP_GOVERNANCE_STATES_PATH,
        LOOKUP_EXECUTION_POLICY_PATH,
        LOOKUP_REQUEST_CONTRACTS_PATH,
    )
    assert all((ROOT / path).is_file() for path in paths)

    capability_data = json.loads(
        (ROOT / LOOKUP_CAPABILITY_CONTRACTS_PATH).read_text(encoding="utf-8")
    )
    capability_contract = capability_data["contracts"][0]
    forbidden = {
        "contract_version",
        "runtime_compatibility_version",
        "governance_states",
        "cancellation_behaviors",
        "policy_sections",
        "render_modes",
        "context_types",
        "content_types",
        "truncation_modes",
        "planner_contract",
    }
    assert not (set(capability_contract) & forbidden)


def test_alexis_bounded_entity_search_policy_validates():
    binding = alexis_bounded_search_binding()

    assert validate_lookup_capability_policies(binding) == []
    assert binding["lookup_request_policy"]["lookup_type"] == (
        "bounded_entity_search"
    )
    assert binding["lookup_request_policy"]["execution_status"] == (
        "implemented"
    )


def test_malformed_render_injection_and_budget_policies_validate_and_fail_closed():
    binding = generic_binding()
    bad_render = copy.deepcopy(binding["lookup_context_render_policy"])
    bad_render["max_packets"] = 0
    bad_injection = copy.deepcopy(binding["lookup_context_injection_policy"])
    bad_injection["require_render_decision"] = False
    bad_budget = copy.deepcopy(binding["lookup_context_injection_policy"])
    bad_budget["truncation_mode"] = "semantic_summary"
    bad_execution = {
        "timeout_ms": 0,
        "cancellation_behavior": "fail_closed",
        "max_concurrent_lookups": 1,
    }
    bad_compatibility = {
        "contract_version": 1,
        "min_runtime_version": 2,
        "max_runtime_version": 3,
        "required_features": ["exact_entity_lookup"],
    }
    bad_concurrency = {
        "timeout_ms": 3000,
        "cancellation_behavior": "fail_closed",
        "max_concurrent_lookups": 0,
    }

    assert "max_packets" in error_fields(
        validate_lookup_context_render_policy(bad_render)
    )
    assert evaluate_lookup_context_render_gate(
        lookup_context_packets=[packet()],
        render_policy=bad_render,
    )["render_allowed"] is False

    assert "require_render_decision" in error_fields(
        validate_lookup_context_injection_policy(bad_injection)
    )
    assert maybe_inject_lookup_context(
        [{"role": "user", "content": "Draft"}],
        rendered_lookup_context=rendered_context(),
        render_decision=render_decision(),
        injection_policy=bad_injection,
    ).trace["injection_allowed"] is False

    assert "truncation_mode" in error_fields(
        validate_lookup_context_budget_policy(bad_budget)
    )
    assert apply_lookup_context_budget(
        rendered_lookup_context=rendered_context(),
        budget_policy=bad_budget,
    ).rendered_lookup_context is None

    assert "policy" in error_fields(
        validate_lookup_execution_policy(bad_execution)
    )
    assert "policy" in error_fields(
        validate_lookup_execution_policy(bad_concurrency)
    )
    assert "policy" in error_fields(
        validate_lookup_capability_compatibility(bad_compatibility)
    )


def test_malformed_shared_manifest_fails_closed(tmp_path):
    manifest = tmp_path / LOOKUP_CAPABILITY_CONTRACTS_PATH
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "contracts": [
                    {
                        "id": "bounded_lookup_context_capability",
                        "capability_type": "lookup_context_pipeline",
                        "contract_version": 1,
                        "runtime_compatibility_version": 1,
                        "lookup_types": ["exact_entity_lookup"],
                        "supported_features": ["exact_entity_lookup"],
                        "policy_sections": {
                            "required": ["lookup_request_policy"],
                            "agent_owned_values": [],
                        },
                        "render_modes": ["structured_fact_block"],
                        "context_types": ["bounded_lookup_result"],
                        "content_types": ["lookup_context_block"],
                        "truncation_modes": ["drop_tail"],
                        "planner_contract": {
                            "required_fields": ["entity_name"],
                            "optional_fields": ["workflow_topic"],
                            "agent_policy_fields_forbidden": [],
                        },
                        "fail_closed": {"malformed_policy": False},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_lookup_capability_contracts(tmp_path) == ()


def test_alexis_lookup_policy_validates_but_semantics_remain_agent_local():
    binding = alexis_binding()
    assert validate_lookup_capability_policies(binding) == []

    serialized_runtime_validator = (
        ROOT / "runtime/lookup/policy_validation.py"
    ).read_text(encoding="utf-8").lower()
    serialized_shared_manifest = (
        ROOT / LOOKUP_CAPABILITY_CONTRACTS_PATH
    ).read_text(encoding="utf-8").lower()
    assert "guest" not in serialized_runtime_validator
    assert "alexis" not in serialized_runtime_validator
    assert "guest" not in serialized_shared_manifest
    assert "alexis" not in serialized_shared_manifest

    serialized_binding = json.dumps(binding, sort_keys=True).lower()
    assert "guest" in serialized_binding
    assert "alexis_guest_canonical_csv" in serialized_binding
    assert "public_booking_notes" in serialized_binding


def main():
    test_generic_lookup_capability_policy_validates_without_alexis()
    test_shared_lookup_capability_contract_manifest_loads()
    test_shared_lookup_contract_source_files_are_split_by_authority()
    test_alexis_bounded_entity_search_policy_validates()
    test_malformed_render_injection_and_budget_policies_validate_and_fail_closed()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        test_malformed_shared_manifest_fails_closed(Path(tmp))
    test_alexis_lookup_policy_validates_but_semantics_remain_agent_local()
    print("PASS lookup policy validation")


if __name__ == "__main__":
    main()
