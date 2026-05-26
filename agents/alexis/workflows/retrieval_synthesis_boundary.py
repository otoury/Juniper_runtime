from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from runtime.registries.artifacts import artifact_allows_semantic_grounding


RETRIEVAL_TO_NEWSROOM_SYNTHESIS_BOUNDARY_TYPE = (
    "retrieval_to_newsroom_synthesis_boundary"
)
RETRIEVAL_TO_NEWSROOM_SYNTHESIS_STAGE = "normalized_source_grounded_synthesis"
RETRIEVAL_ARTIFACT_TYPES = frozenset(
    {
        "external_discovery_result_set",
        "external_search_result_set",
        "search_api_result_set",
    }
)
NEWSROOM_SYNTHESIS_ARTIFACT_TYPES = frozenset({"summary"})
FORBIDDEN_SYNTHESIS_TOP_LEVEL_FIELDS = frozenset(
    {
        "answer",
        "briefing",
        "delivery_payload",
        "final_answer",
        "news_briefing",
        "provider_payload",
        "raw_provider_payload",
        "raw_results",
        "results",
        "telegram_prose",
        "telegram_text",
    }
)


@dataclass(frozen=True)
class RetrievalSynthesisBoundaryValidationError:
    error_code: str
    field: str
    message: str


def attach_retrieval_to_newsroom_synthesis_boundary(
    *,
    synthesis_artifact: Mapping[str, Any],
    source_retrieval_artifacts: tuple[Mapping[str, Any], ...],
    synthesis_kind: str,
) -> dict[str, Any]:
    artifact = deepcopy(dict(synthesis_artifact))
    artifact["retrieval_synthesis_boundary"] = (
        build_retrieval_to_newsroom_synthesis_boundary(
            synthesis_artifact=artifact,
            source_retrieval_artifacts=source_retrieval_artifacts,
            synthesis_kind=synthesis_kind,
        )
    )
    return artifact


def build_retrieval_to_newsroom_synthesis_boundary(
    *,
    synthesis_artifact: Mapping[str, Any],
    source_retrieval_artifacts: tuple[Mapping[str, Any], ...],
    synthesis_kind: str,
) -> dict[str, Any]:
    return {
        "boundary_type": RETRIEVAL_TO_NEWSROOM_SYNTHESIS_BOUNDARY_TYPE,
        "boundary_stage": RETRIEVAL_TO_NEWSROOM_SYNTHESIS_STAGE,
        "synthesis_artifact_type": _safe_string(
            synthesis_artifact.get("artifact_type")
        ),
        "synthesis_kind": _safe_string(synthesis_kind),
        "source_retrieval_artifacts": [
            _source_retrieval_record(artifact)
            for artifact in source_retrieval_artifacts
            if isinstance(artifact, Mapping)
        ],
        "allowed_crossing_payloads": [
            "normalized_source_items",
            "source_refs",
            "citations",
            "retrieval_lineage_refs",
        ],
        "raw_retrieval_payload_crossed": False,
        "provider_final_prose_crossed": False,
        "source_grounding_required": True,
        "source_grounding_preserved": True,
        "retrieval_semantic_authority_inherited": False,
        "planner_semantic_grounding": False,
        "runtime_semantic_grounding": False,
        "model_used_for_boundary": False,
        "delivery_performed": False,
    }


def validate_retrieval_to_newsroom_synthesis_boundary(
    artifact: Any,
    *,
    agent_root: str | None = None,
) -> tuple[RetrievalSynthesisBoundaryValidationError, ...]:
    if not isinstance(artifact, Mapping):
        return (
            RetrievalSynthesisBoundaryValidationError(
                "invalid_synthesis_artifact",
                "artifact",
                "newsroom synthesis artifact must be an object.",
            ),
        )

    errors: list[RetrievalSynthesisBoundaryValidationError] = []
    artifact_type = artifact.get("artifact_type")
    if artifact_type not in NEWSROOM_SYNTHESIS_ARTIFACT_TYPES:
        errors.append(
            RetrievalSynthesisBoundaryValidationError(
                "invalid_synthesis_artifact_type",
                "artifact_type",
                "newsroom synthesis boundary currently supports summary artifacts.",
            )
        )

    _validate_no_raw_retrieval_payload(artifact, errors=errors)
    _validate_source_grounding(artifact, errors=errors)
    _validate_boundary_record(
        artifact.get("retrieval_synthesis_boundary"),
        artifact=artifact,
        agent_root=agent_root,
        errors=errors,
    )
    return tuple(errors)


def _source_retrieval_record(artifact: Mapping[str, Any]) -> dict[str, Any]:
    artifact_type = _safe_string(artifact.get("artifact_type"))
    semantic_authority = artifact.get("semantic_authority")
    return {
        "artifact_type": artifact_type,
        "result_type": _safe_string(artifact.get("result_type")),
        "query": _safe_string(artifact.get("query")),
        "source_ref_count": _bounded_count(artifact.get("source_refs")),
        "citation_count": _bounded_count(artifact.get("citations")),
        "result_lineage_count": _bounded_count(artifact.get("result_lineage")),
        "planner_semantic_grounding": _semantic_authority_flag(
            semantic_authority,
            "planner_semantic_grounding",
        ),
        "runtime_semantic_grounding": _semantic_authority_flag(
            semantic_authority,
            "runtime_semantic_grounding",
        ),
    }


