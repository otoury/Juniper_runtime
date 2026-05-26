import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from agents.alexis.adapters.guest_db.record_validator import (  # noqa: E402
    validate_guest_record,
)
from agents.alexis.adapters.guest_db.schema_registry import (  # noqa: E402
    GuestDbSchema,
    load_guest_db_schema,
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


def valid_record():
    return {
        "guest_id": "guest-001",
        "display_name": "Ada Lovelace",
        "title": "Mathematician",
        "expertise": "Computing history",
        "booking_notes": "Available for historical context.",
        "source_updated_at": "2026-05-17T00:00:00Z",
    }


def error_codes(result):
    return [error.error_code for error in result.errors]


def field_names(result):
    return [error.field_name for error in result.errors]


def test_valid_record_passes():
    result = validate_guest_record(valid_record())

    assert result.ok is True
    assert result.errors == ()


def test_missing_guest_id_fails():
    record = valid_record()
    record.pop("guest_id")

    result = validate_guest_record(record)

    assert result.ok is False
    assert error_codes(result) == ["required_field_missing"]
    assert field_names(result) == ["guest_id"]


def test_empty_display_name_fails():
    record = valid_record()
    record["display_name"] = "  "

    result = validate_guest_record(record)

    assert result.ok is False
    assert error_codes(result) == ["required_string_empty"]
    assert field_names(result) == ["display_name"]


def test_non_string_optional_field_fails():
    record = valid_record()
    record["booking_notes"] = ["not", "a", "string"]

    result = validate_guest_record(record)

    assert result.ok is False
    assert error_codes(result) == ["field_type_invalid"]
    assert field_names(result) == ["booking_notes"]


def test_non_dict_record_fails():
    result = validate_guest_record(["not", "a", "record"])

    assert result.ok is False
    assert error_codes(result) == ["record_not_object"]
    assert field_names(result) == [None]


def test_extra_unknown_field_does_not_fail():
    record = valid_record()
    record["unknown_future_field"] = {"ignored": True}

    result = validate_guest_record(record)

    assert result.ok is True
    assert result.errors == ()


def test_validator_does_not_mutate_record():
    record = valid_record()
    before = dict(record)

    result = validate_guest_record(record)

    assert result.ok is True
    assert record == before


def test_malformed_schema_fails_closed():
    result = validate_guest_record(
        valid_record(),
        schema=GuestDbSchema(version=1, fields=(), raw_data={}),
    )

    assert result.ok is False
    assert error_codes(result) == ["schema_unavailable"]


def test_loaded_schema_can_be_supplied_explicitly():
    schema = load_guest_db_schema(ROOT)

    result = validate_guest_record(valid_record(), schema=schema)

    assert result.ok is True


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_record_validator",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_valid_record_passes()
    test_missing_guest_id_fails()
    test_empty_display_name_fails()
    test_non_string_optional_field_fails()
    test_non_dict_record_fails()
    test_extra_unknown_field_does_not_fail()
    test_validator_does_not_mutate_record()
    test_malformed_schema_fails_closed()
    test_loaded_schema_can_be_supplied_explicitly()
    test_context_composer_behavior_unchanged()
    print("PASS guest db record validator")


if __name__ == "__main__":
    main()
