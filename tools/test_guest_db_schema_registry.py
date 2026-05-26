import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from agents.alexis.adapters.guest_db.schema_registry import (  # noqa: E402
    GUEST_DB_SCHEMA_PATH,
    list_guest_db_schema_fields,
    load_guest_db_schema,
    load_guest_db_schema_strict,
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


def clear_cache():
    load_guest_db_schema.cache_clear()


def schema_data(**overrides):
    data = {
        "version": 1,
        "fields": [
            {
                "name": "guest_id",
                "type": "string",
                "required": True,
            },
            {
                "name": "display_name",
                "type": "string",
                "required": True,
            },
            {
                "name": "title",
                "type": "string",
                "required": False,
            },
        ],
    }
    data.update(overrides)
    return data


def with_temp_schema(data):
    root = Path(tempfile.mkdtemp())
    path = root / GUEST_DB_SCHEMA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    clear_cache()
    return root


def cleanup(root):
    shutil.rmtree(root)
    clear_cache()


def test_schema_loads():
    schema = load_guest_db_schema(ROOT)

    assert schema is not None
    assert schema.version == 1
    assert schema.field_names() == (
        "guest_id",
        "display_name",
        "title",
        "expertise",
        "booking_notes",
        "source_updated_at",
    )
    assert len(list_guest_db_schema_fields(ROOT)) == 6


def test_required_fields_present():
    schema = load_guest_db_schema_strict(ROOT)

    assert set(schema.required_field_names()) == {
        "guest_id",
        "display_name",
    }


def test_duplicate_field_names_fail():
    root = with_temp_schema(
        schema_data(
            fields=[
                {
                    "name": "guest_id",
                    "type": "string",
                    "required": True,
                },
                {
                    "name": "guest_id",
                    "type": "string",
                    "required": False,
                },
                {
                    "name": "display_name",
                    "type": "string",
                    "required": True,
                },
            ],
        )
    )

    try:
        assert load_guest_db_schema(root) is None
        try:
            load_guest_db_schema_strict(root)
        except Exception as exc:
            assert "field names must be unique" in str(exc)
        else:
            raise AssertionError("expected strict schema validation failure")
    finally:
        cleanup(root)


def test_unsupported_field_type_fails():
    root = with_temp_schema(
        schema_data(
            fields=[
                {
                    "name": "guest_id",
                    "type": "string",
                    "required": True,
                },
                {
                    "name": "display_name",
                    "type": "object",
                    "required": True,
                },
            ],
        )
    )

    try:
        assert load_guest_db_schema(root) is None
        try:
            load_guest_db_schema_strict(root)
        except Exception as exc:
            assert "unsupported type" in str(exc)
        else:
            raise AssertionError("expected strict schema validation failure")
    finally:
        cleanup(root)


def test_malformed_schema_fails_closed():
    root = with_temp_schema([
        {
            "name": "guest_id",
            "type": "string",
            "required": True,
        },
    ])

    try:
        assert load_guest_db_schema(root) is None
        assert list_guest_db_schema_fields(root) == []
    finally:
        cleanup(root)


def test_missing_required_field_fails_closed():
    root = with_temp_schema(
        schema_data(
            fields=[
                {
                    "name": "guest_id",
                    "type": "string",
                    "required": True,
                },
            ],
        )
    )

    try:
        assert load_guest_db_schema(root) is None
        try:
            load_guest_db_schema_strict(root)
        except Exception as exc:
            assert "missing required fields" in str(exc)
        else:
            raise AssertionError("expected strict schema validation failure")
    finally:
        cleanup(root)


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_schema_registry",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_schema_loads()
    test_required_fields_present()
    test_duplicate_field_names_fail()
    test_unsupported_field_type_fails()
    test_malformed_schema_fails_closed()
    test_missing_required_field_fails_closed()
    test_context_composer_behavior_unchanged()
    print("PASS guest db schema registry")


if __name__ == "__main__":
    main()
