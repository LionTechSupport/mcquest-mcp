"""Phase D regression: ``mcquest_search_docs`` summary-first, paged.

Mirrors the ``mcquest_search`` contract for Markdown documentation: canonical
``[SUMMARY]`` block, deterministic ``(relative_path ASC, line ASC)`` ordering,
default ``max_results=50``, per-match documentation context capped at
``SEARCH_CONTEXT_CAP_DOCS`` (5), 4,000/16,000 budgets, 200-char line clip,
2MB size guard, and Markdown-only extension handling (D003/D008/D009/D016).
"""

from __future__ import annotations

import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.tools.docs import search_docs


def summary_of(output: str) -> dict[str, str]:
    """Parse the ``[SUMMARY]`` block into ``{key: value}``."""
    text = output.partition("[EVIDENCE]")[0]
    data: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("tool: "):
            data["tool"] = line[6:]
        elif line.startswith("scope: "):
            data["scope"] = line[7:]
        elif ": " in line:
            key, value = line.split(": ", 1)
            data[key] = value
    return data


def locations(output: str) -> list[tuple[str, int]]:
    """``(relative, line)`` pairs from the snippet-header lines."""
    body = output.partition("[EVIDENCE]")[2]
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(r"^(\S+?):(\d+)$", body, re.M)
    ]


def context_numbers(output: str) -> list[int]:
    """Line numbers rendered in snippet context lines."""
    body = output.partition("[EVIDENCE]")[2]
    return [int(n) for n in re.findall(r"^  (\d+):", body, re.M)]


def test_summary_first_for_docs(write_file) -> None:
    write_file(
        "docs/guide.md",
        "# Guide\n\nSome targetName appears here.\n",
    )
    write_file("docs/other.md", "nothing relevant\n")

    out = search_docs(pattern="targetName", path="docs")

    s = summary_of(out)
    assert s["tool"] == "mcquest_search_docs"
    assert s["scope"] == 'path="docs"'
    assert s["PATTERN"] == "targetName"
    assert s["PATH"] == "docs"
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert s["returned"] == "1"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["budget"] == "4000/16000"
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("docs/guide.md", 3)]


def test_markdown_extensions_are_scanned(write_file) -> None:
    write_file("docs/a.md", "targetName\n")
    write_file("docs/b.markdown", "targetName\n")
    write_file("docs/c.mdown", "targetName\n")
    write_file("docs/d.mkd", "targetName\n")
    write_file("docs/e.txt", "targetName\n")

    # The default file_pattern is "*.md"; widen it to "*" to prove the
    # Markdown extension set is recognized and non-Markdown files are not.
    out = search_docs(pattern="targetName", path="docs", file_pattern="*")

    assert summary_of(out)["total"] == "4"
    assert locations(out) == [
        ("docs/a.md", 1),
        ("docs/b.markdown", 1),
        ("docs/c.mdown", 1),
        ("docs/d.mkd", 1),
    ]


def test_file_pattern_restricts_docs(write_file) -> None:
    write_file("docs/phase-61-audit.md", "targetName\n")
    write_file("docs/guide.md", "targetName\n")

    out = search_docs(
        pattern="targetName", path="docs", file_pattern="*audit*.md"
    )

    assert summary_of(out)["total"] == "1"
    assert locations(out) == [("docs/phase-61-audit.md", 1)]


def test_default_max_results_is_50_for_docs(write_file) -> None:
    write_file("docs/guide.md", "overflow\n" * 80)

    out = search_docs(pattern="overflow", path="docs", context_lines=0)

    s = summary_of(out)
    assert s["total"] == "80"
    assert s["returned"] == "50"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "50"
    assert len(locations(out)) == 50


def test_context_lines_capped_at_docs_limit_5(write_file) -> None:
    lines = [f"line {i}" if i != 7 else "line 7 targetName" for i in range(1, 14)]
    write_file("docs/guide.md", "\n".join(lines) + "\n")

    out = search_docs(pattern="targetName", path="docs", context_lines=99)

    assert context_numbers(out) == list(range(2, 13))


def test_context_lines_floor_zero(write_file) -> None:
    write_file("docs/guide.md", "a\ntargetName\nb\n")

    out = search_docs(pattern="targetName", path="docs", context_lines=-5)

    assert context_numbers(out) == [2]
def test_paging_by_offset_contiguous_no_gaps_for_docs(write_file) -> None:
    write_file("docs/guide.md", "overflow\n" * 12)

    p1 = search_docs(pattern="overflow", path="docs", max_results=5, offset=0)
    p2 = search_docs(pattern="overflow", path="docs", max_results=5, offset=5)
    p3 = search_docs(pattern="overflow", path="docs", max_results=5, offset=10)

    assert summary_of(p3)["has_more"] == "false"
    assert locations(p1) + locations(p2) + locations(p3) == [
        ("docs/guide.md", n) for n in range(1, 13)
    ]


def test_default_budget_4000_expanded_16000_for_docs(write_file) -> None:
    write_file("docs/guide.md", ("x" * 150 + " targetName\n") * 60)

    default = search_docs(pattern="targetName", path="docs")
    assert len(default) <= 4000
    assert summary_of(default)["budget"] == "4000/16000"

    expanded = search_docs(pattern="targetName", path="docs", max_results=500)
    assert 4000 < len(expanded) <= 16000
    assert summary_of(expanded)["budget"] == "16000/16000"


def test_lines_clipped_at_200_chars_for_docs(write_file) -> None:
    write_file("docs/guide.md", ("y" * 300 + " targetName") + "\n")

    out = search_docs(pattern="targetName", path="docs")

    assert max(len(line) for line in out.splitlines()) <= 200


def test_2mb_file_skip_guard_for_docs(repo, write_file) -> None:
    write_file("docs/small.md", "targetName\n")
    big_rel = write_file("docs/big.md", "targetName\n")
    big_abs = os.path.join(repo, big_rel.replace("/", os.sep))
    with open(big_abs, "r+b") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")

    out = search_docs(pattern="targetName", path="docs")

    s = summary_of(out)
    assert s["total"] == "1"
    assert locations(out) == [("docs/small.md", 1)]


def test_offset_negative_rejected_for_docs(write_file) -> None:
    write_file("docs/guide.md", "targetName\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        search_docs(pattern="targetName", path="docs", offset=-1)