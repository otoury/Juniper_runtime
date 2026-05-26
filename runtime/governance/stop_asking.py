from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.atomic_write import atomic_write_text


DEFAULT_STOP_ASKING_POLICY_STORE_PATH = Path(
    "data/governance/stop_asking_policies.json"
)
STOP_ASKING_POLICY_CONTRACT_ID = "operator_stop_asking_policy_v1"
OPERATOR_OVERRIDE_RECEIPT_CONTRACT_ID = "operator_override_receipt_v1"
OPERATOR_OVERRIDE_RECEIPT_TYPE = "operator_override_receipt"
STOP_ASKING_OPERATOR_DIAGNOSTIC_TYPE = "operator_stop_asking_diagnostic"
STOP_ASKING_GOVERNANCE_ENABLED = "enabled"
STOP_ASKING_GOVERNANCE_DISABLED = "disabled"
STOP_ASKING_SCOPE_FIELDS = (
    "source_bot",
    "agent",
    "user_id",
    "action_type",
    "workflow_id",
    "step_id",
)


@dataclass(frozen=True)
class StopAskingDecision:
    contract_id: str
    asking_allowed: bool
    asking_suppressed: bool
    governance_state: str
    matched_policy_id: str | None
    scope: dict[str, str]
    expires_at: str | None
    revoked: bool
    execution_performed: bool
    delivery_performed: bool
    skipped_reasons: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "asking_allowed": self.asking_allowed,
            "asking_suppressed": self.asking_suppressed,
            "governance_state": self.governance_state,
            "matched_policy_id": self.matched_policy_id,
            "scope": dict(self.scope),
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "execution_performed": self.execution_performed,
            "delivery_performed": self.delivery_performed,
            "skipped_reasons": list(self.skipped_reasons),
        }


@dataclass(frozen=True)
class OperatorOverrideReceipt:
    contract_id: str
    receipt_type: str
    receipt_id: str
    receipt_ref: str
    governance_boundary: str
    policy_contract_id: str
    governance_state: str
    matched_policy_id: str | None
    asking_suppressed: bool
    asking_allowed: bool
    override_applied: bool
    scope: dict[str, str]
    skipped_reasons: tuple[str, ...]
    execution_performed: bool
    delivery_performed: bool
    semantic_reinterpretation_performed: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "receipt_type": self.receipt_type,
            "receipt_id": self.receipt_id,
            "receipt_ref": self.receipt_ref,
            "governance_boundary": self.governance_boundary,
            "policy_contract_id": self.policy_contract_id,
            "governance_state": self.governance_state,
            "matched_policy_id": self.matched_policy_id,
            "asking_suppressed": self.asking_suppressed,
            "asking_allowed": self.asking_allowed,
            "override_applied": self.override_applied,
            "scope": dict(self.scope),
            "skipped_reasons": list(self.skipped_reasons),
            "execution_performed": self.execution_performed,
            "delivery_performed": self.delivery_performed,
            "semantic_reinterpretation_performed": (
                self.semantic_reinterpretation_performed
            ),
        }


def create_stop_asking_policy(
    *,
    scope: Mapping[str, Any],
    created_by: str,
    expires_at: datetime | str,
    reason: str | None = None,
    created_at: datetime | str | None = None,
    governance_state: str = STOP_ASKING_GOVERNANCE_ENABLED,
    store_path: str | Path = DEFAULT_STOP_ASKING_POLICY_STORE_PATH,
) -> dict[str, Any] | None:
    safe_scope = _normalize_scope(scope)
    operator = _operator_id(created_by)
    created = _timestamp(created_at)
    expires = _required_timestamp(expires_at)
    state = _string(governance_state) or STOP_ASKING_GOVERNANCE_DISABLED
    if not safe_scope or not operator or not expires:
        return None

    policy = {
        "contract_id": STOP_ASKING_POLICY_CONTRACT_ID,
        "policy_id": _policy_id(
            scope=safe_scope,
            created_by=operator,
            created_at=created,
            expires_at=expires,
        ),
        "governance_state": state,
        "scope": safe_scope,
        "created_by": operator,
        "created_at": created,
        "expires_at": expires,
        "reason": _optional_string(reason),
        "revoked": False,
        "revoked_by": None,
        "revoked_at": None,
        "execution_performed": False,
        "delivery_performed": False,
    }
    records = _load_policies(store_path)
    records.append(policy)
    _write_policies(records, store_path)
    return policy


