from __future__ import annotations

import fnmatch
import heapq
import os
import re
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
    SEARCH_CONTEXT_CAP_CODE,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path


def _iter_search_files(root: Path, file_pattern: str):
    """Yield matching source files under ``root`` (policy + size guard).

    Applies the exact legacy ``search_text`` walk: ignored directories pruned,
    ignored extensions skipped, ``fnmatch`` on the basename, ignored-path
    check, and the ``MAX_FILE_BYTES`` file-size guard.
    """
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            if Path(filename).suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if not fnmatch.fnmatch(filename, file_pattern):
                continue

            file_path = current / filename

            if is_ignored_path(file_path):
                continue

            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            yield file_path


def _read_lines(file_path: Path) -> list[str]:
    try:
        return file_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return []


def _build_snippet(
    relative: str,
    line_no: int,
    lines: list[str],
    context_lines: int,
) -> str:
    """Render one match as a ``relative:line`` header plus context lines.

    Context lines use the existing ``  {absolute_line_no}: {content}`` shape;
    the shared ``search_block`` renderer applies the 200-char per-line clip.
    """
    index = line_no - 1
    start = max(0, index - context_lines)
    end = min(len(lines), index + context_lines + 1)
    context = "\n".join(
        f"  {i + 1}: {lines[i]}"
        for i in range(start, end)
    )
    return f"{relative}:{line_no}\n{context}"


def search_text(
    pattern: str,
    path: str = "frontend/src",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    context_lines: int = 1,
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """
    Search source files with a regex and return exact file/line evidence.

    Summary-first and explicitly paged (D008/D009/D016): returns a canonical
    ``[SUMMARY]`` block (total, files_affected, returned, offset, next_offset,
    has_more, truncated, collection_complete, budget) followed by one page of
    at most ``max_results`` snippet results ordered deterministically by
    ``(relative_path ASC, line ASC)``. Results never exceed the 4,000-char
    normal presentation budget (default calls) or the 16,000-char absolute
    ceiling (explicit pages); every snippet line is clipped to 200 chars.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    context_lines = min(max(context_lines, 0), SEARCH_CONTEXT_CAP_CODE)

    if offset < 0:
        raise ValueError("offset must be >= 0")

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    flags = 0 if case_sensitive else re.IGNORECASE

    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc

    # Pass 1: authoritative full count (approved two-pass full-count) so
    # ``total`` / ``files_affected`` are truthful and collection_complete is
    # always true.
    total = 0
    files_affected = 0

    for file_path in _iter_search_files(root, file_pattern):
        lines = _read_lines(file_path)
        matches = sum(1 for line in lines if regex.search(line))
        if matches:
            total += matches
            files_affected += 1

    # Pass 2: bounded, deterministic page window.
    page_size = min(max_results, max(total - offset, 0))
    page: list[tuple[str, int]] = []
    if page_size > 0:
        def iter_locations():
            for file_path in _iter_search_files(root, file_pattern):
                relative = file_path.relative_to(project_root()).as_posix()
                for index, line in enumerate(
                    _read_lines(file_path),
                    start=1,
                ):
                    if regex.search(line):
                        yield (relative, index)

        needed = min(offset + page_size, total)
        smallest = heapq.nsmallest(needed, iter_locations())
        page = sorted(smallest)[offset : offset + page_size]

    # Build snippet items; cache the rare page file contents.
    items: list[str] = []
    cache: dict[str, list[str]] = {}
    for relative, line_no in page:
        if relative not in cache:
            cache[relative] = _read_lines(resolve_project_path(relative))
        items.append(_build_snippet(relative, line_no, cache[relative], context_lines))

    return search_block(
        tool="mcquest_search",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields={"PATTERN": pattern, "PATH": path},
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )