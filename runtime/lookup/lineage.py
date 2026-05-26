from __future__ import annotations

import hashlib
import itertools
import os
from typing import Any


LINEAGE_STAGES = {
    "request": "lookup_request_id",
    "execution": "lookup_execution_id",
    "packet": "lookup_packet_id",
    "render": "lookup_render_id",
    "injection": "lookup_injection_id",
}

_LINEAGE_COUNTER = itertools.count(1)


def new_lookup_lineage_root() -> str:
    sequence = next(_LINEAGE_COUNTER)
    seed = f"{os.getpid()}:{sequence}"
    return f"lookup_lineage_{_digest(seed)}"


def derive_lookup_stage_id(lineage_root: str | None, stage: str) -> str | None:
    if (
        not isinstance(lineage_root, str)
        or not lineage_root.strip()
        or stage not in LINEAGE_STAGES
    ):
        return None

    return f"{stage}_{_digest(f'{lineage_root}:{stage}')}"


def lookup_lineage_ids(lineage_root: str | None) -> dict[str, str]:
    if not isinstance(lineage_root, str) or not lineage_root.strip():
        return {}

    ids: dict[str, str] = {"lookup_lineage_id": lineage_root.strip()}
    for stage, field_name in LINEAGE_STAGES.items():
        stage_id = derive_lookup_stage_id(lineage_root, stage)
        if stage_id is not None:
            ids[field_name] = stage_id
    return ids


def lineage_from_lookup_request(
    lookup_request: dict[str, Any] | None,
) -> dict[str, str]:
    if not isinstance(lookup_request, dict):
        return {}

    lineage_root = lookup_request.get("lookup_lineage_id")
    if not isinstance(lineage_root, str) or not lineage_root.strip():
        return {}

    ids = lookup_lineage_ids(lineage_root)
    return {
        key: value
        for key, value in ids.items()
        if key in {
            "lookup_lineage_id",
            "lookup_request_id",
            "lookup_execution_id",
            "lookup_packet_id",
            "lookup_render_id",
            "lookup_injection_id",
        }
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "LINEAGE_STAGES",
    "derive_lookup_stage_id",
    "lineage_from_lookup_request",
    "lookup_lineage_ids",
    "new_lookup_lineage_root",
]
