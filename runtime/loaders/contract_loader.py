# runtime/loaders/contract_loader.py

from __future__ import annotations

import json
from pathlib import Path

from runtime.loaders.manifest_loader import (
    load_manifest,
    read_text,
)


def get_contract_config(
    *,
    agent_root: Path,
    name: str | None,
) -> dict:
    if not name:
        return {}

    manifest = load_manifest(
        agent_root / "contracts"
    )

    return manifest.get(name, {})


def _read_json(path: Path):
    if not path.exists():
        return None

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def load_contract_schema(
    *,
    agent_root: Path,
    name: str | None,
) -> dict:
    config = get_contract_config(
        agent_root=agent_root,
        name=name,
    )

    contract_dir = config.get("contract_dir")
    schema_file = config.get("schema_file")

    if not contract_dir or not schema_file:
        return {}

    schema = _read_json(
        agent_root
        / "contracts"
        / contract_dir
        / schema_file
    )

    return schema or {}


def load_contract_examples(
    *,
    agent_root: Path,
    name: str | None,
):
    config = get_contract_config(
        agent_root=agent_root,
        name=name,
    )

    contract_dir = config.get("contract_dir")
    examples_file = config.get("examples_file")

    if not contract_dir or not examples_file:
        return None

    return _read_json(
        agent_root
        / "contracts"
        / contract_dir
        / examples_file
    )


def load_contract_instructions(
    *,
    agent_root: Path,
    name: str | None,
) -> str:
    config = get_contract_config(
        agent_root=agent_root,
        name=name,
    )

    contract_dir = config.get("contract_dir")
    instructions_file = config.get("instructions_file")

    if not contract_dir or not instructions_file:
        return ""

    return read_text(
        agent_root
        / "contracts"
        / contract_dir
        / instructions_file
    )


def load_contract(
    *,
    agent_root: Path,
    name: str | None,
) -> str:
    instructions = load_contract_instructions(
        agent_root=agent_root,
        name=name,
    )

    schema = load_contract_schema(
        agent_root=agent_root,
        name=name,
    )

    examples = load_contract_examples(
        agent_root=agent_root,
        name=name,
    )

    blocks = []

    if instructions:
        blocks.append(instructions)

    if schema:
        blocks.append(
            "OUTPUT SCHEMA:\n"
            + json.dumps(
                schema,
                indent=2,
                ensure_ascii=False,
            )
        )

    if examples:
        blocks.append(
            "EXAMPLES:\n"
            + json.dumps(
                examples,
                indent=2,
                ensure_ascii=False,
            )
        )

    return "\n\n".join(blocks).strip()

def load_contract_repair_prompt(
    *,
    agent_root: Path,
    name: str | None,
) -> str:
    config = get_contract_config(
        agent_root=agent_root,
        name=name,
    )

    contract_dir = config.get("contract_dir")
    repair_file = config.get("repair_file")

    if not contract_dir or not repair_file:
        return ""

    return read_text(
        agent_root
        / "contracts"
        / contract_dir
        / repair_file
    )

def list_contract_names(
    *,
    agent_root: Path,
) -> list[str]:
    manifest = load_manifest(
        agent_root / "contracts"
    )

    return sorted(manifest.keys())

