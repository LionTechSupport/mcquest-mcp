"""Phase D regression: ``phase_context`` summary-first query mode.

Query mode now emits the canonical ``[SUMMARY]`` block + one explicit page
of at most ``max_results`` matches ordered by ``(relative_path ASC, line
ASC)`` with deterministic content ordering (D008/D009/D016). Phase mode
(``phase`` given) keeps the grouped structured lookup; when no grouped
matches exist it falls back to a content search without raising.
"""

from __future__ import annotations

import re

import pytest

from mcquest_mcp.tools.docs import phase_context


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


def test_query_mode_summary_first(write_file) -> None:
    write_file("docs/guide.md", "# Guide\n\noverflow in responsive layout\n")

    out = phase_context(query="overflow")

    assert out.startswith("[SUMMARY]\n")
    s = summary_of(out)
    assert s["tool"] == "mcquest_phase_context"
    assert s["scope"] == 'path="docs"'
    assert s["QUERY"] == "overflow"
    assert s["PATH"] == "docs"
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert s["returned"] == "1"
    assert s["budget"] == "4000/16000"
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("docs/guide.md", 3)]


def test_query_mode_deterministic_and_sorted(write_file) -> None:
    write_file("docs/z.md", "# Z\n\ntarget phrase\n")
    write_file("docs/a.md", "# A\n\ntarget phrase\ntarget phrase\n")

    first = phase_context(query="target phrase")
    second = phase_context(query="target phrase")

    assert first == second
    assert locations(first) == [("docs/a.md", 3), ("docs/a.md", 4), ("docs/z.md", 3)]


def test_query_mode_default_max_results_50(write_file) -> None:
    write_file("docs/guide.md", "# Guide\n\noverflow\n" * 40 + "overflow line\n" * 30)

    out = phase_context(query="overflow")

    s = summary_of(out)
    assert s["total"] == "70"
    assert int(s["returned"]) <= 50
    assert s["has_more"] == "true"
    assert int(s["next_offset"]) == int(s["returned"])


def test_query_mode_offset_rejected_when_negative(write_file) -> None:
    write_file("docs/guide.md", "overflow\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        phase_context(query="overflow", offset=-1)


def test_requires_query_or_phase(write_file) -> None:
    write_file("docs/guide.md", "x\n")

    with pytest.raises(ValueError):
        phase_context()


def test_phase_mode_grouped_structured_lookup(write_file) -> None:
    write_file("docs/phase-61-implementation.md", "# Phase 61 Implementation\n")
    write_file("docs/phase-61-audit.md", "# Phase 61 Audit\n")

    out = phase_context(query="unused", phase="61")

    assert out.startswith("PHASE: 61")
    assert "DOCUMENTS FOUND: 2" in out
    assert "## IMPLEMENTATION DOCUMENTS" in out
    assert "## AUDIT DOCUMENTS" in out


def test_phase_mode_falls_back_without_raising(write_file) -> None:
    write_file("docs/guide.md", "# Guide\n")

    out = phase_context(query="unused", phase="99")

    assert out.startswith("PHASE: 99")