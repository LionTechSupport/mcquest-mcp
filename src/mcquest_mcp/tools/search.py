from __future__ import annotations

import re
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_SEARCH_RESULTS,
)
from ..formatting import truncate
from ..security import is_ignored_path, project_root, resolve_project_path


def search_text(
    pattern: str,
    path: str = "frontend/src",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    context_lines: int = 1,
    max_results: int = 200,
) -> str:
    """
    Search source files with a regex and return exact file/line evidence.

    Results include line numbers and surrounding context.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    context_lines = min(max(context_lines, 0), 5)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    flags = 0 if case_sensitive else re.IGNORECASE

    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc

    results: list[str] = []
    match_count = 0

    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            if match_count >= max_results:
                break

            if Path(filename).suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if not __import__("fnmatch").fnmatch(filename, file_pattern):
                continue

            file_path = current / filename

            if is_ignored_path(file_path):
                continue

            try:
                if file_path.stat().st_size > 2_000_000:
                    continue

                lines = file_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()

            except OSError:
                continue

            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue

                match_count += 1

                relative = file_path.relative_to(project_root()).as_posix()

                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)

                results.append(
                    f"{relative}:{index + 1}\n"
                    + "\n".join(
                        f"  {i + 1}: {lines[i]}"
                        for i in range(start, end)
                    )
                    + "\n"
                )

                if match_count >= max_results:
                    break

        if match_count >= max_results:
            break

    if not results:
        return (
            f"PATTERN: {pattern}\n"
            f"PATH: {path}\n"
            "MATCHES: 0"
        )

    return truncate(
        f"PATTERN: {pattern}\n"
        f"PATH: {path}\n"
        f"MATCHES RETURNED: {match_count}\n\n"
        + "\n".join(results)
    )