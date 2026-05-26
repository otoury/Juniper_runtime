from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from runtime.governance.retrieval_trust_decoupling import (
    trust_provenance_blocked_paths,
    trust_provenance_is_retrieval_isolated,
)
from runtime.workflows.trust_lineage import (
    build_capability_scoped_trust_lineage,
    trust_lineage_scopes_match,
)
from runtime.workflows.instances import (
    APPROVAL_STATE_APPROVED,
    APPROVAL_STATE_DENIED,
    APPROVAL_STATE_PENDING,
    STATUS_APPROVED_PENDING_RESUME,
    STATUS_SUSPENDED,
    STATUS_TERMINATED_DENIED,
)


APPROVAL_PROGRESSION_CONTRACT_ID = "governed_approval_progression_v1"
TRUST_PROGRESSION_DIAGNOSTIC_TYPE = "approval_trust_progression"
OPERATOR_APPROVAL_DIAGNOSTIC_TYPE = "operator_approval_progression_diagnostic"
TRUST_AUTHORITY_EXPLICIT_VERIFICATION = "explicit_verification"
TRUST_AUTHORITY_APPROVAL_DECISION = "approval_decision"
TRUST_PROGRESS_UNCHANGED = "unchanged_without_explicit_verification"
TRUST_PROGRESS_VERIFIED = "verified_by_explicit_verification"
APPROVAL_GOVERNANCE_ENABLED = "enabled"
DECISION_APPROVE = "approve"
DECISION_DENY = "deny"


@dataclass(frozen=True)
class TrustProgressionDiagnostics:
    diagnostic_type: str
    prior_trust_state: str | None
    requested_trust_state: str | None
    resulting_trust_state: str | None
    explicit_verification_present: bool
    approval_decision: str | None
    trust_lineage: dict[str, Any] | None
    prior_trust_lineage: dict[str, Any] | None
    prior_trust_scope_match: bool | None
    trust_scope_bleed_prevented: bool
    approval_promotes_trust: bool
    progression_allowed: bool
    progression_authority: str
    progression_result: str
    skipped_reasons: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "diagnostic_type": self.diagnostic_type,
            "prior_trust_state": self.prior_trust_state,
            "requested_trust_state": self.requested_trust_state,
            "resulting_trust_state": self.resulting_trust_state,
            "explicit_verification_present": self.explicit_verification_present,
            "approval_decision": self.approval_decision,
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
            "trust_scope_bleed_prevented": self.trust_scope_bleed_prevented,
            "approval_promotes_trust": self.approval_promotes_trust,
            "progression_allowed": self.progression_allowed,
            "progression_authority": self.progression_authority,
            "progression_result": self.progression_result,
            "skipped_reasons": list(self.skipped_reasons),
        }


@dataclass(frozen=True)
class GovernedApprovalProgression:
    contract_id: str
    progression_allowed: bool
    decision: str | None
    from_status: str | None
    to_status: str | None
    from_approval_state: str | None
    to_approval_state: str | None
    governance_state: str
    workflow_governance_state: str | None
    step_governance_state: str | None
    execution_performed: bool
    delivery_performed: bool
    trust_progression: TrustProgressionDiagnostics
    skipped_reasons: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "progression_allowed": self.progression_allowed,
            "decision": self.decision,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "from_approval_state": self.from_approval_state,
            "to_approval_state": self.to_approval_state,
            "governance_state": self.governance_state,
            "workflow_governance_state": self.workflow_governance_state,
            "step_governance_state": self.step_governance_state,
            "execution_performed": self.execution_performed,
            "delivery_performed": self.delivery_performed,
            "trust_progression": self.trust_progression.to_record(),
            "skipped_reasons": list(self.skipped_reasons),
        }


