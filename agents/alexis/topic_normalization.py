from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.ingestion.source_item_store import normalize_topic_entity_focus


DEFAULT_TOPIC_NORMALIZATION_CONFIG = (
    Path(__file__).resolve().parent / "topic_normalization.json"
)


@dataclass(frozen=True)
class AlexisRssTopicNormalization:
    requested_focus: dict[str, tuple[str, ...]] | None
    matching_focus: dict[str, tuple[str, ...]] | None
    provenance: dict[str, Any]

    @property
    def has_focus(self) -> bool:
        return self.requested_focus is not None

    def requested_record(self) -> dict[str, list[str]] | None:
        return _focus_record(self.requested_focus)

    def matching_record(self) -> dict[str, list[str]] | None:
        return _focus_record(self.matching_focus)


def normalize_alexis_rss_topic_focus(
    topic_entity_focus: dict[str, Any] | None,
    *,
    config_path: str | Path = DEFAULT_TOPIC_NORMALIZATION_CONFIG,
) -> AlexisRssTopicNormalization:
    requested_focus = normalize_topic_entity_focus(topic_entity_focus)
    config = _load_config(config_path)
    if not requested_focus:
        return AlexisRssTopicNormalization(
            requested_focus=None,
            matching_focus=None,
            provenance=_provenance(
                config=config,
                matched_family_ids=(),
                aliases_applied=False,
                requested_focus=None,
                matching_focus=None,
            ),
        )

    matching: dict[str, list[str]] = {
        "topics": list(requested_focus.get("topics", ())),
        "entities": list(requested_focus.get("entities", ())),
    }
    matched_family_ids: list[str] = []
    for family in config.get("families", []):
        if not isinstance(family, dict):
            continue
        if not _family_matches_focus(family, requested_focus):
            continue
        family_id = _safe_text(family.get("family_id"), limit=80)
        family_type = _safe_text(family.get("type"), limit=40)
        target_key = "entities" if family_type == "entity" else "topics"
        if family_id and family_id not in matched_family_ids:
            matched_family_ids.append(family_id)
        for term in _family_terms(family):
            _append_unique(matching[target_key], term)

    matching_focus = {
        "topics": tuple(matching["topics"][:10]),
        "entities": tuple(matching["entities"][:10]),
    }
    return AlexisRssTopicNormalization(
        requested_focus=requested_focus,
        matching_focus=matching_focus,
        provenance=_provenance(
            config=config,
            matched_family_ids=tuple(matched_family_ids[:10]),
            aliases_applied=bool(matched_family_ids),
            requested_focus=requested_focus,
            matching_focus=matching_focus,
        ),
    )


def apply_topic_normalization_metadata(
    artifact: dict[str, Any] | None,
    normalization: AlexisRssTopicNormalization,
) -> None:
    if not isinstance(artifact, dict) or not normalization.has_focus:
        return
    requested = normalization.requested_record()
    artifact["topic_entity_focus"] = requested
    artifact["topic_normalization"] = dict(normalization.provenance)
    retrieval_metadata = artifact.get("retrieval_metadata")
    if isinstance(retrieval_metadata, dict):
        retrieval_metadata["topic_entity_focus"] = requested
        retrieval_metadata["topic_normalization"] = dict(
            normalization.provenance
        )


def retrieval_metadata_with_topic_normalization(
    retrieval_metadata: dict[str, Any],
    normalization: AlexisRssTopicNormalization,
) -> dict[str, Any]:
    metadata = dict(retrieval_metadata)
    if not normalization.has_focus:
        return metadata
    metadata["topic_entity_focus"] = normalization.requested_record()
    metadata["topic_normalization"] = dict(normalization.provenance)
    return metadata


def _load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    families = raw.get("families")
    if not isinstance(families, list):
        families = []
    return {
        "config_id": _safe_text(raw.get("config_id"), limit=120)
        or "alexis_rss_topic_normalization_v1",
        "version": raw.get("version") if isinstance(raw.get("version"), int) else 1,
        "scope": _safe_text(raw.get("scope"), limit=120)
        or "alexis_rss_synthesis",
        "matching_boundary": _safe_text(raw.get("matching_boundary"), limit=160)
        or "cluster_relevance_and_rss_adequacy_only",
        "families": families[:20],
    }


def _family_matches_focus(
    family: dict[str, Any],
    requested_focus: dict[str, tuple[str, ...]],
) -> bool:
    requested_terms = {
        term
        for terms in requested_focus.values()
        for term in terms
        if isinstance(term, str)
    }
    family_terms = set(_family_terms(family))
    return bool(requested_terms & family_terms)


def _family_terms(family: dict[str, Any]) -> tuple[str, ...]:
    terms: list[str] = []
    for value in (family.get("canonical"), *(_raw_aliases(family))):
        normalized = _normalize_term(value)
        if normalized and normalized not in terms:
            terms.append(normalized)
    return tuple(terms[:30])


def _raw_aliases(family: dict[str, Any]) -> tuple[Any, ...]:
    aliases = family.get("aliases")
    if not isinstance(aliases, list):
        return ()
    return tuple(aliases[:30])


def _normalize_term(value: Any) -> str:
    focus = normalize_topic_entity_focus({"topics": [value], "entities": []})
    if not focus:
        return ""
    terms = focus.get("topics", ())
    return terms[0] if terms else ""


def _append_unique(values: list[str], term: str) -> None:
    if term and term not in values:
        values.append(term)


def _provenance(
    *,
    config: dict[str, Any],
    matched_family_ids: tuple[str, ...],
    aliases_applied: bool,
    requested_focus: dict[str, tuple[str, ...]] | None,
    matching_focus: dict[str, tuple[str, ...]] | None,
) -> dict[str, Any]:
    return {
        "config_id": config["config_id"],
        "version": config["version"],
        "scope": config["scope"],
        "matching_boundary": config["matching_boundary"],
        "aliases_applied": aliases_applied,
        "matched_family_ids": list(matched_family_ids),
        "requested_focus": _focus_record(requested_focus),
        "matching_focus": _focus_record(matching_focus),
        "cloud_model_called": False,
        "search_api_called": False,
        "article_body_fetched": False,
    }


def _focus_record(
    value: dict[str, tuple[str, ...]] | None,
) -> dict[str, list[str]] | None:
    if not value:
        return None
    return {
        "topics": list(value.get("topics", ())),
        "entities": list(value.get("entities", ())),
    }


def _safe_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


__all__ = [
    "AlexisRssTopicNormalization",
    "apply_topic_normalization_metadata",
    "normalize_alexis_rss_topic_focus",
    "retrieval_metadata_with_topic_normalization",
]
