"""Phase D regression: ``find_evidence`` merged-stream, summary-first paging.

Rewrite of the legacy suite for the canonical summary-first contract
(D003/D008/D009/D013/D016). ``scope=\"all\"`` reports an authoritative
``total = code + docs`` (never ``min(code, docs)``), per-scope ``counts:``
metadata, and ONE shared page budget over the deterministic merged stream
(code group first, then docs group; each ``(relative_path ASC, line ASC)``).
The ``phase`` scope maps to the documentation group and honors the ``phase``
filter (CHANGE B regression is preserved). Offset paging walks the merged
stream with no gaps or overlaps.
"""

from __future__ import annotations

import re

import pytest

from mcquest_mcp.tools.context import find_evidence


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


def test_code_scope_summary_with_echo_fields(write_file) -> None:
    write_file("src/app.ts", "targetName in code\n")

    out = find_evidence(query="targetName", scope="code", path="src", docs_path="docs")

    s = summary_of(out)
    assert s["tool"] == "mcquest_find_evidence"
    assert s["QUERY"] == "targetName"
    assert s["SCOPE"] == "code"
    assert s["counts"] == "code=1; docs=0"
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert s["returned"] == "1"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert 'query="targetName" scope="code" path="src" docs_path="docs"' in s["scope"]
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("src/app.ts", 1)]


def test_scope_code_ignores_docs(write_file) -> None:
    write_file("src/app.ts", "targetName in code\n")
    write_file("docs/guide.md", "targetName in docs\n")

    out = find_evidence(query="targetName", scope="code", path="src", docs_path="docs")

    s = summary_of(out)
    assert s["counts"] == "code=1; docs=0"
    assert s["total"] == "1"
    assert "docs/guide.md" not in out


def test_scope_docs_ignores_code(write_file) -> None:
    write_file("src/app.ts", "targetName in code\n")
    write_file("docs/guide.md", "targetName in docs\n")

    out = find_evidence(query="targetName", scope="docs", path="src", docs_path="docs")

    s = summary_of(out)
    assert s["counts"] == "code=0; docs=1"
    assert s["total"] == "1"
    assert "docs/guide.md" in out
    assert "src/app.ts" not in out


def test_scope_all_merged_order_code_then_docs(write_file) -> None:
    write_file("src/z.ts", "targetName\n")
    write_file("src/a.ts", "targetName\n")
    write_file("docs/z.md", "targetName\n")
    write_file("docs/a.md", "targetName\n")

    out = find_evidence(query="targetName", scope="all", path="src", docs_path="docs")

    s = summary_of(out)
    assert s["counts"] == "code=2; docs=2"
    assert s["total"] == "4"
    assert s["files_affected"] == "4"
    # Code group first, then docs group; each sorted (path, line).
    assert locations(out) == [
        ("src/a.ts", 1),
        ("src/z.ts", 1),
        ("docs/a.md", 1),
        ("docs/z.md", 1),
    ]


def test_all_scope_total_is_authoritative_sum_never_min(write_file) -> None:
    # 1 code match + 5 doc matches: a min() bug would report total=1.
    write_file("src/app.ts", "targetName\n")
    for i in range(5):
        write_file(f"docs/d{i}.md", "targetName\n")

    out = find_evidence(query="targetName", scope="all", path="src", docs_path="docs")

    s = summary_of(out)
    assert s["counts"] == "code=1; docs=5"
    assert s["total"] == "6"
    assert s["returned"] == "6"
    assert len(locations(out)) == 6
def test_shared_page_budget_across_merged_stream(write_file) -> None:
    write_file("src/a.ts", "targetName\n")
    write_file("src/b.ts", "targetName\n")
    for i in range(5):
        write_file(f"docs/d{i}.md", "targetName\n")

    out = find_evidence(
        query="targetName", scope="all", path="src", docs_path="docs",
        max_results=4,
    )

    s = summary_of(out)
    assert s["total"] == "7"
    assert s["returned"] == "4"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "4"
    # The single page budget consumed BOTH code matches and part of docs.
    assert locations(out) == [
        ("src/a.ts", 1),
        ("src/b.ts", 1),
        ("docs/d0.md", 1),
        ("docs/d1.md", 1),
    ]


def test_offset_paging_walks_merged_stream_no_gaps(write_file) -> None:
    write_file("src/a.ts", "targetName\n")
    write_file("src/b.ts", "targetName\n")
    for i in range(3):
        write_file(f"docs/d{i}.md", "targetName\n")
    expected = [
        ("src/a.ts", 1),
        ("src/b.ts", 1),
        ("docs/d0.md", 1),
        ("docs/d1.md", 1),
        ("docs/d2.md", 1),
    ]

    seen: list[tuple[str, int]] = []
    offset = 0
    pages = 0
    while True:
        out = find_evidence(
            query="targetName", scope="all", path="src", docs_path="docs",
            max_results=2, offset=offset,
        )
        s = summary_of(out)
        page = locations(out)
        assert page == expected[offset : offset + len(page)]
        seen.extend(page)
        pages += 1
        if s["has_more"] == "true":
            offset = int(s["next_offset"])
        else:
            assert "next_offset" not in s
            break

    assert seen == expected
    assert pages == 3


def test_offset_negative_rejected(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        find_evidence(query="targetName", path="src", offset=-1)


def test_context_lines_capped_at_5(write_file) -> None:
    lines = [f"line {i}" if i != 7 else "line 7 targetName" for i in range(1, 14)]
    write_file("src/app.ts", "\n".join(lines) + "\n")

    out = find_evidence(
        query="targetName", scope="code", path="src", context_lines=99
    )

    assert context_numbers(out) == list(range(2, 13))


def test_phase_scope_maps_to_docs_group(write_file) -> None:
    write_file("src/app.ts", "targetName in code\n")
    write_file("docs/phase-61-audit.md", "targetName in 61\n")

    out = find_evidence(
        query="targetName", scope="phase", phase="61",
        path="src", docs_path="docs",
    )

    s = summary_of(out)
    assert s["SCOPE"] == "phase"
    assert s["PHASE"] == "61"
    assert s["counts"] == "code=0; docs=1"
    assert s["total"] == "1"
    assert "src/app.ts" not in out
    assert locations(out) == [("docs/phase-61-audit.md", 1)]


def test_phase_scope_honors_phase_filter(write_file) -> None:
    write_file("docs/phase-61-audit.md", "targetName\n")
    write_file("docs/phase-62-audit.md", "targetName\n")

    out = find_evidence(
        query="targetName", scope="phase", phase="61",
        path="src", docs_path="docs",
    )

    s = summary_of(out)
    assert s["total"] == "1"
    assert "phase-61-audit.md" in out
    assert "phase-62-audit.md" not in out


def test_phase_filter_honored_within_all_scope(write_file) -> None:
    write_file("src/app.ts", "targetName\n")
    write_file("docs/phase-61-audit.md", "targetName\n")
    write_file("docs/phase-62-audit.md", "targetName\n")

    out = find_evidence(
        query="targetName", scope="all", phase="61",
        path="src", docs_path="docs",
    )

    s = summary_of(out)
    assert s["counts"] == "code=1; docs=1"
    assert s["total"] == "2"
    assert "phase-62-audit.md" not in out


def test_repeated_calls_byte_identical(write_file) -> None:
    write_file("src/app.ts", "targetName\n" * 3)
    write_file("docs/guide.md", "targetName\n" * 2)

    first = find_evidence(query="targetName", scope="all", path="src", docs_path="docs")
    second = find_evidence(query="targetName", scope="all", path="src", docs_path="docs")

    assert first == second


def test_invalid_scope_rejected(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    with pytest.raises(ValueError, match="Scope must be one of"):
        find_evidence(query="targetName", scope="bogus", path="src")


def test_empty_query_rejected(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    with pytest.raises(ValueError, match="Query cannot be empty"):
        find_evidence(query="   ", path="src")