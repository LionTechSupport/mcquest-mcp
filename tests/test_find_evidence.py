"""Regression for CHANGE B (``find_evidence(scope="phase")`` fix).

The advertised ``phase`` scope previously matched no execution branch and
always returned zero results. It must now run a phase-scoped documentation
search using the existing phase-filtering mechanism, while ``code``, ``docs``,
and ``all`` keep their current behavior.
"""

from __future__ import annotations

import re

from mcquest_mcp.tools.context import find_evidence


def _total_matches(output: str) -> int:
    match = re.search(r"TOTAL MATCHES: (\d+)", output)
    return int(match.group(1)) if match else -1


def test_scope_phase_returns_phase_document_matches(write_file) -> None:
    write_file("src/app.ts", "export const overflowSource = 1;\n")
    write_file("docs/phase-61-audit.md", "Investigate overflowing header.\n")
    write_file("docs/phase-61-notes.md", "More overflow notes.\n")

    output = find_evidence(
        query="overflow",
        scope="phase",
        phase="61",
        path="src",
        docs_path="docs",
    )

    assert "## DOCUMENTATION EVIDENCE" in output
    assert "## CODE EVIDENCE" not in output
    assert _total_matches(output) == 2


def test_scope_phase_honors_phase_filter(write_file) -> None:
    write_file("docs/phase-61-audit.md", "overflow only in 61\n")
    write_file("docs/phase-62-audit.md", "overflow also here\n")

    output = find_evidence(
        query="overflow",
        scope="phase",
        phase="61",
        path="src",
        docs_path="docs",
    )

    assert _total_matches(output) == 1
    assert "phase-61-audit.md" in output
    assert "phase-62-audit.md" not in output


def test_code_scope_preserved(write_file) -> None:
    write_file("src/app.ts", "export const targetName = 1;\n")

    output = find_evidence(
        query="targetName", scope="code", path="src", docs_path="docs"
    )

    assert "## CODE EVIDENCE" in output
    assert "## DOCUMENTATION EVIDENCE" not in output
    assert _total_matches(output) == 1


def test_docs_scope_preserved(write_file) -> None:
    write_file("docs/guide.md", "targetName docs\n")

    output = find_evidence(
        query="targetName", scope="docs", path="src", docs_path="docs"
    )

    assert "## DOCUMENTATION EVIDENCE" in output
    assert "## CODE EVIDENCE" not in output
    assert _total_matches(output) == 1


def test_all_scope_preserved(write_file) -> None:
    write_file("src/app.ts", "targetName source\n")
    write_file("docs/guide.md", "targetName docs\n")

    output = find_evidence(
        query="targetName", scope="all", path="src", docs_path="docs"
    )

    assert "## CODE EVIDENCE" in output
    assert "## DOCUMENTATION EVIDENCE" in output
    assert _total_matches(output) == 2