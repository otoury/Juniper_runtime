import json
from pathlib import Path

SEMANTIC_TRANSFORM_PATH = Path(
    "config/semantic/transforms.json"
)
LEGACY_TRANSFORM_PATH = Path(
    "config/transforms.json"
)
AGENTS_SHARED_TRANSFORMS_DIR = Path(
    "agents/shared/transforms"
)
RETIRED_COMPAT_TRANSFORM_PATHS = (
    LEGACY_TRANSFORM_PATH,
    SEMANTIC_TRANSFORM_PATH,
)

_transform_cache = None


def _load_transform_file(path: Path) -> dict:
    with path.open(
        encoding="utf-8"
    ) as f:
        return json.load(f)


def _load_transform_directory(folder: Path) -> dict:
    registry = {}

    if not folder.exists():
        return registry

    for path in sorted(folder.glob("*.json")):
        registry.update(
            _load_transform_file(path)
        )

    return registry


def _load_transform_registry() -> dict:
    registry = {}

    for path in RETIRED_COMPAT_TRANSFORM_PATHS:
        if path.exists():
            registry.update(
                _load_transform_file(path)
            )

    registry.update(
        _load_transform_directory(AGENTS_SHARED_TRANSFORMS_DIR)
    )

    return registry


def load_transform_registry():

    global _transform_cache

    if _transform_cache is None:
        _transform_cache = _load_transform_registry()

    return _transform_cache


def resolve_transform_type(
    text: str,
) -> str | None:

    lowered = text.lower()

    registry = load_transform_registry()
    best_match = None
    best_score = 0

    for transform_type, config in registry.items():

        for alias in config["aliases"]:

            if alias.lower() in lowered:
                score = len(alias)

                if score > best_score:
                    best_score = score
                    best_match = transform_type

    return best_match

def get_transform_planning(
    transform_type: str,
):
    registry = load_transform_registry()

    config = registry.get(
        transform_type,
        {},
    )

    return config.get(
        "planning",
        {},
    )


def get_transform_metadata(
    transform_type: str,
):
    registry = load_transform_registry()

    config = registry.get(
        transform_type,
        {},
    )

    return {
        key: value
        for key, value in config.items()
        if key not in {"aliases", "planning"}
    }
