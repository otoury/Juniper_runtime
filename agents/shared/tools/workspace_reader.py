# agents/shared/tools/workspace_reader.py

from __future__ import annotations

from pathlib import Path


def read_optional_text_file(
    *,
    workspace: Path,
    filename: str,
    max_chars: int = 3000,
) -> str:
    path = workspace / filename

    if not path.exists():
        return ""

    if not path.is_file():
        return ""

    try:
        return path.read_text(
            encoding="utf-8"
        )[:max_chars]
    except Exception:
        return ""