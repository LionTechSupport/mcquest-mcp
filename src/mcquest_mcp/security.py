from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_PROJECT_ROOT, IGNORED_DIRECTORIES


def project_root() -> Path:
    return DEFAULT_PROJECT_ROOT


def resolve_project_path(relative_path: str) -> Path:
    """
    Resolve a path while preventing directory traversal outside MCQuest.
    """

    if not relative_path:
        raise ValueError("Path cannot be empty.")

    root = project_root()
    candidate = (root / relative_path).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Path escapes MCQuest project root: {relative_path}"
        ) from exc

    return candidate


def is_ignored_path(path: Path) -> bool:
    """
    Return True when any path component is a known generated/dependency directory.
    """

    return any(
        part in IGNORED_DIRECTORIES
        for part in path.parts
    )


def validate_readable_file(relative_path: str) -> Path:
    path = resolve_project_path(relative_path)

    if not path.exists():
        raise FileNotFoundError(relative_path)

    if not path.is_file():
        raise ValueError(f"Not a file: {relative_path}")

    if is_ignored_path(path):
        raise ValueError(f"File is inside an ignored directory: {relative_path}")

    return path