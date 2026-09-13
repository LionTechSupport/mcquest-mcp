from __future__ import annotations

import fnmatch
import heapq
import os
from pathlib import Path

from ..config import (
    DISCOVERY_DEFAULT_RESULTS,
    DISCOVERY_MAX_RESULTS,
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
)
from ..formatting import discovery_block, read_window_block
from ..security import (
    is_ignored_path,
    project_root,
    resolve_project_path,
    validate_readable_file,
)


def _iter_listing_matches(root: Path, pattern: str):
    """Yield relative POSIX paths matching the ``list_files`` filters.

    Applies the exact ``list_files`` contract: ignored directories pruned
    during the walk, ignored extensions skipped, ignored-path check, and
    ``fnmatch`` on the basename. Matches are produced in ``os.walk`` order
    (the caller is responsible for deterministic global ordering).
    """
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            full_path = current / filename

            if full_path.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if is_ignored_path(full_path):
                continue

            if not fnmatch.fnmatch(filename, pattern):
                continue

            yield full_path.relative_to(project_root()).as_posix()


def _iter_find_matches(root: Path, query_lower: str):
    """Yield relative POSIX paths matching the ``find_files`` filters.

    Preserves the existing ``find_files`` contract exactly (ignore extension
    skip + case-insensitive substring match on the basename; the historical
    behavior does not apply the extra ignored-path check used by
    ``list_files``).
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

            if query_lower not in filename.lower():
                continue

            full_path = current / filename

            yield full_path.relative_to(project_root()).as_posix()


def _format_aggregates(
    dir_counts: dict[str, int],
    ext_counts: dict[str, int],
) -> str:
    """Render compact deterministic aggregate metadata for discovery tools.

    ``dir_counts`` keys are top-level directories (or ``.`` for the root);
    ``ext_counts`` keys are lowercase suffixes (or ``(none)``). Both are
    sorted by key so repeated calls produce byte-identical output (D009).
    """
    parts: list[str] = []
    if dir_counts:
        parts.append(
            "dirs: " + ", ".join(
                f"{key}={dir_counts[key]}" for key in sorted(dir_counts)
            )
        )
    if ext_counts:
        parts.append(
            "exts: " + ", ".join(
                f"{key}={ext_counts[key]}" for key in sorted(ext_counts)
            )
        )
    return "; ".join(parts)


def _aggregate_dir_key(relative: str) -> str:
    """Top-level directory for aggregate metadata (``.`` for the root)."""
    parts = Path(relative).parts
    return parts[0] if len(parts) > 1 else "."


def list_files(
    path: str = ".",
    pattern: str = "*",
    max_results: int = DISCOVERY_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """
    List source files beneath a project directory (summary-first, paged).

    Returns a canonical ``[SUMMARY]`` block (total, COUNT, returned, offset,
    next_offset, has_more, truncated, aggregate directory/extension
    breakdown) followed by one explicit page of at most ``max_results``
    relative paths, ordered deterministically by ``relative_path ASC``
    (D009). ``offset`` (0-based) continues from the previous page's
    ``next_offset``; page 2 is never returned automatically (D008).

    This is read-only and excludes dependency/generated directories.
    """

    if offset < 0:
        raise ValueError("offset must be >= 0")

    page_size = min(max(max_results, 1), DISCOVERY_MAX_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if root.is_file():
        return root.relative_to(project_root()).as_posix()

    total = 0
    dir_counts: dict[str, int] = {}
    ext_counts: dict[str, int] = {}

    for relative in _iter_listing_matches(root, pattern):
        total += 1
        dir_key = _aggregate_dir_key(relative)
        dir_counts[dir_key] = dir_counts.get(dir_key, 0) + 1
        ext_key = Path(relative).suffix.lower() or "(none)"
        ext_counts[ext_key] = ext_counts.get(ext_key, 0) + 1

    page: list[str] = []
    if offset < total:
        keep = min(offset + page_size, total)
        smallest = heapq.nsmallest(keep, _iter_listing_matches(root, pattern))
        page = sorted(smallest)[offset:offset + page_size]

    root_display = (
        root.relative_to(project_root()).as_posix()
        if root != project_root()
        else "."
    )

    return discovery_block(
        tool="mcquest_list_files",
        path=path,
        items=page,
        total=total,
        offset=offset,
        fields={"ROOT": root_display, "PATTERN": pattern},
        aggregates=_format_aggregates(dir_counts, ext_counts),
        expanded=offset > 0 or max_results > DISCOVERY_DEFAULT_RESULTS,
    )


def read_file(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    """
    Read a project source file with exact line numbers.

    Unranged reads (start_line=1, end_line omitted) return a bounded
    default window (at most 250 lines) with total_lines / next_start_line /
    has_more continuation metadata. Explicitly ranged reads are honored up
    to a 1,000-line window under the absolute 16,000-character ceiling.

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

    return read_window_block(
        tool="mcquest_read_file",
        path=path,
        text=text,
        start_line=start_line,
        end_line=end_line,
    )


def find_files(
    query: str,
    path: str = ".",
    max_results: int = DISCOVERY_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """
    Find files by filename using a case-insensitive substring (summary-first,
    paged).

    Returns a canonical ``[SUMMARY]`` block (total, COUNT, returned, offset,
    next_offset, has_more, truncated, aggregate directory/extension
    breakdown) followed by one explicit page of at most ``max_results``
    relative paths, ordered deterministically by ``relative_path ASC``
    (D009). ``offset`` (0-based) continues from the previous page's
    ``next_offset``; page 2 is never returned automatically (D008).
    """

    if offset < 0:
        raise ValueError("offset must be >= 0")

    page_size = min(max(max_results, 1), DISCOVERY_MAX_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    query_lower = query.lower()

    total = 0
    dir_counts: dict[str, int] = {}
    ext_counts: dict[str, int] = {}

    for relative in _iter_find_matches(root, query_lower):
        total += 1
        dir_key = _aggregate_dir_key(relative)
        dir_counts[dir_key] = dir_counts.get(dir_key, 0) + 1
        ext_key = Path(relative).suffix.lower() or "(none)"
        ext_counts[ext_key] = ext_counts.get(ext_key, 0) + 1

    page: list[str] = []
    if offset < total:
        keep = min(offset + page_size, total)
        smallest = heapq.nsmallest(keep, _iter_find_matches(root, query_lower))
        page = sorted(smallest)[offset:offset + page_size]

    root_display = (
        root.relative_to(project_root()).as_posix()
        if root != project_root()
        else "."
    )

    return discovery_block(
        tool="mcquest_find_files",
        path=path,
        items=page,
        total=total,
        offset=offset,
        fields={"ROOT": root_display, "QUERY": query},
        aggregates=_format_aggregates(dir_counts, ext_counts),
        expanded=offset > 0 or max_results > DISCOVERY_DEFAULT_RESULTS,
    )