def build_trust_progression_diagnostics(
    *,
    prior_trust_state: str | None,
    requested_trust_state: str | None = None,
    approval_decision: str | None = None,
    explicit_verification_present: bool = False,
    prior_trust_lineage: Mapping[str, Any] | None = None,
    current_trust_lineage: Mapping[str, Any] | None = None,
) -> TrustProgressionDiagnostics:
    current_lineage = (
        dict(current_trust_lineage)
        if isinstance(current_trust_lineage, Mapping)
        else None
    )
    prior_lineage = (
        dict(prior_trust_lineage)
        if isinstance(prior_trust_lineage, Mapping)
        else None
    )
    skipped: list[str] = []
    if not trust_provenance_is_retrieval_isolated(current_lineage):
        skipped.append("current_trust_provenance_contains_retrieval_authority")
        skipped.extend(
            f"current_trust_provenance_blocked:{path}"
            for path in trust_provenance_blocked_paths(current_lineage)
        )
        current_lineage = None
    if not trust_provenance_is_retrieval_isolated(prior_lineage):
        skipped.append("prior_trust_provenance_contains_retrieval_authority")
        skipped.extend(
            f"prior_trust_provenance_blocked:{path}"
            for path in trust_provenance_blocked_paths(prior_lineage)
        )
        prior_lineage = None
        prior_trust_state = None
    prior = _optional_string(prior_trust_state)
    scope_match: bool | None = None
    scope_bleed_prevented = False
    if current_lineage is not None:
        if prior_lineage is None and prior is None:
            scope_match = None
        else:
            scope_match = trust_lineage_scopes_match(prior_lineage, current_lineage)
        scope_bleed_prevented = (
            (prior_lineage is not None and scope_match is False)
            or (prior is not None and prior_lineage is None)
        )
    if current_lineage is not None and not scope_match:
        prior = None
    requested = _optional_string(requested_trust_state)
    decision = _optional_string(approval_decision)
    if current_lineage is not None and prior_lineage is None:
        skipped.append("prior_trust_lineage_missing")
    if scope_bleed_prevented:
        skipped.append("trust_lineage_scope_mismatch")

    if explicit_verification_present:
        resulting = requested or prior
        allowed = (
            requested is not None
            and requested != prior
            and (current_lineage is None or scope_match is True)
        )
        authority = TRUST_AUTHORITY_EXPLICIT_VERIFICATION
        if not allowed:
            skipped.append("trust_progression_not_requested")
        progression_label = (
            TRUST_PROGRESS_VERIFIED
            if allowed
            else TRUST_PROGRESS_UNCHANGED
        )
    else:
        resulting = prior
        allowed = False
        authority = TRUST_AUTHORITY_APPROVAL_DECISION if decision else "none"
        if requested and requested != prior:
            skipped.append("explicit_verification_required")
        else:
            skipped.append("trust_progression_not_requested")
        progression_label = TRUST_PROGRESS_UNCHANGED

    return TrustProgressionDiagnostics(
        diagnostic_type=TRUST_PROGRESSION_DIAGNOSTIC_TYPE,
        prior_trust_state=prior,
        requested_trust_state=requested,
        resulting_trust_state=resulting,
        explicit_verification_present=explicit_verification_present,
        approval_decision=decision,
        trust_lineage=current_lineage,
        prior_trust_lineage=prior_lineage,
        prior_trust_scope_match=scope_match,
        trust_scope_bleed_prevented=scope_bleed_prevented,
        approval_promotes_trust=False,
        progression_allowed=allowed,
        progression_authority=authority,
        progression_result=progression_label,
        skipped_reasons=tuple(skipped),
    )


def build_governed_approval_progression(
    *,
    instance: Mapping[str, Any] | None,
    decision: str | None,
    approval_governance_state: str = APPROVAL_GOVERNANCE_ENABLED,
    workflow_governance_state: str | None = APPROVAL_GOVERNANCE_ENABLED,
    step_governance_state: str | None = APPROVAL_GOVERNANCE_ENABLED,
    prior_trust_state: str | None = None,
    requested_trust_state: str | None = None,
    explicit_verification_present: bool = False,
    prior_trust_lineage: Mapping[str, Any] | None = None,
    current_trust_lineage: Mapping[str, Any] | None = None,
    skipped_reasons: Sequence[str] | None = None,
) -> GovernedApprovalProgression:
    normalized_decision = _optional_string(decision)
    skipped = _string_tuple(skipped_reasons)
    trust = build_trust_progression_diagnostics(
        prior_trust_state=prior_trust_state,
        requested_trust_state=requested_trust_state,
        approval_decision=normalized_decision,
        explicit_verification_present=explicit_verification_present,
        prior_trust_lineage=prior_trust_lineage,
        current_trust_lineage=current_trust_lineage,
    )
    from_status = _mapping_string(instance, "status")
    from_approval_state = _mapping_string(instance, "approval_state")
    to_status, to_approval_state = _next_state(
        decision=normalized_decision,
        from_status=from_status,
        from_approval_state=from_approval_state,
    )
    governance_reasons = _governance_reasons(
        approval_governance_state=approval_governance_state,
        workflow_governance_state=workflow_governance_state,
        step_governance_state=step_governance_state,
    )
    all_skipped = (*skipped, *governance_reasons)
    progression_allowed = (
        not all_skipped
        and from_status == STATUS_SUSPENDED
        and from_approval_state == APPROVAL_STATE_PENDING
        and normalized_decision in {DECISION_APPROVE, DECISION_DENY}
    )
    if not progression_allowed:
        to_status = from_status
        to_approval_state = from_approval_state

    return GovernedApprovalProgression(
        contract_id=APPROVAL_PROGRESSION_CONTRACT_ID,
        progression_allowed=progression_allowed,
        decision=normalized_decision,
        from_status=from_status,
        to_status=to_status,
        from_approval_state=from_approval_state,
        to_approval_state=to_approval_state,
        governance_state=_string(approval_governance_state),
        workflow_governance_state=_optional_string(workflow_governance_state),
        step_governance_state=_optional_string(step_governance_state),
        execution_performed=False,
        delivery_performed=False,
        trust_progression=trust,
        skipped_reasons=all_skipped,
    )


