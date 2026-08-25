"""Regression: path security, read-only guarantees, and output bounds."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcquest_mcp.formatting import truncate
from mcquest_mcp.security import resolve_project_path
from mcquest_mcp.tools.files import list_files, read_file
from mcquest_mcp.tools.git_context import git_context


SOURCE = Path(__file__).resolve().parent.parent / "src" / "mcquest_mcp"

# Any occurrence of these in the package source would indicate a write or
# arbitrary-execution capability the MCP must never have.
FORBIDDEN_PRIMITIVES = [
    "write_text",
    "write_bytes",
    "unlink",
    "os.remove",
    "os.rename",
    "shutil.rmtree",
    "subprocess.Popen",
    "os.system",
    "os.popen",
]


def test_path_traversal_rejected() -> None:
    for unsafe in ("..", "../..", "sub/../../../outside"):
        with pytest.raises(ValueError):
            resolve_project_path(unsafe)


def test_source_has_no_write_primitives() -> None:
    for py_path in sorted(SOURCE.rglob("*.py")):
        text = py_path.read_text(encoding="utf-8")
        for token in FORBIDDEN_PRIMITIVES:
            assert token not in text, f"{py_path.name} contains {token!r}"


def test_git_context_outside_repository(repo) -> None:
    output = git_context()
    assert "No Git repository" in output


def test_list_files_inside_root(write_file) -> None:
    write_file("src/a.ts", "x\n")
    output = list_files(path="src")
    assert "src/a.ts" in output
    assert "COUNT: 1" in output


def test_read_file_line_numbers(write_file):
    relative = write_file("tiny.txt", "hello\nworld\n")
    output = read_file(path=relative)
    assert "1: hello" in output
    assert "2: world" in output


def test_truncate_bounds_output() -> None:
    output = truncate("x" * 200_000)
    assert "[OUTPUT TRUNCATED" in output