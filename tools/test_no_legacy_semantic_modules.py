from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOVED_MODULES = [
    ROOT / "runtime" / "semantic_attachment.py",
    ROOT / "runtime" / "semantic_continuation.py",
]
FORBIDDEN_REFERENCES = [
    "runtime.semantic_attachment",
    "runtime.semantic_continuation",
    "classify_semantic_attachment",
    "resolve_semantic_continuation",
]
SEARCH_DIRS = [
    ROOT / "agents",
    ROOT / "gateway",
    ROOT / "planner",
    ROOT / "runtime",
    ROOT / "tests",
    ROOT / "tools",
]


def main():
    failures = []

    for path in REMOVED_MODULES:
        if path.exists():
            failures.append(f"legacy module still exists: {path}")

    for directory in SEARCH_DIRS:
        for path in directory.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue

            if path == Path(__file__).resolve():
                continue

            text = path.read_text(encoding="utf-8")

            for needle in FORBIDDEN_REFERENCES:
                if needle in text:
                    rel = path.relative_to(ROOT)
                    failures.append(f"{rel} references {needle}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")

        raise SystemExit(1)

    print("PASS no legacy semantic module references")


if __name__ == "__main__":
    main()
