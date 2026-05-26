from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from runtime.workflows.trust_inheritance import (
    BOUNDARY_RESUMPTION,
    build_trust_inheritance_decision,
    build_workflow_step_trust_lineage,
    validate_trust_inheritance_decision,
)


WORKFLOW_RESUME_INTEGRITY_CONTRACT_ID = "workflow_resume_integrity_v1"
WORKFLOW_RESUME_INTEGRITY_RECEIPT_TYPE = "workflow_resume_integrity_receipt"


@dataclass(frozen=True)
class WorkflowResumeIntegrityReceipt:
    contract_id: str
    receipt_type: str
    receipt_id: str
    receipt_ref: str
    validation_performed: bool
    validation_passed: bool
    continuation_id: str | None
    workflow_instance_id: str | None
    workflow_id: str | None
    owning_agent: str | None
    step_id: str | None
    status: str | None
    approval_state: str | None
    suspended: bool | None
    lineage_record_refs: tuple[str, ...]
    artifact_ref_count: int
    action_ref_count: int
    skipped_reasons: tuple[str, ...]
    execution_performed: bool
    delivery_performed: bool
    semantic_reinterpretation_performed: bool
    trust_inheritance: dict[str, Any]

    def to_record(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "receipt_type": self.receipt_type,
            "receipt_id": self.receipt_id,
            "receipt_ref": self.receipt_ref,
            "validation_performed": self.validation_performed,
            "validation_passed": self.validation_passed,
            "continuation_id": self.continuation_id,
            "workflow_instance_id": self.workflow_instance_id,
            "workflow_id": self.workflow_id,
            "owning_agent": self.owning_agent,
            "step_id": self.step_id,
            "status": self.status,
            "approval_state": self.approval_state,
            "suspended": self.suspended,
            "lineage_record_refs": list(self.lineage_record_refs),
            "artifact_ref_count": self.artifact_ref_count,
            "action_ref_count": self.action_ref_count,
            "skipped_reasons": list(self.skipped_reasons),
            "execution_performed": self.execution_performed,
            "delivery_performed": self.delivery_performed,
            "semantic_reinterpretation_performed": (
                self.semantic_reinterpretation_performed
            ),
            "trust_inheritance": dict(self.trust_inheritance),
        }


def validate_workflow_resume_integrity(
    *,
    instance: dict[str, Any],
    workflow: Any,
    step: Any,
) -> WorkflowResumeIntegrityReceipt:
    reasons: list[str] = []
    lineage = _lineage_records(instance.get("state_lineage"))
    artifact_refs = _refs(instance.get("artifact_refs"), "artifact")
    action_refs = _refs(instance.get("action_refs"), "action")
    provenance = instance.get("provenance")

    if _string(instance.get("workflow_id")) != _string(
        getattr(workflow, "workflow_id", None)
    ):
        reasons.append("workflow_id_mismatch")
    if _string(instance.get("owning_agent")) != _string(
        getattr(workflow, "owning_agent", None)
    ):
        reasons.append("owning_agent_mismatch")
    if _string(instance.get("step_id")) != _string(getattr(step, "step_id", None)):
        reasons.append("step_id_mismatch")
    if artifact_refs is None:
        reasons.append("unsafe_artifact_refs")
    if action_refs is None:
        reasons.append("unsafe_action_refs")
    if not isinstance(provenance, dict):
        reasons.append("missing_resume_provenance")
    else:
        reasons.extend(_provenance_reasons(instance, provenance))
    reasons.extend(_lineage_reasons(instance, lineage))

    inheritance = _trust_inheritance(
        instance=instance,
        workflow=workflow,
        step=step,
        resume_integrity_passed=not reasons,
    )
    return _receipt(
        instance=instance,
        lineage=lineage,
        artifact_ref_count=len(artifact_refs or ()),
        action_ref_count=len(action_refs or ()),
        skipped_reasons=tuple(_unique(reasons)),
        trust_inheritance=inheritance,
    )


def validate_workflow_resume_integrity_receipt(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("contract_id") == WORKFLOW_RESUME_INTEGRITY_CONTRACT_ID
        and record.get("receipt_type") == WORKFLOW_RESUME_INTEGRITY_RECEIPT_TYPE
        and isinstance(record.get("receipt_id"), str)
        and record["receipt_id"].startswith("wri_")
        and record.get("receipt_ref") == f"receipt:workflow-resume-integrity:{record['receipt_id']}"
        and record.get("validation_performed") is True
        and isinstance(record.get("validation_passed"), bool)
        and isinstance(record.get("skipped_reasons"), list)
        and record.get("execution_performed") is False
        and record.get("delivery_performed") is False
        and record.get("semantic_reinterpretation_performed") is False
        and validate_trust_inheritance_decision(record.get("trust_inheritance"))
    )


def _receipt(
    *,
    instance: dict[str, Any],
    lineage: tuple[dict[str, Any], ...],
    artifact_ref_count: int,
    action_ref_count: int,
    skipped_reasons: tuple[str, ...],
    trust_inheritance: dict[str, Any],
) -> WorkflowResumeIntegrityReceipt:
    receipt_id = _receipt_id(
        instance=instance,
        lineage=lineage,
        skipped_reasons=skipped_reasons,
    )
    return WorkflowResumeIntegrityReceipt(
        contract_id=WORKFLOW_RESUME_INTEGRITY_CONTRACT_ID,
        receipt_type=WORKFLOW_RESUME_INTEGRITY_RECEIPT_TYPE,
        receipt_id=receipt_id,
        receipt_ref=f"receipt:workflow-resume-integrity:{receipt_id}",
        validation_performed=True,
        validation_passed=not skipped_reasons,
        continuation_id=_optional_string(instance.get("continuation_id")),
        workflow_instance_id=_optional_string(instance.get("workflow_instance_id")),
        workflow_id=_optional_string(instance.get("workflow_id")),
        owning_agent=_optional_string(instance.get("owning_agent")),
        step_id=_optional_string(instance.get("step_id")),
        status=_optional_string(instance.get("status")),
        approval_state=_optional_string(instance.get("approval_state")),
        suspended=instance.get("suspended") is True,
        lineage_record_refs=tuple(
            record["lineage_record_id"] for record in lineage
        ),
        artifact_ref_count=artifact_ref_count,
        action_ref_count=action_ref_count,
        skipped_reasons=skipped_reasons,
        execution_performed=False,
        delivery_performed=False,
        semantic_reinterpretation_performed=False,
        trust_inheritance=trust_inheritance,
    )


def _trust_inheritance(
    *,
    instance: dict[str, Any],
    workflow: Any,
    step: Any,
    resume_integrity_passed: bool,
) -> dict[str, Any]:
    provenance = (
        instance.get("provenance")
        if isinstance(instance.get("provenance"), dict)
        else {}
    )
    prior_lineage = (
        provenance.get("trust_lineage")
        if isinstance(provenance.get("trust_lineage"), dict)
        else None
    )
    current_lineage = build_workflow_step_trust_lineage(
        owning_agent=getattr(workflow, "owning_agent", None),
        workflow_id=getattr(workflow, "workflow_id", None),
        workflow_type=getattr(workflow, "workflow_type", None),
        step_id=getattr(step, "step_id", None),
        capability=getattr(step, "capability", None),
        action_type=getattr(step, "action_type", None),
    )
    return build_trust_inheritance_decision(
        boundary_type=BOUNDARY_RESUMPTION,
        prior_trust_state=_optional_string(provenance.get("trust_state")),
        prior_trust_lineage=prior_lineage,
        current_trust_lineage=current_lineage,
        resume_integrity_passed=resume_integrity_passed,
    ).to_record()


def _provenance_reasons(
    instance: dict[str, Any],
    provenance: dict[str, Any],
) -> tuple[str, ...]:
    reasons: list[str] = []
    for field in ("continuation_id", "workflow_instance_id", "workflow_id"):
        if _string(provenance.get(field)) != _string(instance.get(field)):
            reasons.append(f"provenance_{field}_mismatch")
    if provenance.get("delivery_performed") is not False:
        reasons.append("provenance_delivery_not_false")
    if provenance.get("execution_performed") is True:
        reasons.append("provenance_execution_not_false")
    return tuple(reasons)


def _lineage_reasons(
    instance: dict[str, Any],
    lineage: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    if not lineage:
        return ("missing_state_lineage",)

    reasons: list[str] = []
    previous_id: str | None = None
    for index, record in enumerate(lineage, start=1):
        if record["transition_sequence"] != index:
            reasons.append("state_lineage_sequence_gap")
        if record["previous_lineage_record_id"] != previous_id:
            reasons.append("state_lineage_previous_ref_mismatch")
        if record["lineage_record_id"] != _lineage_record_id(record):
            reasons.append("state_lineage_record_id_mismatch")
        for field in ("workflow_id", "workflow_instance_id", "continuation_id"):
            if _string(record.get(field)) != _string(instance.get(field)):
                reasons.append(f"state_lineage_{field}_mismatch")
        previous_id = record["lineage_record_id"]

    latest = lineage[-1]
    if latest["to_status"] != _string(instance.get("status")):
        reasons.append("state_lineage_status_mismatch")
    if latest["to_approval_state"] != _string(instance.get("approval_state")):
        reasons.append("state_lineage_approval_state_mismatch")
    if latest["to_suspended"] is not (instance.get("suspended") is True):
        reasons.append("state_lineage_suspended_mismatch")
    if latest["to_step_id"] != _string(instance.get("step_id")):
        reasons.append("state_lineage_step_mismatch")
    return tuple(reasons)


def _lineage_records(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()

    records: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return ()
        record = {
            "lineage_record_id": _string(item.get("lineage_record_id")),
            "workflow_id": _string(item.get("workflow_id")),
            "owning_agent": _string(item.get("owning_agent")),
            "workflow_instance_id": _string(item.get("workflow_instance_id")),
            "continuation_id": _string(item.get("continuation_id")),
            "transition_type": _string(item.get("transition_type")),
            "transition_sequence": _positive_int(item.get("transition_sequence")),
            "previous_lineage_record_id": _optional_string(
                item.get("previous_lineage_record_id")
            ),
            "from_status": _optional_string(item.get("from_status")),
            "to_status": _string(item.get("to_status")),
            "from_approval_state": _optional_string(item.get("from_approval_state")),
            "to_approval_state": _string(item.get("to_approval_state")),
            "from_suspended": _optional_bool(item.get("from_suspended")),
            "to_suspended": item.get("to_suspended") is True,
            "from_step_id": _optional_string(item.get("from_step_id")),
            "to_step_id": _string(item.get("to_step_id")),
            "transitioned_at": _string(item.get("transitioned_at")),
        }
        if not all(
            (
                record["lineage_record_id"],
                record["workflow_id"],
                record["workflow_instance_id"],
                record["continuation_id"],
                record["transition_type"],
            )
        ):
            return ()
        records.append(record)
    return tuple(records)


def _lineage_record_id(record: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "workflow_id": record.get("workflow_id"),
            "workflow_instance_id": record.get("workflow_instance_id"),
            "continuation_id": record.get("continuation_id"),
            "transition_type": record.get("transition_type"),
            "transition_sequence": record.get("transition_sequence"),
            "previous_lineage_record_id": record.get("previous_lineage_record_id"),
            "from_status": record.get("from_status"),
            "to_status": record.get("to_status"),
            "from_approval_state": record.get("from_approval_state"),
            "to_approval_state": record.get("to_approval_state"),
            "from_suspended": record.get("from_suspended"),
            "to_suspended": record.get("to_suspended"),
            "from_step_id": record.get("from_step_id"),
            "to_step_id": record.get("to_step_id"),
            "transitioned_at": record.get("transitioned_at"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"wfl_{hashlib.sha256(payload).hexdigest()[:16]}"


def _receipt_id(
    *,
    instance: dict[str, Any],
    lineage: tuple[dict[str, Any], ...],
    skipped_reasons: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "contract_id": WORKFLOW_RESUME_INTEGRITY_CONTRACT_ID,
            "workflow_id": _string(instance.get("workflow_id")),
            "workflow_instance_id": _string(instance.get("workflow_instance_id")),
            "continuation_id": _string(instance.get("continuation_id")),
            "step_id": _string(instance.get("step_id")),
            "status": _string(instance.get("status")),
            "approval_state": _string(instance.get("approval_state")),
            "suspended": instance.get("suspended") is True,
            "lineage_record_refs": [
                record["lineage_record_id"] for record in lineage
            ],
            "skipped_reasons": list(skipped_reasons),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"wri_{hashlib.sha256(payload).hexdigest()[:16]}"


def _refs(value: Any, expected_prefix: str) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return ()

    refs: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        text = item.strip()
        if not _safe_ref(text, expected_prefix):
            return None
        refs.append(text)
    return tuple(refs)


def _safe_ref(value: str, expected_prefix: str) -> bool:
    if not value or len(value) > 200:
        return False
    if any(character.isspace() for character in value):
        return False
    parts = value.split(":")
    if len(parts) < 3:
        return False
    if parts[0] != expected_prefix:
        return False
    return all(part.strip() for part in parts)


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    text = _string(value)
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _positive_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


__all__ = [
    "WORKFLOW_RESUME_INTEGRITY_CONTRACT_ID",
    "WORKFLOW_RESUME_INTEGRITY_RECEIPT_TYPE",
    "WorkflowResumeIntegrityReceipt",
    "validate_workflow_resume_integrity",
    "validate_workflow_resume_integrity_receipt",
]
