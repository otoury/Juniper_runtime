from __future__ import annotations

from dataclasses import dataclass
from typing import Any


WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT = "web_guest_discovery_query_plan"
ALLOWED_PREFERRED_SIGNALS = (
    "has_email_contact",
    "has_video_presence",
)
FORBIDDEN_EXECUTION_FIELDS = (
    "browser_api_called",
    "cloud_model_called",
    "delivery_performed",
    "generated_queries",
    "generated_search_queries",
    "provider_execution_result",
    "queries",
    "search_api_called",
    "search_queries",
    "web_search_executed",
)


@dataclass(frozen=True)
class QueryPlanValidationError:
    error_code: str
    field: str
    message: str


def preferred_signal_metadata(signal_id: str) -> dict[str, Any]:
    normalized = _safe_string(signal_id)
    return {
        "signal_id": normalized,
        "metadata_only": True,
        "execution_required": False,
    }


def build_web_guest_discovery_query_plan(
    *,
    discovery_intent: str,
    topic_entity_focus: dict[str, Any],
    preferred_guest_traits: list[str] | tuple[str, ...],
    preferred_signals: list[str] | tuple[str, ...],
    max_queries: int,
) -> dict[str, Any]:
    return {
        "artifact_type": WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT,
        "discovery_intent": _safe_string(discovery_intent),
        "topic_entity_focus": _normalize_focus(topic_entity_focus),
        "preferred_guest_traits": _string_list(preferred_guest_traits),
        "preferred_signals": [
            preferred_signal_metadata(signal_id)
            for signal_id in _string_list(preferred_signals)
        ],
        "max_queries": max_queries,
        "provenance": {
            "declaration_only": True,
            "web_search_executed": False,
            "search_api_called": False,
            "browser_api_called": False,
            "cloud_model_called": False,
            "delivery_performed": False,
            "generated_search_queries": False,
        },
    }


def validate_web_guest_discovery_query_plan(
    artifact: Any,
) -> tuple[QueryPlanValidationError, ...]:
    if not isinstance(artifact, dict):
        return (
            QueryPlanValidationError(
                "invalid_query_plan_artifact",
                "artifact",
                "query plan artifact must be an object.",
            ),
        )

    errors: list[QueryPlanValidationError] = []
    _validate_forbidden_execution_fields(artifact, errors=errors)

    if artifact.get("artifact_type") != WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT:
        errors.append(
            QueryPlanValidationError(
                "invalid_artifact_type",
                "artifact_type",
                "artifact_type must be web_guest_discovery_query_plan.",
            )
        )

    if not _safe_string(artifact.get("discovery_intent")):
        errors.append(
            QueryPlanValidationError(
                "missing_discovery_intent",
                "discovery_intent",
                "discovery_intent must be a non-empty string.",
            )
        )

    _validate_focus(artifact.get("topic_entity_focus"), errors=errors)
    _validate_string_list(
        artifact.get("preferred_guest_traits"),
        field="preferred_guest_traits",
        required=True,
        errors=errors,
    )
    _validate_preferred_signals(
        artifact.get("preferred_signals"),
        errors=errors,
    )
    _validate_max_queries(artifact.get("max_queries"), errors=errors)
    _validate_provenance(artifact.get("provenance"), errors=errors)

    return tuple(errors)


def _validate_focus(
    value: Any,
    *,
    errors: list[QueryPlanValidationError],
) -> None:
    if not isinstance(value, dict):
        errors.append(
            QueryPlanValidationError(
                "invalid_topic_entity_focus",
                "topic_entity_focus",
                "topic_entity_focus must be an object.",
            )
        )
        return

    topics = _string_list(value.get("topics"))
    entities = _string_list(value.get("entities"))
    if not topics and not entities:
        errors.append(
            QueryPlanValidationError(
                "empty_topic_entity_focus",
                "topic_entity_focus",
                "topic_entity_focus must include topics or entities.",
            )
        )

    _validate_string_list(value.get("topics", []), field="topic_entity_focus.topics", required=False, errors=errors)
    _validate_string_list(value.get("entities", []), field="topic_entity_focus.entities", required=False, errors=errors)


