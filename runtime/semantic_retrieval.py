from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from runtime.semantic_index import LocalSemanticIndex, SemanticIndexEntry


DEFAULT_SEMANTIC_RETRIEVAL_LIMIT = 5
MAX_SEMANTIC_RETRIEVAL_LIMIT = 5
SEMANTIC_RETRIEVAL_POLICY_ID = "local_term_overlap_v1"


@dataclass(frozen=True)
class SemanticRetrievalMatch:
    candidate_id: str
    semantic_match_score: float
    semantic_match_reasons: tuple[str, ...]
    matched_terms: tuple[str, ...]
    entry: SemanticIndexEntry


@dataclass(frozen=True)
class SemanticRetrievalResult:
    ok: bool
    query_terms: tuple[str, ...]
    matches: tuple[SemanticRetrievalMatch, ...]
    skipped_reasons: tuple[str, ...]
    provenance: dict[str, Any]


def retrieve_semantic_index_matches(
    *,
    semantic_query: Mapping[str, Any] | None,
    semantic_index: LocalSemanticIndex | None,
) -> SemanticRetrievalResult:
    if not isinstance(semantic_query, Mapping):
        return _closed(
            query_terms=(),
            semantic_index=semantic_index,
            skipped_reasons=("malformed_semantic_query",),
        )

    query_text = _query_text(semantic_query)
    query_terms = _normalized_terms(query_text)
    if not query_terms:
        return _closed(
            query_terms=(),
            semantic_index=semantic_index,
            skipped_reasons=("missing_semantic_query_text",),
        )

    if not isinstance(semantic_index, LocalSemanticIndex):
        return _closed(
            query_terms=query_terms,
            semantic_index=semantic_index,
            skipped_reasons=("malformed_semantic_index",),
        )

    limit = _max_results(semantic_query)
    records: list[tuple[int, SemanticRetrievalMatch]] = []
    for index, entry in enumerate(semantic_index.entries):
        match = _match_entry(entry=entry, query_terms=query_terms)
        if match is not None:
            records.append((index, match))

    ordered = sorted(
        records,
        key=lambda item: (
            -item[1].semantic_match_score,
            item[0],
        ),
    )
    matches = tuple(match for _, match in ordered[:limit])
    skipped_reasons = () if matches else ("no_semantic_match",)
    return SemanticRetrievalResult(
        ok=bool(matches),
        query_terms=query_terms,
        matches=matches,
        skipped_reasons=skipped_reasons,
        provenance=_provenance(
            semantic_index=semantic_index,
            query_terms=query_terms,
            matches=matches,
            skipped_reasons=skipped_reasons,
        ),
    )


def _match_entry(
    *,
    entry: SemanticIndexEntry,
    query_terms: tuple[str, ...],
) -> SemanticRetrievalMatch | None:
    text_terms = set(_normalized_terms(entry.semantic_text))
    tag_terms = set(_normalized_terms(" ".join(entry.tags)))
    category_terms = set(_normalized_terms(" ".join(entry.categories)))
    all_terms = text_terms | tag_terms | category_terms
    matched = tuple(term for term in query_terms if term in all_terms)
    if not matched:
        return None

    reasons: list[str] = []
    if any(term in text_terms for term in matched):
        reasons.append("semantic_text_term_overlap")
    if any(term in tag_terms for term in matched):
        reasons.append("semantic_tag_term_overlap")
    if any(term in category_terms for term in matched):
        reasons.append("semantic_category_term_overlap")

    return SemanticRetrievalMatch(
        candidate_id=entry.candidate_id,
        semantic_match_score=round(len(matched) / len(query_terms), 6),
        semantic_match_reasons=tuple(reasons),
        matched_terms=matched,
        entry=entry,
    )


def _query_text(query: Mapping[str, Any]) -> str:
    for key in ("query_text", "semantic_query"):
        value = query.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _max_results(query: Mapping[str, Any]) -> int:
    value = query.get("max_results", DEFAULT_SEMANTIC_RETRIEVAL_LIMIT)
    if not isinstance(value, int) or isinstance(value, bool):
        return DEFAULT_SEMANTIC_RETRIEVAL_LIMIT
    return min(max(1, value), MAX_SEMANTIC_RETRIEVAL_LIMIT)


def _normalized_terms(value: str) -> tuple[str, ...]:
    normalized = value.lower()
    terms: list[str] = []
    seen: set[str] = set()
    for term in re.split(r"[^a-z0-9]+", normalized):
        if not term or term in seen:
            continue
        terms.append(term)
        seen.add(term)
    return tuple(terms)


def _closed(
    *,
    query_terms: tuple[str, ...],
    semantic_index: Any,
    skipped_reasons: tuple[str, ...],
) -> SemanticRetrievalResult:
    return SemanticRetrievalResult(
        ok=False,
        query_terms=query_terms,
        matches=(),
        skipped_reasons=skipped_reasons,
        provenance=_provenance(
            semantic_index=semantic_index,
            query_terms=query_terms,
            matches=(),
            skipped_reasons=skipped_reasons,
        ),
    )


def _provenance(
    *,
    semantic_index: Any,
    query_terms: tuple[str, ...],
    matches: tuple[SemanticRetrievalMatch, ...],
    skipped_reasons: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "operation_id": "semantic_index_retrieval",
        "retrieval_boundary": "runtime.semantic_retrieval",
        "retrieval_policy_id": SEMANTIC_RETRIEVAL_POLICY_ID,
        "index_id": (
            semantic_index.index_id
            if isinstance(semantic_index, LocalSemanticIndex)
            else None
        ),
        "query_term_count": len(query_terms),
        "records_returned": len(matches),
        "deterministic": True,
        "external_calls_executed": False,
        "cloud_model_called": False,
        "llm_ranking_performed": False,
        "skipped_reasons": list(skipped_reasons),
    }


__all__ = [
    "DEFAULT_SEMANTIC_RETRIEVAL_LIMIT",
    "MAX_SEMANTIC_RETRIEVAL_LIMIT",
    "SEMANTIC_RETRIEVAL_POLICY_ID",
    "SemanticRetrievalMatch",
    "SemanticRetrievalResult",
    "retrieve_semantic_index_matches",
]
