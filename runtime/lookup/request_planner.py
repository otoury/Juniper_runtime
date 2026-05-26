from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.bindings import ROOT
from runtime.registries.lookup_capability_registry import (
    LookupCapabilityRegistrationError,
    ResolvedLookupCapability,
    resolve_lookup_capability,
)
from runtime.registries.exact_entity_lookup_registry import (
    validate_exact_entity_lookup_request,
)
from runtime.registries.bounded_entity_search_registry import (
    validate_bounded_entity_search_request,
)
from runtime.lookup.governance import governance_block_reason
from runtime.lookup.lineage import (
    lookup_lineage_ids,
    new_lookup_lineage_root,
)


LOOKUP_POLICY_FIELD = "lookup_request_policy"


@dataclass(frozen=True)
class PlannedLookupRequest:
    request: dict[str, Any] | None
    status: str
    skipped_reasons: tuple[str, ...]
    validation_errors: tuple[str, ...]
    trace: dict[str, Any]


def create_explicit_lookup_request(
    *,
    agent_name: str,
    shared_capability: str | None,
    planner_lookup: dict[str, Any] | None,
    root: Path = ROOT,
    resolved_capability: (
        ResolvedLookupCapability | LookupCapabilityRegistrationError | None
    ) = None,
) -> PlannedLookupRequest:
    requests = create_explicit_lookup_requests(
        agent_name=agent_name,
        shared_capability=shared_capability,
        planner_lookup=planner_lookup,
        root=root,
        resolved_capability=resolved_capability,
    )
    if requests:
        return requests[0]

    return _create_explicit_lookup_request(
        agent_name=agent_name,
        shared_capability=shared_capability,
        planner_lookup=planner_lookup,
        root=root,
        ordinal=None,
        resolved_capability=resolved_capability,
    )


def create_explicit_lookup_requests(
    *,
    agent_name: str,
    shared_capability: str | None,
    planner_lookup: dict[str, Any] | None,
    root: Path = ROOT,
    resolved_capability: (
        ResolvedLookupCapability | LookupCapabilityRegistrationError | None
    ) = None,
) -> list[PlannedLookupRequest]:
    if not isinstance(planner_lookup, dict):
        return []

    search_requests = planner_lookup.get("search_requests")
    if isinstance(search_requests, list):
        requests: list[PlannedLookupRequest] = []
        for index, search_request in enumerate(search_requests, start=1):
            if not isinstance(search_request, dict):
                requests.append(
                    _closed(
                        status="lookup_request_not_created",
                        skipped_reasons=("malformed_search_request",),
                        policy=None,
                        request=None,
                    )
                )
                continue

            requests.append(
                _create_explicit_lookup_request(
                    agent_name=agent_name,
                    shared_capability=shared_capability,
                    planner_lookup=search_request,
                    root=root,
                    ordinal=index,
                    resolved_capability=resolved_capability,
                )
            )

        return requests

    target_entities = planner_lookup.get("target_entities")
    if not isinstance(target_entities, list):
        return []

    requests: list[PlannedLookupRequest] = []
    for index, target in enumerate(target_entities, start=1):
        if not isinstance(target, dict):
            requests.append(
                _closed(
                    status="lookup_request_not_created",
                    skipped_reasons=("malformed_target_entity",),
                    policy=None,
                    request=None,
                )
            )
            continue

        entity_name = target.get("entity_name")
        per_entity_lookup = {
            "entity_name": entity_name,
            "workflow_topic": planner_lookup.get("workflow_topic"),
        }
        if "entity_type" in target or "source_scope" in target:
            per_entity_lookup["entity_type"] = target.get("entity_type")
            per_entity_lookup["source_scope"] = target.get("source_scope")

        requests.append(
            _create_explicit_lookup_request(
                agent_name=agent_name,
                shared_capability=shared_capability,
                planner_lookup=per_entity_lookup,
                root=root,
                ordinal=index,
                resolved_capability=resolved_capability,
            )
        )

    return requests


