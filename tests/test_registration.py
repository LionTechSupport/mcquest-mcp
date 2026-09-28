"""Regression: exactly the approved MCP tools remain registered.

No tool may be added, renamed, or removed beyond the approved set. V0.7
Phase 2 (DEC-008) added ``mcquest_find_strings`` (literal inventory).
V0.7 Stage 3 (DEC-012) added ``mcquest_locale_inspect`` (JSON locale
inspection). V0.7 Stage 4 (DEC-013 updated + DEC-014) added
``mcquest_component_inventory`` (lexical component inventory).

V0.8 (DEC-020/DEC-032/DEC-031/DEC-033/DEC-034/DEC-035): ``mcquest_find_ui_text``,
``mcquest_ui_contract_audit``, ``mcquest_doc_gap_audit``, and
``mcquest_feature_impact_audit`` are implemented (24 registered tools; the
expected count is reached with the last approved V0.8 tool).

V0.9 P2 (decision A11, phase 1 of 3): ``mcquest_shell_environment``,
``mcquest_shell_terminal``, ``mcquest_shell_context``, and
``mcquest_shell_capabilities`` are registered (24 -> 28).

V0.9 P4 (decision A11, phase 2 of 3): ``mcquest_shell_validate`` (full
deterministic validation report, including the ``lint`` mode) and
``mcquest_shell_observe`` (A14 observation ingestion and invalidation) are
registered (28 -> 30). ``shell_lint`` stays a mode of ``mcquest_shell_validate``;
no separate lint tool exists.
``EXPECTED_TOOLS`` remains the single registration authority (decision A12);
the ``shell/capabilities.py`` registry is metadata only and is drift-tested
against this list in both directions.
"""

from __future__ import annotations

import asyncio

from mcquest_mcp.server import mcp


EXPECTED_TOOLS = [
    "mcquest_compare_phase",
    "mcquest_component_inventory",
    "mcquest_diagnostics",
    "mcquest_doc_gap_audit",
    "mcquest_feature_impact_audit",
    "mcquest_find_evidence",
    "mcquest_find_files",
    "mcquest_find_imports",
    "mcquest_find_strings",
    "mcquest_find_ui_text",
    "mcquest_find_usages",
    "mcquest_git_context",
    "mcquest_list_docs",
    "mcquest_list_files",
    "mcquest_locale_inspect",
    "mcquest_pattern_audit",
    "mcquest_phase_context",
    "mcquest_project_context",
    "mcquest_project_info",
    "mcquest_read_doc",
    "mcquest_read_file",
    "mcquest_search",
    "mcquest_search_docs",
    "mcquest_shell_capabilities",
    "mcquest_shell_context",
    "mcquest_shell_environment",
    "mcquest_shell_observe",
    "mcquest_shell_terminal",
    "mcquest_shell_validate",
    "mcquest_ui_contract_audit",
]


def test_exactly_30_tools_remain_registered() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = sorted(tool.name for tool in tools)
    assert names == EXPECTED_TOOLS
    assert len(names) == 30


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


def test_mcquest_find_ui_text_parameter_descriptions_and_semantics() -> None:
    """mcquest_find_ui_text exposes a description per parameter (DEC-020/DEC-032)."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_find_ui_text")
    properties = tool.input_schema["properties"]

    for param in ("path", "file_pattern", "max_results", "offset", "classify"):
        assert param in properties
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    # Preserved schema semantics (DEC-032: classify defaults to true).
    assert tool.input_schema.get("required", []) == []
    assert properties["path"]["type"] == "string"
    assert properties["file_pattern"]["type"] == "string"
    assert properties["max_results"]["default"] == 50
    assert properties["max_results"]["type"] == "integer"
    assert properties["offset"]["default"] == 0
    assert properties["offset"]["type"] == "integer"
    assert properties["classify"]["default"] is True
    assert properties["classify"]["type"] == "boolean"


def test_mcquest_ui_contract_audit_parameter_descriptions_and_semantics() -> None:
    """mcquest_ui_contract_audit exposes a description per parameter (DEC-020)."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_ui_contract_audit")
    properties = tool.input_schema["properties"]

    for param in (
        "path",
        "component_pattern",
        "include_callers",
        "max_results",
        "offset",
    ):
        assert param in properties
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    # Preserved schema semantics (DEC-020: five approved inputs, no required).
    assert tool.input_schema.get("required", []) == []
    assert properties["path"]["type"] == "string"
    assert properties["component_pattern"]["type"] == "string"
    assert properties["include_callers"]["type"] == "boolean"
    assert properties["max_results"]["default"] == 50
    assert properties["max_results"]["type"] == "integer"
    assert properties["offset"]["default"] == 0
    assert properties["offset"]["type"] == "integer"
def test_mcquest_doc_gap_audit_parameter_descriptions_and_semantics() -> None:
    """mcquest_doc_gap_audit exposes a description per parameter (DEC-020/DEC-033)."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_doc_gap_audit")
    properties = tool.input_schema["properties"]

    for param in ("docs_path", "code_path", "max_results", "offset"):
        assert param in properties
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    # Preserved schema semantics (DEC-033: the four approved inputs only,
    # no required parameters, and never a feature_scope input).
    assert set(properties) == {"docs_path", "code_path", "max_results", "offset"}
    assert tool.input_schema.get("required", []) == []
    assert properties["docs_path"]["type"] == "string"
    assert properties["docs_path"]["default"] == "."
    assert properties["code_path"]["type"] == "string"
    assert properties["code_path"]["default"] == "."
    assert properties["max_results"]["default"] == 50
    assert properties["max_results"]["type"] == "integer"
    assert properties["offset"]["default"] == 0
    assert properties["offset"]["type"] == "integer"


def test_mcquest_feature_impact_audit_parameter_descriptions_and_semantics() -> None:
    """mcquest_feature_impact_audit exposes a description per parameter
    (DEC-019/DEC-034/DEC-035)."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_feature_impact_audit")
    properties = tool.input_schema["properties"]

    for param in (
        "target",
        "path",
        "max_results",
        "offset",
        "include_docs",
        "include_locales",
    ):
        assert param in properties
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    # Preserved schema semantics (DEC-034/DEC-035: the six approved inputs
    # only, ``target`` is the sole required input, and never a ``feature_scope``
    # input).
    assert set(properties) == {
        "target",
        "path",
        "max_results",
        "offset",
        "include_docs",
        "include_locales",
    }
    assert tool.input_schema.get("required", []) == ["target"]
    assert properties["target"]["type"] == "string"
    assert properties["path"]["type"] == "string"
    assert properties["path"]["default"] == "."
    assert properties["max_results"]["default"] == 50
    assert properties["max_results"]["type"] == "integer"
    assert properties["offset"]["default"] == 0
    assert properties["offset"]["type"] == "integer"
    assert properties["include_docs"]["default"] is True
    assert properties["include_docs"]["type"] == "boolean"
    assert properties["include_locales"]["default"] is True
    assert properties["include_locales"]["type"] == "boolean"
