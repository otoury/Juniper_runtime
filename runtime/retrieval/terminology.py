from __future__ import annotations

from typing import Iterable


RETRIEVAL_CONCEPT = "retrieval"
LOOKUP_RETRIEVAL_SPECIALIZATION = "lookup"
BOUNDED_RETRIEVAL_SCOPE = "bounded"
LOOKUP_RETRIEVAL_AUTHORITY = (
    "planner_declared_runtime_orchestrated_agent_bound"
)


def bounded_lookup_retrieval_metadata(
    *,
    retrieval_types: Iterable[str] = (),
) -> dict[str, object]:
    types = [
        item.strip()
        for item in retrieval_types
        if isinstance(item, str) and item.strip()
    ]
    return {
        "retrieval_concept": RETRIEVAL_CONCEPT,
        "retrieval_specialization": LOOKUP_RETRIEVAL_SPECIALIZATION,
        "retrieval_scope": BOUNDED_RETRIEVAL_SCOPE,
        "retrieval_authority": LOOKUP_RETRIEVAL_AUTHORITY,
        "retrieval_types": types,
    }


__all__ = [
    "BOUNDED_RETRIEVAL_SCOPE",
    "LOOKUP_RETRIEVAL_AUTHORITY",
    "LOOKUP_RETRIEVAL_SPECIALIZATION",
    "RETRIEVAL_CONCEPT",
    "bounded_lookup_retrieval_metadata",
]
