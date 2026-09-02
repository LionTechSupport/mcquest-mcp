"""Regression: exactly the 17 approved MCP tools remain registered.

No tool may be added, renamed, or removed by the v0.3/v0.4 changes.
"""

from __future__ import annotations

import asyncio

from mcquest_mcp.server import mcp


EXPECTED_TOOLS = [
    "mcquest_compare_phase",
    "mcquest_diagnostics",
    "mcquest_find_evidence",
    "mcquest_find_files",
    "mcquest_find_imports",
    "mcquest_find_usages",
    "mcquest_git_context",
    "mcquest_list_docs",
    "mcquest_list_files",
    "mcquest_pattern_audit",
    "mcquest_phase_context",
    "mcquest_project_context",
    "mcquest_project_info",
    "mcquest_read_doc",
    "mcquest_read_file",
    "mcquest_search",
    "mcquest_search_docs",
]


def test_exactly_17_tools_remain_registered() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = sorted(tool.name for tool in tools)
    assert names == EXPECTED_TOOLS
    assert len(names) == 17


def test_mcquest_read_file_parameter_descriptions_and_semantics() -> None:
    """mcquest_read_file exposes a description per parameter and keeps schema semantics."""
    tools = asyncio.run(mcp.list_tools())
    read_file = next(t for t in tools if t.name == "mcquest_read_file")
    properties = read_file.input_schema["properties"]

    for param in ("path", "start_line", "end_line"):
        assert param in properties
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    # Preserved schema semantics.
    assert read_file.input_schema["required"] == ["path"]
    assert properties["path"]["type"] == "string"
    assert properties["start_line"]["default"] == 1
    assert properties["start_line"]["type"] == "integer"
    assert properties["end_line"]["default"] is None


def test_mcquest_diagnostics_parameter_descriptions_and_semantics() -> None:
    """mcquest_diagnostics exposes a description per parameter and keeps schema semantics."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_diagnostics")
    properties = tool.input_schema["properties"]

    for param in (
        "path",
        "context_lines",
        "max_diagnostics",
        "line",
        "column",
        "diagnostic_kind",
    ):
        assert param in properties
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    # Preserved schema semantics.
    assert tool.input_schema["required"] == ["path"]
    assert properties["path"]["type"] == "string"
    assert properties["context_lines"]["default"] == 12
    assert properties["context_lines"]["type"] == "integer"
    assert properties["max_diagnostics"]["default"] == 20
    assert properties["max_diagnostics"]["type"] == "integer"
    assert properties["line"]["default"] is None
    assert properties["column"]["default"] is None
    assert properties["diagnostic_kind"]["default"] == "syntax"