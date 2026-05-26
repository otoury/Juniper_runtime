import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.context_types import validate_resolved_context_item  # noqa: E402
from agents.alexis.adapters.guest_db.context_item import (  # noqa: E402
    guest_record_to_context_item,
)
from runtime.lookup.context import (  # noqa: E402
    lookup_result_to_context_items,
)
from runtime.lookup.types import BoundedLookupResult  # noqa: E402


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


def valid_record(**overrides):
    data = {
        "guest_id": "guest-001",
        "display_name": "Jane Doe",
        "title": "Former State Department official",
        "expertise": "Middle East policy",
        "booking_notes": "Good on live hits",
    }
    data.update(overrides)
    return data


def valid_result(**overrides):
    data = {
        "lookup_id": "lookup-001",
        "source_contract_id": "alexis_guest_db",
        "records": [valid_record()],
        "retrieval_executed": True,
        "skipped_reasons": [],
    }
    data.update(overrides)
    return BoundedLookupResult(**data)


def guest_converter(record, source_contract_id):
    return guest_record_to_context_item(
        record,
        source_contract_id=source_contract_id,
        item_id_prefix="lookup-001:guest_db_record",
    )


def to_items(result):
    return lookup_result_to_context_items(
        result,
        record_converter=guest_converter,
    )


def test_valid_result_with_one_record_returns_one_item():
    items = to_items(valid_result())

    assert len(items) == 1
    assert items[0].content_type == "database_summary"
    assert validate_resolved_context_item(items[0]) == []


def test_retrieval_not_executed_returns_empty_list():
    assert to_items(valid_result(retrieval_executed=False)) == []


def test_invalid_result_returns_empty_list():
    assert to_items(valid_result(records={"record_id": "record-001"})) == []


def test_multiple_records_returns_at_most_one_item():
    items = to_items(
        valid_result(
            records=[
                valid_record(guest_id="guest-001"),
                valid_record(guest_id="guest-002"),
            ],
        )
    )

    assert len(items) == 1
    assert items[0].id == "lookup-001:guest_db_record:guest-001"


def test_invalid_record_returns_empty_list():
    assert to_items(valid_result(records=[{"display_name": "Jane Doe"}])) == []


def test_source_contract_id_is_preserved():
    item = to_items(valid_result(source_contract_id="alexis_guest_db"))[0]

    assert item.source_contract_id == "alexis_guest_db"
    assert item.provenance.source_contract_id == "alexis_guest_db"


def test_converter_does_not_mutate_result_records():
    result = valid_result()
    before = [dict(record) for record in result.records]

    to_items(result)

    assert result.records == before


def test_lookup_result_to_context_items_requires_explicit_converter():
    try:
        lookup_result_to_context_items(valid_result())
    except TypeError:
        return

    raise AssertionError("lookup_result_to_context_items accepted no converter")


def test_runtime_lookup_context_does_not_import_guest_converter():
    source = (ROOT / "runtime" / "lookup" / "context.py").read_text()

    assert "guest_db_context_item" not in source
    assert "guest_record_to_context_item" not in source


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_lookup_context",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_valid_result_with_one_record_returns_one_item()
    test_retrieval_not_executed_returns_empty_list()
    test_invalid_result_returns_empty_list()
    test_multiple_records_returns_at_most_one_item()
    test_invalid_record_returns_empty_list()
    test_source_contract_id_is_preserved()
    test_converter_does_not_mutate_result_records()
    test_lookup_result_to_context_items_requires_explicit_converter()
    test_runtime_lookup_context_does_not_import_guest_converter()
    test_context_composer_behavior_unchanged()
    print("PASS bounded lookup context")


if __name__ == "__main__":
    main()
