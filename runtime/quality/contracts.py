from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QualityViolation:
    code: str
    message: str
    severity: str = "error"


@dataclass
class QualityResult:
    ok: bool
    violations: list[QualityViolation] = field(default_factory=list)

    @classmethod
    def pass_(cls):
        return cls(ok=True, violations=[])

    @classmethod
    def fail(cls, violations: list[QualityViolation]):
        return cls(ok=False, violations=violations)
