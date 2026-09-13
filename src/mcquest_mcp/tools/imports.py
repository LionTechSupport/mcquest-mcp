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
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path


IMPORT_PATTERNS = [
    re.compile(
        r"""^\s*import\s+.*?\s+from\s+['"]([^'"]+)['"]""",
        re.MULTILINE,
    ),
    re.compile(
        r"""^\s*import\s+['"]([^'"]+)['"]""",
        re.MULTILINE,
    ),
    re.compile(
        r"""^\s*(?:export\s+)?(?:type\s+)?\{.*?\}\s+from\s+['"]([^'"]+)['"]""",
        re.MULTILINE,
    ),
]


def _source_files(root: Path):
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            path = current / filename

            if path.suffix.lower() not in {
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
            }:
                continue

            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if is_ignored_path(path):
                continue

            try:
                # Phase D input-side guard: skip oversized files the same way
                # search_text / search_docs already do (audit finding G7).
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            yield path


def _read_lines(file_path: Path) -> list[str]:
    try:
        return file_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return []


def _load_page_lines(page: list[tuple[str, int]]) -> dict[str, list[str]]:
    """Read and cache file contents for the (relative, line) page items."""
    cache: dict[str, list[str]] = {}
    for relative, _line_number in page:
        if relative not in cache:
            cache[relative] = _read_lines(resolve_project_path(relative))
    return cache


def _match_import(line: str, target_lower: str) -> bool:
    for pattern in IMPORT_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        module = match.group(1)
        if target_lower in module.lower():
            return True
    return False


def find_imports(
    target: str,
    path: str = "frontend/src",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """
    Find ES module imports referencing a component/module.

    Summary-first and explicitly paged: returns a canonical ``[SUMMARY]``
    block (total, files_affected, returned, offset, next_offset, has_more,
    truncated, budget) followed by one page of at most ``max_results``
    ``path:line: import`` lines ordered deterministically by
    ``(relative_path ASC, line ASC)``. This is a textual import analysis,
    not a full TypeScript AST.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    root = resolve_project_path(path)
    if not root.exists():
        raise FileNotFoundError(path)

    target_lower = target.lower()

    # Pass 1: authoritative full count (approved two-pass full-count).
    total = 0
    files_affected = 0
    locs: list[tuple[str, int]] = []

    for file_path in _source_files(root):
        relative = file_path.relative_to(project_root()).as_posix()
        lines = _read_lines(file_path)
        file_hits = [
            (relative, n)
            for n, line in enumerate(lines, start=1)
            if _match_import(line, target_lower)
        ]
        if file_hits:
            total += len(file_hits)
            files_affected += 1
            locs.extend(file_hits)

    # Pass 2: bounded, deterministic page window.
    page_size = min(max_results, max(total - offset, 0))
    page: list[tuple[str, int]] = []
    if page_size > 0:
        needed = min(offset + page_size, len(locs))
        smallest = heapq.nsmallest(needed, locs)
        page = sorted(smallest)[offset : offset + page_size]

    cache = _load_page_lines(page)
    items = [
        f"{rel}:{line_no}: {cache[rel][line_no - 1].strip()}"
        for rel, line_no in page
    ]

    return search_block(
        tool="mcquest_find_imports",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields={"TARGET": target, "PATH": path},
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )


def find_usages(
    symbol: str,
    path: str = "frontend/src",
    file_pattern: str = "*",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """
    Find textual references to a symbol across source files.

    Summary-first and explicitly paged: returns a canonical ``[SUMMARY]``
    block (total, files_affected, returned, offset, next_offset, has_more,
    truncated, budget) followed by one page of at most ``max_results``
    matching lines ordered deterministically by (relative_path ASC, line ASC).
    Searches identifiers rather than arbitrary substrings.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    root = resolve_project_path(path)
    if not root.exists():
        raise FileNotFoundError(path)

    try:
        regex = re.compile(rf"\b{re.escape(symbol)}\b")
    except re.error as exc:
        raise ValueError(str(exc)) from exc

    # Pass 1: authoritative full count (approved two-pass full-count).
    total = 0
    files_affected = 0
    locs: list[tuple[str, int]] = []

    for file_path in _source_files(root):
        if not fnmatch.fnmatch(file_path.name, file_pattern):
            continue
        relative = file_path.relative_to(project_root()).as_posix()
        lines = _read_lines(file_path)
        file_hits = [
            (relative, n)
            for n, line in enumerate(lines, start=1)
            if regex.search(line)
        ]
        if file_hits:
            total += len(file_hits)
            files_affected += 1
            locs.extend(file_hits)

    # Pass 2: bounded, deterministic page window.
    page_size = min(max_results, max(total - offset, 0))
    page: list[tuple[str, int]] = []
    if page_size > 0:
        needed = min(offset + page_size, len(locs))
        smallest = heapq.nsmallest(needed, locs)
        page = sorted(smallest)[offset : offset + page_size]

    cache = _load_page_lines(page)
    items = [
        f"{rel}:{line_no}: {cache[rel][line_no - 1].strip()}"
        for rel, line_no in page
    ]

    return search_block(
        tool="mcquest_find_usages",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields={"SYMBOL": symbol, "PATH": path},
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )