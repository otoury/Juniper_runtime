import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.actions.capabilities import (
    CAPABILITIES,
    CAPABILITY_ALIASES,
    validate_action_capability,
)


def main():
    assert "draft_email" in CAPABILITIES
    assert "send_email" in CAPABILITIES
    assert CAPABILITIES["draft_email"].requires_approval is False
    assert CAPABILITIES["send_email"].requires_approval is True
    assert CAPABILITIES["draft_email"].allowed_agents == ["alexis"]
    assert CAPABILITIES["send_email"].allowed_agents == ["alexis"]

    assert CAPABILITY_ALIASES["draft_lower_third"] == "create_lower_third"

    capability, normalized = validate_action_capability(
        agent_name="alexis",
        action_type="draft_lower_third",
    )

    assert normalized == "create_lower_third"
    assert capability is CAPABILITIES["create_lower_third"]

    print("PASS action capability config loading")


if __name__ == "__main__":
    main()