def _create_explicit_lookup_request(
    *,
    agent_name: str,
    shared_capability: str | None,
    planner_lookup: dict[str, Any] | None,
    root: Path,
    ordinal: int | None,
    resolved_capability: (
        ResolvedLookupCapability | LookupCapabilityRegistrationError | None
    ),
) -> PlannedLookupRequest:
    if not shared_capability:
        return _closed(
            status="lookup_not_declared",
            skipped_reasons=("missing_shared_capability",),
            policy=None,
            request=None,
        )

    if resolved_capability is None:
        resolved_capability = resolve_lookup_capability(
            agent=agent_name,
            shared_capability=shared_capability,
            root=root,
        )

    if isinstance(resolved_capability, LookupCapabilityRegistrationError):
        return _closed(
            status="lookup_not_declared",
            skipped_reasons=("lookup_capability_resolution_failed",),
            policy=None,
            request=None,
            validation_errors=(resolved_capability.field,),
        )

    if not resolved_capability.governance.request_allowed:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=(
                governance_block_reason(resolved_capability.governance.state),
            ),
            policy=None,
            request=None,
            governance_state=resolved_capability.governance.state,
        )

    policy = resolved_capability.policy_section(LOOKUP_POLICY_FIELD)
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return _closed(
            status="lookup_not_declared",
            skipped_reasons=("lookup_policy_not_declared",),
            policy=None,
            request=None,
            governance_state=resolved_capability.governance.state,
        )

    policy_errors = _validate_policy(policy)
    if policy_errors:
        return _closed(
            status="invalid_lookup_policy",
            skipped_reasons=("invalid_lookup_policy",),
            validation_errors=tuple(policy_errors),
            policy=policy,
            request=None,
            governance_state=resolved_capability.governance.state,
        )

    if not isinstance(planner_lookup, dict):
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("missing_planner_lookup_metadata",),
            policy=policy,
            request=None,
            governance_state=resolved_capability.governance.state,
        )

    lookup_type = policy.get("lookup_type")
    if lookup_type == "bounded_entity_search":
        return _create_bounded_entity_search_request(
            agent_name=agent_name,
            shared_capability=shared_capability,
            planner_lookup=planner_lookup,
            policy=policy,
            ordinal=ordinal,
            governance_state=resolved_capability.governance.state,
        )

    entity_name = planner_lookup.get("entity_name")
    if not isinstance(entity_name, str) or not entity_name.strip():
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("missing_entity_name",),
            policy=policy,
            request=None,
            governance_state=resolved_capability.governance.state,
        )

    if "entity_type" in planner_lookup or "source_scope" in planner_lookup:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("planner_policy_field_not_allowed",),
            policy=policy,
            request={
                "lookup_type": policy["lookup_type"],
                "source_scope": policy.get("source_scope"),
            },
            governance_state=resolved_capability.governance.state,
        )

    source_scope = policy.get("source_scope")
    allowed_scopes = set(policy["allowed_source_scopes"])
    if source_scope not in allowed_scopes:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("unauthorized_source_scope",),
            policy=policy,
            request={
                "lookup_type": policy["lookup_type"],
                "source_scope": source_scope,
            },
            governance_state=resolved_capability.governance.state,
        )

    lineage = lookup_lineage_ids(new_lookup_lineage_root())
    request = {
        "lookup_type": policy["lookup_type"],
        "lookup_id": _lookup_id(
            agent_name=agent_name,
            shared_capability=shared_capability,
            lookup_type=policy["lookup_type"],
            ordinal=ordinal,
        ),
        "lookup_lineage_id": lineage["lookup_lineage_id"],
        "lookup_request_id": lineage["lookup_request_id"],
        "lookup_execution_id": lineage["lookup_execution_id"],
        "lookup_packet_id": lineage["lookup_packet_id"],
        "lookup_render_id": lineage["lookup_render_id"],
        "lookup_injection_id": lineage["lookup_injection_id"],
        "entity_name": entity_name.strip(),
        "entity_type": policy.get("entity_type"),
        "workflow_topic": _optional_string(
            planner_lookup.get("workflow_topic")
        ),
        "source_scope": source_scope,
    }

    errors = validate_exact_entity_lookup_request(request)
    if errors:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("invalid_exact_entity_lookup_request",),
            validation_errors=tuple(error.field for error in errors),
            policy=policy,
            request=request,
            governance_state=resolved_capability.governance.state,
        )

    return PlannedLookupRequest(
        request=request,
        status="lookup_request_created",
        skipped_reasons=(),
        validation_errors=(),
        trace=_trace(
            policy=policy,
            request=request,
            request_created=True,
            skipped_reasons=(),
            validation_errors=(),
            governance_state=resolved_capability.governance.state,
        ),
    )


def _validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    lookup_type = policy.get("lookup_type")
    if lookup_type not in {"exact_entity_lookup", "bounded_entity_search"}:
        errors.append("lookup_type")

    source_scope = policy.get("source_scope")
    if not isinstance(source_scope, str) or not source_scope.strip():
        errors.append("source_scope")

    allowed_scopes = policy.get("allowed_source_scopes")
    if (
        not isinstance(allowed_scopes, list)
        or not allowed_scopes
        or any(
            not isinstance(scope, str) or not scope.strip()
            for scope in allowed_scopes
        )
    ):
        errors.append("allowed_source_scopes")
    elif source_scope not in allowed_scopes:
        errors.append("source_scope")

    if lookup_type == "bounded_entity_search":
        required_any = policy.get("required_any_planner_fields")
        if required_any != ["search_topic", "query_intent"]:
            errors.append("required_any_planner_fields")

        optional_fields = policy.get("optional_planner_fields", [])
        if not isinstance(optional_fields, list) or any(
            field not in {"constraints", "max_results"}
            for field in optional_fields
        ):
            errors.append("optional_planner_fields")

        execution_status = policy.get("execution_status")
        if execution_status not in {"not_implemented", "implemented"}:
            errors.append("execution_status")

        max_results = policy.get("max_results")
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or max_results < 1
            or max_results > 10
        ):
            errors.append("max_results")
    else:
        required_fields = policy.get("required_planner_fields")
        if required_fields != ["entity_name"]:
            errors.append("required_planner_fields")

        optional_fields = policy.get("optional_planner_fields", [])
        if not isinstance(optional_fields, list) or any(
            field not in {"workflow_topic"}
            for field in optional_fields
        ):
            errors.append("optional_planner_fields")

    entity_type = policy.get("entity_type")
    if entity_type is not None and not isinstance(entity_type, str):
        errors.append("entity_type")

    return errors


def _create_bounded_entity_search_request(
    *,
    agent_name: str,
    shared_capability: str,
    planner_lookup: dict[str, Any],
    policy: dict[str, Any],
    ordinal: int | None,
    governance_state: str | None,
) -> PlannedLookupRequest:
    search_topic = _optional_string(planner_lookup.get("search_topic"))
    query_intent = _optional_string(planner_lookup.get("query_intent"))
    if search_topic is None and query_intent is None:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("missing_search_topic_or_query_intent",),
            policy=policy,
            request=None,
            governance_state=governance_state,
        )

    if any(
        key in planner_lookup
        for key in (
            "entity_type",
            "source_scope",
            "raw_source_target",
            "adapter_id",
            "datasource_path",
        )
    ):
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("planner_policy_field_not_allowed",),
            policy=policy,
            request={
                "lookup_type": policy["lookup_type"],
                "source_scope": policy.get("source_scope"),
            },
            governance_state=governance_state,
        )

    source_scope = policy.get("source_scope")
    allowed_scopes = set(policy["allowed_source_scopes"])
    if source_scope not in allowed_scopes:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("unauthorized_source_scope",),
            policy=policy,
            request={
                "lookup_type": policy["lookup_type"],
                "source_scope": source_scope,
            },
            governance_state=governance_state,
        )

    max_results = planner_lookup.get("max_results", policy.get("max_results"))
    lineage = lookup_lineage_ids(new_lookup_lineage_root())
    request: dict[str, Any] = {
        "lookup_type": policy["lookup_type"],
        "lookup_id": _lookup_id(
            agent_name=agent_name,
            shared_capability=shared_capability,
            lookup_type=policy["lookup_type"],
            ordinal=ordinal,
        ),
        "lookup_lineage_id": lineage["lookup_lineage_id"],
        "lookup_request_id": lineage["lookup_request_id"],
        "lookup_execution_id": lineage["lookup_execution_id"],
        "lookup_packet_id": lineage["lookup_packet_id"],
        "lookup_render_id": lineage["lookup_render_id"],
        "lookup_injection_id": lineage["lookup_injection_id"],
        "entity_type": policy.get("entity_type"),
        "source_scope": source_scope,
        "max_results": max_results,
    }
    if search_topic is not None:
        request["search_topic"] = search_topic
    if query_intent is not None:
        request["query_intent"] = query_intent

    constraints = planner_lookup.get("constraints")
    if constraints is not None:
        request["constraints"] = dict(constraints) if isinstance(
            constraints,
            dict,
        ) else constraints

    errors = validate_bounded_entity_search_request(
        request,
        allow_policy_fields=True,
    )
    if errors:
        return _closed(
            status="lookup_request_not_created",
            skipped_reasons=("invalid_bounded_entity_search_request",),
            validation_errors=tuple(error.field for error in errors),
            policy=policy,
            request=request,
            governance_state=governance_state,
        )

    return PlannedLookupRequest(
        request=request,
        status="lookup_request_created",
        skipped_reasons=(),
        validation_errors=(),
        trace=_trace(
            policy=policy,
            request=request,
            request_created=True,
            skipped_reasons=(),
            validation_errors=(),
            governance_state=governance_state,
        ),
    )


def _lookup_id(
    *,
    agent_name: str,
    shared_capability: str,
    lookup_type: str,
    ordinal: int | None,
) -> str:
    base = f"{agent_name}:{shared_capability}:{lookup_type}"
    if ordinal is None:
        return base
    return f"{base}:{ordinal}"


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def _closed(
    *,
    status: str,
    skipped_reasons: tuple[str, ...],
    policy: dict[str, Any] | None,
    request: dict[str, Any] | None,
    validation_errors: tuple[str, ...] = (),
    governance_state: str | None = None,
) -> PlannedLookupRequest:
    return PlannedLookupRequest(
        request=None,
        status=status,
        skipped_reasons=skipped_reasons,
        validation_errors=validation_errors,
        trace=_trace(
            policy=policy,
            request=request,
            request_created=False,
            skipped_reasons=skipped_reasons,
            validation_errors=validation_errors,
            governance_state=governance_state,
        ),
    )


def _trace(
    *,
    policy: dict[str, Any] | None,
    request: dict[str, Any] | None,
    request_created: bool,
    skipped_reasons: tuple[str, ...],
    validation_errors: tuple[str, ...],
    governance_state: str | None = None,
) -> dict[str, Any]:
    return {
        "lookup_type": (
            request.get("lookup_type")
            if request is not None
            else policy.get("lookup_type") if policy is not None else None
        ),
        "lookup_id": (
            request.get("lookup_id")
            if request is not None
            else None
        ),
        "lookup_lineage_id": (
            request.get("lookup_lineage_id")
            if request is not None
            else None
        ),
        "lookup_request_id": (
            request.get("lookup_request_id")
            if request is not None
            else None
        ),
        "lookup_execution_id": (
            request.get("lookup_execution_id")
            if request is not None
            else None
        ),
        "lookup_packet_id": (
            request.get("lookup_packet_id")
            if request is not None
            else None
        ),
        "lookup_render_id": (
            request.get("lookup_render_id")
            if request is not None
            else None
        ),
        "lookup_injection_id": (
            request.get("lookup_injection_id")
            if request is not None
            else None
        ),
        "entity_type": (
            request.get("entity_type")
            if request is not None
            else policy.get("entity_type") if policy is not None else None
        ),
        "workflow_topic": (
            request.get("workflow_topic")
            if request is not None
            else None
        ),
        "source_scope": (
            request.get("source_scope")
            if request is not None
            else policy.get("source_scope") if policy is not None else None
        ),
        "request_created": request_created,
        "governance_state": governance_state,
        "retrieval_executed": False,
        "records_returned": 0,
        "skipped_reasons": list(skipped_reasons),
        "validation_errors": list(validation_errors),
    }


__all__ = [
    "LOOKUP_POLICY_FIELD",
    "PlannedLookupRequest",
    "create_explicit_lookup_request",
    "create_explicit_lookup_requests",
]
