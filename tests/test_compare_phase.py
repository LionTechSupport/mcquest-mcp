"""Regression for CHANGE A: evidence-neutral ``compare_phase`` vocabulary."""

from __future__ import annotations

import re

from mcquest_mcp.tools.docs import compare_phase


def test_compare_phase_uses_neutral_vocabulary(write_file) -> None:
    write_file("docs/phase-61-audit.md", "# Audit 61\n")
    write_file("docs/phase-61-implementation.md", "# Impl 61\n")
    write_file("docs/phase-61-phase-62-common.md", "# Shared\n")
    write_file("docs/phase-62-implementation.md", "# Impl 62\n")

    output = compare_phase(from_phase="61", to_phase="62", path="docs")

    # Required positive evidence
    assert "ADDED documents in 62" in output
    assert "REMOVED from 61" in output
    assert "COMMON documents: 1" in output
    assert "## ADDED in 62:" in output
    assert "## REMOVED (present in 61, absent in 62):" in output

    # Required explicit disclaimers
    assert "STATUS BASIS: document-existence/set diff only" in output
    assert "RUNTIME VERIFICATION: NOT PERFORMED" in output

    # Banned conclusion vocabulary must never be emitted by the MCP
    assert "RESOLVED" not in output
    assert "POTENTIAL REGRESSION" not in output
    assert not re.search(r"\bNEW\b", output)


def test_compare_phase_document_removal_is_not_resolution(write_file) -> None:
    # A document present in 61 but absent in 62 must be described as REMOVED,
    # never as RESOLVED.
    write_file("docs/phase-61-audit.md", "# Audit\n")

    output = compare_phase(from_phase="61", to_phase="62", path="docs")

    assert "## REMOVED (present in 61, absent in 62):" in output
    assert "RESOLVED" not in output