from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from runtime.workflows.trust_lineage import (
    build_capability_scoped_trust_lineage,
    trust_lineage_scopes_match,
)


TRUST_INHERITANCE_CONTRACT_ID = "bounded_trust_inheritance_v1"
TRUST_INHERITANCE_DECISION_TYPE = "bounded_trust_inheritance_decision"
BOUNDARY_RESUMPTION = "resumption"
BOUNDARY_NESTED_WORKFLOW = "nested_workflow"
BOUNDARY_DELEGATED_WORKFLOW_STEP = "delegated_workflow_step"


@dataclass(frozen=True)
class TrustInheritanceDecision:
    contract_id: str
    decision_type: str
    boundary_type: str
    inheritance_allowed: bool
    inherited_trust_state: str | None
    prior_trust_state: str | None
    trust_lineage: dict[str, Any] | None
    prior_trust_lineage: dict[str, Any] | None
    prior_trust_scope_match: bool | None
    bounded: bool
    explicit_boundary: bool
    resume_integrity_passed: bool | None
    cross_workflow_inheritance_allowed: bool
    cross_capability_inheritance_allowed: bool
    semantic_reinterpretation_performed: bool
    skipped_reasons: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "decision_type": self.decision_type,
            "boundary_type": self.boundary_type,
            "inheritance_allowed": self.inheritance_allowed,
            "inherited_trust_state": self.inherited_trust_state,
            "prior_trust_state": self.prior_trust_state,
            "trust_lineage": (
                dict(self.trust_lineage)
                if isinstance(self.trust_lineage, dict)
                else None
            ),
            "prior_trust_lineage": (
                dict(self.prior_trust_lineage)
                if isinstance(self.prior_trust_lineage, dict)
                else None
            ),
            "prior_trust_scope_match": self.prior_trust_scope_match,
            "bounded": self.bounded,
            "explicit_boundary": self.explicit_boundary,
            "resume_integrity_passed": self.resume_integrity_passed,
            "cross_workflow_inheritance_allowed": (
                self.cross_workflow_inheritance_allowed
            ),
            "cross_capability_inheritance_allowed": (
                self.cross_capability_inheritance_allowed
            ),
            "semantic_reinterpretation_performed": (
                self.semantic_reinterpretation_performed
            ),
            "skipped_reasons": list(self.skipped_reasons),
        }


def build_trust_inheritance_decision(
    *,
    boundary_type: str,
    prior_trust_state: str | None = None,
    prior_trust_lineage: Mapping[str, Any] | None = None,
    current_trust_lineage: Mapping[str, Any] | None = None,
    bounded: bool = True,
    explicit_boundary: bool = True,
    resume_integrity_passed: bool | None = None,
) -> TrustInheritanceDecision:
    boundary = _boundary(boundary_type)
    prior_state = _optional_string(prior_trust_state)
    prior_lineage = _lineage(prior_trust_lineage)
    current_lineage = _lineage(current_trust_lineage)
    scope_match: bool | None = None
    skipped: list[str] = []

    if not bounded:
        skipped.append("trust_inheritance_unbounded")
    if not explicit_boundary:
        skipped.append("trust_inheritance_boundary_not_explicit")
    if current_lineage is None:
        skipped.append("current_trust_lineage_missing")
    if prior_state is None:
        skipped.append("prior_trust_state_missing")
    if prior_state is not None and prior_lineage is None:
        skipped.append("prior_trust_lineage_missing")

    if prior_lineage is not None and current_lineage is not None:
        scope_match = trust_lineage_scopes_match(prior_lineage, current_lineage)
        if not scope_match:
            skipped.append("trust_lineage_scope_mismatch")
    elif prior_state is not None and current_lineage is not None:
        scope_match = False

    if boundary == BOUNDARY_RESUMPTION and resume_integrity_passed is not True:
        skipped.append("resume_integrity_not_validated")

    allowed = (
        bounded
        and explicit_boundary
        and prior_state is not None
        and prior_lineage is not None
        and current_lineage is not None
        and scope_match is True
        and (
            boundary != BOUNDARY_RESUMPTION
            or resume_integrity_passed is True
        )
    )

    return TrustInheritanceDecision(
        contract_id=TRUST_INHERITANCE_CONTRACT_ID,
        decision_type=TRUST_INHERITANCE_DECISION_TYPE,
        boundary_type=boundary,
        inheritance_allowed=allowed,
        inherited_trust_state=prior_state if allowed else None,
        prior_trust_state=prior_state,
        trust_lineage=current_lineage,
        prior_trust_lineage=prior_lineage,
        prior_trust_scope_match=scope_match,
        bounded=bounded,
        explicit_boundary=explicit_boundary,
        resume_integrity_passed=resume_integrity_passed,
        cross_workflow_inheritance_allowed=False,
        cross_capability_inheritance_allowed=False,
        semantic_reinterpretation_performed=False,
        skipped_reasons=tuple(_unique(skipped)),
    )


def build_workflow_step_trust_lineage(
    *,
    owning_agent: str | None,
    workflow_id: str | None,
    workflow_type: str | None,
    step_id: str | None,
    capability: str | None,
    action_type: str | None = None,
) -> dict[str, Any] | None:
    return build_capability_scoped_trust_lineage(
        owning_agent=owning_agent,
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        step_id=step_id,
        capability=capability,
        action_type=action_type,
    )


def validate_trust_inheritance_decision(record: Any) -> bool:
    if not isinstance(record, Mapping):
        return False
    if record.get("contract_id") != TRUST_INHERITANCE_CONTRACT_ID:
        return False
    if record.get("decision_type") != TRUST_INHERITANCE_DECISION_TYPE:
        return False
    if record.get("boundary_type") not in {
        BOUNDARY_RESUMPTION,
        BOUNDARY_NESTED_WORKFLOW,
        BOUNDARY_DELEGATED_WORKFLOW_STEP,
    }:
        return False
    if not isinstance(record.get("inheritance_allowed"), bool):
        return False
    if record.get("cross_workflow_inheritance_allowed") is not False:
        return False
    if record.get("cross_capability_inheritance_allowed") is not False:
        return False
    if record.get("semantic_reinterpretation_performed") is not False:
        return False
    if not isinstance(record.get("skipped_reasons"), list):
        return False
    if (
        record.get("inheritance_allowed") is True
        and record.get("inherited_trust_state") is None
    ):
        return False
    return True


def _boundary(value: str) -> str:
    text = _optional_string(value)
    if text in {
        BOUNDARY_RESUMPTION,
        BOUNDARY_NESTED_WORKFLOW,
        BOUNDARY_DELEGATED_WORKFLOW_STEP,
    }:
        return text
    return BOUNDARY_DELEGATED_WORKFLOW_STEP


def _lineage(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "BOUNDARY_DELEGATED_WORKFLOW_STEP",
    "BOUNDARY_NESTED_WORKFLOW",
    "BOUNDARY_RESUMPTION",
    "TRUST_INHERITANCE_CONTRACT_ID",
    "TRUST_INHERITANCE_DECISION_TYPE",
    "TrustInheritanceDecision",
    "build_trust_inheritance_decision",
    "build_workflow_step_trust_lineage",
    "validate_trust_inheritance_decision",
]
