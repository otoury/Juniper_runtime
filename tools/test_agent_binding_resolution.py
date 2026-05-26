import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.bindings import (  # noqa: E402
    AgentBinding,
    BindingResolutionError,
    get_binding_manifest,
    list_agent_bindings,
    resolve_agent_binding,
)


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def make_agent(
    root: Path,
    *,
    agent_name: str = "tester",
    binding: dict,
    skill_names: list[str] | None = None,
    resource_names: list[str] | None = None,
):
    agent_dir = root / "agents" / agent_name

    for skill in skill_names or []:
        skill_path = agent_dir / "skills" / f"{skill}.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(f"{skill}\n", encoding="utf-8")

    for resource in resource_names or []:
        resource_path = agent_dir / "tools" / f"{resource}.py"
        resource_path.parent.mkdir(parents=True, exist_ok=True)
        resource_path.write_text("# test resource\n", encoding="utf-8")

    write_json(
        agent_dir / "capabilities" / "bindings.json",
        {
            "bindings": {
                "test_binding": binding,
            },
        },
    )

    return agent_dir


def assert_error(
    result,
    error_code: str,
):
    assert isinstance(result, BindingResolutionError), result
    assert result.error_code == error_code, result


def test_successful_alexis_binding_resolution():
    result = resolve_agent_binding("alexis", "draft_email")

    assert isinstance(result, AgentBinding), result
    assert result.agent_name == "alexis"
    assert result.binding_id == "draft_email"
    assert result.shared_capability == "draft_email"
    assert result.skills == ["structured_actions"]
    assert result.resources == ["guest_db"]
    assert result.tone == "newsroom"

    bindings = list_agent_bindings("alexis")
    assert isinstance(bindings, list)
    assert {binding.shared_capability for binding in bindings} == {
        "create_lower_third",
        "discover_entities",
        "draft_email",
        "producer_note",
        "send_email",
    }


def test_alexis_split_binding_manifest_composes_effective_shape():
    manifest = get_binding_manifest("alexis", root=ROOT)

    assert isinstance(manifest, dict), manifest
    assert not (ROOT / "agents/alexis/capabilities/bindings.json").exists()

    draft_email = manifest["bindings"]["draft_email"]
    assert draft_email["shared_capability"] == "draft_email"
    assert draft_email["lookup_capability_governance"]["state"] == "enabled"
    assert draft_email["lookup_execution_policy"]["timeout_ms"] == 3000
    assert draft_email["lookup_context_render_policy"]["max_packets"] == 1
    assert draft_email["lookup_context_injection_policy"]["allowed"] is True
    assert draft_email["tone"] == "newsroom"
    assert draft_email["lookup_capability_compatibility"]["contract_version"] == 1

    send_email = manifest["bindings"]["send_email"]
    assert send_email["approval_policy"] == "shared_capability_required"


def test_missing_capability_binding():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_agent(
            root,
            binding={
                "shared_capability": "draft_email",
                "skills": ["structured_actions"],
                "resources": [],
            },
            skill_names=["structured_actions"],
        )

        result = resolve_agent_binding(
            "tester",
            "send_email",
            root=root,
        )

        assert_error(result, "missing_binding")


def test_missing_agent():
    with tempfile.TemporaryDirectory() as tmp:
        result = resolve_agent_binding(
            "missing_agent",
            "draft_email",
            root=Path(tmp),
        )

        assert_error(result, "missing_agent")


def test_invalid_binding_reference():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_agent(
            root,
            binding={
                "shared_capability": "draft_email",
                "skills": ["missing_skill"],
                "resources": ["missing_resource"],
            },
        )

        result = resolve_agent_binding(
            "tester",
            "draft_email",
            root=root,
        )

        assert_error(result, "missing_local_reference")
        assert result.details == [
            "skill:missing_skill",
            "resource:missing_resource",
        ]


def test_approval_policy_tightening_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_agent(
            root,
            binding={
                "shared_capability": "draft_email",
                "skills": ["structured_actions"],
                "resources": [],
                "approval_policy": "always_require_approval",
            },
            skill_names=["structured_actions"],
        )

        result = resolve_agent_binding(
            "tester",
            "draft_email",
            root=root,
        )

        assert isinstance(result, AgentBinding), result
        assert result.approval_policy == "always_require_approval"


def test_approval_weakening_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_agent(
            root,
            binding={
                "shared_capability": "send_email",
                "skills": ["structured_actions"],
                "resources": [],
                "approval_policy": False,
            },
            skill_names=["structured_actions"],
        )

        result = resolve_agent_binding(
            "tester",
            "send_email",
            root=root,
        )

        assert_error(result, "approval_policy_weakened")


def main():
    test_successful_alexis_binding_resolution()
    test_alexis_split_binding_manifest_composes_effective_shape()
    test_missing_capability_binding()
    test_missing_agent()
    test_invalid_binding_reference()
    test_approval_policy_tightening_accepted()
    test_approval_weakening_rejected()
    print("PASS agent binding resolution")


if __name__ == "__main__":
    main()
