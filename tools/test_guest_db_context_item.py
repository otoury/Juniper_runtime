import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from runtime.context_types import (  # noqa: E402
    ResolvedContextItem,
    validate_context_item_source_contract,
    validate_resolved_context_item,
)
from agents.alexis.adapters.guest_db.context_item import (  # noqa: E402
    guest_record_to_context_item,
)
from agents.alexis.adapters.guest_db.record_renderer import (  # noqa: E402
    render_guest_record_summary,
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


def test_valid_record_converts_to_resolved_context_item():
    item = guest_record_to_context_item(valid_record())

    assert isinstance(item, ResolvedContextItem)
    assert item.id == "guest_db_record:guest-001"
    assert item.source_contract_id == "alexis_guest_db"
    assert item.content_type == "database_summary"
    assert item.trust_level == "retrieved_unverified"
    assert item.rendering_policy == "bounded_context_block"


def test_invalid_record_returns_none():
    record = valid_record()
    record.pop("guest_id")

    assert guest_record_to_context_item(record) is None


def test_item_and_provenance_source_ids_match():
    item = guest_record_to_context_item(
        valid_record(),
        source_contract_id="alexis_guest_db",
    )

    assert item is not None
    assert item.source_contract_id == item.provenance.source_contract_id
    assert item.provenance.retrieval_executed is True
    assert item.provenance.attribution == "guest_db_record"


def test_rendered_content_matches_record_renderer():
    record = valid_record()
    item = guest_record_to_context_item(record)

    assert item is not None
    assert item.content == render_guest_record_summary(record)


def test_estimated_tokens_positive():
    item = guest_record_to_context_item(valid_record())

    assert item is not None
    assert item.estimated_tokens > 0


def test_output_passes_context_item_validators():
    item = guest_record_to_context_item(valid_record())

    assert item is not None
    assert validate_resolved_context_item(item) == []
    assert validate_context_item_source_contract(
        item,
        require_declared_source=True,
        root=ROOT,
    ) == []


def test_unknown_fields_not_included():
    record = valid_record()
    record["private_notes"] = "Do not include this."

    item = guest_record_to_context_item(record)

    assert item is not None
    assert "private_notes" not in item.content
    assert "Do not include this." not in item.content


def test_converter_does_not_mutate_record():
    record = valid_record()
    before = dict(record)

    guest_record_to_context_item(record)

    assert record == before


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_context_item",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_valid_record_converts_to_resolved_context_item()
    test_invalid_record_returns_none()
    test_item_and_provenance_source_ids_match()
    test_rendered_content_matches_record_renderer()
    test_estimated_tokens_positive()
    test_output_passes_context_item_validators()
    test_unknown_fields_not_included()
    test_converter_does_not_mutate_record()
    test_context_composer_behavior_unchanged()
    print("PASS guest db context item")


if __name__ == "__main__":
    main()
