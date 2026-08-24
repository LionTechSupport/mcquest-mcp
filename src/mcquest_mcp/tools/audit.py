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


def pattern_audit(
    path: str = "frontend/src",
    categories: str = "all",
    max_results_per_category: int = 100,
) -> str:
    """
    Run a predefined MCQuest responsive/layout audit.

    Categories:
    viewport-width, large-min-width, large-fixed-width, nowrap,
    negative-horizontal-margin, horizontal-transform, negative-position,
    overflow-x, min-width, fixed-position, sticky-position, or all.
    """

    max_results_per_category = min(
        max(max_results_per_category, 1),
        MAX_SEARCH_RESULTS,
    )

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if categories.strip().lower() == "all":
        selected = AUDIT_PATTERNS
    else:
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

        selected = {
            name: AUDIT_PATTERNS[name]
            for name in requested
        }

    output: list[str] = []

    for category, regex in selected.items():
        matches: list[str] = []

        for file_path in _files(root):
            try:
                lines = file_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
            except OSError:
                continue

            for line_number, line in enumerate(
                lines,
                start=1,
            ):
                match = regex.search(line)

                if not match:
                    continue

                relative = file_path.relative_to(
                    project_root()
                ).as_posix()

                matches.append(
                    f"{relative}:{line_number}: "
                    f"{line.strip()}"
                )

                if len(matches) >= max_results_per_category:
                    break

            if len(matches) >= max_results_per_category:
                break

        output.append(
            f"## {category}\n"
            f"Matches: {len(matches)}\n"
            + (
                "\n".join(matches)
                if matches
                else "(none)"
            )
        )

    return truncate("\n\n".join(output))