import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.artifacts.extractors import normalize_artifact_response
from runtime.quality.validators import validate_text_constraints


def test_subject_prefixed_email_wrapper_normalizes_to_body():
    raw = (
        '{'
        '"email": "Subject: Join Our Discussion on AI Regulation\\n\\n'
        'Hi Dr. Chen,\\n\\nCan we book you for a live hit next week?\\n\\n'
        'Best,\\nAlexis"'
        '}'
    )
    normalized = normalize_artifact_response(
        artifact_type="email_draft",
        response=raw,
    )
    assert normalized.extracted_content.startswith("Hi Dr. Chen,")
    assert not normalized.extracted_content.startswith("Subject:")


def test_nested_email_draft_body_wrapper_normalizes_to_body():
    raw = (
        '{'
        '"email_draft": {"body": "Hi Dr. Jain,\\n\\nCan you join us Tuesday?\\n\\nBest,\\nAlexis"}'
        '}'
    )
    normalized = normalize_artifact_response(
        artifact_type="email_draft",
        response=raw,
    )
    assert normalized.extracted_content.startswith("Hi Dr. Jain,")
    assert "email_draft: body:" not in normalized.extracted_content


def test_validator_stays_strict_for_raw_subject_prefixed_text():
    content = (
        "Subject: Join Our Discussion on AI Regulation\n\n"
        "Hi Dr. Chen,\n\nCan we book you?\n\nBest,\nAlexis"
    )
    result = validate_text_constraints(
        artifact_type="email_draft",
        content=content,
    )
    assert not result.ok
    assert any(v.code == "invalid_start" for v in result.violations)


def main():
    test_subject_prefixed_email_wrapper_normalizes_to_body()
    test_nested_email_draft_body_wrapper_normalizes_to_body()
    test_validator_stays_strict_for_raw_subject_prefixed_text()
    print("PASS email_draft normalization")


if __name__ == "__main__":
    main()
