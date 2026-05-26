# contracts/exceptions.py

from __future__ import annotations


class ContractValidationError(ValueError):
    def __init__(
        self,
        *,
        message: str,
        violations: list[str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.violations = violations or []
