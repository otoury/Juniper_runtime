# runtime/loaders/skill_loader.py

from pathlib import Path

from runtime.loaders.manifest_loader import load_manifest, read_text


def resolve_skill_names(
    *,
    agent_root: Path,
    semantic_output_type: str | None,
    interaction_mode: str | None,
    expected_output_type: str | None = None,
) -> list[str]:
    skills_dir = agent_root / "skills"
    manifest = load_manifest(skills_dir)

    names = []
    names.extend(manifest.get("default_skills", []))

    if semantic_output_type:
        names.extend(
            manifest
            .get("semantic_output_skills", {})
            .get(semantic_output_type, [])
        )

    if interaction_mode:
        names.extend(
            manifest
            .get("interaction_mode_skills", {})
            .get(interaction_mode, [])
        )

    names = list(dict.fromkeys(names))

    if expected_output_type != "action":
        action_skills = set(
            manifest.get("action_output_skills", [])
        )
        names = [
            name
            for name in names
            if name not in action_skills
        ]

    return names


def load_identity(agent_root: Path) -> str:
    return read_text(agent_root / "identity.md")


def load_skills(
    *,
    agent_root: Path,
    semantic_output_type: str | None,
    interaction_mode: str | None,
    expected_output_type: str | None = None,
) -> list[str]:
    skills_dir = agent_root / "skills"
    blocks = []

    for name in resolve_skill_names(
        agent_root=agent_root,
        semantic_output_type=semantic_output_type,
        interaction_mode=interaction_mode,
        expected_output_type=expected_output_type,
    ):
        block = read_text(skills_dir / f"{name}.md")

        if block:
            blocks.append(block)

    return blocks
