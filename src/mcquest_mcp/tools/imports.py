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
            } and path.suffix.lower() not in IGNORED_EXTENSIONS:
                if not is_ignored_path(path):
                    yield path


def find_imports(
    target: str,
    path: str = "frontend/src",
    max_results: int = 200,
) -> str:
    """
    Find ES module imports referencing a component/module.

    This is a textual import analysis, not a full TypeScript AST.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    target_lower = target.lower()

    results: list[str] = []

    for file_path in _source_files(root):
        try:
            text = file_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        for line_number, line in enumerate(
            text.splitlines(),
            start=1,
        ):
            for pattern in IMPORT_PATTERNS:
                match = pattern.search(line)

                if not match:
                    continue

                module = match.group(1)

                if target_lower not in module.lower():
                    continue

                relative = file_path.relative_to(
                    project_root()
                ).as_posix()

                results.append(
                    f"{relative}:{line_number}: {line.strip()}"
                )

                break

            if len(results) >= max_results:
                break

        if len(results) >= max_results:
            break

    return truncate(
        f"TARGET: {target}\n"
        f"MATCHES: {len(results)}\n\n"
        + "\n".join(results)
    )


def find_usages(
    symbol: str,
    path: str = "frontend/src",
    file_pattern: str = "*",
    max_results: int = 200,
) -> str:
    """
    Find textual references to a symbol across source files.

    Searches identifiers rather than arbitrary substrings.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    try:
        regex = re.compile(
            rf"\b{re.escape(symbol)}\b"
        )
    except re.error as exc:
        raise ValueError(str(exc)) from exc

    results: list[str] = []

    for file_path in _source_files(root):
        if not __import__("fnmatch").fnmatch(
            file_path.name,
            file_pattern,
        ):
            continue

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
            if regex.search(line):
                relative = file_path.relative_to(
                    project_root()
                ).as_posix()

                results.append(
                    f"{relative}:{line_number}: {line.strip()}"
                )

            if len(results) >= max_results:
                break

        if len(results) >= max_results:
            break

    return truncate(
        f"SYMBOL: {symbol}\n"
        f"MATCHES: {len(results)}\n\n"
        + "\n".join(results)
    )