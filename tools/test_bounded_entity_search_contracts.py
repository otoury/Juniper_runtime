import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.bounded_entity_search_registry import (  # noqa: E402
    BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH,
    FORBIDDEN_BEHAVIORS,
    FORBIDDEN_PLANNER_FIELDS,
    FORBIDDEN_TELEMETRY_FIELDS,
    get_bounded_entity_search_contract,
    load_bounded_entity_search_contracts,
    validate_bounded_entity_search_request,
)


def error_fields(errors):
    return [error.field for error in errors]


def valid_request(**overrides):
    data = {
        "lookup_type": "bounded_entity_search",
        "lookup_id": "bounded-search-001",
        "search_topic": "healthcare reform",
        "entity_type": "person",
        "constraints": {"availability": "future"},
        "max_results": 3,
    }
    data.update(overrides)
    return data


def write_registry(root: Path, data):
    path = root / BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    load_bounded_entity_search_contracts.cache_clear()


def with_temp_registry(data):
    root = Path(tempfile.mkdtemp())
    write_registry(root, data)
    return root


def cleanup(root: Path):
    shutil.rmtree(root)
    load_bounded_entity_search_contracts.cache_clear()


def test_valid_bounded_entity_search_contract_loads():
    contracts = load_bounded_entity_search_contracts(ROOT)
    contract = get_bounded_entity_search_contract(
        "bounded_entity_search",
        root=ROOT,
    )

    assert [item.lookup_type for item in contracts] == [
        "bounded_entity_search"
    ]
    assert contract is not None
    assert contract.operation_id == "bounded_entity_search"
    assert set(contract.required_any_inputs) == {
        "search_topic",
        "query_intent",
    }
    assert set(contract.optional_inputs) == {
        "entity_type",
        "constraints",
        "max_results",
    }
    assert contract.result_expectations["max_results"] == 5
    assert contract.result_expectations["final_answer"] is False
    assert contract.bounded_source_reference["raw_target_allowed"] is False
    assert contract.bounded_source_reference["owner"] == (
        "agent_capability_policy"
    )


def test_missing_search_topic_or_query_intent_fails_validation():
    errors = validate_bounded_entity_search_request(
        valid_request(search_topic="", query_intent=""),
        root=ROOT,
    )

    assert error_fields(errors) == ["search_topic"]


def test_query_intent_can_satisfy_required_planner_metadata():
    errors = validate_bounded_entity_search_request(
        valid_request(search_topic="", query_intent="find panel results"),
        root=ROOT,
    )

    assert errors == []


def test_unknown_search_type_fails_closed():
    errors = validate_bounded_entity_search_request(
        valid_request(lookup_type="semantic_entity_search"),
        root=ROOT,
    )

    assert len(errors) == 1
    assert errors[0].error_code == "unknown_bounded_entity_search_type"
    assert errors[0].field == "lookup_type"


def test_candidate_entity_search_is_not_canonical_lookup_type():
    errors = validate_bounded_entity_search_request(
        valid_request(lookup_type="candidate_entity_search"),
        root=ROOT,
    )

    assert len(errors) == 1
    assert errors[0].error_code == "unknown_bounded_entity_search_type"
    assert (
        get_bounded_entity_search_contract(
            "candidate_entity_search",
            root=ROOT,
        )
        is None
    )


def test_agent_policy_fields_are_not_planner_owned():
    request = valid_request(source_scope="private_agent_scope")
    errors = validate_bounded_entity_search_request(request, root=ROOT)

    assert "source_scope" in error_fields(errors)
    contract = get_bounded_entity_search_contract(
        "bounded_entity_search",
        root=ROOT,
    )
    assert contract is not None
    assert FORBIDDEN_PLANNER_FIELDS.issubset(
        set(contract.agent_policy_fields_forbidden)
    )


def test_runtime_request_can_include_policy_source_scope_when_explicitly_allowed():
    request = valid_request(source_scope="bounded_agent_scope")
    errors = validate_bounded_entity_search_request(
        request,
        root=ROOT,
        allow_policy_fields=True,
    )

    assert errors == []


def test_bounded_contract_does_not_authorize_execution_or_ranking():
    contract = get_bounded_entity_search_contract(
        "bounded_entity_search",
        root=ROOT,
    )

    assert contract is not None
    assert FORBIDDEN_BEHAVIORS.issubset(set(contract.forbidden_behaviors))
    assert "semantic_search_execution" in contract.forbidden_behaviors
    assert "ranking" in contract.forbidden_behaviors
    assert "embeddings" in contract.forbidden_behaviors
    assert "hidden_rag" in contract.forbidden_behaviors
    assert "prompt_injection" in contract.forbidden_behaviors
    assert contract.fail_closed["execution_not_implemented"] is True


def test_bounded_contract_telemetry_is_content_safe():
    contract = get_bounded_entity_search_contract(
        "bounded_entity_search",
        root=ROOT,
    )

    assert contract is not None
    assert "lookup_id" in contract.telemetry_safe_provenance_fields
    assert "result_count" in contract.telemetry_safe_provenance_fields
    assert FORBIDDEN_TELEMETRY_FIELDS.isdisjoint(
        set(contract.telemetry_safe_provenance_fields)
    )
    assert FORBIDDEN_TELEMETRY_FIELDS.issubset(
        set(contract.telemetry_forbidden_fields)
    )


def test_malformed_bounded_contract_fails_closed():
    root = with_temp_registry(
        {
            "version": 1,
            "contracts": [
                {
                    "id": "bounded_entity_search",
                    "operation_id": "bounded_entity_search",
                    "lookup_type": "bounded_entity_search",
                    "enabled": True,
                    "inputs": {
                        "required_any": [],
                        "optional": [],
                        "agent_policy_fields_forbidden": [],
                    },
                }
            ],
        }
    )

    try:
        assert load_bounded_entity_search_contracts(root) == ()
        assert (
            get_bounded_entity_search_contract(
                "bounded_entity_search",
                root=root,
            )
            is None
        )
    finally:
        cleanup(root)


def test_shared_bounded_contract_remains_domain_neutral():
    contract_text = (
        ROOT / BOUNDED_ENTITY_SEARCH_CONTRACTS_PATH
    ).read_text(encoding="utf-8")

    lowered = contract_text.lower()
    assert "guest" not in lowered
    assert "alexis" not in lowered
    assert "booking" not in lowered
    assert "newsroom" not in lowered
    assert "candidate" not in lowered
    assert "bounded_entity_search" in lowered


def main():
    test_valid_bounded_entity_search_contract_loads()
    test_missing_search_topic_or_query_intent_fails_validation()
    test_query_intent_can_satisfy_required_planner_metadata()
    test_unknown_search_type_fails_closed()
    test_candidate_entity_search_is_not_canonical_lookup_type()
    test_agent_policy_fields_are_not_planner_owned()
    test_runtime_request_can_include_policy_source_scope_when_explicitly_allowed()
    test_bounded_contract_does_not_authorize_execution_or_ranking()
    test_bounded_contract_telemetry_is_content_safe()
    test_malformed_bounded_contract_fails_closed()
    test_shared_bounded_contract_remains_domain_neutral()
    print("PASS bounded entity search contracts")


if __name__ == "__main__":
    main()
