import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.semantic_taxonomy import (  # noqa: E402
    build_context_resolver_taxonomy_block,
    build_request_gate_taxonomy_block,
    load_semantic_taxonomy,
)


INTERACTION_MODES_PATH = ROOT / "semantics" / "interaction_modes.json"
OPERATIONS_PATH = ROOT / "semantics" / "operations.json"
ARTIFACT_ATTACHMENT_PATH = (
    ROOT / "planner" / "policies" / "artifact_attachment.json"
)
TRANSFORM_GUIDANCE_PATH = ROOT / "semantics" / "transform_guidance.json"
TRANSFORM_EXAMPLES_PATH = ROOT / "semantics" / "transform_examples.json"
CONTEXT_RESOLUTION_PATH = (
    ROOT / "planner" / "policies" / "context_resolution.json"
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_transitional_taxonomy_file_is_retired():
    taxonomy_path = ROOT / "config" / "semantic_taxonomy.json"

    assert not taxonomy_path.exists()


def test_ontology_files_exclude_policy_and_transform_examples():
    interaction_modes = load_json(INTERACTION_MODES_PATH)
    operations = load_json(OPERATIONS_PATH)

    assert set(interaction_modes) == {"interaction_modes"}
    assert set(operations) == {"operations"}

    for data in (interaction_modes, operations):
        assert "context_resolver" not in data
        assert "transform_intents" not in data


def test_transform_examples_are_examples_only():
    examples = load_json(TRANSFORM_EXAMPLES_PATH)

    assert set(examples) == {"transform_intents"}
    assert set(examples["transform_intents"]) == {"examples"}
    assert examples["transform_intents"]["examples"]["shorten"] == "shorten"


def test_transform_guidance_is_not_examples():
    guidance = load_json(TRANSFORM_GUIDANCE_PATH)

    assert set(guidance) == {"transform_intents"}
    assert set(guidance["transform_intents"]) == {"guidance"}
    assert "examples" not in guidance["transform_intents"]


def test_artifact_attachment_policy_lives_under_planner_policy():
    attachment = load_json(ARTIFACT_ATTACHMENT_PATH)

    assert set(attachment) == {"attachment"}
    assert "uses_active_artifact_true" in attachment["attachment"]
    assert "uses_active_artifact_false" in attachment["attachment"]


def test_context_resolution_policy_is_not_ontology():
    policy = load_json(CONTEXT_RESOLUTION_PATH)

    assert set(policy) == {"context_resolver"}
    assert "allowed_actions" in policy["context_resolver"]
    assert "rules" in policy["context_resolver"]
    assert "interaction_modes" not in policy
    assert "operations" not in policy


def test_composed_taxonomy_preserves_legacy_runtime_shape():
    load_semantic_taxonomy.cache_clear()
    taxonomy = load_semantic_taxonomy()

    assert "interaction_modes" in taxonomy
    assert "operations" in taxonomy
    assert "attachment" in taxonomy
    assert "transform_intents" in taxonomy
    assert "examples" in taxonomy["transform_intents"]
    assert "guidance" in taxonomy["transform_intents"]
    assert "context_resolver" in taxonomy


def test_taxonomy_prompt_blocks_preserve_content():
    load_semantic_taxonomy.cache_clear()
    request_gate_block = build_request_gate_taxonomy_block()
    resolver_block = build_context_resolver_taxonomy_block()

    assert "NEW_REQUEST:" in request_gate_block
    assert "'shorten' -> 'shorten'" in request_gate_block
    assert "Allowed resolver actions:" in resolver_block
    assert "Resolver rules:" in resolver_block


def main():
    test_transitional_taxonomy_file_is_retired()
    test_ontology_files_exclude_policy_and_transform_examples()
    test_transform_examples_are_examples_only()
    test_transform_guidance_is_not_examples()
    test_artifact_attachment_policy_lives_under_planner_policy()
    test_context_resolution_policy_is_not_ontology()
    test_composed_taxonomy_preserves_legacy_runtime_shape()
    test_taxonomy_prompt_blocks_preserve_content()
    print("PASS semantic taxonomy split")


if __name__ == "__main__":
    main()
