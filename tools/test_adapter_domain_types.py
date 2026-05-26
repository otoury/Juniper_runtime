import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.adapter_domain_types import (  # noqa: E402
    AdapterRecordContextConverter,
    AdapterRecordRenderer,
    AdapterRecordSchema,
    AdapterRecordValidationResult,
    AdapterRecordValidator,
)
from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from agents.alexis.adapters.guest_db.context_item import (  # noqa: E402
    guest_record_to_context_item,
)
from agents.alexis.adapters.guest_db.record_renderer import (  # noqa: E402
    render_guest_record_summary,
)
from agents.alexis.adapters.guest_db.record_validator import (  # noqa: E402
    validate_guest_record,
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
        "display_name": "Jane Doe",
        "title": "Former State Department official",
        "expertise": "Middle East policy",
        "booking_notes": "Good on live hits",
        "source_updated_at": "2026-05-17T00:00:00Z",
    }


class FakeValidator:
    def validate(self, record):
        if not isinstance(record, dict):
            return AdapterRecordValidationResult(
                ok=False,
                errors=("record_not_object",),
            )
        return AdapterRecordValidationResult(ok=True)


class FakeRenderer:
    def render(self, record):
        if not isinstance(record, dict):
            return None
        return "record"


class FakeConverter:
    def to_context_item(self, record, *, source_contract_id):
        return guest_record_to_context_item(
            record,
            source_contract_id=source_contract_id,
            item_id_prefix="fake_adapter_record",
        )


def test_adapter_record_validation_result_works():
    result = AdapterRecordValidationResult(
        ok=False,
        errors=("missing_id", "invalid_name"),
    )

    assert result.ok is False
    assert result.errors == ("missing_id", "invalid_name")


def test_adapter_record_schema_is_generic():
    schema = AdapterRecordSchema(
        schema_id="generic_record",
        version=1,
        fields=("record_id", "display_name"),
    )

    assert schema.schema_id == "generic_record"
    assert schema.fields == ("record_id", "display_name")


def test_protocols_can_be_satisfied_by_fake_implementations():
    validator = FakeValidator()
    renderer = FakeRenderer()
    converter = FakeConverter()

    assert isinstance(validator, AdapterRecordValidator)
    assert isinstance(renderer, AdapterRecordRenderer)
    assert isinstance(converter, AdapterRecordContextConverter)
    assert validator.validate({}).ok is True
    assert renderer.render({}) == "record"
    assert converter.to_context_item(
        valid_record(),
        source_contract_id="alexis_guest_db",
    ) is not None


def test_guest_db_validator_result_shape_remains_compatible():
    valid = validate_guest_record(valid_record())

    assert isinstance(valid.ok, bool)
    assert isinstance(valid.errors, tuple)

    generic_valid = AdapterRecordValidationResult(
        ok=valid.ok,
        errors=tuple(error.error_code for error in valid.errors),
    )

    assert generic_valid == AdapterRecordValidationResult(ok=True)

    invalid_record = valid_record()
    invalid_record.pop("guest_id")
    invalid = validate_guest_record(invalid_record)
    generic_invalid = AdapterRecordValidationResult(
        ok=invalid.ok,
        errors=tuple(error.error_code for error in invalid.errors),
    )

    assert generic_invalid.ok is False
    assert generic_invalid.errors == ("required_field_missing",)


def test_guest_renderer_and_converter_behavior_unchanged():
    record = valid_record()
    summary = render_guest_record_summary(record)
    item = guest_record_to_context_item(record)

    assert summary == (
        "Guest: Jane Doe\n"
        "Title: Former State Department official\n"
        "Expertise: Middle East policy\n"
        "Booking notes: Good on live hits"
    )
    assert item is not None
    assert item.content == summary
    assert item.id == "guest_db_record:guest-001"


def test_runtime_lookup_code_remains_agent_agnostic():
    for path in (
        ROOT / "runtime" / "lookup" / "types.py",
        ROOT / "runtime" / "lookup" / "context.py",
        ROOT / "runtime" / "lookup" / "telemetry.py",
        ROOT / "runtime" / "adapter_domain_types.py",
    ):
        source = path.read_text()
        assert "guest_db" not in source
        assert "Guest" not in source
        assert "alexis" not in source


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_adapter_domain_types",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_adapter_record_validation_result_works()
    test_adapter_record_schema_is_generic()
    test_protocols_can_be_satisfied_by_fake_implementations()
    test_guest_db_validator_result_shape_remains_compatible()
    test_guest_renderer_and_converter_behavior_unchanged()
    test_runtime_lookup_code_remains_agent_agnostic()
    test_context_composer_behavior_unchanged()
    print("PASS adapter domain types")


if __name__ == "__main__":
    main()
