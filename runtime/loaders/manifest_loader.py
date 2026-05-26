# runtime/loaders/manifest_loader.py

import json
from pathlib import Path


def read_text(path: Path) -> str:
    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8").strip()


def load_manifest(folder: Path) -> dict:
    path = folder / "manifest.json"

    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))
