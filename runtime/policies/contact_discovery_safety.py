from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


CONTACT_DISCOVERY_SAFETY_CONTRACTS_PATH = Path(
    "agents/shared/contracts/contact_discovery_safety_contracts.json"
)
CONTACT_DISCOVERY_SAFETY_GOVERNANCE_PATH = Path(
    "agents/shared/governance/contact_discovery_safety.json"
)
CONTACT_DISCOVERY_SAFETY_POLICY_PATH = Path(
    "agents/shared/policies/contact_discovery_safety_policy.json"
)

CONTACT_CLASS_PUBLIC_PROFESSIONAL_EMAIL = "public_professional_email"
CONTACT_CLASS_PUBLIC_OFFICE_PRESS = "public_office_press_contact"
CONTACT_CLASS_PUBLIC_BOOKING_REPRESENTATIVE = "public_booking_representative"
CONTACT_CLASS_PUBLIC_SOCIAL_PROFILE = "public_social_profile"
CONTACT_CLASS_UNVERIFIED_POSSIBLE = "unverified_possible_contact"
CONTACT_CLASS_REJECTED = "rejected_private_or_personal_contact"

VERIFICATION_VERIFIED_PUBLIC_PROFESSIONAL = "verified_public_professional"
VERIFICATION_PUBLIC_SOURCE_UNVERIFIED = "public_source_unverified"
VERIFICATION_REJECTED_PRIVATE_OR_PERSONAL = "rejected_private_or_personal"
VERIFICATION_REJECTED_UNSAFE_ACQUISITION = "rejected_unsafe_acquisition"

FORBIDDEN_AUDIT_FIELDS = {
    "address",
    "citations",
    "contact_value",
    "email",
    "phone",
    "provider_payload",
    "query",
    "raw_provider_payload",
    "raw_results",
    "rendered_context",
    "source_refs",
}


class ContactDiscoverySafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContactDiscoverySafetyContract:
    id: str
    semantic_type: str
    allowed_contact_classes: tuple[str, ...]
    verification_states: tuple[str, ...]
    required_contact_fields: tuple[str, ...]
    content_safe_audit_fields: tuple[str, ...]
    forbidden_audit_fields: tuple[str, ...]
    semantic_authority: dict[str, bool]
    fail_closed: dict[str, bool]


@dataclass(frozen=True)
class ContactDiscoverySafetyGovernance:
    id: str
    semantic_type: str
    governance_state: str
    live_contact_search_enabled: bool
    public_professional_sources_only: bool
    allowed_source_types: tuple[str, ...]
    forbidden_source_contexts: tuple[str, ...]


@dataclass(frozen=True)
class ContactDiscoverySafetyPolicy:
    id: str
    semantic_type: str
    runtime_bounds: dict[str, bool]
    contact_class_rules: dict[str, dict[str, Any]]
    unsafe_contact_types: tuple[str, ...]
    unsafe_acquisition_methods: tuple[str, ...]


@dataclass(frozen=True)
class ContactDiscoverySafetyDecision:
    semantic_type: str
    contact_class: str
    verification_state: str
    allowed_for_contact_use: bool
    fail_closed: bool
    skipped_reasons: tuple[str, ...]
    policy_id: str | None = None
    governance_id: str | None = None
    contract_id: str | None = None

    def to_audit_record(self) -> dict[str, Any]:
        return {
            "semantic_type": self.semantic_type,
            "contact_class": self.contact_class,
            "verification_state": self.verification_state,
            "allowed_for_contact_use": self.allowed_for_contact_use,
            "fail_closed": self.fail_closed,
            "policy_id": self.policy_id,
            "governance_id": self.governance_id,
            "contract_id": self.contract_id,
            "skipped_reasons": list(self.skipped_reasons),
        }


def evaluate_contact_discovery_safety(
    contact_record: Mapping[str, Any] | None,
    *,
    root: str | Path | None = None,
) -> ContactDiscoverySafetyDecision:
    contract = load_contact_discovery_safety_contract(root)
    governance = load_contact_discovery_safety_governance(root)
    policy = load_contact_discovery_safety_policy(root)
    reasons: list[str] = []

    if contract is None:
        reasons.append("missing_contract")
    if governance is None:
        reasons.append("missing_governance")
    if policy is None:
        reasons.append("missing_policy")
    if not isinstance(contact_record, Mapping):
        reasons.append("missing_contact_record")
        return _decision(
            contact_class=CONTACT_CLASS_REJECTED,
            verification_state=VERIFICATION_REJECTED_PRIVATE_OR_PERSONAL,
            reasons=reasons,
            contract=contract,
            governance=governance,
            policy=policy,
        )

    if "raw_provider_payload" in contact_record or "provider_payload" in contact_record:
        reasons.append("raw_provider_payload_present")

    contact_type = _safe_string(contact_record.get("contact_type"))
    source_type = _safe_string(contact_record.get("source_type"))
    acquisition_method = _safe_string(contact_record.get("acquisition_method"))
    source_public = contact_record.get("source_public")
    source_professional = contact_record.get("source_professional")

    missing = [
        field
        for field in (
            contract.required_contact_fields
            if contract
            else (
                "contact_type",
                "source_type",
                "source_public",
                "source_professional",
                "acquisition_method",
                "verification_state",
            )
        )
        if field not in contact_record
    ]
    if missing:
        reasons.append("missing_required_contact_field")

    if source_public is not True:
        reasons.append("non_public_source")
    if source_professional is not True:
        reasons.append("non_professional_source")
    if governance and source_type not in governance.allowed_source_types:
        reasons.append("source_type_not_allowed")

    if policy and contact_type in policy.unsafe_contact_types:
        reasons.append("personal_private_contact")
    if policy and acquisition_method in policy.unsafe_acquisition_methods:
        reasons.append("guessed_or_generated_contact")

    contact_class = _classify_contact_record(
        contact_type=contact_type,
        source_type=source_type,
        source_public=source_public,
        source_professional=source_professional,
        policy=policy,
    )
    verification_state = _verification_state_for(
        contact_class=contact_class,
        contact_record=contact_record,
        policy=policy,
        reasons=reasons,
    )

    if contact_class == CONTACT_CLASS_REJECTED:
        reasons.append("unknown_contact_class")
    if verification_state not in {
        VERIFICATION_VERIFIED_PUBLIC_PROFESSIONAL,
        VERIFICATION_PUBLIC_SOURCE_UNVERIFIED,
    }:
        reasons.append("contact_not_verified_for_use")

    return _decision(
        contact_class=contact_class,
        verification_state=verification_state,
        reasons=reasons,
        contract=contract,
        governance=governance,
        policy=policy,
    )


def validate_contact_discovery_record(
    contact_record: Mapping[str, Any] | None,
    *,
    root: str | Path | None = None,
) -> tuple[str, ...]:
    decision = evaluate_contact_discovery_safety(contact_record, root=root)
    return decision.skipped_reasons


def validate_contact_safety_audit_record(record: Any) -> tuple[str, ...]:
    if not isinstance(record, Mapping):
        return ("audit_record_not_object",)
    forbidden = sorted(FORBIDDEN_AUDIT_FIELDS & set(record))
    return tuple(f"forbidden_audit_field:{field}" for field in forbidden)


@lru_cache(maxsize=None)
def load_contact_discovery_safety_contract(
    root: str | Path | None = None,
) -> ContactDiscoverySafetyContract | None:
    try:
        data = _read_json(CONTACT_DISCOVERY_SAFETY_CONTRACTS_PATH, root)
        contracts = data.get("contracts")
        if not isinstance(contracts, list) or len(contracts) != 1:
            raise ContactDiscoverySafetyError("contract list invalid")
        entry = contracts[0]
        if not isinstance(entry, dict):
            raise ContactDiscoverySafetyError("contract entry invalid")
        safe_fields = _string_tuple(entry.get("content_safe_audit_fields"))
        forbidden_fields = _string_tuple(entry.get("forbidden_audit_fields"))
        if FORBIDDEN_AUDIT_FIELDS & set(safe_fields):
            raise ContactDiscoverySafetyError("unsafe audit field exposed")
        if not FORBIDDEN_AUDIT_FIELDS.issubset(set(forbidden_fields)):
            raise ContactDiscoverySafetyError("forbidden audit fields missing")
        semantic_authority = _bool_object(entry.get("semantic_authority"))
        if any(value is not False for value in semantic_authority.values()):
            raise ContactDiscoverySafetyError("contract grants semantic authority")
        fail_closed = _bool_object(entry.get("fail_closed"))
        if any(value is not True for value in fail_closed.values()):
            raise ContactDiscoverySafetyError("contract does not fail closed")
        return ContactDiscoverySafetyContract(
            id=_required_string(entry.get("id")),
            semantic_type=_required_string(entry.get("semantic_type")),
            allowed_contact_classes=_string_tuple(
                entry.get("allowed_contact_classes")
            ),
            verification_states=_string_tuple(entry.get("verification_states")),
            required_contact_fields=_string_tuple(entry.get("required_contact_fields")),
            content_safe_audit_fields=safe_fields,
            forbidden_audit_fields=forbidden_fields,
            semantic_authority=semantic_authority,
            fail_closed=fail_closed,
        )
    except (FileNotFoundError, json.JSONDecodeError, ContactDiscoverySafetyError):
        return None


