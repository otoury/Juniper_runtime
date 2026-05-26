import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.lookup.types import (  # noqa: E402
    BoundedLookupRequest,
    BoundedLookupResult,
    validate_bounded_lookup_request,
    validate_bounded_lookup_result,
)


class Env:
    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def valid_request(**overrides):
    data = {
        "lookup_id": "lookup-001",
        "source_contract_id": "alexis_guest_db",
        "lookup_mode": "fixed_id",
        "query": None,
        "lookup_key": "entity_id",
        "lookup_value": "entity-001",
        "max_records": 1,
    }
    data.update(overrides)
    return BoundedLookupRequest(**data)


def valid_result(**overrides):
    data = {
        "lookup_id": "lookup-001",
        "source_contract_id": "alexis_guest_db",
        "records": [],
        "retrieval_executed": False,
        "skipped_reasons": ["not_implemented"],
    }
    data.update(overrides)
    return BoundedLookupResult(**data)


def error_fields(errors):
    return [error.field for error in errors]


def test_valid_bounded_lookup_request_validates():
    assert validate_bounded_lookup_request(valid_request()) == []
    assert validate_bounded_lookup_request(
        valid_request(
            lookup_mode="declared_fixture",
            query="record-001",
            lookup_key=None,
            lookup_value=None,
        )
    ) == []


def test_invalid_lookup_mode_fails():
    errors = validate_bounded_lookup_request(
        valid_request(lookup_mode="semantic_search")
    )

    assert error_fields(errors) == ["lookup_mode"]


def test_max_records_other_than_one_fails():
    errors = validate_bounded_lookup_request(
        valid_request(max_records=2)
    )

    assert error_fields(errors) == ["max_records"]


def test_fixed_id_request_with_entity_id_validates():
    assert validate_bounded_lookup_request(
        valid_request(
            lookup_mode="fixed_id",
            lookup_key="entity_id",
            lookup_value="entity-001",
        )
    ) == []


def test_fixed_id_missing_lookup_value_fails():
    errors = validate_bounded_lookup_request(
        valid_request(lookup_value=" ")
    )

    assert "lookup_value" in error_fields(errors)


def test_unsupported_lookup_key_fails():
    errors = validate_bounded_lookup_request(
        valid_request(lookup_key="display_name")
    )

    assert "lookup_key" in error_fields(errors)


def test_valid_bounded_lookup_result_validates():
    assert validate_bounded_lookup_result(
        valid_result(
            records=[
                {
                    "record_id": "record-001",
                    "display_name": "Jane Doe",
                }
            ],
            retrieval_executed=True,
            skipped_reasons=[],
        )
    ) == []


def test_non_bool_retrieval_executed_fails():
    errors = validate_bounded_lookup_result(
        valid_result(retrieval_executed="yes")
    )

    assert error_fields(errors) == ["retrieval_executed"]


def test_records_not_list_fails():
    errors = validate_bounded_lookup_result(
        valid_result(records={"record_id": "record-001"})
    )

    assert error_fields(errors) == ["records"]


def test_skipped_reasons_not_list_of_strings_fails():
    errors = validate_bounded_lookup_result(
        valid_result(skipped_reasons=["ok", 1])
    )

    assert error_fields(errors) == ["skipped_reasons"]


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_lookup_types",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_valid_bounded_lookup_request_validates()
    test_invalid_lookup_mode_fails()
    test_max_records_other_than_one_fails()
    test_fixed_id_request_with_entity_id_validates()
    test_fixed_id_missing_lookup_value_fails()
    test_unsupported_lookup_key_fails()
    test_valid_bounded_lookup_result_validates()
    test_non_bool_retrieval_executed_fails()
    test_records_not_list_fails()
    test_skipped_reasons_not_list_of_strings_fails()
    test_context_composer_behavior_unchanged()
    print("PASS bounded lookup types")


if __name__ == "__main__":
    main()
