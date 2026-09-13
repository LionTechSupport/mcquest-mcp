"""Phase B focused tests: mcquest_read_doc windowed reads (v0.5).

Mirrors ``tests/test_read_file.py`` for Markdown documentation, plus the
Markdown-specific behaviors: non-Markdown rejection, missing file, and
path-traversal rejection (read-only/security regression).
"""

from __future__ import annotations

import json
import re

import pytest

from mcquest_mcp.tools.docs import read_doc

NORMAL = 4_000
CEILING = 16_000
SERIALIZED_ALLOWANCE = 500

NUMBERED_RE = re.compile(r"^ {0,5}\d+: ")
SUMMARY_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z_0-9]*): (.*)$")


def _body(output: str) -> str:
    return output[output.index("[EVIDENCE]") + len("[EVIDENCE]") :]


def _numbered(output: str) -> list[str]:
    return [line for line in _body(output).splitlines() if NUMBERED_RE.match(line)]
# --- markdown windowed reads ---------------------------------------------

def test_read_doc_default_window_and_summary(write_file) -> None:
    write_file("docs/a.md", "\n".join(f"h{i}" for i in range(1, 301)))
    out = read_doc("docs/a.md")
    s = _summary(out)
    assert s["tool"] == "mcquest_read_doc"
    assert s["scope"] == 'path="docs/a.md"'
    assert s["start_line"] == "1"
    assert s["end_line"] == "250"
    assert s["total_lines"] == "300"
    assert s["has_more"] == "true"
    assert s["next_start_line"] == "251"
    assert s["budget"] == "4000/16000"
    assert len(_numbered(out)) == 250


def test_read_doc_default_stays_within_normal_budget(write_file) -> None:
    write_file("docs/big.md", "\n".join("x" * 40 for _ in range(5000)))
    out = read_doc("docs/big.md")
    assert len(out) <= NORMAL
    assert "[OUTPUT TRUNCATED" in out


def test_read_doc_continuation_walk(write_file) -> None:
    write_file("docs/walk.md", "\n".join(f"h{i}" for i in range(1, 1001)))
    out = read_doc("docs/walk.md")
    pages: list[tuple[int, int]] = []
    while True:
        s = _summary(out)
        pages.append((int(s["start_line"]), int(s["end_line"])))
        if s["has_more"] == "false":
            break
        out = read_doc("docs/walk.md", start_line=int(s["next_start_line"]))
    assert pages[0][0] == 1
    assert pages[-1][1] == 1000
    for first, second in zip(pages, pages[1:]):
        assert second[0] == first[1] + 1, (first, second)
    assert sum(b - a + 1 for a, b in pages) == 1000


def test_read_doc_explicit_range(write_file) -> None:
    write_file("docs/r.md", "\n".join(f"h{i}" for i in range(1, 2001)))
    out = read_doc("docs/r.md", start_line=10, end_line=20)
    s = _summary(out)
    assert s["start_line"] == "10"
    assert s["end_line"] == "20"
    assert s["total_lines"] == "2000"
    assert len(_numbered(out)) == 11


def test_read_doc_explicit_range_clamped_to_1000(write_file) -> None:
    write_file("docs/c.md", "\n".join(f"h{i}" for i in range(1, 5001)))
    s = _summary(read_doc("docs/c.md", start_line=1, end_line=5000))
    assert s["end_line"] == "1000"
    assert s["has_more"] == "true"


def test_read_doc_explicit_range_within_ceiling(write_file) -> None:
    write_file("docs/big.md", "\n".join("x" * 800 for _ in range(2000)))
    out = read_doc("docs/big.md", start_line=1, end_line=2000)
    assert len(out) <= CEILING
    assert _serialized_len(out) <= CEILING + SERIALIZED_ALLOWANCE


def test_read_doc_long_line_clipped(write_file) -> None:
    write_file("docs/long.md", "z" * 20_000)
    out = read_doc("docs/long.md")
    assert len(_numbered(out)[0]) == 200
    assert _summary(out)["truncated"] == "true"


# --- summary / boundary ---------------------------------------------------

def test_read_doc_summary_survives_truncation(write_file) -> None:
    write_file("docs/big.md", "\n".join("w" * 100 for _ in range(5000)))
    out = read_doc("docs/big.md", start_line=1, end_line=5000)
    assert out.startswith("[SUMMARY]\n")
    assert out.index("[EVIDENCE]") < out.index("OUTPUT TRUNCATED")
    for key in ("tool", "scope", "start_line", "end_line", "total_lines",
                "has_more", "truncated", "budget"):
        assert key in _summary(out), key


def test_read_doc_empty_file(write_file) -> None:
    write_file("docs/empty.md", "")
    s = _summary(read_doc("docs/empty.md"))
    assert s["end_line"] == "0"
    assert s["total_lines"] == "0"
    assert s["has_more"] == "false"


def test_read_doc_one_line_file(write_file) -> None:
    write_file("docs/one.md", "# One")
    s = _summary(read_doc("docs/one.md"))
    assert s["end_line"] == "1"
    assert s["has_more"] == "false"


def test_read_doc_start_beyond_eof(write_file) -> None:
    write_file("docs/e.md", "h1\nh2\nh3")
    out = read_doc("docs/e.md", start_line=999)
    s = _summary(out)
    assert s["end_line"] == "0"
    assert s["has_more"] == "false"
    assert _numbered(out) == []


def test_read_doc_atomic_cutoff(write_file) -> None:
    lines = ["q" * 5000 for _ in range(300)]
    write_file("docs/atomic.md", "\n".join(lines))
    out = read_doc("docs/atomic.md", start_line=1, end_line=300)
    expected = [f"{i:6}: {line}" for i, line in enumerate(lines, start=1)]
    expected = [line[:199] + "\u2026" if len(line) > 200 else line for line in expected]
    rendered = _numbered(out)
    assert rendered == expected[: len(rendered)]
    assert len(rendered) < 300


# --- markdown-specific behavior / security --------------------------------

def test_read_doc_rejects_non_markdown(write_file) -> None:
    write_file("notes.txt", "plain text")
    with pytest.raises(ValueError, match="Not a Markdown file"):
        read_doc("notes.txt")


def test_read_doc_missing_file_raises(write_file) -> None:
    with pytest.raises(FileNotFoundError):
        read_doc("nope.md")


def test_read_doc_traversal_rejected() -> None:
    with pytest.raises(ValueError):
        read_doc("../outside.md")


def _summary(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if line == "[EVIDENCE]":
            break
        match = SUMMARY_KEY_RE.match(line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def _serialized_len(text: str) -> int:
    return len(json.dumps({"content": [{"type": "text", "text": text}]}))