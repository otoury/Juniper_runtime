import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.semantic_index import (  # noqa: E402
    MAX_SEMANTIC_INDEX_ENTRIES,
    MAX_SEMANTIC_TEXT_CHARS,
    SemanticIndexEntry,
    build_local_semantic_index,
    normalize_semantic_labels,
    normalize_semantic_text,
    validate_semantic_index_entry,
)


def error_codes(result):
    return [error.error_code for error in result.errors]


def test_semantic_index_entry_validates():
    entry = SemanticIndexEntry(
        candidate_id="candidate-1",
        semantic_text="A normalized local semantic text.",
        tags=("topic",),
        categories=("role",),
        provenance={"source_scope": "fixture"},
    )

    result = validate_semantic_index_entry(entry)

    assert result.ok is True
    assert result.errors == ()


def test_malformed_semantic_index_entry_fails_safely():
    entry = SemanticIndexEntry(
        candidate_id=" ",
        semantic_text=" ",
        tags=("valid", ""),
        categories=["not", "a", "tuple"],
        provenance=[],
    )

    result = validate_semantic_index_entry(entry)

    assert result.ok is False
    assert error_codes(result) == [
        "candidate_id_invalid",
        "semantic_text_invalid",
        "tags_contains_invalid_value",
        "categories_invalid",
        "provenance_invalid",
    ]


def test_local_semantic_index_is_bounded_and_deterministic():
    entries = [
        SemanticIndexEntry(
            candidate_id=f"candidate-{index}",
            semantic_text=f"semantic text {index}",
            tags=(),
            categories=(),
            provenance={"ordinal": index},
        )
        for index in range(3)
    ]

    index = build_local_semantic_index(
        index_id="fixture_index",
        entries=entries,
        provenance={"source_scope": "fixture"},
        max_entries=2,
    )

    assert index.index_id == "fixture_index"
    assert [entry.candidate_id for entry in index.entries] == [
        "candidate-0",
        "candidate-1",
    ]
    assert index.provenance == {"source_scope": "fixture"}


def test_normalizers_are_local_and_bounded():
    text = normalize_semantic_text(
        ["  Ada   Lovelace ", None, " computing\nhistory "],
        max_chars=20,
    )
    labels = normalize_semantic_labels(
        [" History ", "history", "", 7, "Mathematics"],
        max_labels=2,
    )

    assert text == "Ada Lovelace computi"
    assert labels == ("history", "mathematics")


def test_invalid_index_bounds_fail_closed():
    try:
        build_local_semantic_index(
            index_id="fixture_index",
            entries=(),
            max_entries=MAX_SEMANTIC_INDEX_ENTRIES + 1,
        )
    except ValueError as exc:
        assert "outside the local index bounds" in str(exc)
    else:
        raise AssertionError("Expected invalid max_entries to fail.")


def test_semantic_text_bound_is_enforced():
    entry = SemanticIndexEntry(
        candidate_id="candidate-1",
        semantic_text="x" * (MAX_SEMANTIC_TEXT_CHARS + 1),
        tags=(),
        categories=(),
        provenance={},
    )

    result = validate_semantic_index_entry(entry)

    assert result.ok is False
    assert error_codes(result) == ["semantic_text_too_long"]


def test_no_external_calls_occur_for_runtime_semantic_index():
    source = (ROOT / "runtime" / "semantic_index.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    forbidden = (
        "requests",
        "urllib",
        "selenium",
        "playwright",
        "openai",
        "anthropic",
        "browser.search",
        "webbrowser",
        "telegram",
        "gateway",
        "smtp",
        "gmail",
        "mailgun",
        "send_email(",
        "search_web(",
        "embedding",
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_semantic_index_entry_validates()
    test_malformed_semantic_index_entry_fails_safely()
    test_local_semantic_index_is_bounded_and_deterministic()
    test_normalizers_are_local_and_bounded()
    test_invalid_index_bounds_fail_closed()
    test_semantic_text_bound_is_enforced()
    test_no_external_calls_occur_for_runtime_semantic_index()
    print("PASS semantic index structure")


if __name__ == "__main__":
    main()
