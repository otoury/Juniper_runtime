from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping


RSS_CITATION_ATTACHMENT_TYPE = "rss_synthesis_citation_attachment"
RSS_CITATION_ATTACHMENT_STAGE = "rss_synthesis_citation_attachment"
RSS_CITATION_ATTACHMENT_SCOPE = "story_cluster"
RSS_SYNTHESIS_KIND = "rss_corpus_synthesis"


@dataclass(frozen=True)
class RssCitationAttachmentValidationError:
    error_code: str
    field: str
    message: str


def build_rss_story_cluster_citation_attachment(
    *,
    cluster_id: str,
    source_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    citations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    artifact_type: str = "summary",
    synthesis_kind: str = RSS_SYNTHESIS_KIND,
) -> dict[str, Any]:
    return {
        "attachment_type": RSS_CITATION_ATTACHMENT_TYPE,
        "attachment_stage": RSS_CITATION_ATTACHMENT_STAGE,
        "attachment_scope": RSS_CITATION_ATTACHMENT_SCOPE,
        "artifact_type": _safe_string(artifact_type),
        "synthesis_kind": _safe_string(synthesis_kind),
        "cluster_id": _safe_string(cluster_id),
        "source_ref_ids": _ids(source_refs, "source_ref_id"),
        "citation_ids": _ids(citations, "citation_id"),
        "source_refs": [deepcopy(item) for item in source_refs],
        "citations": [deepcopy(item) for item in citations],
        "source_grounding_preserved": True,
        "model_used": False,
        "source_expansion_performed": False,
        "live_fetch_performed": False,
        "delivery_performed": False,
    }


def validate_rss_citation_attachments(
    artifact: Any,
) -> tuple[RssCitationAttachmentValidationError, ...]:
    if not isinstance(artifact, Mapping):
        return (
            RssCitationAttachmentValidationError(
                "invalid_artifact",
                "artifact",
                "RSS synthesis artifact must be an object.",
            ),
        )

    errors: list[RssCitationAttachmentValidationError] = []
    attachments = artifact.get("citation_attachments")
    if not isinstance(attachments, list) or not attachments:
        return (
            RssCitationAttachmentValidationError(
                "missing_citation_attachments",
                "citation_attachments",
                "RSS synthesis artifacts must attach citation contracts.",
            ),
        )

    clusters = artifact.get("story_clusters")
    if not isinstance(clusters, list) or not clusters:
        errors.append(
            RssCitationAttachmentValidationError(
                "missing_story_clusters",
                "story_clusters",
                "citation attachments require story_clusters.",
            )
        )
        clusters = []

    cluster_by_id = {
        cluster.get("cluster_id"): cluster
        for cluster in clusters
        if isinstance(cluster, Mapping) and _safe_string(cluster.get("cluster_id"))
    }
    seen_cluster_ids: set[str] = set()
    for index, attachment in enumerate(attachments):
        item_field = f"citation_attachments[{index}]"
        if not isinstance(attachment, Mapping):
            errors.append(
                RssCitationAttachmentValidationError(
                    "invalid_citation_attachment",
                    item_field,
                    "citation attachment must be an object.",
                )
            )
            continue
        _validate_attachment_shape(attachment, item_field, errors)
        cluster_id = _safe_string(attachment.get("cluster_id"))
        if not cluster_id:
            continue
        if cluster_id in seen_cluster_ids:
            errors.append(
                RssCitationAttachmentValidationError(
                    "duplicate_cluster_attachment",
                    f"{item_field}.cluster_id",
                    "each story cluster may have only one citation attachment.",
                )
            )
        seen_cluster_ids.add(cluster_id)
        cluster = cluster_by_id.get(cluster_id)
        if cluster is None:
            errors.append(
                RssCitationAttachmentValidationError(
                    "orphan_citation_attachment",
                    f"{item_field}.cluster_id",
                    "citation attachment must reference an existing story cluster.",
                )
            )
            continue
        _validate_attachment_links(
            attachment,
            cluster=cluster,
            field=item_field,
            errors=errors,
        )

    missing = set(cluster_by_id) - seen_cluster_ids
    for cluster_id in sorted(missing):
        errors.append(
            RssCitationAttachmentValidationError(
                "missing_cluster_citation_attachment",
                "citation_attachments",
                f"story cluster {cluster_id} must have a citation attachment.",
            )
        )
    return tuple(errors)


