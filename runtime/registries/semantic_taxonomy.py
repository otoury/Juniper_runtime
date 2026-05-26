from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from runtime.actions.capabilities import load_action_capability_config


INTERACTION_MODES_PATH = Path("semantics/interaction_modes.json")
OPERATIONS_PATH = Path("semantics/operations.json")
ARTIFACT_ATTACHMENT_POLICY_PATH = Path(
    "planner/policies/artifact_attachment.json"
)
TRANSFORM_GUIDANCE_PATH = Path("semantics/transform_guidance.json")
TRANSFORM_EXAMPLES_PATH = Path("semantics/transform_examples.json")
CONTEXT_RESOLUTION_POLICY_PATH = Path(
    "planner/policies/context_resolution.json"
)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)

    for key, value in override.items():
        if (
            isinstance(value, dict)
            and isinstance(merged.get(key), dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value

    return merged


@lru_cache(maxsize=None)
def load_semantic_taxonomy() -> dict:
    taxonomy = {}

    for path in (
        INTERACTION_MODES_PATH,
        OPERATIONS_PATH,
        ARTIFACT_ATTACHMENT_POLICY_PATH,
        TRANSFORM_GUIDANCE_PATH,
        TRANSFORM_EXAMPLES_PATH,
        CONTEXT_RESOLUTION_POLICY_PATH,
    ):
        taxonomy = _deep_merge(taxonomy, _read_json(path))

    return taxonomy


def _bullet_lines(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values]


def _mode_block(name: str, config: dict) -> list[str]:
    lines = [
        f"{name}:",
        str(config.get("description", "")).strip(),
    ]

    negative_guidance = config.get("negative_guidance", [])

    if negative_guidance:
        lines.append("Negative guidance:")
        lines.extend(_bullet_lines(negative_guidance))

    examples = config.get("examples", [])

    if examples:
        lines.append("Examples:")
        lines.extend(_bullet_lines(examples))

    return [line for line in lines if line]


def _capability_lines() -> list[str]:
    capabilities, _aliases = load_action_capability_config()
    lines = []

    for name, capability in capabilities.items():
        lines.append(
            f"- {name}: {capability.description} "
            f"(requires_approval={capability.requires_approval})"
        )

    return lines


def build_request_gate_taxonomy_block() -> str:
    taxonomy = load_semantic_taxonomy()
    modes = taxonomy.get("interaction_modes", {})
    operations = taxonomy.get("operations", {})
    attachment = taxonomy.get("attachment", {})
    transform_intents = taxonomy.get("transform_intents", {})
    capability_lines = _capability_lines()

    lines = ["SHARED SEMANTIC TAXONOMY:"]

    for name in [
        "NEW_REQUEST",
        "TRANSFORM_EXISTING",
        "CONVERT_ARTIFACT",
        "CONTINUE_WORKFLOW",
        "ANSWER_QUESTION",
    ]:
        if name in modes:
            lines.extend(_mode_block(name, modes[name]))
            lines.append("")

    if operations:
        lines.append("Operation mapping:")

        for name, config in operations.items():
            mode = config.get("mode", "")
            description = config.get("description", "")
            lines.append(f"- {name} -> {mode}: {description}")

        lines.append("")

    if capability_lines:
        lines.append("Action capabilities:")
        lines.extend(capability_lines)

        lines.append("")

    true_cases = attachment.get("uses_active_artifact_true", [])
    false_cases = attachment.get("uses_active_artifact_false", [])

    if true_cases or false_cases:
        lines.append("uses_active_artifact:")

        if true_cases:
            lines.append("Set true for:")
            lines.extend(_bullet_lines(true_cases))

        if false_cases:
            lines.append("Set false for:")
            lines.extend(_bullet_lines(false_cases))

        lines.append("")

    guidance = transform_intents.get("guidance", [])
    examples = transform_intents.get("examples", {})

    if guidance or examples:
        lines.append("Transform intent:")
        lines.extend(_bullet_lines(guidance))

        if examples:
            lines.append("Examples:")

            for phrase, intent in examples.items():
                lines.append(f"- {phrase!r} -> {intent!r}")

    return "\n".join(lines).strip()


def build_context_resolver_taxonomy_block() -> str:
    taxonomy = load_semantic_taxonomy()
    resolver = taxonomy.get("context_resolver", {})
    operations = taxonomy.get("operations", {})
    actions = resolver.get("allowed_actions", {})
    rules = resolver.get("rules", [])
    capability_lines = _capability_lines()

    lines = ["SHARED SEMANTIC TAXONOMY:"]

    if actions:
        lines.append("Allowed resolver actions:")

        for name, description in actions.items():
            lines.append(f"- {name}: {description}")

        lines.append("")

    if operations:
        lines.append("Operation distinctions:")

        for name, config in operations.items():
            description = config.get("description", "")
            lines.append(f"- {name}: {description}")

        lines.append("")

    if capability_lines:
        lines.append("Action capabilities:")
        lines.extend(capability_lines)

        lines.append("")

    if rules:
        lines.append("Resolver rules:")
        lines.extend(_bullet_lines(rules))

    return "\n".join(lines).strip()


__all__ = [
    "ARTIFACT_ATTACHMENT_POLICY_PATH",
    "CONTEXT_RESOLUTION_POLICY_PATH",
    "INTERACTION_MODES_PATH",
    "OPERATIONS_PATH",
    "load_semantic_taxonomy",
    "TRANSFORM_GUIDANCE_PATH",
    "TRANSFORM_EXAMPLES_PATH",
    "build_request_gate_taxonomy_block",
    "build_context_resolver_taxonomy_block",
]
