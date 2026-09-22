"""Lexical UI-text candidate finder (V0.8, DEC-015/DEC-032).

Composes the approved ``mcquest_find_strings`` lexical scanner
(:mod:`mcquest_mcp.tools.strings`) -- V0.8 adds no extractor (P016/DEC-019).
Candidates are quoted string literals and template-literal static segments
in ``.js``/``.jsx``/``.ts``/``.tsx`` sources. Classification is lexical-only
per DEC-032: a literal with no ASCII letter (``[A-Za-z]``) is ``decorative``;
a literal with at least one ASCII letter is ``unknown`` while the
brand-token list and admin-marker list remain unrecorded.
``localizable``, ``brand``, and ``admin-only`` are never emitted and are
never inferred by elimination. JSX text nodes are not extracted, comments
are not a candidate source (the scanner has no comment awareness, so a
quoted literal on a comment line may appear incidentally), and a zero
result never proves absence.
"""

from __future__ import annotations

import heapq
import re
from pathlib import Path

from ..config import (
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path
from .strings import SOURCE_SUFFIXES, _scan_line, _source_files

# The approved mcquest_find_strings scanner's own default minimum length;
# DEC-032 exposes no separate min_length input for this tool.
_SCAN_MIN_LENGTH = 1

_ASCII_LETTER = re.compile(r"[A-Za-z]")

_DECORATIVE_REASON = "no ASCII letter ([A-Za-z]); DEC-032 letter-absence branch"
_UNKNOWN_REASON = (
    "brand token list and admin marker list are not recorded (DEC-032); "
    "classification unresolved"
)


def _classify(value: str) -> tuple[str, str, str]:
    """Return (classification, confidence, reason) for one literal (DEC-032)."""
    if _ASCII_LETTER.search(value):
        return "unknown", "medium", _UNKNOWN_REASON
    return "decorative", "high", _DECORATIVE_REASON


def find_ui_text(
    path: str = ".",
    file_pattern: str = "*",
    max_results: int = 50,
    offset: int = 0,
    classify: bool = True,
) -> str:
    """
    Find lexical UI-text candidates in JS/TS/JSX/TSX sources (DEC-015).

    Summary-first and explicitly paged: returns a canonical ``[SUMMARY]``
    block (total, files_affected, returned, offset, next_offset, has_more,
    truncated, collection_complete, budget) followed by one page of at most
    ``max_results`` ``file:line: "snippet"`` evidence rows ordered
    deterministically by (relative_path ASC, line ASC, col ASC). Candidates
    are quoted string literals and template-literal static segments
    extracted by the approved ``mcquest_find_strings`` scanner
    (``src/mcquest_mcp/tools/strings.py``); V0.8 adds no extractor. JSX
    text nodes are NOT extracted, comments are not a candidate source (the
    scanner has no comment awareness, so a quoted literal on a comment line
    may appear incidentally), and a zero result never proves absence.

    Classification is lexical-only per DEC-032: a literal with no ASCII
    letter (``[A-Za-z]``) is ``decorative`` (confidence ``high``); a
    literal with at least one ASCII letter is ``unknown`` (confidence
    ``medium``) with a reason naming the missing brand-token list and
    admin-marker list. ``localizable``/``brand``/``admin-only`` are NOT
    EMITTABLE and are never inferred by elimination. When ``classify`` is
    false, rows carry only the location and snippet and the summary is
    unchanged.

    Pass 1 performs an honest counting pass over the in-scope candidate
    evidence, so ``total`` is the authoritative full count and
    ``collection_complete`` is always true (DEC-016 full-scan two-pass);
    pagination is explicit only (``offset``/``next_offset``/``has_more``).
    ``total`` is the known count, NOT the delivered count.
    """
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    # Contract §2.0: an explicitly empty path scans the project root, same
    # as the omitted/default case; every other invalid path still rejects
    # through the shared resolver (DEC-027).
    if not path:
        path = "."

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if root.is_file():
        if is_ignored_path(root):
            raise ValueError(f"File is inside an ignored directory: {path}")
        if (
            root.suffix.lower() not in SOURCE_SUFFIXES
            or root.suffix.lower() in IGNORED_EXTENSIONS
        ):
            raise ValueError(f"Unsupported file type: {path}")
        try:
            if root.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(
                    f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {path}"
                )
            files: list[Path] = [root]
        except OSError:
            raise ValueError(f"Unreadable file: {path}")
    else:
        # Contract §2.0: an ignored directory input is rejected with
        # ValueError, not silently scanned to an empty result (mirrors the
        # single-file branch above and the shared path-validation
        # conventions in security.py / component_inventory.py).
        if is_ignored_path(root):
            raise ValueError(f"Directory is inside an ignored directory: {path}")
        files = list(_source_files(root, file_pattern))

    # Pass 1: honest full count over the in-scope candidate evidence so
    # total / files_affected are authoritative and collection_complete is
    # true (DEC-016 full-scan two-pass model).
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
            for col, value in _scan_line(line, _SCAN_MIN_LENGTH):
                file_hits.append((relative, line_no, col, value))
        if file_hits:
            total += len(file_hits)
            files_affected += 1
            records.extend(file_hits)

    # Pass 2: bounded, deterministic page window over (relative, line, col)
    # (04-V0.8-TEST-PLAN.md section 2.3 sort key).
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

    rendered: list[str] = []
    for relative, line_no, _col, value in page:
        location = f'{relative}:{line_no}: "{value}"'
        if classify:
            label, confidence, reason = _classify(value)
            rendered.append(
                f"{location} [classification: {label}; "
                f"confidence: {confidence}; reason: {reason}]"
            )
        else:
            rendered.append(location)

    return search_block(
        tool="mcquest_find_ui_text",
        path=path,
        items=rendered,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields={"PATH": path, "max_results": max_results},
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )

