import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.alexis.adapters.guest_db.semantic_index import (  # noqa: E402
    GUEST_DB_SEMANTIC_INDEX_ID,
    GUEST_DB_SEMANTIC_INDEX_VERSION,
    build_guest_db_semantic_index,
    guest_record_to_semantic_index_entry,
)


def valid_record(candidate_id="guest-001"):
    return {
        "guest_id": candidate_id,
        "display_name": "Ada Lovelace",
        "title": "Computing historian",
        "expertise": "Analytical engines",
        "booking_notes": "Available for local-first runtime segments.",
        "source_updated_at": "2026-05-17T00:00:00Z",
    }


def test_guest_record_normalizes_to_semantic_index_entry():
    entry = guest_record_to_semantic_index_entry(
        valid_record(),
        source_scope="alexis_guest_canonical_csv",
    )

    assert entry is not None
    assert entry.candidate_id == "guest-001"
    assert entry.semantic_text == (
        "Ada Lovelace Computing historian Analytical engines "
        "Available for local-first runtime segments."
    )
    assert entry.tags == ("analytical engines",)
    assert entry.categories == ("computing historian",)


def test_guest_record_provenance_is_preserved():
    entry = guest_record_to_semantic_index_entry(
        valid_record(),
        source_scope="alexis_guest_canonical_csv",
    )

    assert entry is not None
    assert entry.provenance == {
        "source_scope": "alexis_guest_canonical_csv",
        "source_record_id": "guest-001",
        "source_updated_at": "2026-05-17T00:00:00Z",
        "index_id": GUEST_DB_SEMANTIC_INDEX_ID,
        "index_version": GUEST_DB_SEMANTIC_INDEX_VERSION,
    }


def test_malformed_guest_records_fail_safely():
    malformed = valid_record()
    malformed["display_name"] = " "

    entry = guest_record_to_semantic_index_entry(
        malformed,
        source_scope="alexis_guest_canonical_csv",
    )
    result = build_guest_db_semantic_index(
        rows=[valid_record("guest-001"), malformed],
        max_entries=5,
    )

    assert entry is None
    assert result.ok is False
    assert result.records_seen == 2
    assert result.records_indexed == 1
    assert result.skipped_reasons == ("malformed_guest_record",)
    assert [item.candidate_id for item in result.index.entries] == [
        "guest-001"
    ]


def test_semantic_index_build_is_bounded():
    result = build_guest_db_semantic_index(
        rows=[
            valid_record("guest-001"),
            valid_record("guest-002"),
            valid_record("guest-003"),
        ],
        max_entries=2,
    )

    assert result.ok is False
    assert result.records_seen == 3
    assert result.records_indexed == 2
    assert result.skipped_reasons == ("max_entries_reached",)
    assert [entry.candidate_id for entry in result.index.entries] == [
        "guest-001",
        "guest-002",
    ]


def test_unauthorized_source_scope_fails_closed():
    result = build_guest_db_semantic_index(
        source_scope="unauthorized",
        rows=[valid_record()],
    )

    assert result.ok is False
    assert result.index.entries == ()
    assert result.skipped_reasons == ("unauthorized_source_scope",)
    assert result.provenance["external_calls_executed"] is False


def test_index_build_provenance_records_local_behavior():
    result = build_guest_db_semantic_index(
        rows=[valid_record()],
        max_entries=5,
    )

    assert result.ok is True
    assert result.provenance == {
        "source_scope": "alexis_guest_canonical_csv",
        "operation_id": "local_semantic_index_build",
        "index_id": GUEST_DB_SEMANTIC_INDEX_ID,
        "index_version": GUEST_DB_SEMANTIC_INDEX_VERSION,
        "records_seen": 1,
        "records_indexed": 1,
        "skipped_reasons": [],
        "embedding_generated": False,
        "external_calls_executed": False,
    }


def test_no_external_calls_occur_for_guest_semantic_index():
    source = (
        ROOT / "agents" / "alexis" / "adapters" / "guest_db" /
        "semantic_index.py"
    ).read_text(encoding="utf-8")
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
    )
    assert all(term not in lowered for term in forbidden)


def main():
    test_guest_record_normalizes_to_semantic_index_entry()
    test_guest_record_provenance_is_preserved()
    test_malformed_guest_records_fail_safely()
    test_semantic_index_build_is_bounded()
    test_unauthorized_source_scope_fails_closed()
    test_index_build_provenance_records_local_behavior()
    test_no_external_calls_occur_for_guest_semantic_index()
    print("PASS guest db semantic index")


if __name__ == "__main__":
    main()
