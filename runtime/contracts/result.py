# contracts/result.py

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContractValidationResult:
    ok: bool
    error: str = ""
    violations: list[str] | None = None
