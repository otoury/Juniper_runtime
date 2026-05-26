from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


CONTRACT_PATHS = {
    "request_gate": Path("planner/contracts/request_gate.json"),
    "execution_planner": Path("planner/contracts/execution_planner.json"),
    "artifact_repair": Path("runtime/contracts/artifact_repair.json"),
    "guest_candidate_merge_receipt": Path(
        "agents/shared/contracts/guest_candidate_merge_receipt_contracts.json"
    ),
}


@lru_cache(maxsize=None)
def load_runtime_contract(name: str) -> dict:
    path = CONTRACT_PATHS.get(name)
    if path is None:
        return {}

    if not path.exists():
        return {}

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def build_contract_prompt_block(name: str) -> str:
    contract = load_runtime_contract(name)

    if not contract:
        return ""

    parts = []

    description = contract.get("description")
    instruction = contract.get("return_instruction")
    schema = contract.get("schema")

    if description:
        parts.append(description)

    if instruction:
        parts.append(instruction)

    if schema:
        parts.append(
            "OUTPUT SCHEMA:\n"
            + json.dumps(
                schema,
                indent=2,
                ensure_ascii=False,
            )
        )

    return "\n\n".join(parts).strip()
