import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semantics.transforms import (
    get_transform_metadata,
    get_transform_planning,
    resolve_transform_type,
)


CASES = {
    "Also mention liability.": "expand_scope",
    "mention liability": "expand_scope",
    "Include what this could mean legally.": "expand_scope",
    "Work in the court fight.": "expand_scope",
    "Bring in the regulatory consequences.": "expand_scope",
    "Add a line about possible challenges in court.": "expand_scope",
    "Make it into 150 words again.": "shorten",
    "Make it sharper.": "sharpen",
    "Tighten this.": "tighten",
    "Shorter and punchier.": "punchy",
    "Make it more urgent.": "urgent",
}


def main():
    failed = []

    for text, expected in CASES.items():
        got = resolve_transform_type(text)

        if got != expected:
            failed.append((text, expected, got))

    if failed:
        for text, expected, got in failed:
            print(
                f"FAIL {text!r}: expected {expected!r}, got {got!r}"
            )

        raise SystemExit(1)

    assert "artifact_type" not in get_transform_planning("shorten")
    assert get_transform_metadata("shorten")["operation"] == "TRANSFORM"

    print(f"PASS {len(CASES)} transform resolver cases")


if __name__ == "__main__":
    main()
