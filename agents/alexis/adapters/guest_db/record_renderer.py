from __future__ import annotations

from typing import Any

from agents.alexis.adapters.guest_db.record_validator import (
    validate_guest_record,
)


MAX_GUEST_SUMMARY_CHARS = 500
SUMMARY_FIELDS = (
    ("display_name", "Guest"),
    ("title", "Title"),
    ("expertise", "Expertise"),
    ("booking_notes", "Booking notes"),
)


def render_guest_record_summary(record: dict[str, Any]) -> str | None:
    validation = validate_guest_record(record)

    if not validation.ok:
        return None

    lines: list[str] = []

    for field_name, label in SUMMARY_FIELDS:
        value = record.get(field_name)

        if not isinstance(value, str):
            continue

        rendered_value = value.strip()

        if not rendered_value:
            continue

        lines.append(f"{label}: {rendered_value}")

    summary = "\n".join(lines)

    if len(summary) > MAX_GUEST_SUMMARY_CHARS:
        return None

    return summary


__all__ = [
    "MAX_GUEST_SUMMARY_CHARS",
    "render_guest_record_summary",
]
