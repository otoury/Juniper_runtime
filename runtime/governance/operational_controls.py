from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core.atomic_write import atomic_write_text


OPERATIONAL_CONTROLS_PATH = Path("agents/shared/governance/operational_controls.json")
CONTROL_STATE_ENABLED = "enabled"
CONTROL_STATE_DISABLED = "disabled"
ACCESS_STATE_ALLOWED = "allowed"
ACCESS_STATE_BLOCKED = "blocked"
ALLOWED_BINARY_STATES = frozenset({CONTROL_STATE_ENABLED, CONTROL_STATE_DISABLED})
ALLOWED_ACCESS_STATES = frozenset({ACCESS_STATE_ALLOWED, ACCESS_STATE_BLOCKED})
FORBIDDEN_RECEIPT_FIELDS = {
    "api_key",
    "authorization_header",
    "bearer_token",
    "credential",
    "memory_write",
    "provider_payload",
    "query",
    "raw_provider_payload",
    "raw_results",
}


@dataclass(frozen=True)
class OperationalControlDecision:
    control: str
    effective_state: str
    allowed: bool
    source: str
    operator_identity: str | None = None
    expires_at: str | None = None
    quota: dict[str, Any] | None = None
    receipt_ref: str | None = None
    fail_closed: bool = False
    reason_codes: tuple[str, ...] = ()

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "effective_state": self.effective_state,
            "allowed": self.allowed,
            "source": self.source,
            "operator_identity": self.operator_identity,
            "expires_at": self.expires_at,
            "quota": deepcopy(self.quota) if self.quota is not None else None,
            "receipt_ref": self.receipt_ref,
            "fail_closed": self.fail_closed,
            "reason_codes": list(self.reason_codes),
            "planner_semantic_authority": False,
            "semantic_reinterpretation_performed": False,
            "hidden_provider_execution_allowed": False,
            "hidden_approval_bypass_allowed": False,
            "memory_writes_allowed": False,
        }


def evaluate_cloud_execution_control(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> OperationalControlDecision:
    return _evaluate_binary_control(
        "cloud_execution",
        root=root,
        environ=environ,
        now=now,
        bootstrap_env_var="CLOUD_EXECUTION_ENABLED",
        disabled_when_env_true="CLOUD_DRY_RUN",
    )


def evaluate_tavily_execution_control(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> OperationalControlDecision:
    return _evaluate_binary_control(
        "tavily_execution",
        root=root,
        environ=environ,
        now=now,
        bootstrap_env_var="TAVILY_EXECUTION_ENABLED",
    )


def evaluate_provider_authorization_control(
    provider_id: str | None,
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> OperationalControlDecision:
    provider = _safe_string(provider_id)
    state = _load_operational_controls(root=root, environ=environ)
    if state is None:
        return _missing_governance_bootstrap_decision("provider_authorization")
    if state.get("_malformed") is True:
        return _blocked_decision(
            "provider_authorization",
            source="fail_closed",
            reason_codes=("malformed_operational_governance",),
        )
    if provider is None:
        return _blocked_decision(
            "provider_authorization",
            source="request",
            reason_codes=("missing_provider_id",),
        )
    control = _control_object(state, "provider_authorization")
    if control is None:
        return _blocked_decision(
            "provider_authorization",
            source="fail_closed",
            reason_codes=("missing_provider_authorization_control",),
        )
    for entry in _object_list(control.get("providers")):
        if _safe_string(entry.get("provider_id")) != provider:
            continue
        if _expired(entry.get("expires_at"), now=now):
            return _blocked_decision(
                "provider_authorization",
                source="expired_provider_grant",
                operator_identity=_safe_string(entry.get("operator_identity")),
                expires_at=_safe_string(entry.get("expires_at")),
                reason_codes=("provider_authorization_expired",),
            )
        return _access_decision(
            "provider_authorization",
            state=_required_access_state(entry.get("state")),
            source="explicit_provider",
            operator_identity=_safe_string(entry.get("operator_identity"))
            or _safe_string(control.get("operator_identity")),
            expires_at=_safe_string(entry.get("expires_at")),
            reason_codes=("explicit_provider_authorization",),
        )
    return _access_decision(
        "provider_authorization",
        state=_required_access_state(control.get("default_state")),
        source="default_provider_authorization",
        operator_identity=_safe_string(control.get("operator_identity")),
        reason_codes=("provider_authorization_default",),
    )


def evaluate_telegram_user_access(
    *,
    bot_name: str | None,
    user_id: str | None,
    legacy_allowed: bool = False,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> OperationalControlDecision:
    del bot_name
    user = _safe_string(user_id)
    state = _load_operational_controls(root=root, environ=environ)
    if state is None:
        return OperationalControlDecision(
            control="telegram_user_access",
            effective_state=ACCESS_STATE_ALLOWED if legacy_allowed else ACCESS_STATE_BLOCKED,
            allowed=bool(legacy_allowed),
            source="legacy_bootstrap_auth_store",
            reason_codes=("operational_governance_missing_bootstrap_defaults",),
        )
    if state.get("_malformed") is True:
        return _blocked_decision(
            "telegram_user_access",
            source="fail_closed",
            reason_codes=("malformed_operational_governance",),
        )
    if user is None:
        return _blocked_decision(
            "telegram_user_access",
            source="request",
            reason_codes=("missing_user_id",),
        )
    control = _control_object(state, "telegram_user_access")
    if control is None:
        return _blocked_decision(
            "telegram_user_access",
            source="fail_closed",
            reason_codes=("missing_telegram_user_access_control",),
        )
    for entry in _object_list(control.get("users")):
        if _safe_string(entry.get("user_id")) != user:
            continue
        if _expired(entry.get("expires_at"), now=now):
            return _blocked_decision(
                "telegram_user_access",
                source="expired_user_control",
                operator_identity=_safe_string(entry.get("operator_identity")),
                expires_at=_safe_string(entry.get("expires_at")),
                reason_codes=("telegram_user_control_expired",),
            )
        return _access_decision(
            "telegram_user_access",
            state=_required_access_state(entry.get("state")),
            source="explicit_user",
            operator_identity=_safe_string(entry.get("operator_identity"))
            or _safe_string(control.get("operator_identity")),
            expires_at=_safe_string(entry.get("expires_at")),
            quota=_quota(entry.get("quota")),
            reason_codes=("explicit_telegram_user_control",),
        )
    default_state = _required_access_state(control.get("default_state"))
    if legacy_allowed and default_state == ACCESS_STATE_BLOCKED:
        return OperationalControlDecision(
            control="telegram_user_access",
            effective_state=ACCESS_STATE_ALLOWED,
            allowed=True,
            source="legacy_bootstrap_auth_store",
            operator_identity=_safe_string(control.get("operator_identity")),
            reason_codes=("legacy_bootstrap_user_allowed",),
        )
    return _access_decision(
        "telegram_user_access",
        state=default_state,
        source="default_telegram_user_access",
        operator_identity=_safe_string(control.get("operator_identity")),
        reason_codes=("telegram_user_access_default",),
    )


def build_operational_control_change_receipt(
    *,
    control: str,
    previous_state: str | None,
    requested_state: str,
    effective_state: str,
    operator_identity: str,
    target: dict[str, Any] | None = None,
    expires_at: str | None = None,
    quota: dict[str, Any] | None = None,
    reason: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    operator = _safe_string(operator_identity)
    if operator is None:
        raise ValueError("operator_identity is required for control receipts")
    timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    target_payload = _safe_target(target)
    receipt_ref_parts = [
        "receipt:operational_control_change",
        _safe_string(control) or "unknown_control",
        _safe_string(target_payload.get("provider_id"))
        or _safe_string(target_payload.get("user_id"))
        or "global",
        timestamp.strftime("%Y%m%dT%H%M%SZ"),
    ]
    receipt = {
        "receipt_type": "operational_control_change_receipt",
        "receipt_ref": ":".join(receipt_ref_parts),
        "control": _safe_string(control),
        "previous_state": _safe_string(previous_state),
        "requested_state": _safe_string(requested_state),
        "effective_state": _safe_string(effective_state),
        "operator_identity": operator,
        "target": target_payload,
        "expires_at": _safe_string(expires_at),
        "quota": _quota(quota),
        "reason": _safe_string(reason),
        "generated_at": timestamp.isoformat(),
        "planner_semantic_authority": False,
        "semantic_reinterpretation_performed": False,
        "hidden_provider_execution_allowed": False,
        "hidden_approval_bypass_allowed": False,
        "memory_writes_performed": False,
    }
    errors = validate_operational_control_change_receipt(receipt)
    if errors:
        raise ValueError(",".join(errors))
    return receipt


def validate_operational_control_change_receipt(record: Any) -> tuple[str, ...]:
    if not isinstance(record, dict):
        return ("receipt_not_object",)
    errors: list[str] = []
    if record.get("receipt_type") != "operational_control_change_receipt":
        errors.append("invalid_receipt_type")
    for field in ("receipt_ref", "control", "requested_state", "effective_state", "operator_identity", "generated_at"):
        if _safe_string(record.get(field)) is None:
            errors.append(f"missing_{field}")
    forbidden = sorted(FORBIDDEN_RECEIPT_FIELDS & set(record))
    errors.extend(f"forbidden_receipt_field:{field}" for field in forbidden)
    if record.get("planner_semantic_authority") is not False:
        errors.append("planner_semantic_authority_not_false")
    if record.get("semantic_reinterpretation_performed") is not False:
        errors.append("semantic_reinterpretation_not_false")
    if record.get("hidden_provider_execution_allowed") is not False:
        errors.append("hidden_provider_execution_not_false")
    if record.get("hidden_approval_bypass_allowed") is not False:
        errors.append("hidden_approval_bypass_not_false")
    if record.get("memory_writes_performed") is not False:
        errors.append("memory_writes_not_false")
    return tuple(errors)


def apply_operational_control_change(
    state: dict[str, Any],
    *,
    control: str,
    requested_state: str,
    operator_identity: str,
    target: dict[str, Any] | None = None,
    expires_at: str | None = None,
    quota: dict[str, Any] | None = None,
    reason: str | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    new_state = deepcopy(state)
    controls = new_state.setdefault("controls", {})
    control_name = _safe_string(control)
    if control_name is None:
        raise ValueError("control is required")
    current = controls.setdefault(control_name, {})
    previous_state = _safe_string(current.get("state") or current.get("default_state"))
    target_payload = _safe_target(target)
    operator = _safe_string(operator_identity)
    if operator is None:
        raise ValueError("operator_identity is required")

    if control_name in {"cloud_execution", "tavily_execution"}:
        current["state"] = _required_binary_state(requested_state)
        current["operator_identity"] = operator
        if expires_at is not None:
            current["expires_at"] = _safe_string(expires_at)
    elif control_name == "provider_authorization":
        provider_id = _safe_string(target_payload.get("provider_id"))
        if provider_id is None:
            current["default_state"] = _required_access_state(requested_state)
        else:
            providers = current.setdefault("providers", [])
            _upsert_target(providers, "provider_id", provider_id, requested_state, operator, expires_at, None)
    elif control_name == "telegram_user_access":
        user_id = _safe_string(target_payload.get("user_id"))
        if user_id is None:
            current["default_state"] = _required_access_state(requested_state)
        else:
            users = current.setdefault("users", [])
            _upsert_target(users, "user_id", user_id, requested_state, operator, expires_at, quota)
    else:
        raise ValueError("unsupported operational control")

    if reason is not None:
        current["reason"] = _safe_string(reason)
    receipt = build_operational_control_change_receipt(
        control=control_name,
        previous_state=previous_state,
        requested_state=requested_state,
        effective_state=requested_state,
        operator_identity=operator,
        target=target_payload,
        expires_at=expires_at,
        quota=quota,
        reason=reason,
        generated_at=generated_at,
    )
    return new_state, receipt


def load_operational_controls_state(
    *,
    root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    state = _load_operational_controls(root=root, environ=environ)
    if state is None:
        raise ValueError("missing_operational_governance")
    if state.get("_malformed") is True:
        raise ValueError("malformed_operational_governance")
    return deepcopy(state)


def save_operational_controls_state(
    state: dict[str, Any],
    *,
    root: str | Path | None = None,
) -> None:
    if not isinstance(state, dict):
        raise ValueError("operational_governance_state_not_object")
    bounds = state.get("runtime_bounds")
    if not isinstance(bounds, dict):
        raise ValueError("missing_runtime_bounds")
    required_false = (
        "planner_semantic_authority",
        "semantic_reinterpretation_performed",
        "hidden_provider_execution_allowed",
        "hidden_approval_bypass_allowed",
        "memory_writes_allowed",
    )
    if any(bounds.get(field) is not False for field in required_false):
        raise ValueError("invalid_runtime_bounds")
    if bounds.get("env_flags_are_bootstrap_defaults_only") is not True:
        raise ValueError("invalid_runtime_bounds")

    path = OPERATIONAL_CONTROLS_PATH if root is None else Path(root) / OPERATIONAL_CONTROLS_PATH
    atomic_write_text(
        path,
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _evaluate_binary_control(
    control_name: str,
    *,
    root: str | Path | None,
    environ: Mapping[str, str] | None,
    now: datetime | None,
    bootstrap_env_var: str,
    disabled_when_env_true: str | None = None,
) -> OperationalControlDecision:
    state = _load_operational_controls(root=root, environ=environ)
    if state is None:
        return _bootstrap_binary_decision(
            control_name,
            environ=environ,
            bootstrap_env_var=bootstrap_env_var,
            disabled_when_env_true=disabled_when_env_true,
            missing_governance=True,
        )
    if state.get("_malformed") is True:
        return _blocked_decision(
            control_name,
            source="fail_closed",
            effective_state=CONTROL_STATE_DISABLED,
            reason_codes=("malformed_operational_governance",),
        )
    control = _control_object(state, control_name)
    if control is None:
        return _blocked_decision(
            control_name,
            source="fail_closed",
            effective_state=CONTROL_STATE_DISABLED,
            reason_codes=(f"missing_{control_name}_control",),
        )
    if _expired(control.get("expires_at"), now=now):
        return _blocked_decision(
            control_name,
            source="expired_control",
            effective_state=CONTROL_STATE_DISABLED,
            operator_identity=_safe_string(control.get("operator_identity")),
            expires_at=_safe_string(control.get("expires_at")),
            reason_codes=(f"{control_name}_expired",),
        )
    state_value = _required_binary_state(control.get("state"))
    return OperationalControlDecision(
        control=control_name,
        effective_state=state_value,
        allowed=state_value == CONTROL_STATE_ENABLED,
        source="explicit_governance",
        operator_identity=_safe_string(control.get("operator_identity")),
        expires_at=_safe_string(control.get("expires_at")),
        fail_closed=state_value != CONTROL_STATE_ENABLED,
        reason_codes=(f"{control_name}_{state_value}",),
    )


def _load_operational_controls(
    *,
    root: str | Path | None,
    environ: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    del environ
    path = OPERATIONAL_CONTROLS_PATH if root is None else Path(root) / OPERATIONAL_CONTROLS_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return {"_malformed": True}
        bounds = data.get("runtime_bounds")
        if not isinstance(bounds, dict):
            return {"_malformed": True}
        required_false = (
            "planner_semantic_authority",
            "semantic_reinterpretation_performed",
            "hidden_provider_execution_allowed",
            "hidden_approval_bypass_allowed",
            "memory_writes_allowed",
        )
        if any(bounds.get(field) is not False for field in required_false):
            return {"_malformed": True}
        if bounds.get("env_flags_are_bootstrap_defaults_only") is not True:
            return {"_malformed": True}
        return data
    except (OSError, json.JSONDecodeError):
        return {"_malformed": True}


def _bootstrap_binary_decision(
    control: str,
    *,
    environ: Mapping[str, str] | None,
    bootstrap_env_var: str,
    disabled_when_env_true: str | None,
    missing_governance: bool,
) -> OperationalControlDecision:
    env = os.environ if environ is None else environ
    if disabled_when_env_true and _truthy(env.get(disabled_when_env_true)):
        return OperationalControlDecision(
            control=control,
            effective_state=CONTROL_STATE_DISABLED,
            allowed=False,
            source=f"bootstrap_env:{disabled_when_env_true}",
            fail_closed=True,
            reason_codes=("env_bootstrap_disabled",),
        )
    raw = env.get(bootstrap_env_var)
    if raw is not None:
        enabled = _truthy(raw)
        return OperationalControlDecision(
            control=control,
            effective_state=CONTROL_STATE_ENABLED if enabled else CONTROL_STATE_DISABLED,
            allowed=enabled,
            source=f"bootstrap_env:{bootstrap_env_var}",
            fail_closed=not enabled,
            reason_codes=("env_bootstrap_default",),
        )
    return OperationalControlDecision(
        control=control,
        effective_state=CONTROL_STATE_DISABLED,
        allowed=False,
        source="bootstrap_default_missing_governance" if missing_governance else "bootstrap_default",
        fail_closed=True,
        reason_codes=("operational_governance_missing_bootstrap_defaults",),
    )


def _missing_governance_bootstrap_decision(control: str) -> OperationalControlDecision:
    return OperationalControlDecision(
        control=control,
        effective_state=ACCESS_STATE_ALLOWED,
        allowed=True,
        source="bootstrap_default_missing_governance",
        reason_codes=("operational_governance_missing_bootstrap_defaults",),
    )


def _access_decision(
    control: str,
    *,
    state: str,
    source: str,
    operator_identity: str | None = None,
    expires_at: str | None = None,
    quota: dict[str, Any] | None = None,
    reason_codes: tuple[str, ...] = (),
) -> OperationalControlDecision:
    return OperationalControlDecision(
        control=control,
        effective_state=state,
        allowed=state == ACCESS_STATE_ALLOWED,
        source=source,
        operator_identity=operator_identity,
        expires_at=expires_at,
        quota=deepcopy(quota) if quota is not None else None,
        fail_closed=state != ACCESS_STATE_ALLOWED,
        reason_codes=reason_codes,
    )


def _blocked_decision(
    control: str,
    *,
    source: str,
    effective_state: str = ACCESS_STATE_BLOCKED,
    operator_identity: str | None = None,
    expires_at: str | None = None,
    reason_codes: tuple[str, ...],
) -> OperationalControlDecision:
    return OperationalControlDecision(
        control=control,
        effective_state=effective_state,
        allowed=False,
        source=source,
        operator_identity=operator_identity,
        expires_at=expires_at,
        fail_closed=True,
        reason_codes=reason_codes,
    )


def _control_object(state: dict[str, Any], control: str) -> dict[str, Any] | None:
    controls = state.get("controls")
    if not isinstance(controls, dict):
        return None
    value = controls.get(control)
    return value if isinstance(value, dict) else None


def _upsert_target(
    entries: list[Any],
    key: str,
    value: str,
    requested_state: str,
    operator_identity: str,
    expires_at: str | None,
    quota: dict[str, Any] | None,
) -> None:
    for entry in entries:
        if isinstance(entry, dict) and _safe_string(entry.get(key)) == value:
            target = entry
            break
    else:
        target = {key: value}
        entries.append(target)
    target["state"] = _required_access_state(requested_state)
    target["operator_identity"] = operator_identity
    if expires_at is not None:
        target["expires_at"] = _safe_string(expires_at)
    if quota is not None:
        target["quota"] = _quota(quota)


def _expired(value: Any, *, now: datetime | None) -> bool:
    text = _safe_string(value)
    if text is None:
        return False
    try:
        expires = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return True
    active_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return expires.astimezone(timezone.utc) <= active_now


def _object_list(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _quota(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed: dict[str, Any] = {}
    for key in ("max_requests", "window_seconds", "max_cost"):
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool) and item >= 0:
            allowed[key] = item
    return allowed or None


def _safe_target(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    target: dict[str, Any] = {}
    for key in ("provider_id", "user_id", "bot_name"):
        text = _safe_string(value.get(key))
        if text is not None:
            target[key] = text
    return target


def _required_binary_state(value: Any) -> str:
    state = _safe_string(value)
    if state not in ALLOWED_BINARY_STATES:
        return CONTROL_STATE_DISABLED
    return state


def _required_access_state(value: Any) -> str:
    state = _safe_string(value)
    if state not in ALLOWED_ACCESS_STATES:
        return ACCESS_STATE_BLOCKED
    return state


def _truthy(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "ACCESS_STATE_ALLOWED",
    "ACCESS_STATE_BLOCKED",
    "CONTROL_STATE_DISABLED",
    "CONTROL_STATE_ENABLED",
    "OPERATIONAL_CONTROLS_PATH",
    "OperationalControlDecision",
    "apply_operational_control_change",
    "build_operational_control_change_receipt",
    "evaluate_cloud_execution_control",
    "evaluate_provider_authorization_control",
    "evaluate_tavily_execution_control",
    "evaluate_telegram_user_access",
    "load_operational_controls_state",
    "save_operational_controls_state",
    "validate_operational_control_change_receipt",
]
