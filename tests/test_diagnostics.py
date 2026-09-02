"""Tests for the read-only mcquest_diagnostics tool.

Deterministic engine tests monkeypatch the Node driver boundary so the suite
runs without a TypeScript installation. A real TypeScript integration test is
enabled only when ``MCQUEST_TEST_TYPESCRIPT_LIB`` points at a real
``typescript.js`` (it is skipped otherwise; nothing is ever downloaded or
installed to make tests pass).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

import mcquest_mcp.tools.diagnostics  # noqa: F401  (register the submodule)

# The package attribute "diagnostics" is the exported function; fetch the
# actual module from sys.modules so tests can patch its internals.
diag = sys.modules["mcquest_mcp.tools.diagnostics"]


REAL_TS_LIB = os.environ.get("MCQUEST_TEST_TYPESCRIPT_LIB") or ""
REAL_TS_LIB = REAL_TS_LIB if (REAL_TS_LIB and Path(REAL_TS_LIB).is_file()) else ""


def _result(
    payload_diagnostics: list | None = None,
    script_kind: str = "TSX",
    version: str = "5.4.5",
) -> dict:
    return {
        "ok": True,
        "file": "ignored",
        "scriptKindName": script_kind,
        "typeScriptVersion": version,
        "diagnostics": payload_diagnostics or [],
    }


MISSING_BRACE = {
    "code": 1005,
    "message": "'}' expected",
    "severity": "error",
    "line": 84,
    "column": 44,
    "length": 1,
}


@pytest.fixture
def fake_engine(repo, monkeypatch):
    """Pin node/TypeScript detection and let each test set a canned payload."""

    monkeypatch.setattr(diag, "_node_available", lambda: True)
    monkeypatch.setattr(
        diag,
        "_detect_typescript",
        lambda root: (
            Path(repo) / "node_modules" / "typescript" / "lib" / "typescript.js",
            "5.4.5",
        ),
    )

    def set_result(payload: dict) -> None:
        monkeypatch.setattr(
            diag,
            "_run_driver",
            lambda root, tslib, relative, source: payload,
        )

    return set_result


def _context_line_count(output: str) -> int:
    return len(re.findall(r"^[ >]\s*\d+\s+\|", output, re.MULTILINE))


def _has_line_marker(output: str, line_number: int) -> bool:
    return bool(
        re.search(rf"^[ >]\s*{line_number}\s+\|", output, re.MULTILINE)
    )


def _snapshot(repo: str) -> dict:
    snapshot = {}
    for current, dirs, files in os.walk(repo):
        for name in files:
            full = Path(current) / name
            stat = full.stat()
            snapshot[str(full)] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _install_typescript_lib(repo: str) -> Path:
    """Copy an existing local typescript.js into the temp project root."""
    tslib_src = Path(REAL_TS_LIB)
    dest = Path(repo) / "node_modules" / "typescript" / "lib" / "typescript.js"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tslib_src, dest)

    pkg = Path(repo) / "node_modules" / "typescript" / "package.json"
    version = "unknown"
    src_pkg = tslib_src.parent.parent / "package.json"
    try:
        data = json.loads(src_pkg.read_text(encoding="utf-8"))
        candidate = data.get("version")
        if isinstance(candidate, str) and candidate.strip():
            version = candidate.strip()
    except (OSError, ValueError):
        pass
    pkg.write_text(json.dumps({"version": version}), encoding="utf-8")
    return dest


def test_valid_ts_has_no_syntax_diagnostics(write_file, fake_engine) -> None:
    write_file("src/ok.ts", "const value: number = 1;\nexport default value;\n")
    fake_engine(_result([], script_kind="TS"))

    output = diag.diagnostics("src/ok.ts")

    assert "DIAGNOSTICS FOR: src/ok.ts" in output
    assert "SCRIPT KIND: TS" in output
    assert "ENGINE: project-local TypeScript 5.4.5" in output
    assert "No syntax diagnostics found." in output


def test_valid_tsx_has_no_syntax_diagnostics(write_file, fake_engine) -> None:
    write_file("src/ok.tsx", "export const App = () => <div>Hello</div>;\n")
    fake_engine(_result([], script_kind="TSX"))

    output = diag.diagnostics("src/ok.tsx")

    assert "DIAGNOSTICS FOR: src/ok.tsx" in output
    assert "SCRIPT KIND: TSX" in output
    assert "No syntax diagnostics found." in output


def test_valid_js_and_jsx_script_kinds(write_file, fake_engine) -> None:
    write_file("src/plain.js", "const x = 1;\n")
    write_file("src/plain.jsx", "const a = <div />;\n")

    fake_engine(_result([], script_kind="JS"))
    assert "SCRIPT KIND: JS" in diag.diagnostics("src/plain.js")

    fake_engine(_result([], script_kind="JSX"))
    assert "SCRIPT KIND: JSX" in diag.diagnostics("src/plain.jsx")


def test_missing_brace_tsx_diagnostic_reported(write_file, fake_engine) -> None:
    write_file(
        "src/TeacherDashboard.tsx",
        "\n".join(f"line {i}" for i in range(1, 94)) + "\n",
    )
    fake_engine(_result([MISSING_BRACE]))

    output = diag.diagnostics("src/TeacherDashboard.tsx")

    assert "code: TS1005" in output
    assert "severity: error" in output
    assert "message: '}' expected" in output
    assert "file: src/TeacherDashboard.tsx" in output
    assert "line: 84" in output
    assert "column: 44" in output
    assert ">   84 | line 84" in output
    assert "Summary:" in output
    assert "errors: 1" in output
    assert "warnings: 0" in output
    assert "diagnostics shown: 1 (of 1)" in output
    assert "READ ONLY. No project files were modified." in output


def test_related_location_rendered_when_provided(write_file, fake_engine) -> None:
    write_file(
        "src/a.tsx",
        "export function A() {\nreturn <div />;\n}\n",
    )
    related_brace = {
        "code": 1005,
        "message": "'}' expected",
        "severity": "error",
        "line": 3,
        "column": 1,
        "length": 1,
        "related": [
            {
                "file": "src/a.tsx",
                "line": 1,
                "column": 20,
                "message": "opening '{' was found here",
            }
        ],
    }
    fake_engine(_result([related_brace]))

    output = diag.diagnostics("src/a.tsx")

    assert "Related location:" in output
    assert "file: src/a.tsx" in output
    assert "line: 1" in output
    assert "column: 20" in output
    assert "opening '{' was found here" in output


def test_no_related_location_block_when_absent(write_file, fake_engine) -> None:
    write_file("src/a.tsx", "export const A = <div />;\n")
    fake_engine(_result([MISSING_BRACE]))

    output = diag.diagnostics("src/a.tsx")

    assert "Related location:" not in output


def test_context_lines_zero_shows_only_error_line(write_file, fake_engine) -> None:
    content = "\n".join(f"line-{i}" for i in range(1, 31)) + "\n"
    write_file("src/a.tsx", content)
    at_line_10 = dict(MISSING_BRACE)
    at_line_10["line"] = 10
    fake_engine(_result([at_line_10]))

    output = diag.diagnostics("src/a.tsx", context_lines=0)

    assert _context_line_count(output) == 1
    assert _has_line_marker(output, 10)
    assert not _has_line_marker(output, 9)
    assert not _has_line_marker(output, 11)


def test_context_lines_capped_at_25(write_file, fake_engine) -> None:
    content = "\n".join(f"line-{i}" for i in range(1, 101)) + "\n"
    write_file("src/a.tsx", content)
    at_line_50 = dict(MISSING_BRACE)
    at_line_50["line"] = 50
    fake_engine(_result([at_line_50]))

    output = diag.diagnostics("src/a.tsx", context_lines=999)

    # 25 before + error line + 25 after = 51 context lines maximum.
    assert _context_line_count(output) == 51
    assert _has_line_marker(output, 25)
    assert _has_line_marker(output, 75)
    assert not _has_line_marker(output, 24)
    assert not _has_line_marker(output, 76)


def test_context_lines_clipped_to_one_line(write_file, fake_engine) -> None:
    long_line = "x" * 500
    lines = [f"line-{i}" for i in range(1, 20)]
    lines[13] = long_line  # line 14
    write_file("src/a.tsx", "\n".join(lines) + "\n")
    at_line_14 = dict(MISSING_BRACE)
    at_line_14["line"] = 14
    fake_engine(_result([at_line_14]))

    output = diag.diagnostics("src/a.tsx")

    assert "…" in output
    assert "x" * 200 not in output


def test_max_diagnostics_limits_output(write_file, fake_engine) -> None:
    content = "\n".join(f"line-{i}" for i in range(1, 101)) + "\n"
    write_file("src/a.tsx", content)
    many = [
        {
            "code": 1005,
            "message": "'}' expected",
            "severity": "error",
            "line": 10 + i,
            "column": 1,
            "length": 1,
        }
        for i in range(1, 31)
    ]
    fake_engine(_result(many))

    output = diag.diagnostics("src/a.tsx", max_diagnostics=5)

    assert len(re.findall(r"Diagnostic \d+:", output)) == 5
    assert "diagnostics shown: 5 (of 30)" in output

    capped = diag.diagnostics("src/a.tsx", max_diagnostics=999)
    assert len(re.findall(r"Diagnostic \d+:", capped)) == 30
    assert "diagnostics shown: 30 (of 30)" in capped


def test_large_file_does_not_return_entire_file(write_file, fake_engine) -> None:
    lines = ["first-line-marker"]
    lines.extend(f"line-{i}" for i in range(2, 1420))
    lines.append("last-line-marker")
    write_file("src/huge.tsx", "\n".join(lines) + "\n")

    at_1200 = dict(MISSING_BRACE)
    at_1200["line"] = 1200
    at_1200["column"] = 3
    fake_engine(_result([at_1200]))

    output = diag.diagnostics("src/huge.tsx")

    assert "line: 1200" in output
    assert "column: 3" in output
    assert _has_line_marker(output, 1200)
    assert "first-line-marker" not in output
    assert "last-line-marker" not in output
    assert len(output) < 4000


def test_missing_typescript_returns_required_message(repo, write_file, monkeypatch) -> None:
    write_file("src/a.ts", "const x = 1;\n")
    monkeypatch.setattr(diag, "_node_available", lambda: True)
    monkeypatch.setattr(diag, "_detect_typescript", lambda root: None)

    output = diag.diagnostics("src/a.ts")

    assert "TypeScript compiler unavailable in selected project." in output
    assert "node_modules/typescript" in output


def test_missing_node_returns_required_message(repo, write_file, monkeypatch) -> None:
    write_file("src/a.ts", "const x = 1;\n")
    monkeypatch.setattr(diag, "_node_available", lambda: False)

    output = diag.diagnostics("src/a.ts")

    assert "TypeScript compiler unavailable in selected project." in output


def test_nonexistent_path_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        diag.diagnostics("src/nope.ts")


def test_unsupported_extension_rejected(write_file) -> None:
    write_file("notes.txt", "hello")

    with pytest.raises(ValueError, match="Unsupported file type"):
        diag.diagnostics("notes.txt")


def test_traversal_rejected() -> None:
    with pytest.raises(ValueError, match="escapes"):
        diag.diagnostics("../../outside.ts")


def test_ignored_directory_rejected(write_file) -> None:
    write_file("node_modules/pkg/x.ts", "const x = 1;\n")

    with pytest.raises(ValueError, match="ignored directory"):
        diag.diagnostics("node_modules/pkg/x.ts")


def test_unsupported_diagnostic_kind_rejected(write_file, fake_engine) -> None:
    write_file("src/a.ts", "const x = 1;\n")
    fake_engine(_result([], script_kind="TS"))

    with pytest.raises(ValueError, match="only 'syntax'"):
        diag.diagnostics("src/a.ts", diagnostic_kind="type")


def test_explicit_syntax_kind_accepted(write_file, fake_engine) -> None:
    write_file("src/a.ts", "const x = 1;\n")
    fake_engine(_result([], script_kind="TS"))

    output = diag.diagnostics("src/a.ts", diagnostic_kind="syntax")

    assert "No syntax diagnostics found." in output


def test_line_filter(write_file, fake_engine) -> None:
    content = "\n".join(f"line-{i}" for i in range(1, 31)) + "\n"
    write_file("src/a.tsx", content)
    many = [{**MISSING_BRACE, "line": line_number, "column": 1} for line_number in (3, 7, 10)]
    fake_engine(_result(many))

    output = diag.diagnostics("src/a.tsx", line=7)

    assert "FILTER: line=7" in output
    assert "diagnostics shown: 1 (of 1)" in output
    assert _has_line_marker(output, 7)


def test_line_and_column_filter(write_file, fake_engine) -> None:
    content = "\n".join(f"line-{i}" for i in range(1, 31)) + "\n"
    write_file("src/a.tsx", content)
    many = [
        {**MISSING_BRACE, "line": 3, "column": 5},
        {**MISSING_BRACE, "line": 3, "column": 9},
    ]
    fake_engine(_result(many))

    output = diag.diagnostics("src/a.tsx", line=3, column=9)

    assert "FILTER: line=3 column=9" in output
    assert "diagnostics shown: 1 (of 1)" in output


def test_driver_controlled_failure_raises(write_file, fake_engine) -> None:
    write_file("src/a.tsx", "export {};\n")
    fake_engine({"ok": False, "error": {"code": "TS_LOAD", "message": "boom"}})

    with pytest.raises(RuntimeError, match="TypeScript diagnostics failed: boom"):
        diag.diagnostics("src/a.tsx")


def test_diagnostics_is_read_only(write_file, repo, fake_engine) -> None:
    write_file("src/a.tsx", "export const A = () => <div>ok</div>;\n")
    fake_engine(_result([]))

    before = _snapshot(repo)
    diag.diagnostics("src/a.tsx")
    after = _snapshot(repo)

    assert before == after


@pytest.mark.skipif(
    not REAL_TS_LIB,
    reason="Set MCQUEST_TEST_TYPESCRIPT_LIB to a real typescript.js to run live "
    "TypeScript parsing tests.",
)
def test_real_missing_brace_tsx_diagnostic(repo, write_file) -> None:
    """Live check against a real TypeScript parser for a malformed TSX file."""
    _install_typescript_lib(repo)
    write_file("src/ok.tsx", "export const App = () => <div>Hello</div>;\n")
    write_file(
        "src/broken.tsx",
        "export function TeacherDashboard() {\n"
        "  return <div className=\"dashboard\">Teachers</div>;\n",
    )

    before = _snapshot(repo)

    ok_output = diag.diagnostics("src/ok.tsx")
    assert "No syntax diagnostics found." in ok_output
    assert "SCRIPT KIND: TSX" in ok_output

    broken_output = diag.diagnostics("src/broken.tsx")
    assert "Diagnostic 1:" in broken_output
    assert "code: TS1005" in broken_output
    assert "severity: error" in broken_output
    assert "'>' expected" in broken_output or "'}' expected" in broken_output
    assert "line: " in broken_output
    assert "column: " in broken_output
    assert "Summary:" in broken_output
    assert "diagnostics shown: 1 (of " in broken_output

    after = _snapshot(repo)
    assert before == after