def _validate_boundary_record(
    value: Any,
    *,
    artifact: Mapping[str, Any],
    agent_root: str | None,
    errors: list[RetrievalSynthesisBoundaryValidationError],
) -> None:
    if not isinstance(value, Mapping):
        errors.append(
            RetrievalSynthesisBoundaryValidationError(
                "missing_boundary_record",
                "retrieval_synthesis_boundary",
                "newsroom synthesis from retrieval requires an explicit boundary record.",
            )
        )
        return

    expected = {
        "boundary_type": RETRIEVAL_TO_NEWSROOM_SYNTHESIS_BOUNDARY_TYPE,
        "boundary_stage": RETRIEVAL_TO_NEWSROOM_SYNTHESIS_STAGE,
        "synthesis_artifact_type": artifact.get("artifact_type"),
        "raw_retrieval_payload_crossed": False,
        "provider_final_prose_crossed": False,
        "source_grounding_required": True,
        "source_grounding_preserved": True,
        "retrieval_semantic_authority_inherited": False,
        "planner_semantic_grounding": False,
        "runtime_semantic_grounding": False,
        "model_used_for_boundary": False,
        "delivery_performed": False,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "invalid_boundary_field",
                    f"retrieval_synthesis_boundary.{field}",
                    f"{field} must be {expected_value!r}.",
                )
            )

    source_artifacts = value.get("source_retrieval_artifacts")
    if not isinstance(source_artifacts, list) or not source_artifacts:
        errors.append(
            RetrievalSynthesisBoundaryValidationError(
                "missing_source_retrieval_artifacts",
                "retrieval_synthesis_boundary.source_retrieval_artifacts",
                "boundary must name at least one source retrieval artifact.",
            )
        )
        return

    for index, source in enumerate(source_artifacts):
        field = f"retrieval_synthesis_boundary.source_retrieval_artifacts[{index}]"
        if not isinstance(source, Mapping):
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "invalid_source_retrieval_artifact",
                    field,
                    "source retrieval artifact boundary entry must be an object.",
                )
            )
            continue
        source_type = source.get("artifact_type")
        if source_type not in RETRIEVAL_ARTIFACT_TYPES:
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "invalid_source_retrieval_artifact_type",
                    f"{field}.artifact_type",
                    "source artifact must be a governed raw retrieval result set.",
                )
            )
        if artifact_allows_semantic_grounding(
            source_type,
            authority="planner",
            agent_root=agent_root,
        ):
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "retrieval_planner_grounding_allowed",
                    f"{field}.artifact_type",
                    "retrieval source artifact policy must deny planner semantic grounding.",
                )
            )
        if artifact_allows_semantic_grounding(
            source_type,
            authority="runtime",
            agent_root=agent_root,
        ):
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "retrieval_runtime_grounding_allowed",
                    f"{field}.artifact_type",
                    "retrieval source artifact policy must deny runtime semantic grounding.",
                )
            )
        if source.get("planner_semantic_grounding") is not False:
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "source_planner_grounding_crossed",
                    f"{field}.planner_semantic_grounding",
                    "retrieval source must not grant planner semantic grounding.",
                )
            )
        if source.get("runtime_semantic_grounding") is not False:
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "source_runtime_grounding_crossed",
                    f"{field}.runtime_semantic_grounding",
                    "retrieval source must not grant runtime semantic grounding.",
                )
            )


def _validate_no_raw_retrieval_payload(
    artifact: Mapping[str, Any],
    *,
    errors: list[RetrievalSynthesisBoundaryValidationError],
) -> None:
    for field in sorted(FORBIDDEN_SYNTHESIS_TOP_LEVEL_FIELDS):
        if field in artifact:
            errors.append(
                RetrievalSynthesisBoundaryValidationError(
                    "raw_retrieval_payload_leaked",
                    field,
                    "newsroom synthesis artifacts must not contain raw retrieval payload or provider final prose fields.",
                )
            )


def _validate_source_grounding(
    artifact: Mapping[str, Any],
    *,
    errors: list[RetrievalSynthesisBoundaryValidationError],
) -> None:
    source_refs = artifact.get("source_refs")
    citations = artifact.get("citations")
    summary_blocks = artifact.get("summary_blocks")
    if not isinstance(source_refs, list) or not source_refs:
        errors.append(
            RetrievalSynthesisBoundaryValidationError(
                "missing_source_refs",
                "source_refs",
                "newsroom synthesis artifact must preserve source refs.",
            )
        )
    if not isinstance(citations, list) or not citations:
        errors.append(
            RetrievalSynthesisBoundaryValidationError(
                "missing_citations",
                "citations",
                "newsroom synthesis artifact must preserve citations.",
            )
        )
    if not isinstance(summary_blocks, list) or not summary_blocks:
        errors.append(
            RetrievalSynthesisBoundaryValidationError(
                "missing_summary_blocks",
                "summary_blocks",
                "newsroom synthesis artifact must contain source-grounded summary blocks.",
            )
        )


def _semantic_authority_flag(value: Any, field: str) -> bool | None:
    if isinstance(value, Mapping) and isinstance(value.get(field), bool):
        return value[field]
    return None


def _bounded_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    return 0


def _safe_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


__all__ = [
    "RETRIEVAL_ARTIFACT_TYPES",
    "RETRIEVAL_TO_NEWSROOM_SYNTHESIS_BOUNDARY_TYPE",
    "RETRIEVAL_TO_NEWSROOM_SYNTHESIS_STAGE",
    "RetrievalSynthesisBoundaryValidationError",
    "attach_retrieval_to_newsroom_synthesis_boundary",
    "build_retrieval_to_newsroom_synthesis_boundary",
    "validate_retrieval_to_newsroom_synthesis_boundary",
]
