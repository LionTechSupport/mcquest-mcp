"""READ-ONLY TypeScript/TSX/JS/JSX syntax diagnostics for MCQuest MCP.

Runs the selected project's own Node runtime against the project-local
TypeScript compiler parser (``node_modules/typescript/lib/typescript.js``)
for a single source file. The driver uses ``ts.createSourceFile`` -- a pure
parser -- so no module resolution, type checking, tsconfig reading, or
application code is ever executed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..config import MAX_FILE_BYTES
from ..formatting import truncate
from ..security import project_root, validate_readable_file

# v1 exposes syntax-only diagnostics. Semantic/type diagnostics require full
# program construction (imports, lib.d.ts, tsconfig) and are intentionally
# not implemented yet.
SUPPORTED_DIAGNOSTIC_KINDS = {"syntax"}
SUPPORTED_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx"}

DEFAULT_CONTEXT_LINES = 12
MAX_CONTEXT_LINES = 25
DEFAULT_MAX_DIAGNOSTICS = 20
MAX_DIAGNOSTICS = 50
DRIVER_TIMEOUT_SECONDS = 30
MAX_CONTEXT_LINE_CHARS = 200

DRIVER_PATH = Path(__file__).resolve().parent.parent / "ts" / "diagnose.js"

TS_UNAVAILABLE_MESSAGE = "TypeScript compiler unavailable in selected project."


def _node_available() -> bool:
    """Return True when a Node.js executable is discoverable on PATH."""
    return shutil.which("node") is not None


def _detect_typescript(root: Path) -> "tuple[Path, str] | None":
    """Locate the project-local TypeScript compiler bundle, read-only.

    Returns ``(path-to-typescript.js, version)`` or ``None`` when the selected
    project has no local TypeScript installation under
    ``node_modules/typescript``.
    """
    tslib = root / "node_modules" / "typescript" / "lib" / "typescript.js"
    if not tslib.is_file():
        return None

    version = "unknown"
    package_json = root / "node_modules" / "typescript" / "package.json"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        candidate = data.get("version")
        if isinstance(candidate, str) and candidate.strip():
            version = candidate.strip()
    except (OSError, ValueError):
        pass

    return tslib, version


def _run_driver(root: Path, tslib: Path, relative_path: str, source_text: str) -> dict:
    """Invoke the bundled Node driver using the git_context subprocess pattern.

    Fixed executable name (``node``), no shell, paths constrained to the
    project root, bounded timeout, source passed through stdin. Raises
    :class:`RuntimeError` on any unexpected failure.
    """
    argv = [
        "node",
        str(DRIVER_PATH),
        "--root",
        str(root),
        "--tslib",
        str(tslib),
        "--file",
        relative_path,
    ]

    try:
        proc = subprocess.run(
            argv,
            input=source_text,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=DRIVER_TIMEOUT_SECONDS,
            cwd=str(root),
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(TS_UNAVAILABLE_MESSAGE) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"TypeScript diagnostics timed out after {DRIVER_TIMEOUT_SECONDS}s."
        ) from exc

    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(
            "TypeScript diagnostics failed unexpectedly."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError("TypeScript diagnostics failed unexpectedly.")

    if not payload.get("ok", False):
        error = payload.get("error") or {}
        message = error.get("message") or "unknown driver error"
        raise RuntimeError(f"TypeScript diagnostics failed: {message}")

    return payload


def _clip(line: str) -> str:
    """Bound a single source line so one long line cannot blow up the output."""
    if len(line) <= MAX_CONTEXT_LINE_CHARS:
        return line
    return line[: MAX_CONTEXT_LINE_CHARS - 1] + "…"


def _format_diagnostic(
    index: int,
    diag: dict,
    relative: str,
    source_lines: "list[str]",
    context_lines: int,
) -> "list[str]":
    """Render one diagnostic with a compact line-numbered context window."""
    parts = [
        f"Diagnostic {index}:",
        f"  code: TS{diag.get('code', '?')}",
        f"  severity: {diag.get('severity', 'error')}",
        f"  message: {diag.get('message', '')}",
        f"  file: {relative}",
        f"  line: {diag.get('line', '?')}",
        f"  column: {diag.get('column', '?')}",
        "",
        "Context:",
    ]

    diag_line = diag.get("line")
    if isinstance(diag_line, int):
        start = max(0, diag_line - 1 - context_lines)
        end = min(len(source_lines), diag_line - 1 + context_lines + 1)
        for idx in range(start, end):
            marker = ">" if idx + 1 == diag_line else " "
            parts.append(f"{marker}{idx + 1:5} | {_clip(source_lines[idx])}")
    else:
        parts.append("  (no line context available)")

    related = diag.get("related")
    if isinstance(related, list) and related:
        for rel in related:
            parts.append("")
            parts.append("Related location:")
            parts.append(f"  file: {rel.get('file', relative)}")
            parts.append(f"  line: {rel.get('line', '?')}")
            parts.append(f"  column: {rel.get('column', '?')}")
            parts.append(f"  message: {rel.get('message', '')}")

    parts.append("")
    return parts


def diagnostics(
    path: str,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    max_diagnostics: int = DEFAULT_MAX_DIAGNOSTICS,
    line: int | None = None,
    column: int | None = None,
    diagnostic_kind: str = "syntax",
) -> str:
    """Return compact syntax diagnostics for one TypeScript/TSX/JS/JSX file.

    Requires the selected project to have its own TypeScript installation
    (``node_modules/typescript``) and a Node.js runtime on PATH. The tool is
    strictly read-only: it reads the file, parses it, and returns a bounded
    report including exact diagnostic locations, a small source context
    window, and TypeScript-provided related locations when available.
    """

    file_path = validate_readable_file(path)

    extension = file_path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {path}. Supported extensions are "
            ".ts, .tsx, .js, .jsx."
        )

    if file_path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(
            f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {path}"
        )

    if diagnostic_kind not in SUPPORTED_DIAGNOSTIC_KINDS:
        raise ValueError(
            f"Unsupported diagnostic_kind: {diagnostic_kind!r}. This version "
            "of mcquest_diagnostics supports only 'syntax' diagnostics."
        )

    context_lines = min(max(context_lines, 0), MAX_CONTEXT_LINES)
    max_diagnostics = min(max(max_diagnostics, 1), MAX_DIAGNOSTICS)

    root = project_root()

    if not _node_available():
        return TS_UNAVAILABLE_MESSAGE + " Reason: no Node.js runtime found on PATH."

    detected = _detect_typescript(root)
    if detected is None:
        return (
            TS_UNAVAILABLE_MESSAGE
            + " Reason: no project-local TypeScript found under "
            "node_modules/typescript in the selected project."
        )

    tslib, version = detected

    text = file_path.read_text(encoding="utf-8", errors="replace")
    source_lines = text.splitlines()

    relative = file_path.relative_to(root).as_posix()
    payload = _run_driver(root, tslib, relative, text)

    if not payload.get("ok", False):
        error = payload.get("error") or {}
        message = error.get("message") or "unknown driver error"
        raise RuntimeError(f"TypeScript diagnostics failed: {message}")

    raw_diagnostics = payload.get("diagnostics")
    if not isinstance(raw_diagnostics, list):
        raise RuntimeError("TypeScript diagnostics failed unexpectedly.")

    effective = raw_diagnostics
    if line is not None or column is not None:
        effective = []
        for diag in raw_diagnostics:
            if line is not None and diag.get("line") != line:
                continue
            if column is not None and diag.get("column") != column:
                continue
            effective.append(diag)

    shown = effective[:max_diagnostics]

    script_kind = str(payload.get("scriptKindName") or "")
    engine_version = version if version != "unknown" else str(
        payload.get("typeScriptVersion") or "unknown"
    )

    parts = [f"DIAGNOSTICS FOR: {relative}"]
    if script_kind:
        parts.append(f"SCRIPT KIND: {script_kind}")
    parts.append(f"ENGINE: project-local TypeScript {engine_version}")

    if line is not None or column is not None:
        filters = []
        if line is not None:
            filters.append(f"line={line}")
        if column is not None:
            filters.append(f"column={column}")
        parts.append(f"FILTER: {' '.join(filters)}")

    if not shown:
        parts.append("")
        parts.append("No syntax diagnostics found.")
        return truncate("\n".join(parts))

    parts.append("")
    for index, diag in enumerate(shown, start=1):
        parts.extend(
            _format_diagnostic(index, diag, relative, source_lines, context_lines)
        )

    error_count = sum(1 for d in shown if d.get("severity") == "error")
    warning_count = sum(1 for d in shown if d.get("severity") == "warning")

    parts.append("Summary:")
    parts.append(f"  errors: {error_count}")
    parts.append(f"  warnings: {warning_count}")
    parts.append(f"  diagnostics shown: {len(shown)} (of {len(effective)})")
    parts.append("")
    parts.append("---")
    parts.append("READ ONLY. No project files were modified.")
    return truncate("\n".join(parts))