def revoke_stop_asking_policy(
    *,
    policy_id: str,
    revoked_by: str,
    revoked_at: datetime | str | None = None,
    store_path: str | Path = DEFAULT_STOP_ASKING_POLICY_STORE_PATH,
) -> dict[str, Any] | None:
    wanted = _string(policy_id)
    operator = _operator_id(revoked_by)
    if not wanted or not operator:
        return None

    records = _load_policies(store_path)
    changed: dict[str, Any] | None = None
    for index, policy in enumerate(records):
        if policy.get("policy_id") != wanted:
            continue
        updated = dict(policy)
        updated["revoked"] = True
        updated["revoked_by"] = operator
        updated["revoked_at"] = _timestamp(revoked_at)
        updated["execution_performed"] = False
        updated["delivery_performed"] = False
        records[index] = updated
        changed = updated
        break

    if changed is None:
        return None
    _write_policies(records, store_path)
    return changed


def evaluate_stop_asking_policy(
    *,
    context: Mapping[str, Any],
    now: datetime | str | None = None,
    governance_state: str = STOP_ASKING_GOVERNANCE_ENABLED,
    store_path: str | Path = DEFAULT_STOP_ASKING_POLICY_STORE_PATH,
) -> StopAskingDecision:
    safe_context = _normalize_scope(context)
    state = _string(governance_state) or STOP_ASKING_GOVERNANCE_DISABLED
    if state != STOP_ASKING_GOVERNANCE_ENABLED:
        return _decision(
            context=safe_context,
            asking_allowed=True,
            asking_suppressed=False,
            governance_state=state,
            matched_policy=None,
            skipped_reasons=(f"stop_asking_governance_{state}",),
        )

    current = _datetime(now) or datetime.now(timezone.utc)
    expired_seen = False
    revoked_seen = False
    for policy in _load_policies(store_path):
        if policy.get("contract_id") != STOP_ASKING_POLICY_CONTRACT_ID:
            continue
        if policy.get("governance_state") != STOP_ASKING_GOVERNANCE_ENABLED:
            continue
        scope = policy.get("scope")
        if not isinstance(scope, Mapping):
            continue
        safe_scope = _normalize_scope(scope)
        if not _scope_matches(safe_scope, safe_context):
            continue
        if policy.get("revoked") is True:
            revoked_seen = True
            continue
        expires_at = _datetime(policy.get("expires_at"))
        if expires_at is None or expires_at <= current:
            expired_seen = True
            continue
        return _decision(
            context=safe_context,
            asking_allowed=False,
            asking_suppressed=True,
            governance_state=state,
            matched_policy=policy,
            skipped_reasons=(),
        )

    reasons: list[str] = ["stop_asking_policy_not_matched"]
    if expired_seen:
        reasons.append("matching_stop_asking_policy_expired")
    if revoked_seen:
        reasons.append("matching_stop_asking_policy_revoked")
    return _decision(
        context=safe_context,
        asking_allowed=True,
        asking_suppressed=False,
        governance_state=state,
        matched_policy=None,
        skipped_reasons=tuple(reasons),
    )


def validate_stop_asking_decision(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("contract_id") != STOP_ASKING_POLICY_CONTRACT_ID:
        return False
    if not isinstance(payload.get("asking_allowed"), bool):
        return False
    if not isinstance(payload.get("asking_suppressed"), bool):
        return False
    if payload.get("execution_performed") is not False:
        return False
    if payload.get("delivery_performed") is not False:
        return False
    if not isinstance(payload.get("scope"), Mapping):
        return False
    if _forbidden_paths(payload):
        return False
    return True


def materialize_operator_override_receipt(
    decision: StopAskingDecision,
) -> OperatorOverrideReceipt:
    scope = dict(decision.scope)
    receipt_id = _override_receipt_id(
        scope=scope,
        matched_policy_id=decision.matched_policy_id,
        asking_suppressed=decision.asking_suppressed,
        asking_allowed=decision.asking_allowed,
        governance_state=decision.governance_state,
        skipped_reasons=decision.skipped_reasons,
    )
    return OperatorOverrideReceipt(
        contract_id=OPERATOR_OVERRIDE_RECEIPT_CONTRACT_ID,
        receipt_type=OPERATOR_OVERRIDE_RECEIPT_TYPE,
        receipt_id=receipt_id,
        receipt_ref=f"receipt:operator-override:{receipt_id}",
        governance_boundary="operator_stop_asking",
        policy_contract_id=STOP_ASKING_POLICY_CONTRACT_ID,
        governance_state=decision.governance_state,
        matched_policy_id=decision.matched_policy_id,
        asking_suppressed=decision.asking_suppressed,
        asking_allowed=decision.asking_allowed,
        override_applied=decision.asking_suppressed,
        scope=scope,
        skipped_reasons=decision.skipped_reasons,
        execution_performed=False,
        delivery_performed=False,
        semantic_reinterpretation_performed=False,
    )


def validate_operator_override_receipt(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if payload.get("contract_id") != OPERATOR_OVERRIDE_RECEIPT_CONTRACT_ID:
        return False
    if payload.get("receipt_type") != OPERATOR_OVERRIDE_RECEIPT_TYPE:
        return False
    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id.startswith("oor_"):
        return False
    if payload.get("receipt_ref") != f"receipt:operator-override:{receipt_id}":
        return False
    if payload.get("policy_contract_id") != STOP_ASKING_POLICY_CONTRACT_ID:
        return False
    if payload.get("execution_performed") is not False:
        return False
    if payload.get("delivery_performed") is not False:
        return False
    if payload.get("semantic_reinterpretation_performed") is not False:
        return False
    if not isinstance(payload.get("scope"), Mapping):
        return False
    if _forbidden_paths(payload):
        return False
    return True


def build_governance_boundary_diagnostics(
    decision: StopAskingDecision,
    receipt: OperatorOverrideReceipt,
) -> dict[str, Any]:
    diagnostics = {
        "diagnostic_type": "operator_override_governance_boundary",
        "governance_boundary": "operator_stop_asking",
        "policy_contract_id": STOP_ASKING_POLICY_CONTRACT_ID,
        "receipt_ref": receipt.receipt_ref,
        "receipt_contract_id": receipt.contract_id,
        "governance_state": decision.governance_state,
        "asking_suppressed": decision.asking_suppressed,
        "asking_allowed": decision.asking_allowed,
        "override_applied": receipt.override_applied,
        "matched_policy_present": decision.matched_policy_id is not None,
        "scope_fields": sorted(decision.scope.keys()),
        "execution_performed": False,
        "delivery_performed": False,
        "semantic_reinterpretation_performed": False,
        "skipped_reasons": list(decision.skipped_reasons),
        "content_safe": True,
    }
    return diagnostics


def build_stop_asking_operator_diagnostics(
    decision: StopAskingDecision,
    receipt: OperatorOverrideReceipt | None = None,
) -> dict[str, Any]:
    skipped = list(decision.skipped_reasons)
    receipt_ref = receipt.receipt_ref if receipt is not None else None
    receipt_contract_id = receipt.contract_id if receipt is not None else None
    override_applied = (
        receipt.override_applied if receipt is not None else decision.asking_suppressed
    )
    return {
        "diagnostic_type": STOP_ASKING_OPERATOR_DIAGNOSTIC_TYPE,
        "observational_only": True,
        "hidden_context_injection_performed": False,
        "planner_semantic_authority": False,
        "artifact_mutation_performed": False,
        "workflow_state_mutation_performed": False,
        "governance_state_mutation_performed": False,
        "memory_write_performed": False,
        "policy_contract_id": STOP_ASKING_POLICY_CONTRACT_ID,
        "governance_boundary": "operator_stop_asking",
        "governance_state": decision.governance_state,
        "asking_allowed": decision.asking_allowed,
        "asking_suppressed": decision.asking_suppressed,
        "approval_requirement_preserved": True,
        "queued_action_authority_changed": False,
        "execution_performed": False,
        "delivery_performed": False,
        "scope": dict(decision.scope),
        "scope_fields": sorted(decision.scope.keys()),
        "matched_policy_present": decision.matched_policy_id is not None,
        "matched_policy_id": decision.matched_policy_id,
        "expires_at": decision.expires_at,
        "expiration_state": _expiration_state(decision),
        "revoked": decision.revoked,
        "revocation_state": _revocation_state(decision),
        "override_receipt_state": (
            "materialized" if receipt is not None else "not_materialized"
        ),
        "override_receipt_ref": receipt_ref,
        "override_receipt_contract_id": receipt_contract_id,
        "override_applied": override_applied,
        "skipped_reasons": skipped,
    }


def _decision(
    *,
    context: dict[str, str],
    asking_allowed: bool,
    asking_suppressed: bool,
    governance_state: str,
    matched_policy: Mapping[str, Any] | None,
    skipped_reasons: tuple[str, ...],
) -> StopAskingDecision:
    return StopAskingDecision(
        contract_id=STOP_ASKING_POLICY_CONTRACT_ID,
        asking_allowed=asking_allowed,
        asking_suppressed=asking_suppressed,
        governance_state=governance_state,
        matched_policy_id=(
            _optional_string(matched_policy.get("policy_id"))
            if isinstance(matched_policy, Mapping)
            else None
        ),
        scope=context,
        expires_at=(
            _optional_string(matched_policy.get("expires_at"))
            if isinstance(matched_policy, Mapping)
            else None
        ),
        revoked=(
            matched_policy.get("revoked") is True
            if isinstance(matched_policy, Mapping)
            else False
        ),
        execution_performed=False,
        delivery_performed=False,
        skipped_reasons=skipped_reasons,
    )


def _expiration_state(decision: StopAskingDecision) -> str:
    if decision.asking_suppressed and decision.expires_at:
        return "active_until_expiration"
    if "matching_stop_asking_policy_expired" in decision.skipped_reasons:
        return "matched_policy_expired"
    if decision.expires_at:
        return "expiration_recorded"
    return "not_applicable"


def _revocation_state(decision: StopAskingDecision) -> str:
    if decision.revoked:
        return "matched_policy_revoked"
    if "matching_stop_asking_policy_revoked" in decision.skipped_reasons:
        return "revoked_policy_seen"
    return "not_revoked"


def _normalize_scope(scope: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(scope, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for field in STOP_ASKING_SCOPE_FIELDS:
        value = _string(scope.get(field))
        if value:
            normalized[field] = value
    return normalized


def _scope_matches(policy_scope: dict[str, str], context: dict[str, str]) -> bool:
    if not policy_scope:
        return False
    for key, value in policy_scope.items():
        if context.get(key) != value:
            return False
    return True


def _load_policies(store_path: str | Path) -> list[dict[str, Any]]:
    path = Path(store_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, Mapping):
        return []
    policies = data.get("policies")
    if not isinstance(policies, list):
        return []
    records: list[dict[str, Any]] = []
    for item in policies:
        if isinstance(item, dict):
            records.append(dict(item))
    return records


def _write_policies(
    policies: list[dict[str, Any]],
    store_path: str | Path,
) -> None:
    path = Path(store_path)
    atomic_write_text(
        path,
        json.dumps(
            {
                "version": 1,
                "contract_id": STOP_ASKING_POLICY_CONTRACT_ID,
                "policies": policies,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _policy_id(
    *,
    scope: dict[str, str],
    created_by: str,
    created_at: str,
    expires_at: str,
) -> str:
    payload = json.dumps(
        {
            "scope": scope,
            "created_by": created_by,
            "created_at": created_at,
            "expires_at": expires_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sap_{hashlib.sha256(payload).hexdigest()[:16]}"


def _override_receipt_id(
    *,
    scope: Mapping[str, str],
    matched_policy_id: str | None,
    asking_suppressed: bool,
    asking_allowed: bool,
    governance_state: str,
    skipped_reasons: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "contract_id": OPERATOR_OVERRIDE_RECEIPT_CONTRACT_ID,
            "scope": dict(scope),
            "matched_policy_id": matched_policy_id,
            "asking_suppressed": asking_suppressed,
            "asking_allowed": asking_allowed,
            "governance_state": governance_state,
            "skipped_reasons": list(skipped_reasons),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"oor_{hashlib.sha256(payload).hexdigest()[:16]}"


def _datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        current = value
    elif isinstance(value, str) and value.strip():
        try:
            current = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = _datetime(value)
    if parsed is None:
        return datetime.now(timezone.utc).isoformat()
    return parsed.isoformat()


def _required_timestamp(value: datetime | str) -> str | None:
    parsed = _datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _forbidden_paths(value: Any, path: str = "") -> tuple[str, ...]:
    forbidden = {
        "body",
        "contact",
        "contact_value",
        "draft_text",
        "email",
        "message",
        "payload",
        "phone",
        "prompt",
        "raw_results",
        "rendered_context",
        "subject",
        "text",
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


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _operator_id(value: Any) -> str:
    text = _string(value)
    return text if text.startswith("operator:") else ""


__all__ = [
    "DEFAULT_STOP_ASKING_POLICY_STORE_PATH",
    "OPERATOR_OVERRIDE_RECEIPT_CONTRACT_ID",
    "OPERATOR_OVERRIDE_RECEIPT_TYPE",
    "STOP_ASKING_POLICY_CONTRACT_ID",
    "STOP_ASKING_GOVERNANCE_ENABLED",
    "OperatorOverrideReceipt",
    "StopAskingDecision",
    "build_governance_boundary_diagnostics",
    "build_stop_asking_operator_diagnostics",
    "create_stop_asking_policy",
    "evaluate_stop_asking_policy",
    "materialize_operator_override_receipt",
    "revoke_stop_asking_policy",
    "validate_operator_override_receipt",
    "validate_stop_asking_decision",
]