def _validate_attachment_shape(
    attachment: Mapping[str, Any],
    field: str,
    errors: list[RssCitationAttachmentValidationError],
) -> None:
    expected_strings = {
        "attachment_type": RSS_CITATION_ATTACHMENT_TYPE,
        "attachment_stage": RSS_CITATION_ATTACHMENT_STAGE,
        "attachment_scope": RSS_CITATION_ATTACHMENT_SCOPE,
        "artifact_type": "summary",
        "synthesis_kind": RSS_SYNTHESIS_KIND,
    }
    for key, expected in expected_strings.items():
        if attachment.get(key) != expected:
            errors.append(
                RssCitationAttachmentValidationError(
                    "invalid_citation_attachment_contract",
                    f"{field}.{key}",
                    f"{key} must be {expected}.",
                )
            )
    if not _safe_string(attachment.get("cluster_id")):
        errors.append(
            RssCitationAttachmentValidationError(
                "missing_cluster_id",
                f"{field}.cluster_id",
                "cluster_id must be a non-empty string.",
            )
        )
    for list_field in ("source_ref_ids", "citation_ids"):
        value = attachment.get(list_field)
        if (
            not isinstance(value, list)
            or not value
            or any(not _safe_string(item) for item in value)
        ):
            errors.append(
                RssCitationAttachmentValidationError(
                    "invalid_citation_attachment_ids",
                    f"{field}.{list_field}",
                    f"{list_field} must be a non-empty list of strings.",
                )
            )
    for object_list_field in ("source_refs", "citations"):
        value = attachment.get(object_list_field)
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, Mapping) for item in value)
        ):
            errors.append(
                RssCitationAttachmentValidationError(
                    "invalid_citation_attachment_refs",
                    f"{field}.{object_list_field}",
                    f"{object_list_field} must be a non-empty list of objects.",
                )
            )
    for flag in (
        "source_grounding_preserved",
        "model_used",
        "source_expansion_performed",
        "live_fetch_performed",
        "delivery_performed",
    ):
        expected = flag == "source_grounding_preserved"
        if attachment.get(flag) is not expected:
            errors.append(
                RssCitationAttachmentValidationError(
                    "invalid_citation_attachment_flag",
                    f"{field}.{flag}",
                    f"{flag} must be {expected}.",
                )
            )


def _validate_attachment_links(
    attachment: Mapping[str, Any],
    *,
    cluster: Mapping[str, Any],
    field: str,
    errors: list[RssCitationAttachmentValidationError],
) -> None:
    cluster_source_ref_ids = set(_ids(cluster.get("source_refs"), "source_ref_id"))
    attachment_source_ref_ids = set(_string_list(attachment.get("source_ref_ids")))
    citation_source_ref_ids = set(_ids(attachment.get("citations"), "source_ref_id"))
    citation_ids = set(_ids(attachment.get("citations"), "citation_id"))
    declared_citation_ids = set(_string_list(attachment.get("citation_ids")))

    if not cluster_source_ref_ids:
        errors.append(
            RssCitationAttachmentValidationError(
                "missing_cluster_source_refs",
                f"{field}.source_ref_ids",
                "story cluster must expose source_refs before citation attachment.",
            )
        )
    if attachment_source_ref_ids != cluster_source_ref_ids:
        errors.append(
            RssCitationAttachmentValidationError(
                "citation_attachment_source_mismatch",
                f"{field}.source_ref_ids",
                "citation attachment source_ref_ids must match the story cluster.",
            )
        )
    if citation_source_ref_ids != cluster_source_ref_ids:
        errors.append(
            RssCitationAttachmentValidationError(
                "citation_source_ref_mismatch",
                f"{field}.citations",
                "attached citations must cite exactly the story cluster source_refs.",
            )
        )
    if declared_citation_ids != citation_ids:
        errors.append(
            RssCitationAttachmentValidationError(
                "citation_id_mismatch",
                f"{field}.citation_ids",
                "citation_ids must match attached citation objects.",
            )
        )


def _ids(value: Any, key: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        safe = _safe_string(item.get(key))
        if safe and safe not in ids:
            ids.append(safe)
    return ids


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        safe = _safe_string(item)
        if safe and safe not in ids:
            ids.append(safe)
    return ids


def _safe_string(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


__all__ = [
    "RSS_CITATION_ATTACHMENT_SCOPE",
    "RSS_CITATION_ATTACHMENT_STAGE",
    "RSS_CITATION_ATTACHMENT_TYPE",
    "RSS_SYNTHESIS_KIND",
    "RssCitationAttachmentValidationError",
    "build_rss_story_cluster_citation_attachment",
    "validate_rss_citation_attachments",
]
