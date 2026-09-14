from __future__ import annotations

import re
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_SEARCH_RESULTS,
)
from ..formatting import audit_block
from ..security import is_ignored_path, project_root, resolve_project_path


AUDIT_PATTERNS = {
    "viewport-width": re.compile(
        r"(?:w-screen|100vw|w-\[calc\(100vw)",
        re.IGNORECASE,
    ),
    "large-min-width": re.compile(
        r"min-w-\[(?:[3-9]\d{2}|[1-9]\d{3,})px\]",
        re.IGNORECASE,
    ),
    "large-fixed-width": re.compile(
        r"w-\[(?:[3-9]\d{2}|[1-9]\d{3,})px\]",
        re.IGNORECASE,
    ),
    "nowrap": re.compile(
        r"whitespace-nowrap",
        re.IGNORECASE,
    ),
    "negative-horizontal-margin": re.compile(
        r"(?:-mx-|-[mlr]-)",
        re.IGNORECASE,
    ),
    "horizontal-transform": re.compile(
        r"translate-x-",
        re.IGNORECASE,
    ),
    "negative-position": re.compile(
        r"(?:right|left)-\[-",
        re.IGNORECASE,
    ),
    "overflow-x": re.compile(
        r"overflow-x-(?:auto|scroll|hidden|clip)",
        re.IGNORECASE,
    ),
    "min-width": re.compile(
        r"(?:min-width|min-w-)",
        re.IGNORECASE,
    ),
    "fixed-position": re.compile(
        r"\bfixed\b",
        re.IGNORECASE,
    ),
    "sticky-position": re.compile(
        r"\bsticky\b",
        re.IGNORECASE,
    ),
}

AUDIT_CATEGORIES = tuple(AUDIT_PATTERNS.keys())
"""Canonical ordered category enum (fixed set, deterministic ordering)."""

DEFAULT_MAX_RESULTS_PER_CATEGORY = 100
DEFAULT_SAMPLES_PER_CATEGORY = 2


def _files(root: Path):
    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            path = current / filename

            if path.suffix.lower() in {
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".css",
            }:
                if path.suffix.lower() not in IGNORED_EXTENSIONS:
                    if not is_ignored_path(path):
                        yield path


def _select_category(category: str) -> dict[str, re.Pattern]:
    """Validate a single ``category`` value against the fixed enum."""
    if category not in AUDIT_PATTERNS:
        raise ValueError(
            "Unknown category: "
            + category
            + ". Valid categories: "
            + ", ".join(AUDIT_CATEGORIES)
            + "."
        )
    return {category: AUDIT_PATTERNS[category]}


def _select_categories(categories: str) -> dict[str, re.Pattern]:
    """Resolve the legacy comma-separated ``categories`` selector."""
    if categories.strip().lower() == "all":
        return AUDIT_PATTERNS

    requested = {
        item.strip()
        for item in categories.split(",")
        if item.strip()
    }

    unknown = requested - AUDIT_PATTERNS.keys()

    if unknown:
        raise ValueError(
            "Unknown categories: "
            + ", ".join(sorted(unknown))
        )

    # Deterministic canonical order (D009), regardless of input order.
    return {
        name: AUDIT_PATTERNS[name]
        for name in AUDIT_CATEGORIES
        if name in requested
    }


def _collect_matches(
    root: Path,
    regex: re.Pattern,
    cap: int,
) -> list[str]:
    """Collect up to ``cap`` matches for one category (existing semantics).

    Walks the same file set as the legacy implementation: ignored directories
    and extensions pruned, ignored paths skipped, TS/TSX/JS/JSX/CSS files
    only, exact ``relative:line: line`` evidence lines in walk order.
    """
    matches: list[str] = []

    for file_path in _files(root):
        try:
            lines = file_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            continue

        for line_number, line in enumerate(lines, start=1):
            if not regex.search(line):
                continue

            relative = file_path.relative_to(
                project_root()
            ).as_posix()

            matches.append(
                f"{relative}:{line_number}: "
                f"{line.strip()}"
            )

            if len(matches) >= cap:
                return matches

    return matches


def pattern_audit(
    path: str = "frontend/src",
    categories: str = "all",
    max_results_per_category: int = DEFAULT_MAX_RESULTS_PER_CATEGORY,
    category: str = "",
) -> str:
    """Run a predefined responsive/layout audit, summary-first and bounded.

    The default response is a bounded summary under the 4,000-character normal
    presentation budget: a ``[SUMMARY]`` block (category_count, matches,
    samples_shown, has_more, truncated, collection_complete, budget) followed
    by the ``[CATEGORY COUNTS]`` table for every selected category and up to
    ``DEFAULT_SAMPLES_PER_CATEGORY`` sample matches per category. The default
    represents all categories without dumping their full match detail.

    The additive ``category`` parameter is the explicit single-category
    expansion: pass one enum value to list up to ``max_results_per_category``
    matches for that category under the 16,000-character ceiling.
    ``categories`` remains the legacy selector ('all' or a comma-separated
    subset); when ``category`` is provided it wins. Both are validated against
    the fixed category enum. Output is deterministic (fixed category order),
    read-only, and confined to the project root.
    """

    max_results_per_category = min(
        max(max_results_per_category, 1),
        MAX_SEARCH_RESULTS,
    )

    expanded = bool(category.strip()) or (
        max_results_per_category > DEFAULT_MAX_RESULTS_PER_CATEGORY
    )

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if category.strip():
        selected = _select_category(category.strip())
    else:
        selected = _select_categories(categories)

    counts: list[int] = []
    samples: list[list[str]] = []
    for name, regex in selected.items():
        collected = _collect_matches(root, regex, max_results_per_category)
        counts.append(len(collected))
        sample_size = (
            len(collected)
            if expanded
            else min(len(collected), DEFAULT_SAMPLES_PER_CATEGORY)
        )
        samples.append(collected[:sample_size])

    fields: dict[str, object] = (
        {"CATEGORY": category.strip()}
        if category.strip()
        else {"CATEGORIES": categories.strip() or "all"}
    )

    return audit_block(
        tool="mcquest_pattern_audit",
        path=path,
        categories=list(selected.keys()),
        counts=counts,
        samples=samples,
        fields=fields,
        expanded=expanded,
    )