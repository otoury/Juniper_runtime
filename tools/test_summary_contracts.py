import copy
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.registries.summary_contracts import (  # noqa: E402
    SUMMARY_CONTRACT_PATH,
    load_summary_contracts,
)


def _manifest():
    return json.loads((ROOT / SUMMARY_CONTRACT_PATH).read_text(encoding="utf-8"))


def _write_manifest(data):
    tmp = TemporaryDirectory()
    path = Path(tmp.name) / "summary_contract.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return tmp, path


def test_valid_generic_summary_contract_loads():
    contracts, errors = load_summary_contracts(ROOT / SUMMARY_CONTRACT_PATH)

    assert errors == ()
    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.artifact_type == "summary"
    assert contract.max_items == 5
    assert contract.max_words is None


def test_unknown_artifact_type_fails_closed():
    data = _manifest()
    data["contracts"][0]["artifact_type"] = "freeform_answer"
    tmp, path = _write_manifest(data)
    try:
        contracts, errors = load_summary_contracts(path)
    finally:
        tmp.cleanup()

    assert contracts == ()
    assert any(error.field.endswith("artifact_type") for error in errors)


def test_unbounded_item_request_fails_closed():
    data = _manifest()
    data["contracts"][0]["max_items"] = 100
    tmp, path = _write_manifest(data)
    try:
        contracts, errors = load_summary_contracts(path)
    finally:
        tmp.cleanup()

    assert contracts == ()
    assert any(error.field.endswith("max_items") for error in errors)


def test_safety_flags_must_remain_disabled():
    data = _manifest()
    for field in data["contracts"][0]["safety"]:
        mutated = copy.deepcopy(data)
        mutated["contracts"][0]["safety"][field] = True
        tmp, path = _write_manifest(mutated)
        try:
            contracts, errors = load_summary_contracts(path)
        finally:
            tmp.cleanup()

        assert contracts == ()
        assert any(error.field.endswith(f"safety.{field}") for error in errors)


def test_generic_contract_declares_explicit_non_goals():
    data = _manifest()
    serialized = json.dumps(data, sort_keys=True)

    for phrase in (
        "no source expansion",
        "no live fetching",
        "no memory writes",
        "no embeddings",
        "no autonomous topic discovery",
        "no hidden retrieval",
        "no background cognition",
    ):
        assert phrase in serialized


def main():
    test_valid_generic_summary_contract_loads()
    test_unknown_artifact_type_fails_closed()
    test_unbounded_item_request_fails_closed()
    test_safety_flags_must_remain_disabled()
    test_generic_contract_declares_explicit_non_goals()
    print("PASS summary contracts")


if __name__ == "__main__":
    main()
