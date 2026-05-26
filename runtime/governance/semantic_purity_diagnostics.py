from __future__ import annotations

from typing import Any, Mapping, Sequence

from runtime.governance.visibility_isolation import (
    FORBIDDEN_CONTENT_FIELDS,
    assert_visibility_attachment_allowed,
    validate_visibility_attachment,
)


SEMANTIC_PURITY_DIAGNOSTIC_TYPE = "semantic_purity_visibility_diagnostic"
ATTACHMENT_PATH_DIAGNOSTIC_TYPE = "attachment_path_visibility_diagnostic"
HELPER_BOUNDARY_VISIBILITY_TYPE = "helper_boundary_visibility"
SUBSTRATE_LEAKAGE_VISIBILITY_TYPE = "substrate_leakage_visibility"
CONTENT_SAFE_PROJECTION_TYPE = "content_safe_projection"

SEMANTIC_PURITY_PROJECTION_CONTRACT_ID = "semantic_purity_visibility_v1"


def build_content_safe_projection(
    payload: Mapping[str, Any] | None,
    *,
    projection_label: str = "runtime_payload",
    receipt_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Project payload shape without carrying content-bearing values."""
    if not isinstance(payload, Mapping):
        observed_paths: list[str] = []
        suppressed_paths: list[str] = []
    else:
        observed_paths = _field_paths(payload, include_content=False)
        suppressed_paths = _field_paths(payload, include_content=True)

    return {
        "projection_type": CONTENT_SAFE_PROJECTION_TYPE,
        "projection_label": _safe_text(projection_label) or "runtime_payload",
        "content_safe": True,
        "content_values_included": False,
        "content_fields_suppressed": True,
        "suppressed_content_field_paths": suppressed_paths,
        "observed_non_content_field_paths": observed_paths,
        "receipt_refs": _safe_text_list(receipt_refs),
    }


def build_semantic_purity_diagnostic(
    *,
    source: str = "semantic_purity_visibility",
    helper_diagnostics: Sequence[Mapping[str, Any]] | None = None,
    substrate_diagnostics: Sequence[Mapping[str, Any]] | None = None,
    attachment_diagnostics: Sequence[Mapping[str, Any]] | None = None,
    payload_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    helper_items = _safe_mapping_list(helper_diagnostics)
    substrate_items = _safe_mapping_list(substrate_diagnostics)
    attachment_items = _safe_mapping_list(attachment_diagnostics)

    blocked = _unique(
        [
            *_blocked_fields("helper", helper_items),
            *_blocked_fields("substrate", substrate_items),
            *_blocked_fields("attachment", attachment_items),
        ]
    )
    allowed = not blocked and all(
        _diagnostic_allowed(item)
        for item in [*helper_items, *substrate_items, *attachment_items]
    )
    projection = (
        dict(payload_projection)
        if isinstance(payload_projection, Mapping)
        else build_content_safe_projection(None)
    )

    diagnostic = {
        "contract_id": SEMANTIC_PURITY_PROJECTION_CONTRACT_ID,
        "diagnostic_type": SEMANTIC_PURITY_DIAGNOSTIC_TYPE,
        "source": _safe_text(source) or "semantic_purity_visibility",
        "allowed": bool(allowed),
        "content_safe": True,
        "observational_only": True,
        "planner_semantic_authority": False,
        "semantic_purity_preserved": bool(allowed),
        "substrate_leakage_detected": any(
            item.get("allowed") is False for item in substrate_items
        ),
        "helper_boundary_violation_detected": any(
            item.get("allowed") is False for item in helper_items
        ),
        "attachment_path_violation_detected": any(
            item.get("allowed") is False for item in attachment_items
        ),
        "hidden_context_injection_performed": False,
        "hidden_routing_performed": False,
        "hidden_attachment_performed": False,
        "planner_mutation_performed": False,
        "memory_write_performed": False,
        "hidden_autonomy_escalation_performed": False,
        "blocked_fields": blocked,
        "helper_boundary_summary": _summary(helper_items),
        "substrate_boundary_summary": _summary(substrate_items),
        "attachment_path_summary": _summary(attachment_items),
        "content_safe_projection": projection,
        "skipped_reasons": (
            [] if allowed else ["semantic_purity_visibility_violation"]
        ),
        "reason": (
            "Semantic purity diagnostics are observational and content-safe."
            if allowed
            else "Semantic purity diagnostics report boundary violations."
        ),
    }
    assert_visibility_attachment_allowed(diagnostic, target="operator_report")
    return diagnostic


def build_attachment_path_visibility_diagnostic(
    *,
    payload: Mapping[str, Any],
    target: str,
    source: str = "attachment_path_visibility",
) -> dict[str, Any]:
    attachment = validate_visibility_attachment(payload, target=target)
    allowed = attachment["allowed"] is True
    diagnostic = {
        "contract_id": SEMANTIC_PURITY_PROJECTION_CONTRACT_ID,
        "diagnostic_type": ATTACHMENT_PATH_DIAGNOSTIC_TYPE,
        "source": _safe_text(source) or "attachment_path_visibility",
        "allowed": allowed,
        "content_safe": True,
        "observational_only": True,
        "planner_semantic_authority": False,
        "attachment_target": _safe_text(target) or "unknown",
        "attachment_allowed": allowed,
        "hidden_context_injection_performed": False,
        "hidden_attachment_performed": False,
        "planner_mutation_performed": False,
        "memory_write_performed": False,
        "blocked_fields": list(attachment.get("blocked_fields", [])),
        "skipped_reasons": (
            [] if allowed else ["attachment_path_visibility_violation"]
        ),
        "reason": (
            "Attachment path is explicit and visibility-safe."
            if allowed
            else "Attachment path is not visibility-safe."
        ),
    }
    assert_visibility_attachment_allowed(diagnostic, target="operator_report")
    return diagnostic


def build_helper_boundary_visibility(
    helper_diagnostic: Mapping[str, Any],
    *,
    source: str = "helper_boundary_visibility",
) -> dict[str, Any]:
    allowed = helper_diagnostic.get("allowed") is True
    surface = {
        "visibility_type": HELPER_BOUNDARY_VISIBILITY_TYPE,
        "schema_version": 1,
        "source": _safe_text(source) or "helper_boundary_visibility",
        "content_safe": True,
        "semantic_reinterpretation_performed": False,
        "helper_name": _safe_text(helper_diagnostic.get("helper_name")),
        "input_substrate": _safe_text(helper_diagnostic.get("input_substrate")),
        "output_substrate": _safe_text(helper_diagnostic.get("output_substrate")),
        "helper_boundary_allowed": allowed,
        "semantic_purity_preserved": helper_diagnostic.get(
            "semantic_purity_preserved"
        )
        is True,
        "cross_substrate": helper_diagnostic.get("cross_substrate") is True,
        "leakage_detected": helper_diagnostic.get(
            "helper_layer_cross_substrate_leakage_detected"
        )
        is True,
        "blocked_field_count": len(helper_diagnostic.get("blocked_fields", [])),
        "skipped_reasons": _safe_text_list(helper_diagnostic.get("skipped_reasons")),
    }
    surface = _without_none(surface)
    assert_visibility_attachment_allowed(surface, target="operator_report")
    return surface


def build_substrate_leakage_visibility(
    substrate_diagnostic: Mapping[str, Any],
    *,
    source: str = "substrate_leakage_visibility",
) -> dict[str, Any]:
    allowed = substrate_diagnostic.get("allowed") is True
    surface = {
        "visibility_type": SUBSTRATE_LEAKAGE_VISIBILITY_TYPE,
        "schema_version": 1,
        "source": _safe_text(source) or "substrate_leakage_visibility",
        "content_safe": True,
        "semantic_reinterpretation_performed": False,
        "source_substrate": _safe_text(substrate_diagnostic.get("source_substrate")),
        "target_substrate": _safe_text(substrate_diagnostic.get("target_substrate")),
        "interaction_type": _safe_text(substrate_diagnostic.get("interaction_type")),
        "substrate_boundary_allowed": allowed,
        "substrate_leakage_detected": not allowed,
        "explicit_interaction": substrate_diagnostic.get("explicit_interaction")
        is True,
        "blocked_field_count": len(substrate_diagnostic.get("blocked_fields", [])),
        "skipped_reasons": _safe_text_list(substrate_diagnostic.get("skipped_reasons")),
    }
    surface = _without_none(surface)
    assert_visibility_attachment_allowed(surface, target="operator_report")
    return surface


def _summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "checked_count": len(items),
        "allowed_count": sum(1 for item in items if item.get("allowed") is True),
        "blocked_count": sum(1 for item in items if item.get("allowed") is False),
        "blocked_field_count": sum(
            len(item.get("blocked_fields", [])) for item in items
        ),
    }


def _blocked_fields(prefix: str, items: Sequence[Mapping[str, Any]]) -> list[str]:
    blocked: list[str] = []
    for index, item in enumerate(items):
        for field in item.get("blocked_fields", []):
            text = _safe_text(field)
            if text:
                blocked.append(f"{prefix}[{index}].{text}")
    return blocked


def _diagnostic_allowed(item: Mapping[str, Any]) -> bool:
    return item.get("allowed") is True


def _field_paths(
    value: Any,
    *,
    include_content: bool,
    prefix: str = "",
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            content_field = key in FORBIDDEN_CONTENT_FIELDS
            if content_field is include_content:
                paths.append(path)
            if not content_field:
                paths.extend(
                    _field_paths(item, include_content=include_content, prefix=path)
                )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            paths.extend(
                _field_paths(
                    item,
                    include_content=include_content,
                    prefix=f"{prefix}[{index}]",
                )
            )
    return _unique(paths)


def _safe_mapping_list(
    value: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _safe_text_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return _unique([item for item in value if isinstance(item, str)])


def _without_none(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item for key, item in value.items() if item is not None and item != []
    }


def _safe_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        text = _safe_text(value)
        if text and text not in found:
            found.append(text)
    return found


__all__ = [
    "ATTACHMENT_PATH_DIAGNOSTIC_TYPE",
    "CONTENT_SAFE_PROJECTION_TYPE",
    "HELPER_BOUNDARY_VISIBILITY_TYPE",
    "SEMANTIC_PURITY_DIAGNOSTIC_TYPE",
    "SEMANTIC_PURITY_PROJECTION_CONTRACT_ID",
    "SUBSTRATE_LEAKAGE_VISIBILITY_TYPE",
    "build_attachment_path_visibility_diagnostic",
    "build_content_safe_projection",
    "build_helper_boundary_visibility",
    "build_semantic_purity_diagnostic",
    "build_substrate_leakage_visibility",
]