@lru_cache(maxsize=None)
def load_contact_discovery_safety_governance(
    root: str | Path | None = None,
) -> ContactDiscoverySafetyGovernance | None:
    try:
        data = _read_json(CONTACT_DISCOVERY_SAFETY_GOVERNANCE_PATH, root)
        if data.get("version") != 1:
            raise ContactDiscoverySafetyError("governance version invalid")
        return ContactDiscoverySafetyGovernance(
            id=_required_string(data.get("id")),
            semantic_type=_required_string(data.get("semantic_type")),
            governance_state=_required_string(data.get("governance_state")),
            live_contact_search_enabled=_required_bool(
                data.get("live_contact_search_enabled")
            ),
            public_professional_sources_only=_required_bool(
                data.get("public_professional_sources_only")
            ),
            allowed_source_types=_string_tuple(data.get("allowed_source_types")),
            forbidden_source_contexts=_string_tuple(
                data.get("forbidden_source_contexts")
            ),
        )
    except (FileNotFoundError, json.JSONDecodeError, ContactDiscoverySafetyError):
        return None


@lru_cache(maxsize=None)
def load_contact_discovery_safety_policy(
    root: str | Path | None = None,
) -> ContactDiscoverySafetyPolicy | None:
    try:
        data = _read_json(CONTACT_DISCOVERY_SAFETY_POLICY_PATH, root)
        if data.get("version") != 1:
            raise ContactDiscoverySafetyError("policy version invalid")
        runtime_bounds = _bool_object(data.get("runtime_bounds"))
        for required_false in (
            "contact_value_generation_allowed",
            "email_pattern_inference_allowed",
            "private_phone_harvesting_allowed",
            "personal_address_discovery_allowed",
            "private_personal_data_scraping_allowed",
            "raw_provider_payload_as_contact_record_allowed",
            "memory_writes_allowed",
            "automatic_db_update_allowed",
            "social_engineering_language_allowed",
        ):
            if runtime_bounds.get(required_false) is not False:
                raise ContactDiscoverySafetyError("unsafe runtime bound enabled")
        for required_true in (
            "public_professional_sources_only",
            "content_safe_audit_required",
        ):
            if runtime_bounds.get(required_true) is not True:
                raise ContactDiscoverySafetyError("required runtime bound missing")
        rules = data.get("contact_class_rules")
        if not isinstance(rules, dict) or not rules:
            raise ContactDiscoverySafetyError("contact class rules invalid")
        return ContactDiscoverySafetyPolicy(
            id=_required_string(data.get("id")),
            semantic_type=_required_string(data.get("semantic_type")),
            runtime_bounds=runtime_bounds,
            contact_class_rules={str(key): dict(value) for key, value in rules.items()},
            unsafe_contact_types=_string_tuple(data.get("unsafe_contact_types")),
            unsafe_acquisition_methods=_string_tuple(
                data.get("unsafe_acquisition_methods")
            ),
        )
    except (FileNotFoundError, json.JSONDecodeError, ContactDiscoverySafetyError):
        return None


def _classify_contact_record(
    *,
    contact_type: str | None,
    source_type: str | None,
    source_public: Any,
    source_professional: Any,
    policy: ContactDiscoverySafetyPolicy | None,
) -> str:
    if not policy or source_public is not True or source_professional is not True:
        return CONTACT_CLASS_REJECTED
    for contact_class, rule in policy.contact_class_rules.items():
        if contact_type not in tuple(rule.get("contact_types", ())):
            continue
        if source_type not in tuple(rule.get("source_types", ())):
            continue
        flags = rule.get("required_flags", {})
        if not isinstance(flags, dict):
            continue
        if any(flags.get(flag) is not True for flag in flags):
            continue
        return contact_class
    return CONTACT_CLASS_REJECTED


def _verification_state_for(
    *,
    contact_class: str,
    contact_record: Mapping[str, Any],
    policy: ContactDiscoverySafetyPolicy | None,
    reasons: list[str],
) -> str:
    if reasons or contact_class == CONTACT_CLASS_REJECTED or not policy:
        if "guessed_or_generated_contact" in reasons:
            return VERIFICATION_REJECTED_UNSAFE_ACQUISITION
        return VERIFICATION_REJECTED_PRIVATE_OR_PERSONAL
    declared = _safe_string(contact_record.get("verification_state"))
    expected = policy.contact_class_rules.get(contact_class, {}).get(
        "verification_state"
    )
    if declared == expected:
        return declared
    return VERIFICATION_REJECTED_PRIVATE_OR_PERSONAL


def _decision(
    *,
    contact_class: str,
    verification_state: str,
    reasons: list[str],
    contract: ContactDiscoverySafetyContract | None,
    governance: ContactDiscoverySafetyGovernance | None,
    policy: ContactDiscoverySafetyPolicy | None,
) -> ContactDiscoverySafetyDecision:
    deduped_reasons = tuple(dict.fromkeys(reasons))
    allowed = not deduped_reasons and contact_class != CONTACT_CLASS_REJECTED
    return ContactDiscoverySafetyDecision(
        semantic_type="contact_discovery_safety",
        contact_class=contact_class,
        verification_state=verification_state,
        allowed_for_contact_use=allowed,
        fail_closed=not allowed,
        skipped_reasons=deduped_reasons,
        policy_id=policy.id if policy else None,
        governance_id=governance.id if governance else None,
        contract_id=contract.id if contract else None,
    )


def _read_json(path: Path, root: str | Path | None) -> dict[str, Any]:
    full_path = path if root is None else Path(root) / path
    data = json.loads(full_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContactDiscoverySafetyError("json root must be object")
    return data


def _required_string(value: Any) -> str:
    text = _safe_string(value)
    if text is None:
        raise ContactDiscoverySafetyError("required string missing")
    return text


def _required_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ContactDiscoverySafetyError("required bool missing")
    return value


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ContactDiscoverySafetyError("string list invalid")
    return tuple(item.strip() for item in value)


def _bool_object(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, bool)
        for key, item in value.items()
    ):
        raise ContactDiscoverySafetyError("bool object invalid")
    return dict(value)


__all__ = [
    "CONTACT_CLASS_PUBLIC_BOOKING_REPRESENTATIVE",
    "CONTACT_CLASS_PUBLIC_OFFICE_PRESS",
    "CONTACT_CLASS_PUBLIC_PROFESSIONAL_EMAIL",
    "CONTACT_CLASS_PUBLIC_SOCIAL_PROFILE",
    "CONTACT_CLASS_REJECTED",
    "CONTACT_CLASS_UNVERIFIED_POSSIBLE",
    "CONTACT_DISCOVERY_SAFETY_CONTRACTS_PATH",
    "CONTACT_DISCOVERY_SAFETY_GOVERNANCE_PATH",
    "CONTACT_DISCOVERY_SAFETY_POLICY_PATH",
    "VERIFICATION_PUBLIC_SOURCE_UNVERIFIED",
    "VERIFICATION_REJECTED_PRIVATE_OR_PERSONAL",
    "VERIFICATION_REJECTED_UNSAFE_ACQUISITION",
    "VERIFICATION_VERIFIED_PUBLIC_PROFESSIONAL",
    "ContactDiscoverySafetyDecision",
    "evaluate_contact_discovery_safety",
    "load_contact_discovery_safety_contract",
    "load_contact_discovery_safety_governance",
    "load_contact_discovery_safety_policy",
    "validate_contact_discovery_record",
    "validate_contact_safety_audit_record",
]
