import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.exact_entity_lookup_registry import (  # noqa: E402
    EXACT_ENTITY_LOOKUP_CONTRACTS_PATH,
    FORBIDDEN_BEHAVIORS,
    FORBIDDEN_TELEMETRY_FIELDS,
    get_exact_entity_lookup_contract,
    load_exact_entity_lookup_contracts,
    validate_exact_entity_lookup_request,
)


def error_fields(errors):
    return [error.field for error in errors]


def valid_request(**overrides):
    data = {
        "lookup_type": "exact_entity_lookup",
        "lookup_id": "lookup-001",
        "entity_name": "Jane Doe",
        "entity_type": "person",
        "workflow_topic": "climate policy",
        "source_scope": "agent_bound_entity_source",
    }
    data.update(overrides)
    return data


def write_registry(root: Path, data):
    path = root / EXACT_ENTITY_LOOKUP_CONTRACTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    load_exact_entity_lookup_contracts.cache_clear()


def with_temp_registry(data):
    root = Path(tempfile.mkdtemp())
    write_registry(root, data)
    return root


def cleanup(root: Path):
    shutil.rmtree(root)
    load_exact_entity_lookup_contracts.cache_clear()


def test_valid_exact_entity_lookup_contract_loads():
    contracts = load_exact_entity_lookup_contracts(ROOT)
    contract = get_exact_entity_lookup_contract(
        "exact_entity_lookup",
        root=ROOT,
    )

    assert [item.lookup_type for item in contracts] == [
        "exact_entity_lookup"
    ]
    assert contract is not None
    assert contract.operation_id == "exact_entity_lookup"
    assert contract.required_inputs == ("entity_name",)
    assert set(contract.optional_inputs) == {
        "entity_type",
        "workflow_topic",
        "source_scope",
    }
    assert contract.result_expectations["max_records"] == 1
    assert (
        contract.bounded_source_reference["raw_target_allowed"] is False
    )


def test_missing_entity_name_fails_validation():
    errors = validate_exact_entity_lookup_request(
        valid_request(entity_name=""),
        root=ROOT,
    )

    assert error_fields(errors) == ["entity_name"]


def test_unknown_lookup_type_fails_closed():
    errors = validate_exact_entity_lookup_request(
        valid_request(lookup_type="semantic_entity_lookup"),
        root=ROOT,
    )

    assert len(errors) == 1
    assert errors[0].error_code == "unknown_exact_entity_lookup_type"
    assert errors[0].field == "lookup_type"


def test_contract_does_not_authorize_search_or_ranking_behavior():
    contract = get_exact_entity_lookup_contract(
        "exact_entity_lookup",
        root=ROOT,
    )

    assert contract is not None
    assert FORBIDDEN_BEHAVIORS.issubset(
        set(contract.forbidden_behaviors)
    )
    assert contract.result_expectations["match_mode"] == "exact_name_only"
    assert "fuzzy_search" in contract.forbidden_behaviors
    assert "semantic_search" in contract.forbidden_behaviors
    assert "ranking" in contract.forbidden_behaviors


def test_contract_provenance_is_present_and_content_safe():
    contract = get_exact_entity_lookup_contract(
        "exact_entity_lookup",
        root=ROOT,
    )

    assert contract is not None
    assert "lookup_id" in contract.telemetry_safe_provenance_fields
    assert "lookup_type" in contract.telemetry_safe_provenance_fields
    assert "records_returned" in contract.telemetry_safe_provenance_fields
    assert FORBIDDEN_TELEMETRY_FIELDS.isdisjoint(
        set(contract.telemetry_safe_provenance_fields)
    )
    assert FORBIDDEN_TELEMETRY_FIELDS.issubset(
        set(contract.telemetry_forbidden_fields)
    )
    assert "raw_database_path" not in repr(
        contract.telemetry_safe_provenance_fields
    )


def test_malformed_contract_fails_closed():
    root = with_temp_registry(
        {
            "version": 1,
            "contracts": [
                {
                    "id": "exact_entity_lookup",
                    "operation_id": "exact_entity_lookup",
                    "lookup_type": "exact_entity_lookup",
                    "enabled": True,
                    "inputs": {
                        "required": [],
                        "optional": [],
                    },
                }
            ],
        }
    )

    try:
        assert load_exact_entity_lookup_contracts(root) == ()
        assert (
            get_exact_entity_lookup_contract(
                "exact_entity_lookup",
                root=root,
            )
            is None
        )
    finally:
        cleanup(root)


def test_shared_contract_uses_generic_entity_names():
    contract_text = (
        ROOT / EXACT_ENTITY_LOOKUP_CONTRACTS_PATH
    ).read_text(encoding="utf-8")

    assert "guest" not in contract_text.lower()
    assert "entity_name" in contract_text


def main():
    test_valid_exact_entity_lookup_contract_loads()
    test_missing_entity_name_fails_validation()
    test_unknown_lookup_type_fails_closed()
    test_contract_does_not_authorize_search_or_ranking_behavior()
    test_contract_provenance_is_present_and_content_safe()
    test_malformed_contract_fails_closed()
    test_shared_contract_uses_generic_entity_names()
    print("PASS exact entity lookup contracts")


if __name__ == "__main__":
    main()
