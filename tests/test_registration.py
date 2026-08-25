"""Regression: exactly the 16 approved MCP tools remain registered.

No tool may be added, renamed, or removed by the v0.3 changes.
"""

from __future__ import annotations

import asyncio

from mcquest_mcp.server import mcp


EXPECTED_TOOLS = [
    "mcquest_compare_phase",
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


def test_exactly_16_tools_remain_registered() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = sorted(tool.name for tool in tools)
    assert names == EXPECTED_TOOLS
    assert len(names) == 16


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