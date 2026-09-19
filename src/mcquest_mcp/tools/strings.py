"""Lexical JS/TS string-literal inventory (V0.7 Phase 2, DEC-008)."""

from __future__ import annotations

import fnmatch
import heapq
import os
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

# Identical supported-source set to find_imports / find_usages / the audit
# walk (V0.7 Phase 2 proposal section 7.4); no broad-language expansion.
SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}

MIN_LENGTH_MAX = 100


def _source_files(root: Path, file_pattern: str):
    """Yield supported JS/TS source files under root (policy + size guard).

    Applies the exact legacy walk used by imports._source_files and
    search._iter_search_files: ignored directories pruned, ignored
    extensions skipped, fnmatch on the basename, ignored-path check, and
    the MAX_FILE_BYTES file-size guard.
    """
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            path = current / filename

            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue

            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if not fnmatch.fnmatch(filename, file_pattern):
                continue

            if is_ignored_path(path):
                continue

            try:
                # Phase D input-side guard: skip oversized files the same way
                # search_text / find_imports / find_usages already do.
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue

            yield path


def _quoted_run(line: str, start: int) -> tuple[str | None, int]:
    """Scan a maximal single-line single- or double-quoted run.

    Returns ``(value, index_after_closing_quote)`` on a terminated run, or
    ``(None, len(line))`` when the run is unterminated on this line (the
    remainder of the line is consumed as part of the failed run and nothing
    is emitted; multi-line literals are out of v1 scope, proposal 7.8).
    Backslash escapes are honored so an escaped delimiter never terminates.
    value is the raw content without the surrounding quotes (escapes kept
    verbatim).
    """
    delimiter = line[start]
    n = len(line)
    i = start + 1
    while i < n:
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == delimiter:
            return line[start + 1 : i], i + 1
        i += 1
    return None, n


def _scan_expr(
    line: str,
    start: int,
    min_length: int,
    items: list[tuple[int, str]],
) -> tuple[int, int]:
    """Scan a template expression body; return (next_index, close_index).

    close_index is the 0-based index of the matching closing brace (used as
    the reported column of the following static segment, proposal 7.1).
    Expression characters contribute no literal text, but nested quoted
    literals (single, double, backtick templates) remain independently
    discoverable inside the expression.
    """
    n = len(line)
    depth = 1
    i = start
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1, i
        elif ch in "'\"":
            value, nxt = _quoted_run(line, i)
            if value is not None and len(value) >= min_length:
                items.append((i + 1, value))
            i = nxt
            continue
        elif ch == "`":
            i = _scan_template(line, i, min_length, items)
            continue
        i += 1
    # Unterminated expression (e.g. a multi-line template in v1): consume the
    # remainder of the line; no error, no items (proposal 7.8).
    return n, n - 1


def _scan_template(
    line: str,
    start: int,
    min_length: int,
    items: list[tuple[int, str]],
) -> int:
    """Scan a template literal opening at start; return index after it.

    Static segments are candidates (each emitted as its own literal item);
    template expressions contribute no literal text and keep nested quoted
    literals independently discoverable; empty segments are never emitted;
    escaped backticks never terminate; col of a head segment is the
    backtick column and of a post-expression segment is the brace column.
    """
    n = len(line)
    i = start + 1
    segment_start = i
    segment_col = start
    while i < n:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            value = line[segment_start:i]
            if value and len(value) >= min_length:
                items.append((segment_col + 1, value))
            return i + 1
        if line.startswith("${", i):
            value = line[segment_start:i]
            if value and len(value) >= min_length:
                items.append((segment_col + 1, value))
            i, segment_col = _scan_expr(line, i + 2, min_length, items)
            segment_start = i
            continue
        i += 1
    # Unterminated template (multi-line template in v1): consume the line.
    return n


def _scan_line(line: str, min_length: int) -> list[tuple[int, str]]:
    """Yield (col, value) literal items found in one source line.

    col is the 1-based column of the item's opening delimiter (proposal
    7.1). Literals inside comments may be returned -- Phase 2 is lexical,
    not AST-based, and no comment parser is added (proposal 7).
    """
    items: list[tuple[int, str]] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in "'\"":
            value, nxt = _quoted_run(line, i)
            if value is not None and len(value) >= min_length:
                items.append((i + 1, value))
            i = nxt
        elif ch == "`":
            i = _scan_template(line, i, min_length, items)
        else:
            i += 1
    return items


def find_strings(
    path: str = "frontend/src",
    file_pattern: str = "*",
    min_length: int = 1,
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """
    Inventory quoted string literals in JS/TS source with exact positions.

    Summary-first and explicitly paged: returns a canonical ``[SUMMARY]``
    block (total, files_affected, returned, offset, next_offset, has_more,
    truncated, collection_complete, budget) followed by one page of at most
    ``max_results`` ``path:line:col: "value"`` evidence lines ordered
    deterministically by (relative_path ASC, line ASC, col ASC). total is
    the honest two-pass count of matching literals within the bounded
    repository scope, independent of page size. This is a lexical
    literal-inventory primitive, not a hardcoded-UI-string detector.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if min_length < 0 or min_length > MIN_LENGTH_MAX:
        raise ValueError(f"min_length must be in 0..{MIN_LENGTH_MAX}")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if root.is_file():
        if is_ignored_path(root):
            raise ValueError(f"File is inside an ignored directory: {path}")
        files: list[Path] = []
        if (
            root.suffix.lower() in SOURCE_SUFFIXES
            and root.suffix.lower() not in IGNORED_EXTENSIONS
        ):
            try:
                if root.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError(
                        f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {path}"
                    )
                files = [root]
            except OSError:
                raise ValueError(f"Unreadable file: {path}")
    else:
        files = list(_source_files(root, file_pattern))

    # Pass 1: authoritative full count (approved two-pass full-count) so
    # total / files_affected are truthful and collection_complete is true.
    records: list[tuple[str, int, int, str]] = []
    total = 0
    files_affected = 0

    for file_path in files:
        relative = file_path.relative_to(project_root()).as_posix()
        try:
            lines = file_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            continue
        file_hits: list[tuple[str, int, int, str]] = []
        for line_no, line in enumerate(lines, start=1):
            for col, value in _scan_line(line, min_length):
                file_hits.append((relative, line_no, col, value))
        if file_hits:
            total += len(file_hits)
            files_affected += 1
            records.extend(file_hits)

    # Pass 2: bounded, deterministic page window over (relative, line, col).
    page_size = min(max_results, max(total - offset, 0))
    page: list[tuple[str, int, int, str]] = []
    if page_size > 0:
        needed = min(offset + page_size, total)
        smallest = heapq.nsmallest(
            needed,
            records,
            key=lambda record: (record[0], record[1], record[2]),
        )
        page = smallest[offset : offset + page_size]

    rendered = [
        f"{relative}:{line_no}:{col}: \"{value}\""
        for relative, line_no, col, value in page
    ]

    return search_block(
        tool="mcquest_find_strings",
        path=path,
        items=rendered,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields={"PATH": path, "max_results": max_results},
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )