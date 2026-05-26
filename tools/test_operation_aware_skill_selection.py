import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.loaders.skill_loader import resolve_skill_names


AGENT_ROOT = ROOT / "agents" / "alexis"


def main():
    transform_skills = resolve_skill_names(
        agent_root=AGENT_ROOT,
        semantic_output_type="producer_note",
        interaction_mode="TRANSFORM_EXISTING",
        expected_output_type="artifact",
    )

    assert "producer_note" in transform_skills
    assert "rewrite" in transform_skills
    assert "structured_actions" not in transform_skills

    action_skills = resolve_skill_names(
        agent_root=AGENT_ROOT,
        semantic_output_type=None,
        interaction_mode="CONTINUE_WORKFLOW",
        expected_output_type="action",
    )

    assert "structured_actions" in action_skills

    producer_note_skills = resolve_skill_names(
        agent_root=AGENT_ROOT,
        semantic_output_type="producer_note",
        interaction_mode="NEW_REQUEST",
        expected_output_type="artifact",
    )

    assert "producer_note" in producer_note_skills
    assert "structured_actions" not in producer_note_skills

    print("PASS operation-aware skill selection")


if __name__ == "__main__":
    main()
