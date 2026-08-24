"""READ-ONLY project context and cross-evidence search tools."""

from __future__ import annotations

import re
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
)
from ..formatting import truncate
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
def find_evidence(
    query: str,
    phase: str = "",
    scope: str = "all",
    path: str = "frontend/src",
    docs_path: str = "docs",
    max_results: int = 50,
    context_lines: int = 1,
) -> str:
    """Search across code, documentation, and phase evidence."""
    if not query.strip():
        raise ValueError("Query cannot be empty.")
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    context_lines = min(max(context_lines, 0), 5)
    scope = scope.lower().strip()
    valid_scopes = {"code", "docs", "phase", "all"}
    if scope not in valid_scopes:
        raise ValueError(f"Scope must be one of: {', '.join(sorted(valid_scopes))}")
    parts: list[str] = []
    parts.append(f"EVIDENCE SEARCH: {query}")
    parts.append(f"SCOPE: {scope}")
    if phase.strip():
        parts.append(f"PHASE FILTER: {phase}")
    parts.append("=" * 40)
    try:
        regex = re.compile(query, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"Invalid regex: {exc}") from exc
    total_matches = 0
    if scope in ("code", "all"):
        parts.append("\n## CODE EVIDENCE")
        cr, cc = _search_source_files(regex, path, phase, max_results, context_lines)
        total_matches += cc
        parts.extend(cr) if cr else parts.append("  (no matches)")
    if scope in ("docs", "all"):
        parts.append("\n## DOCUMENTATION EVIDENCE")
        dr, dc = _search_doc_files(regex, docs_path, phase, max_results, context_lines)
        total_matches += dc
        parts.extend(dr) if dr else parts.append("  (no matches)")
    parts.append(f"\nTOTAL MATCHES: {total_matches}")
    return truncate("\n".join(parts))


def _search_source_files(
    regex: "re.Pattern[str]",
    path: str,
    phase: str,
    max_results: int,
    context_lines: int,
) -> "tuple[list[str], int]":
    """Search source code files."""
    root = resolve_project_path(path)
    results: list[str] = []
    match_count = 0
    source_exts = {".ts", ".tsx", ".js", ".jsx", ".css"}
    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        for filename in files:
            if match_count >= max_results:
                break
            file_path = current / filename
            if file_path.suffix.lower() not in source_exts:
                continue
            if is_ignored_path(file_path):
                continue
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                match_count += 1
                relative = file_path.relative_to(project_root()).as_posix()
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                snippet = "\n".join(f"  {i + 1}: {lines[i]}" for i in range(start, end))
                results.append(f"  {relative}:{index + 1}\n{snippet}\n")
                if match_count >= max_results:
                    break
    return results, match_count


def _search_doc_files(
    regex: "re.Pattern[str]",
    path: str,
    phase: str,
    max_results: int,
    context_lines: int,
) -> "tuple[list[str], int]":
    """Search documentation files, optionally filtered by phase."""
    root = resolve_project_path(path)
    results: list[str] = []
    match_count = 0
    markdown_exts = {".md", ".markdown", ".mdown", ".mkd"}
    phase_lower = phase.strip().lower() if phase.strip() else ""
    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        for filename in sorted(files):
            if match_count >= max_results:
                break
            file_path = current / filename
            if file_path.suffix.lower() not in markdown_exts:
                continue
            if is_ignored_path(file_path):
                continue
            if phase_lower:
                name_lower = filename.lower()
                if phase_lower not in name_lower and not re.search(
                    r"phase[-\s]*" + re.escape(phase_lower), name_lower,
                ):
                    continue
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    continue
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines):
                if not regex.search(line):
                    continue
                match_count += 1
                relative = file_path.relative_to(project_root()).as_posix()
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                snippet = "\n".join(f"  {i + 1}: {lines[i]}" for i in range(start, end))
                results.append(f"  {relative}:{index + 1}\n{snippet}\n")
                if match_count >= max_results:
                    break
    return results, match_count