def _validate_preferred_signals(
    value: Any,
    *,
    errors: list[QueryPlanValidationError],
) -> None:
    if not isinstance(value, list) or not value:
        errors.append(
            QueryPlanValidationError(
                "invalid_preferred_signals",
                "preferred_signals",
                "preferred_signals must be a non-empty list.",
            )
        )
        return

    for index, signal in enumerate(value):
        field = f"preferred_signals[{index}]"
        if not isinstance(signal, dict):
            errors.append(
                QueryPlanValidationError(
                    "invalid_preferred_signal_metadata",
                    field,
                    "preferred signal metadata must be an object.",
                )
            )
            continue

        signal_id = _safe_string(signal.get("signal_id"))
        if signal_id not in ALLOWED_PREFERRED_SIGNALS:
            errors.append(
                QueryPlanValidationError(
                    "unsupported_preferred_signal",
                    f"{field}.signal_id",
                    "preferred signal must be an allowed discovery signal.",
                )
            )
        if signal.get("metadata_only") is not True:
            errors.append(
                QueryPlanValidationError(
                    "preferred_signal_not_metadata_only",
                    f"{field}.metadata_only",
                    "preferred signal metadata must be metadata-only.",
                )
            )
        if signal.get("execution_required") is not False:
            errors.append(
                QueryPlanValidationError(
                    "preferred_signal_requires_execution",
                    f"{field}.execution_required",
                    "preferred signal metadata must not require execution.",
                )
            )


def _validate_max_queries(
    value: Any,
    *,
    errors: list[QueryPlanValidationError],
) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        errors.append(
            QueryPlanValidationError(
                "invalid_max_queries",
                "max_queries",
                "max_queries must be a positive integer.",
            )
        )


def _validate_provenance(
    value: Any,
    *,
    errors: list[QueryPlanValidationError],
) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(
            QueryPlanValidationError(
                "invalid_provenance",
                "provenance",
                "provenance must be an object when present.",
            )
        )
        return

    for field in (
        "web_search_executed",
        "search_api_called",
        "browser_api_called",
        "cloud_model_called",
        "delivery_performed",
    ):
        if value.get(field) is not False:
            errors.append(
                QueryPlanValidationError(
                    "query_plan_execution_not_allowed",
                    f"provenance.{field}",
                    "query plan artifact must not record execution.",
                )
            )

    if value.get("generated_search_queries") is not False:
        errors.append(
            QueryPlanValidationError(
                "generated_queries_not_allowed",
                "provenance.generated_search_queries",
                "query plan artifact must not generate search queries yet.",
            )
        )


def _validate_forbidden_execution_fields(
    value: Any,
    *,
    errors: list[QueryPlanValidationError],
    prefix: str = "",
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_EXECUTION_FIELDS and not path.startswith("provenance."):
                errors.append(
                    QueryPlanValidationError(
                        "forbidden_query_plan_execution_field",
                        path,
                        "query plan artifacts cannot include execution or generated-query fields.",
                    )
                )
            _validate_forbidden_execution_fields(
                item,
                errors=errors,
                prefix=path,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_forbidden_execution_fields(
                item,
                errors=errors,
                prefix=f"{prefix}[{index}]",
            )


def _validate_string_list(
    value: Any,
    *,
    field: str,
    required: bool,
    errors: list[QueryPlanValidationError],
) -> None:
    if value is None and not required:
        return
    if (
        not isinstance(value, list)
        or (required and not value)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        errors.append(
            QueryPlanValidationError(
                "invalid_string_list",
                field,
                f"{field} must be a list of non-empty strings.",
            )
        )


def _normalize_focus(value: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "topics": _string_list(value.get("topics")),
        "entities": _string_list(value.get("entities")),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _safe_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


__all__ = [
    "ALLOWED_PREFERRED_SIGNALS",
    "WEB_GUEST_DISCOVERY_QUERY_PLAN_ARTIFACT",
    "QueryPlanValidationError",
    "build_web_guest_discovery_query_plan",
    "preferred_signal_metadata",
    "validate_web_guest_discovery_query_plan",
]
