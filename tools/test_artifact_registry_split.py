import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.artifacts import (  # noqa: E402
    get_artifact_config,
    get_artifact_constraints,
    get_artifact_engine_policy,
    get_artifact_extract_fields,
    list_artifact_types,
    load_artifact_registry,
    should_persist_artifact,
)


ARTIFACTS_PATH = ROOT / "agents" / "shared" / "artifacts" / "artifacts.json"
POLICIES_PATH = (
    ROOT / "agents" / "shared" / "artifacts" / "artifact_policies.json"
)
POLICY_FIELDS = {
    "persist_as_artifact",
    "preferred_engine",
    "fallback_engines",
    "reasoning_depth",
    "style_sensitivity",
    "latency_preference",
    "formatting_constraints",
    "transforms",
    "extract_fields",
}
ONTOLOGY_FIELDS = {
    "description",
    "semantic_class",
    "semantic_signals",
    "aliases",
    "intent_examples",
    "creation_intent_examples",
    "bounded",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_artifact_ontology_file_excludes_runtime_policy_fields():
    artifacts = load_json(ARTIFACTS_PATH)

    assert artifacts
    for artifact_id, config in artifacts.items():
        assert "description" in config, artifact_id
        assert "semantic_class" in config, artifact_id
        assert "bounded" in config, artifact_id
        assert not (set(config) & POLICY_FIELDS), artifact_id


def test_artifact_policy_file_excludes_ontology_identity_fields():
    policies = load_json(POLICIES_PATH)

    assert policies
    for artifact_id, policy in policies.items():
        assert "persist_as_artifact" in policy, artifact_id
        assert "formatting_constraints" in policy, artifact_id
        assert not (set(policy) & ONTOLOGY_FIELDS), artifact_id


def test_artifact_policy_ids_match_artifact_ids():
    artifacts = load_json(ARTIFACTS_PATH)
    policies = load_json(POLICIES_PATH)

    assert set(artifacts) == set(policies)


def test_effective_registry_preserves_artifact_metadata_shape():
    load_artifact_registry.cache_clear()
    config = get_artifact_config("lower_third")

    assert config["description"] == "Broadcast lower-third banner."
    assert config["semantic_class"] == "editorial_microcopy"
    assert config["bounded"] is True
    assert config["persist_as_artifact"] is True
    assert config["preferred_engine"] == "local_agent"
    assert config["fallback_engines"] == [
        "local_router_primary",
        "cloud_fast",
        "cloud_deep",
    ]
    assert config["formatting_constraints"]["max_words"] == 8
    assert config["transforms"]
    assert config["extract_fields"] == ["content", "lower_third"]


def test_artifact_registry_helpers_preserve_behavior():
    load_artifact_registry.cache_clear()

    assert "lower_third" in list_artifact_types()
    assert should_persist_artifact("lower_third") is True
    assert get_artifact_engine_policy("lower_third") == (
        "local_agent",
        ["local_router_primary", "cloud_fast", "cloud_deep"],
    )
    assert get_artifact_constraints("lower_third")["max_words"] == 8
    assert get_artifact_extract_fields("lower_third") == [
        "content",
        "lower_third",
    ]


def test_written_piece_policy_still_composes():
    load_artifact_registry.cache_clear()
    config = get_artifact_config("written_piece")

    assert config["semantic_class"] == "neutral_prose"
    assert config["preferred_engine"] == "local_agent"
    assert config["extract_fields"] == ["content", "text", "piece"]


def main():
    test_artifact_ontology_file_excludes_runtime_policy_fields()
    test_artifact_policy_file_excludes_ontology_identity_fields()
    test_artifact_policy_ids_match_artifact_ids()
    test_effective_registry_preserves_artifact_metadata_shape()
    test_artifact_registry_helpers_preserve_behavior()
    test_written_piece_policy_still_composes()
    print("PASS artifact registry split")


if __name__ == "__main__":
    main()
