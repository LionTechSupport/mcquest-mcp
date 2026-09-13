"""READ-ONLY project context and cross-evidence search tools."""

from __future__ import annotations

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
from ..formatting import search_block, truncate
from ..security import (
    is_ignored_path,
    project_root,
    resolve_project_path,
)

TECH_STACK_INDICATORS: dict[str, str] = {
    "package.json": "Node.js / npm",
    "tsconfig.json": "TypeScript",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "next.config.js": "Next.js",
    "next.config.ts": "Next.js",
    "capacitor.config.ts": "Capacitor (mobile)",
    "tailwind.config.js": "Tailwind CSS",
    "tailwind.config.ts": "Tailwind CSS",
    "pyproject.toml": "Python",
    "firebase.json": "Firebase",
    "Dockerfile": "Docker",
}

IMPORTANT_DIRS = [
    "frontend/src/components",
    "frontend/src/pages",
    "frontend/src/hooks",
    "frontend/src/services",
    "frontend/src/styles",
    "frontend/src/utils",
    "docs",
    "memory-bank",
]
def project_context() -> str:
    """Return a compact high-level understanding of the MCQuest project."""
    root = project_root()
    parts: list[str] = []
    parts.append("MCQUEST PROJECT CONTEXT")
    parts.append("=" * 40)
    parts.append(f"ROOT: {root}")
    parts.append("")

    tech: list[str] = []
    for filename, label in TECH_STACK_INDICATORS.items():
        if (root / filename).exists():
            tech.append(f"  - {label}")
    if tech:
        parts.append("TECHNOLOGY STACK:")
        parts.extend(tech)
    else:
        parts.append("TECHNOLOGY STACK: (not detected)")
    parts.append("")

    parts.append("MAJOR DIRECTORIES:")
    try:
        for item in sorted(root.iterdir()):
            if item.name in IGNORED_DIRECTORIES or item.name.startswith("."):
                continue
            if item.is_dir():
                parts.append(f"  - {item.name}/")
    except OSError:
        parts.append("  (could not read)")

    parts.append("")
    parts.append("IMPORTANT SOURCE AREAS:")
    for relative in IMPORTANT_DIRS:
        p = root / relative
        status = "PRESENT" if p.exists() else "MISSING"
        parts.append(f"  - {relative} ({status})")

    parts.append("")
    parts.append("DOCUMENTATION:")
    for doc_dir in ["docs", "memory-bank"]:
        p = root / doc_dir
        if p.exists() and p.is_dir():
            try:
                fc = sum(1 for _ in p.rglob("*.md") if not is_ignored_path(_))
                parts.append(f"  - {doc_dir}/ ({fc} markdown files)")
            except OSError:
                parts.append(f"  - {doc_dir}/ (present)")

    parts.append("")
    parts.append("KEY CONFIGURATION FILES:")
    for cf in [
        "frontend/package.json", "frontend/vite.config.ts",
        "frontend/tailwind.config.js", "frontend/capacitor.config.ts",
        "frontend/index.html", "frontend/.env", ".gitignore",
    ]:
        status = "PRESENT" if (root / cf).exists() else "MISSING"
        parts.append(f"  - {cf} ({status})")

    parts.append("")
    parts.append("---")
    parts.append("Use mcquest_list_files to explore directories.")
    parts.append("Use mcquest_phase_context for phase-specific docs.")
    parts.append("Use mcquest_find_evidence for cross-searching.")
    return truncate("\n".join(parts))
def _count_stream(iter_locations) -> "tuple[int, int]":
    """Return (total_matches, files_affected) from a (relative, line) stream."""
    total = 0
    files: set[str] = set()
    for relative, _line_no in iter_locations:
        total += 1
        files.add(relative)
    return total, len(files)


def _safe_regex_lines(file_path) -> list[str]:
    try:
        return file_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return []


