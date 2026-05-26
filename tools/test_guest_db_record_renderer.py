import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.context_composer import compose_bounded_context  # noqa: E402
from runtime.context_micro_injection import MICRO_BLOCK  # noqa: E402
from agents.alexis.adapters.guest_db.record_renderer import (  # noqa: E402
    MAX_GUEST_SUMMARY_CHARS,
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


def test_valid_record_renders_expected_summary():
    assert render_guest_record_summary(valid_record()) == (
        "Guest: Jane Doe\n"
        "Title: Former State Department official\n"
        "Expertise: Middle East policy\n"
        "Booking notes: Good on live hits"
    )


def test_missing_optional_fields_omitted_cleanly():
    record = {
        "guest_id": "guest-002",
        "display_name": "Jane Doe",
    }

    assert render_guest_record_summary(record) == "Guest: Jane Doe"


def test_invalid_record_returns_none():
    record = valid_record()
    record.pop("guest_id")

    assert render_guest_record_summary(record) is None


def test_unknown_fields_are_not_rendered():
    record = valid_record()
    record["private_notes"] = "Do not render this."

    summary = render_guest_record_summary(record)

    assert summary is not None
    assert "private_notes" not in summary
    assert "Do not render this." not in summary


def test_oversized_rendered_summary_returns_none():
    record = valid_record()
    record["booking_notes"] = "x" * MAX_GUEST_SUMMARY_CHARS

    assert render_guest_record_summary(record) is None


def test_rendering_is_deterministic():
    record = valid_record()

    assert render_guest_record_summary(record) == render_guest_record_summary(
        dict(reversed(list(record.items())))
    )


def test_renderer_does_not_mutate_record():
    record = valid_record()
    before = dict(record)

    render_guest_record_summary(record)

    assert record == before


def test_context_composer_behavior_unchanged():
    with Env(
        JUNIPER_ENABLE_CONTEXT_INJECTION="1",
        JUNIPER_DISABLE_CONTEXT_INJECTION=None,
        JUNIPER_ENABLE_EXTERNAL_CONTEXT_READS=None,
    ):
        result = compose_bounded_context(
            request_id="req_guest_db_record_renderer",
            agent="alexis",
            shared_capability="draft_email",
            planner_mode="NEW_REQUEST",
        )

    assert result.injection_performed is True
    assert result.rendered_blocks == [MICRO_BLOCK]


def main():
    test_valid_record_renders_expected_summary()
    test_missing_optional_fields_omitted_cleanly()
    test_invalid_record_returns_none()
    test_unknown_fields_are_not_rendered()
    test_oversized_rendered_summary_returns_none()
    test_rendering_is_deterministic()
    test_renderer_does_not_mutate_record()
    test_context_composer_behavior_unchanged()
    print("PASS guest db record renderer")


if __name__ == "__main__":
    main()
