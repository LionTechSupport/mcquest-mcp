"""Phase D regression: ``mcquest_search`` summary-first, explicitly paged.

The search tools now emit a canonical ``[SUMMARY]`` block (total,
files_affected, returned, offset, next_offset, has_more, truncated,
collection_complete, budget) followed by one explicit page of at most
``max_results`` snippets ordered deterministically by
``(relative_path ASC, line ASC)`` (D003/D008/D009/D016). ``max_results``
defaults to ``SEARCH_DEFAULT_RESULTS`` (50) with a hard cap of 500, the
per-match context is capped at ``SEARCH_CONTEXT_CAP_CODE`` (3), lines are
clipped at 200 chars, and oversized (>2MB) files are skipped.
"""

from __future__ import annotations

import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.tools.search import search_text


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


def test_summary_first_with_echo_fields_and_trailer(write_file) -> None:
    write_file("src/app.ts", "const targetName = 1;\n")
    write_file("src/lib.ts", "const other = 2;\n")

    out = search_text(pattern="targetName", path="src")

    assert out.startswith("[SUMMARY]\n")
    s = summary_of(out)
    assert s["tool"] == "mcquest_search"
    assert s["scope"] == 'path="src"'
    assert s["PATTERN"] == "targetName"
    assert s["PATH"] == "src"
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert s["returned"] == "1"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert "[EVIDENCE]" in out
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("src/app.ts", 1)]


def test_snippet_show_match_line_plus_context(write_file) -> None:
    write_file("src/app.ts", "a\nb\ntargetName\nc\n")

    out = search_text(pattern="targetName", path="src")

    assert "src/app.ts:3" in out
    assert context_numbers(out) == [2, 3, 4]


def test_default_max_results_is_50(write_file) -> None:
    write_file("src/app.ts", "targetName\n" * 80)

    out = search_text(pattern="targetName", path="src", context_lines=0)

    s = summary_of(out)
    assert s["total"] == "80"
    assert s["returned"] == "50"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "50"
    assert len(locations(out)) == 50


def test_max_results_hard_cap_is_500_with_16000_budget(write_file) -> None:
    write_file("src/app.ts", "a\n" * 600)

    out = search_text(pattern="a", path="src", context_lines=0, max_results=10**6)

    s = summary_of(out)
    assert s["total"] == "600"
    assert s["returned"] == "500"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "500"
    assert s["budget"] == "16000/16000"
    assert len(locations(out)) == 500
    # Explicitly asking for the cap yields the identical page.
    assert search_text(
        pattern="a", path="src", context_lines=0, max_results=500
    ) == out
def test_order_deterministic_sorted_by_path_then_line(write_file) -> None:
    write_file("src/z.ts", "targetName\n")
    write_file("src/a.ts", "targetName\nx\ntargetName\n")

    first = search_text(pattern="targetName", path="src")
    second = search_text(pattern="targetName", path="src")

    assert first == second
    assert locations(first) == [
        ("src/a.ts", 1),
        ("src/a.ts", 3),
        ("src/z.ts", 1),
    ]


def test_context_lines_capped_at_code_limit_3(write_file) -> None:
    lines = [f"line {i}" if i != 5 else "line 5 targetName" for i in range(1, 12)]
    write_file("src/app.ts", "\n".join(lines) + "\n")

    out = search_text(pattern="targetName", path="src", context_lines=99)

    assert context_numbers(out) == list(range(2, 9))


def test_context_lines_coerced_up_from_negative(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    out = search_text(pattern="targetName", path="src", context_lines=-5)

    assert context_numbers(out) == [1]


def test_offset_negative_rejected(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        search_text(pattern="targetName", path="src", offset=-1)


def test_paging_by_offset_contiguous_no_gaps(write_file) -> None:
    write_file("src/app.ts", "targetName\n" * 12)

    p1 = search_text(
        pattern="targetName", path="src", context_lines=0, max_results=5, offset=0
    )
    p2 = search_text(
        pattern="targetName", path="src", context_lines=0, max_results=5, offset=5
    )
    p3 = search_text(
        pattern="targetName", path="src", context_lines=0, max_results=5, offset=10
    )

    assert [summary_of(p)["next_offset"] for p in (p1, p2)] == ["5", "10"]
    assert summary_of(p3)["has_more"] == "false"
    assert "next_offset" not in summary_of(p3)
    assert locations(p1) + locations(p2) + locations(p3) == [
        ("src/app.ts", n) for n in range(1, 13)
    ]


def test_default_budget_4000_expanded_16000(write_file) -> None:
    write_file("src/app.ts", ("x" * 150 + " targetName\n") * 60)

    default = search_text(pattern="targetName", path="src")
    assert len(default) <= 4000
    assert summary_of(default)["budget"] == "4000/16000"
    assert "[OUTPUT TRUNCATED" in default

    expanded = search_text(pattern="targetName", path="src", max_results=500)
    assert 4000 < len(expanded) <= 16000
    assert summary_of(expanded)["budget"] == "16000/16000"
    assert "[OUTPUT TRUNCATED" in expanded


def test_lines_clipped_at_200_chars(write_file) -> None:
    long_line = "y" * 300 + " targetName"
    write_file("src/app.ts", long_line + "\n")

    out = search_text(pattern="targetName", path="src")

    assert max(len(line) for line in out.splitlines()) <= 200


def test_2mb_file_skip_guard(repo, write_file) -> None:
    write_file("src/small.ts", "targetName\n")
    big_rel = write_file("src/big.ts", "targetName\n")
    big_abs = os.path.join(repo, big_rel.replace("/", os.sep))
    with open(big_abs, "r+b") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")

    out = search_text(pattern="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "1"
    assert locations(out) == [("src/small.ts", 1)]