from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.alexis.adapters.guest_db.context_item import (
    guest_record_to_context_item,
)
from agents.alexis.adapters.guest_db.record_renderer import (
    MAX_GUEST_SUMMARY_CHARS,
)
from runtime.context_types import (
    ResolvedContextItem,
)
from runtime.registries.context_injection_binding_registry import (
    ContextInjectionContract,
)


DEFAULT_FIXTURE_PATH = Path(
    "tools/fixtures/guest_db_readonly_fixture.json"
)
MAX_SUMMARY_CHARS = MAX_GUEST_SUMMARY_CHARS


class GuestDbReadonlyFixtureAdapter:
    adapter_id = "guest_db_readonly_fixture"

    def __init__(
        self,
        contract: ContextInjectionContract,
        *,
        fixture_path: str | Path | None = None,
    ) -> None:
        self.contract = contract
        self.fixture_path = Path(fixture_path or DEFAULT_FIXTURE_PATH)

    def retrieve(
        self,
        *,
        request_id: str | None,
        agent: str,
        shared_capability: str | None,
    ) -> list[ResolvedContextItem]:
        try:
            data = self._read_fixture()
        except (OSError, json.JSONDecodeError, ValueError):
            return []

        item = guest_record_to_context_item(
            data,
            item_id_prefix=f"{request_id or 'context'}:guest_db_record",
        )

        if item is None:
            return []

        return [item]

    def _read_fixture(self) -> dict[str, Any]:
        raw: Any = json.loads(self.fixture_path.read_text(encoding="utf-8"))

        if not isinstance(raw, dict):
            raise ValueError("Guest DB fixture must be an object.")

        return raw


__all__ = [
    "GuestDbReadonlyFixtureAdapter",
    "MAX_SUMMARY_CHARS",
]
