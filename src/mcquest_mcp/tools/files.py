from __future__ import annotations

import fnmatch
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
)
from ..formatting import numbered_lines, truncate
from ..security import (
    is_ignored_path,
    project_root,
    resolve_project_path,
    validate_readable_file,
)


def list_files(
    path: str = ".",
    pattern: str = "*",
    max_results: int = 200,
) -> str:
    """
    List source files beneath a project directory.

    This is read-only and excludes dependency/generated directories.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if root.is_file():
        return root.relative_to(project_root()).as_posix()

    results: list[str] = []

    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            if len(results) >= max_results:
                break

            full_path = current / filename

            if full_path.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if is_ignored_path(full_path):
                continue

            if not fnmatch.fnmatch(filename, pattern):
                continue

            results.append(
                full_path.relative_to(project_root()).as_posix()
            )

        if len(results) >= max_results:
            break

    results.sort()

    output = "\n".join(results)

    return truncate(
        f"ROOT: {root.relative_to(project_root()) if root != project_root() else '.'}\n"
        f"PATTERN: {pattern}\n"
        f"COUNT: {len(results)}\n\n"
        + output
    )


def read_file(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    """
    Read a project source file with exact line numbers.

    Use this instead of requesting an entire directory or project.
    """

    file_path = validate_readable_file(path)

    if file_path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(
            f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {path}"
        )

    text = file_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    return numbered_lines(
        text,
        start_line=start_line,
        end_line=end_line,
    )


def find_files(
    query: str,
    path: str = ".",
    max_results: int = 200,
) -> str:
    """
    Find files by filename using a case-insensitive substring or glob.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    query_lower = query.lower()

    results: list[str] = []

    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            if len(results) >= max_results:
                break

            if Path(filename).suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if query_lower not in filename.lower():
                continue

            full_path = current / filename

            results.append(
                full_path.relative_to(project_root()).as_posix()
            )

        if len(results) >= max_results:
            break

    results.sort()

    return truncate(
        f"QUERY: {query}\n"
        f"COUNT: {len(results)}\n\n"
        + "\n".join(results)
    )