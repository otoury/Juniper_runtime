from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from runtime.context_types import ResolvedContextItem


@dataclass(frozen=True)
class AdapterRecordSchema:
    schema_id: str
    version: int
    fields: tuple[str, ...]


@dataclass(frozen=True)
class AdapterRecordValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()


@runtime_checkable
class AdapterRecordValidator(Protocol):
    def validate(
        self,
        record: dict[str, Any],
    ) -> AdapterRecordValidationResult:
        ...


@runtime_checkable
class AdapterRecordRenderer(Protocol):
    def render(
        self,
        record: dict[str, Any],
    ) -> str | None:
        ...


@runtime_checkable
class AdapterRecordContextConverter(Protocol):
    def to_context_item(
        self,
        record: dict[str, Any],
        *,
        source_contract_id: str,
    ) -> ResolvedContextItem | None:
        ...


__all__ = [
    "AdapterRecordContextConverter",
    "AdapterRecordRenderer",
    "AdapterRecordSchema",
    "AdapterRecordValidationResult",
    "AdapterRecordValidator",
]