def validate_governed_approval_progression(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("contract_id") != APPROVAL_PROGRESSION_CONTRACT_ID:
        return False
    if payload.get("execution_performed") is not False:
        return False
    if payload.get("delivery_performed") is not False:
        return False
    trust = payload.get("trust_progression")
    if not isinstance(trust, Mapping):
        return False
    if trust.get("diagnostic_type") != TRUST_PROGRESSION_DIAGNOSTIC_TYPE:
        return False
    if trust.get("approval_promotes_trust") is not False:
        return False
    if trust.get("trust_scope_bleed_prevented") not in {True, False}:
        return False
    lineage = trust.get("trust_lineage")
    if lineage is not None and not isinstance(lineage, Mapping):
        return False
    prior_lineage = trust.get("prior_trust_lineage")
    if prior_lineage is not None and not isinstance(prior_lineage, Mapping):
        return False
    if (
        trust.get("trust_scope_bleed_prevented") is True
        and trust.get("prior_trust_scope_match") is not False
    ):
        return False
    if not trust_provenance_is_retrieval_isolated(trust):
        return False
    if _forbidden_paths(payload):
        return False
    return True


def build_operator_approval_progression_diagnostics(
    progression: GovernedApprovalProgression | Mapping[str, Any],
) -> dict[str, Any]:
    record = (
        progression.to_record()
        if isinstance(progression, GovernedApprovalProgression)
        else dict(progression)
        if isinstance(progression, Mapping)
        else {}
    )
    trust = (
        record.get("trust_progression")
        if isinstance(record.get("trust_progression"), Mapping)
        else {}
    )
    skipped_reasons = _string_tuple(record.get("skipped_reasons"))
    trust_skipped_reasons = _string_tuple(trust.get("skipped_reasons"))
    approval_allowed = record.get("progression_allowed") is True
    trust_allowed = trust.get("progression_allowed") is True
    return {
        "diagnostic_type": OPERATOR_APPROVAL_DIAGNOSTIC_TYPE,
        "observational_only": True,
        "hidden_context_injection_performed": False,
        "planner_semantic_authority": False,
        "artifact_mutation_performed": False,
        "workflow_state_mutation_performed": False,
        "governance_state_mutation_performed": False,
        "memory_write_performed": False,
        "approval_contract_id": APPROVAL_PROGRESSION_CONTRACT_ID,
        "approval_required_preserved": True,
        "explicit_approval_required": True,
        "approval_progression_allowed": approval_allowed,
        "approval_status_from": _optional_string(record.get("from_status")),
        "approval_status_to": _optional_string(record.get("to_status")),
        "approval_state_from": _optional_string(record.get("from_approval_state")),
        "approval_state_to": _optional_string(record.get("to_approval_state")),
        "approval_decision": _optional_string(record.get("decision")),
        "approval_governance_state": _optional_string(record.get("governance_state")),
        "workflow_governance_state": _optional_string(
            record.get("workflow_governance_state")
        ),
        "step_governance_state": _optional_string(record.get("step_governance_state")),
        "execution_performed": False,
        "delivery_performed": False,
        "approval_skipped_reasons": list(skipped_reasons),
        "trust_prior": _optional_string(trust.get("prior_trust_state")),
        "trust_requested": _optional_string(trust.get("requested_trust_state")),
        "trust_resulting": _optional_string(trust.get("resulting_trust_state")),
        "trust_progression_allowed": trust_allowed,
        "trust_authority": _optional_string(trust.get("progression_authority")),
        "trust_result": _optional_string(trust.get("progression_result")),
        "trust_explicit_verification_present": (
            trust.get("explicit_verification_present") is True
        ),
        "trust_approval_promotes_trust": trust.get("approval_promotes_trust") is True,
        "trust_scope_bleed_prevented": trust.get("trust_scope_bleed_prevented") is True,
        "trust_prior_scope_match": (
            trust.get("prior_trust_scope_match")
            if isinstance(trust.get("prior_trust_scope_match"), bool)
            else None
        ),
        "trust_skipped_reasons": list(trust_skipped_reasons),
        "authority_unchanged": True,
        "autonomy_escalation_performed": False,
    }


def build_approval_trust_lineage(
    *,
    owning_agent: str | None,
    workflow_id: str | None,
    workflow_type: str | None,
    step_id: str | None = None,
    capability: str | None = None,
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


def _next_state(
    *,
    decision: str | None,
    from_status: str | None,
    from_approval_state: str | None,
) -> tuple[str | None, str | None]:
    if decision == DECISION_APPROVE:
        return STATUS_APPROVED_PENDING_RESUME, APPROVAL_STATE_APPROVED
    if decision == DECISION_DENY:
        return STATUS_TERMINATED_DENIED, APPROVAL_STATE_DENIED
    return from_status, from_approval_state


def _governance_reasons(
    *,
    approval_governance_state: str,
    workflow_governance_state: str | None,
    step_governance_state: str | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    approval_state = _string(approval_governance_state)
    if approval_state != APPROVAL_GOVERNANCE_ENABLED:
        reasons.append(f"approval_governance_{approval_state}")
    workflow_state = _optional_string(workflow_governance_state)
    if workflow_state and workflow_state != APPROVAL_GOVERNANCE_ENABLED:
        reasons.append(f"workflow_governance_{workflow_state}")
    step_state = _optional_string(step_governance_state)
    if step_state and step_state != APPROVAL_GOVERNANCE_ENABLED:
        reasons.append(f"step_governance_{step_state}")
    return tuple(reasons)


def _forbidden_paths(value: Any, path: str = "") -> tuple[str, ...]:
    forbidden = {
        "body",
        "content",
        "contact",
        "contact_value",
        "draft_text",
        "email",
        "phone",
        "prompt",
        "raw_results",
        "rendered_context",
        "snippet",
        "subject",
        "title",
        "url",
    }
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            text_key = _string(key)
            next_path = f"{path}.{text_key}" if path else text_key
            if text_key.lower() in forbidden:
                paths.append(next_path)
            paths.extend(_forbidden_paths(item, next_path))
        return tuple(paths)
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_forbidden_paths(item, f"{path}[{index}]"))
        return tuple(paths)
    return ()


def _mapping_string(value: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return _optional_string(value.get(key))


def _string_tuple(values: Sequence[str] | None) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, str):
        return ()
    return tuple(_string(value) for value in values if _string(value))


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


__all__ = [
    "APPROVAL_PROGRESSION_CONTRACT_ID",
    "TRUST_PROGRESSION_DIAGNOSTIC_TYPE",
    "GovernedApprovalProgression",
    "TrustProgressionDiagnostics",
    "build_approval_trust_lineage",
    "build_governed_approval_progression",
    "build_operator_approval_progression_diagnostics",
    "build_trust_progression_diagnostics",
    "validate_governed_approval_progression",
]