def find_evidence(
    query: str,
    phase: str = "",
    scope: str = "all",
    path: str = "frontend/src",
    docs_path: str = "docs",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    context_lines: int = 1,
    offset: int = 0,
) -> str:
    """Search across code, documentation, and phase evidence.

    Summary-first and explicitly paged with ONE shared page budget (D003,
    D013): ``scope=\"all\"`` merges the code stream first and the docs stream
    second into one deterministic ``(relative_path ASC, line ASC)`` ordering,
    and ``max_results`` is a single merged-stream page budget -- never a
    per-scope limit and never ``min(code_total, docs_total)``. Per-scope
    counts are reported separately (``counts: code=N; docs=M``).
    """

    if not query.strip():
        raise ValueError("Query cannot be empty.")
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    context_lines = min(max(context_lines, 0), 5)
    if offset < 0:
        raise ValueError("offset must be >= 0")
    scope = scope.lower().strip()
    valid_scopes = {"code", "docs", "phase", "all"}
    if scope not in valid_scopes:
        raise ValueError(f"Scope must be one of: {', '.join(sorted(valid_scopes))}")
    try:
        regex = re.compile(query, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc

    search_code = scope in ("code", "all")
    search_docs = scope in ("docs", "phase", "all")
    phase_lower = phase.strip().lower() if phase.strip() else ""

    def code_locations() -> "list[tuple[str, int]]":
        root = resolve_project_path(path)
        source_exts = {".ts", ".tsx", ".js", ".jsx", ".css"}
        for current_root, dirs, files in os.walk(root):
            current = Path(current_root)
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
            for filename in sorted(files):
                file_path = current / filename
                if file_path.suffix.lower() not in source_exts:
                    continue
                if is_ignored_path(file_path):
                    continue
                try:
                    if file_path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                relative = file_path.relative_to(project_root()).as_posix()
                for index, line in enumerate(
                    _safe_regex_lines(file_path),
                    start=1,
                ):
                    if regex.search(line):
                        yield (relative, index)

    def doc_locations() -> "list[tuple[str, int]]":
        root = resolve_project_path(docs_path)
        markdown_exts = {".md", ".markdown", ".mdown", ".mkd"}
        for current_root, dirs, files in os.walk(root):
            current = Path(current_root)
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
            for filename in sorted(files):
                file_path = current / filename
                if file_path.suffix.lower() not in markdown_exts:
                    continue
                if is_ignored_path(file_path):
                    continue
                if phase_lower:
                    name_lower = filename.lower()
                    if phase_lower not in name_lower and not re.search(
                        r"phase[-\s]*" + re.escape(phase_lower),
                        name_lower,
                    ):
                        continue
                try:
                    if file_path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                relative = file_path.relative_to(project_root()).as_posix()
                for index, line in enumerate(
                    _safe_regex_lines(file_path),
                    start=1,
                ):
                    if regex.search(line):
                        yield (relative, index)


# Pass 1: authoritative per-scope totals (and therefore merged total).
    code_total = docs_total = 0
    code_files = docs_files = 0
    if search_code:
        code_total, code_files = _count_stream(code_locations())
    if search_docs:
        docs_total, docs_files = _count_stream(doc_locations())
    total = code_total + docs_total  # authoritative; NEVER min(code, docs)
    files_affected = code_files + docs_files

    # Pass 2: ONE shared page budget over the deterministic merged stream
    # (code group first, then docs group; each (relative ASC, line ASC)).
    page_size = min(max_results, max(total - offset, 0))
    page: list[tuple[str, int]] = []
    if page_size > 0:
        needed = min(offset + page_size, total)
        merged: list[tuple[str, int]] = []
        if search_code and needed > 0:
            merged.extend(sorted(heapq.nsmallest(needed, code_locations())))
        if search_docs and needed > 0:
            merged.extend(sorted(heapq.nsmallest(needed, doc_locations())))
        page = merged[offset : offset + page_size]

    items: list[str] = []
    cache: dict[str, list[str]] = {}
    for relative, line_no in page:
        if relative not in cache:
            cache[relative] = _safe_regex_lines(resolve_project_path(relative))
        index = line_no - 1
        start = max(0, index - context_lines)
        end = min(len(cache[relative]), index + context_lines + 1)
        snippet = "\n".join(
            f"  {i + 1}: {cache[relative][i]}" for i in range(start, end)
        )
        items.append(f"{relative}:{line_no}\n{snippet}")

    fields: dict[str, object] = {
        "QUERY": query,
        "SCOPE": scope,
    }
    if phase.strip():
        fields["PHASE"] = phase.strip()
    fields["counts"] = f"code={code_total}; docs={docs_total}"

    return search_block(
        tool="mcquest_find_evidence",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields=fields,
        scope=(
            f'query="{query}" scope="{scope}" '
            f'path="{path}" docs_path="{docs_path}"'
        ),
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )