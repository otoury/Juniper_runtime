from __future__ import annotations

from collections.abc import Mapping, Sequence


def _render_value(value) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, Mapping):
        lines = []

        numeric_keys = all(
            str(key).isdigit()
            for key in value.keys()
        )

        for key, item in value.items():
            rendered = _render_value(item)

            if not rendered:
                continue

            if numeric_keys:
                lines.append(rendered)
            else:
                lines.append(f"{key}: {rendered}")

        return "\n".join(lines).strip()
    
    if (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
    ):
        lines = []

        for item in value:
            rendered = _render_value(item)

            if not rendered:
                continue

            rendered = rendered.strip()

            if "\n" in rendered:
                rendered = rendered.replace(
                    "\n",
                    " | ",
                )

            lines.append(f"- {rendered}")

        return "\n".join(lines).strip()

    if value is None:
        return ""

    return str(value).strip()


def normalize_structured_payload(
    payload: dict,
    *,
    preferred_fields: list[str] | None = None,
) -> str:
    preferred_fields = preferred_fields or []

    for field in preferred_fields:
        value = payload.get(field)

        rendered = _render_value(value)

        if rendered:
            return rendered

    return _render_value(payload)
