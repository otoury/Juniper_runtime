# runtime/components/workspace.py

from __future__ import annotations

from pathlib import Path


def read_workspace_file(
    *,
    workspace: Path,
    filename: str,
    max_chars: int = 3000,
) -> str:
    path = workspace / filename

    if not path.exists() or not path.is_file():
        return ""

    try:
        return path.read_text(encoding="utf-8")[:max_chars]
    except Exception:
        return ""


def build_workspace_components(
    *,
    workspace: Path,
    filenames: list[str] | None,
) -> list[str]:
    blocks: list[str] = []

    for filename in filenames or []:
        content = read_workspace_file(
            workspace=workspace,
            filename=filename,
        )

        if content:
            blocks.append(f"{filename}:\n{content}")

    return blocks
