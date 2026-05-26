import os
import tempfile
from pathlib import Path


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )

    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, path)

        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return

        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass

        raise
