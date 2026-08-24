from __future__ import annotations

import fnmatch
import re
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

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in MARKDOWN_EXTENSIONS


def _markdown_files(root: Path):
    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORED_DIRECTORIES
        ]

        for filename in files:
            path = current / filename

            if not _is_markdown(path):
                continue

            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            if is_ignored_path(path):
                continue

            yield path


def list_docs(
    path: str = "docs",
    pattern: str = "*.md",
    max_results: int = 200,
) -> str:
    """
    List Markdown documentation files beneath a project directory.

    Excludes dependency/generated directories and non-Markdown files.
    """

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if root.is_file():
        if _is_markdown(root):
            return root.relative_to(project_root()).as_posix()
        raise ValueError(f"Not a Markdown file: {path}")

    results: list[str] = []

    for file_path in _markdown_files(root):
        if len(results) >= max_results:
            break

        if not fnmatch.fnmatch(file_path.name, pattern):
            continue

        results.append(
            file_path.relative_to(project_root()).as_posix()
        )

    results.sort()

    output = "\n".join(results)

    return truncate(
        f"ROOT: {root.relative_to(project_root()) if root != project_root() else '.'}\n"
        f"PATTERN: {pattern}\n"
        f"COUNT: {len(results)}\n\n"
        + output
    )


def read_doc(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    """
    Read a Markdown documentation file with exact line numbers.

    Use line ranges whenever possible instead of requesting huge files.
    """

    file_path = validate_readable_file(path)

    if not _is_markdown(file_path):
        raise ValueError(f"Not a Markdown file: {path}")

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


def search_docs(
    pattern: str,
    path: str = "docs",
    file_pattern: str = "*.md",
    case_sensitive: bool = False,
    context_lines: int = 1,
    max_results: int = 200,
) -> str:
    """
    Search Markdown documentation using a regex or text pattern.

    Returns exact file paths, line numbers, matching lines,
    and limited surrounding context.
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

    for file_path in _markdown_files(root):
        if match_count >= max_results:
            break

        if not fnmatch.fnmatch(file_path.name, file_pattern):
            continue

        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
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


def _nearest_heading(lines: list[str], index: int) -> tuple[int, str] | None:
    """Return the nearest preceding Markdown heading (line number, text)."""

    for i in range(index, -1, -1):
        match = HEADING_RE.match(lines[i])

        if match:
            return i + 1, match.group(2).strip()

    return None


def phase_context(
    query: str = "",
    phase: str = "",
    path: str = "docs",
    max_results: int = 50,
    context_lines: int = 2,
    include_implementation: bool = True,
    include_audits: bool = True,
) -> str:
    """
    Locate relevant phase/stage documentation.

    Supports two modes:
    1. query mode: free-text search (e.g. "responsive overflow", "Android")
    2. phase mode: phase number lookup (e.g. "61", "61-Part-II-A")

    When 'phase' is provided, it takes precedence over 'query'.
    Results are grouped by document type when using phase mode.
    """

    effective_query = _resolve_query(query, phase)

    if not effective_query.strip():
        raise ValueError(
            "Provide either 'query' (free-text) or 'phase' (phase number)."
        )

    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    context_lines = min(max(context_lines, 0), 5)

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    # When using phase mode, build a prioritized lookup
    if phase.strip():
        return _phase_structured_lookup(
            phase=phase.strip(),
            root=root,
            max_results=max_results,
            context_lines=context_lines,
            include_implementation=include_implementation,
            include_audits=include_audits,
        )

    # Standard query mode (backward compatible)
    query_lower = effective_query.strip().lower()

    try:
        regex = re.compile(re.escape(query_lower), re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"Invalid query: {exc}") from exc

    results: list[str] = []
    match_count = 0

    for file_path in _markdown_files(root):
        if match_count >= max_results:
            break

        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
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

            heading = _nearest_heading(lines, index)

            heading_str = (
                f"HEADING: {heading[1]} (line {heading[0]})"
                if heading
                else "HEADING: (none)"
            )

            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)

            results.append(
                f"{relative}:{index + 1}\n"
                f"{heading_str}\n"
                + "\n".join(
                    f"  {i + 1}: {lines[i]}"
                    for i in range(start, end)
                )
                + "\n"
            )

            if match_count >= max_results:
                break

    if not results:
        return (
            f"QUERY: {effective_query}\n"
            f"PATH: {path}\n"
            "MATCHES: 0"
        )

    return truncate(
        f"QUERY: {effective_query}\n"
        f"PATH: {path}\n"
        f"MATCHES RETURNED: {match_count}\n\n"
        + "\n".join(results)
    )
def _resolve_query(query: str, phase: str) -> str:
    """Resolve the effective search query from query and phase params."""
    if phase.strip():
        p = phase.strip()
        if p.lower().startswith("phase "):
            p = p[6:].strip()
        return f"Phase-{p}" if not p.lower().startswith("phase ") else p
    return query


def _classify_phase_doc(filename: str) -> str:
    """Classify a phase document by type."""
    name = filename.lower()
    if "audit" in name:
        return "AUDIT"
    if "implementation" in name or "impl" in name:
        return "IMPLEMENTATION"
    if "complete" in name or "completion" in name or "final" in name:
        return "COMPLETION"
    if "verif" in name or "test" in name:
        return "VERIFICATION"
    return "OTHER"
def _phase_structured_lookup(
    phase: str,
    root: Path,
    max_results: int,
    context_lines: int,
    include_implementation: bool,
    include_audits: bool,
) -> str:
    """Perform a structured phase lookup returning grouped results."""
    phase_lower = phase.lower().lstrip("phase ").strip()
    phase_pattern = re.compile(
        r"phase[-\s]*" + re.escape(phase_lower), re.IGNORECASE,
    )

    matching_files: list[tuple[Path, int]] = []

    for file_path in _markdown_files(root):
        filename = file_path.name.lower()
        if phase_pattern.search(filename):
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="replace")
                heading_matches = len([
                    l for l in text.splitlines()
                    if l.startswith("#") and phase_pattern.search(l)
                ])
                matching_files.append((file_path, heading_matches))
            except OSError:
                continue

    if not matching_files:
        return _fallback_phase_search(phase, root, max_results, context_lines)

    type_priority = {
        "IMPLEMENTATION": 0, "AUDIT": 1, "COMPLETION": 2,
        "VERIFICATION": 3, "OTHER": 4,
    }

    matching_files.sort(key=lambda x: (
        type_priority.get(_classify_phase_doc(x[0].name), 5), -x[1],
    ))

    if not include_implementation:
        matching_files = [
            (p, c) for p, c in matching_files
            if _classify_phase_doc(p.name) != "IMPLEMENTATION"
        ]
    if not include_audits:
        matching_files = [
            (p, c) for p, c in matching_files
            if _classify_phase_doc(p.name) != "AUDIT"
        ]

    output_parts: list[str] = []
    output_parts.append(f"PHASE: {phase}")
    output_parts.append(f"DOCUMENTS FOUND: {len(matching_files)}")

    groups: dict[str, list[Path]] = {}
    for file_path, _ in matching_files:
        doc_type = _classify_phase_doc(file_path.name)
        groups.setdefault(doc_type, []).append(file_path)

    total = 0
    for doc_type in ["IMPLEMENTATION", "AUDIT", "COMPLETION", "VERIFICATION", "OTHER"]:
        if doc_type not in groups:
            continue
        output_parts.append(f"\n## {doc_type} DOCUMENTS")
        for file_path in groups[doc_type]:
            if total >= max_results:
                break
            relative = file_path.relative_to(project_root()).as_posix()
            output_parts.append(f"  - {relative}")
            try:
                lines = file_path.read_text(
                    encoding="utf-8", errors="replace",
                ).splitlines()
                for i, line in enumerate(lines[:20]):
                    if line.startswith("#"):
                        output_parts.append(f"    {line.strip()} (line {i + 1})")
                        break
            except OSError:
                pass
            total += 1

    output_parts.append(
        "\n---\nNOTE: Deterministic document listing. "
        "Use mcquest_read_doc to read specific files. "
        "Use mcquest_search_docs for content search within documents."
    )
    return truncate("\n".join(output_parts))


def _fallback_phase_search(
    phase: str,
    root: Path,
    max_results: int,
    context_lines: int,
) -> str:
    """Fallback when no filename match: search document contents."""
    phase_lower = phase.lower().lstrip("phase ").strip()
    patterns = [f"Phase {phase_lower}", f"Phase-{phase_lower}", phase_lower]

    for pat in patterns:
        try:
            regex = re.compile(re.escape(pat), re.IGNORECASE)
        except re.error:
            continue

        results: list[str] = []
        match_count = 0

        for file_path in _markdown_files(root):
            if match_count >= max_results:
                break
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                lines = file_path.read_text(
                    encoding="utf-8", errors="replace",
                ).splitlines()
            except OSError:
                continue

            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                match_count += 1
                relative = file_path.relative_to(project_root()).as_posix()
                heading = _nearest_heading(lines, index)
                heading_str = (
                    f"HEADING: {heading[1]} (line {heading[0]})"
                    if heading else "HEADING: (none)"
                )
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                results.append(
                    f"{relative}:{index + 1}\n{heading_str}\n"
                    + "\n".join(f"  {i + 1}: {lines[i]}"
                               for i in range(start, end))
                    + "\n"
                )
                if match_count >= max_results:
                    break

        if results:
            return truncate(
                f"PHASE: {phase} (content search, no filename match)\n"
                f"MATCHES RETURNED: {match_count}\n\n" + "\n".join(results)
            )

    return f"PHASE: {phase}\nMATCHES: 0\nNo documentation found for this phase."
def compare_phase(
    from_phase: str,
    to_phase: str,
    path: str = "docs",
    max_results: int = 50,
) -> str:
    """Compare documentation evidence between two phases.

    Returns differences between phase documentation sets such as
    documentation changes, new findings, resolved findings.

    Uses terminology: EXISTING, RESOLVED, NEW, POTENTIAL REGRESSION,
    UNKNOWN when appropriate.
    """
    if not from_phase.strip() or not to_phase.strip():
        raise ValueError("Both from_phase and to_phase are required.")

    from_norm = from_phase.strip().lower().lstrip("phase ").strip()
    to_norm = to_phase.strip().lower().lstrip("phase ").strip()

    root = resolve_project_path(path)

    from_files = _find_phase_files(root, from_norm)
    to_files = _find_phase_files(root, to_norm)

    parts: list[str] = []
    parts.append(f"PHASE COMPARISON: {from_phase} -> {to_phase}")
    parts.append("=" * 40)

    if not from_files and not to_files:
        parts.append("\nNo documentation found for either phase.")
        return truncate("\n".join(parts))

    # From phase documents
    parts.append(f"\n## FROM PHASE: {from_phase}")
    parts.append(f"Documents: {len(from_files)}")
    for f in sorted(from_files)[:max_results]:
        relative = f.relative_to(project_root()).as_posix()
        parts.append(f"  - {relative}")

    # To phase documents
    parts.append(f"\n## TO PHASE: {to_phase}")
    parts.append(f"Documents: {len(to_files)}")
    for f in sorted(to_files)[:max_results]:
        relative = f.relative_to(project_root()).as_posix()
        parts.append(f"  - {relative}")

    # Differences
    from_names = {f.name.lower() for f in from_files}
    to_names = {f.name.lower() for f in to_files}

    new_docs = to_names - from_names
    removed_docs = from_names - to_names
    common_docs = from_names & to_names

    parts.append("\n## SUMMARY")
    parts.append(f"  NEW documents in {to_phase}: {len(new_docs)}")
    parts.append(f"  REMOVED from {from_phase}: {len(removed_docs)}")
    parts.append(f"  COMMON documents: {len(common_docs)}")
    parts.append(f"  STATUS: EXISTING={len(common_docs)} NEW={len(new_docs)} RESOLVED={len(removed_docs)}")

    if new_docs:
        parts.append(f"\n## NEW in {to_phase}:")
        for name in sorted(new_docs):
            parts.append(f"  - {name}")
    if removed_docs:
        parts.append(f"\n## RESOLVED/REMOVED (present in {from_phase}, absent in {to_phase}):")
        for name in sorted(removed_docs):
            parts.append(f"  - {name}")

    parts.append(
        "\n---\nNOTE: This compares document existence, not content. "
        "Use mcquest_read_doc to inspect individual documents. "
        "Differences in common documents (content changes) are not detected "
        "by this tool."
    )
    return truncate("\n".join(parts))


def _find_phase_files(root: Path, phase_norm: str) -> list[Path]:
    """Find all markdown files related to a phase."""
    phase_pattern = re.compile(
        r"phase[-\s]*" + re.escape(phase_norm),
        re.IGNORECASE,
    )
    results: list[Path] = []
    for file_path in _markdown_files(root):
        if phase_pattern.search(file_path.name.lower()):
            results.append(file_path)
    return results