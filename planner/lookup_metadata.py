from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.bindings import (
    AgentBinding,
    BindingResolutionError,
    ROOT,
    resolve_agent_binding,
)


LOOKUP_POLICY_FIELD = "lookup_request_policy"


@dataclass(frozen=True)
class PlannerLookupMetadata:
    entity_name: str | None = None
    target_entities: tuple[dict[str, str], ...] = ()
    search_requests: tuple[dict[str, Any], ...] = ()
    workflow_topic: str | None = None

    def to_request_metadata(self) -> dict[str, object]:
        if self.search_requests:
            return {
                "search_requests": [
                    dict(request) for request in self.search_requests
                ],
            }

        if self.target_entities:
            return {
                "target_entities": [
                    dict(entity) for entity in self.target_entities
                ],
                "workflow_topic": self.workflow_topic,
            }

        return {
            "entity_name": self.entity_name,
            "workflow_topic": self.workflow_topic,
        }


def declare_lookup_metadata(
    *,
    text: str,
    agent_name: str,
    shared_capability: str | None,
    model_lookup_metadata: dict[str, Any] | None = None,
    root: Path = ROOT,
) -> PlannerLookupMetadata | None:
    policy = _lookup_policy(
        agent_name=agent_name,
        shared_capability=shared_capability,
        root=root,
    )

    if policy is None:
        return None

    explicit = _metadata_from_model(model_lookup_metadata)
    if explicit is not None:
        return explicit

    if policy.get("lookup_type") != "exact_entity_lookup":
        return None

    return _bootstrap_metadata_from_text(text)


def _lookup_policy(
    *,
    agent_name: str,
    shared_capability: str | None,
    root: Path,
) -> dict[str, Any] | None:
    if not shared_capability:
        return None

    binding = resolve_agent_binding(
        agent_name,
        shared_capability,
        root=root,
    )

    if isinstance(binding, BindingResolutionError):
        return None

    return _policy_from_binding(binding)


def _policy_from_binding(
    binding: AgentBinding,
) -> dict[str, Any] | None:
    policy = binding.raw_binding_data.get(LOOKUP_POLICY_FIELD)

    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return None

    if policy.get("lookup_type") not in {
        "exact_entity_lookup",
        "bounded_entity_search",
    }:
        return None

    return policy


def _metadata_from_model(
    value: dict[str, Any] | None,
) -> PlannerLookupMetadata | None:
    if not isinstance(value, dict):
        return None

    search_requests = _search_requests(value.get("search_requests"))
    if search_requests:
        return PlannerLookupMetadata(search_requests=search_requests)

    target_entities = _target_entities(value.get("target_entities"))
    if target_entities:
        return PlannerLookupMetadata(
            target_entities=target_entities,
            workflow_topic=_optional_string(value.get("workflow_topic")),
        )

    entity_name = value.get("entity_name")
    if not isinstance(entity_name, str) or not entity_name.strip():
        return None

    workflow_topic = value.get("workflow_topic")

    return PlannerLookupMetadata(
        entity_name=entity_name.strip(),
        workflow_topic=_optional_string(workflow_topic),
    )


def _bootstrap_metadata_from_text(text: str) -> PlannerLookupMetadata | None:
    """
    Bootstrap-only deterministic parser for local tests and offline planning.

    The public contract is the typed PlannerLookupMetadata object. Live planner
    implementations should fill that object directly from planner output.
    """
    match = re.search(
        r"\bto\s+(?P<entity>.+?)\s+about\s+(?P<topic>.+?)[.!?]*$",
        text.strip(),
        re.IGNORECASE,
    )

    if match is None:
        return None

    entity_text = match.group("entity")
    target_entities = _split_target_entities(entity_text)
    workflow_topic = _optional_string(match.group("topic"))

    if not target_entities:
        return None

    if len(target_entities) > 1:
        return PlannerLookupMetadata(
            target_entities=tuple(
                {"entity_name": entity_name}
                for entity_name in target_entities
            ),
            workflow_topic=workflow_topic,
        )

    return PlannerLookupMetadata(
        entity_name=target_entities[0],
        workflow_topic=workflow_topic,
    )


def _target_entities(value: Any) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        return ()

    entities: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            return ()

        entity_name = item.get("entity_name")
        if not isinstance(entity_name, str) or not entity_name.strip():
            return ()

        entities.append({"entity_name": entity_name.strip()})

    return tuple(entities)


def _search_requests(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        return ()

    requests: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return ()

        lookup_type = item.get("lookup_type")
        if lookup_type != "bounded_entity_search":
            return ()

        search_topic = _optional_string(item.get("search_topic"))
        query_intent = _optional_string(item.get("query_intent"))
        if search_topic is None and query_intent is None:
            return ()

        request: dict[str, Any] = {"lookup_type": "bounded_entity_search"}
        if search_topic is not None:
            request["search_topic"] = search_topic
        if query_intent is not None:
            request["query_intent"] = query_intent

        constraints = item.get("constraints")
        if constraints is not None:
            if not isinstance(constraints, dict):
                return ()
            request["constraints"] = dict(constraints)

        max_results = item.get("max_results")
        if max_results is not None:
            if (
                not isinstance(max_results, int)
                or isinstance(max_results, bool)
                or max_results < 1
            ):
                return ()
            request["max_results"] = max_results

        requests.append(request)

    return tuple(requests)


def _split_target_entities(value: str) -> tuple[str, ...]:
    cleaned = _clean_entity_name(value)
    if cleaned is None:
        return ()

    parts = [
        part.strip()
        for part in re.split(r"\s+(?:and|&)\s+", cleaned)
        if part.strip()
    ]
    return tuple(parts) if parts else ()


def _clean_entity_name(value: str) -> str | None:
    cleaned = re.sub(
        r"^(draft|write|compose)\s+(an?\s+)?"
        r"(outreach\s+)?(booking\s+)?email\s+",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    ).strip()

    return cleaned or None


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


__all__ = [
    "LOOKUP_POLICY_FIELD",
    "PlannerLookupMetadata",
    "declare_lookup_metadata",
]
