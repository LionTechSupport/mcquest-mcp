"""Regression: P0/P1/P2 agent-discoverability improvements stay in place.

Guards the server-level agent instructions (P0), the generic selected-project
tool descriptions (P1), and the search-parameter UX details (P2) so future
edits cannot silently reintroduce MCQuest-only wording or drop the
tool-selection guidance.
"""

from __future__ import annotations

import asyncio

from mcquest_mcp.server import mcp


def _tool(name: str):
    tools = asyncio.run(mcp.list_tools())
    return next(t for t in tools if t.name == name)


def test_server_instructions_communicate_tool_selection_policy() -> None:
    assert mcp.instructions is not None
    text = mcp.instructions.lower()

    # Read-only identity and arbitrary selected project root.
    assert "read-only" in text
    assert "selected " in text
    assert "--project" in text.lower() or "mcquest_project_root" in text

    # Tool-selection guidance: documentation, source, files-by-name,
    # read-known-files, dependency/reference investigation.
    assert "mcquest_search_docs" in mcp.instructions
    assert "mcquest_search" in mcp.instructions
    assert "mcquest_find_files" in mcp.instructions
    assert "mcquest_read_doc" in mcp.instructions
    assert "mcquest_find_imports" in mcp.instructions
    assert "mcquest_diagnostics" in mcp.instructions

    # Shell is an accepted fallback, not universally prohibited.
    assert "shell remains acceptable" in text


def test_diagnostics_description_is_discoverable_for_compiler_errors() -> None:
    """Cline should clearly select mcquest_diagnostics for parser/compiler errors."""
    desc = _tool("mcquest_diagnostics").description

    # Read-only identity and the exact redirection guidance required.
    assert desc.startswith("READ ONLY.")
    assert (
        "Use this instead of reading the entire source file when the "
        "compiler/parser has already identified a location." in desc
    )
    assert "selected project" in desc
    assert "TypeScript/TSX/JavaScript/JSX" in desc

    # Trigger phrases that must make the tool obvious for compiler diagnostics.
    for trigger in (
        "'}' expected",
        "')' expected",
        "']' expected",
        "TS1005",
        "parser",
        "compiler",
        "line/column",
        "large .tsx",
        "node_modules/typescript",
    ):
        assert trigger in desc, f"description missing trigger {trigger!r}"

    # Never claims MCQuest-only scope.
    assert "MCQuest project" not in desc


def test_search_docs_description_is_preferred_documentation_search_tool() -> None:
    desc = _tool("mcquest_search_docs").description
    assert "PREFERRED TOOL FOR DOCUMENTATION SEARCH" in desc
    assert "Select-String" in desc
    assert "mcquest_search" in desc


def test_search_description_is_generic_and_distinguished_from_docs() -> None:
    desc = _tool("mcquest_search").description
    assert "selected project" in desc
    assert "mcquest_search_docs" in desc

def test_search_exclude_pattern_parameter_described() -> None:
    """Stage 1: exclude_pattern is exposed with actionable, accurate docs."""
    props = _tool("mcquest_search").input_schema["properties"]
    assert "exclude_pattern" in props
    description = props["exclude_pattern"]["description"]
    assert "regex" in description
    assert "overlap" in description
    assert "case_sensitive" in description
    assert "Defaults to ''" in description
    assert props["exclude_pattern"]["default"] == ""


def test_component_inventory_description_states_lexical_candidate_honesty() -> None:
    """Stage 4: the component inventory is unmistakably lexical, not verified."""
    desc = _tool("mcquest_component_inventory").description

    # Read-only identity and the supported extension set.
    assert desc.startswith("READ ONLY.")
    assert ".js, .jsx, .ts, .tsx" in desc
    assert ".d.ts files are excluded" in desc

    # The five binding description requirements (spec section 11).
    assert "LEXICAL CANDIDATES" in desc
    assert "false positives and false negatives are possible" in desc
    assert "comments and strings are NOT stripped" in desc
    assert "zero result does NOT prove that no components exist" in desc
    assert "function, arrow, or class" in desc

    # Approved semantics that must not silently drift.
    assert "Anonymous default declarations are skipped" in desc
    assert "not gated on a React base class" in desc
    assert "ASCII [A-Z][A-Za-z0-9_]* case-sensitively" in desc
    assert "deduplicated" in desc
    assert "collection_complete" in desc
    assert "does NOT mean every row was delivered" in desc


def test_component_inventory_parameter_descriptions_and_schema() -> None:
    props = _tool("mcquest_component_inventory").input_schema["properties"]
    for param in ("path", "file_pattern", "max_results", "offset"):
        description = props[param].get("description")
        assert isinstance(description, str) and description.strip(), param
    assert props["path"]["default"] == "."
    assert props["file_pattern"]["default"] == ""
    assert props["max_results"]["default"] == 50
    assert props["offset"]["default"] == 0


def test_locale_inspect_description_states_json_and_reference_semantics() -> None:
    """Stage 3: the JSON locale inspector is unmistakable and honest."""
    desc = _tool("mcquest_locale_inspect").description
    # Read-only identity and JSON-only scope.
    assert desc.startswith("READ ONLY.")
    assert ".json" in desc
    # Reference semantics: explicit only, never an inferred default locale.
    assert "reference='' means structure/collision/duplicate inspection only" in desc
    assert "no default locale is ever inferred" in desc
    # MISSING/EXTRA direction is spelled out.
    assert "MISSING = present in reference, absent in target" in desc
    assert "EXTRA = present in target, absent in reference" in desc
    # Duplicate-preserving parse + last-occurrence effective structure.
    assert "Duplicate-preserving parse" in desc
    assert "effective structure follows the last occurrence" in desc
    assert "shadowed earlier subtrees" in desc
    # Typed-path display honesty: "0" vs [0].
    assert "'0' is a string key, [0] an array index" in desc
    # Honest completeness: comparisons disabled => collection_complete=false.
    assert (
        "collection_complete=false whenever comparisons are disabled" in desc
    )

def test_no_tool_description_claims_mcquest_only_scope() -> None:
    for tool in asyncio.run(mcp.list_tools()):
        desc = tool.description or ""
        assert "MCQuest project" not in desc, tool.name
        assert "MCQuest source files" not in desc, tool.name
        assert "MCQuest responsive" not in desc, tool.name


def test_search_docs_parameter_descriptions_support_shell_translation() -> None:
    props = _tool("mcquest_search_docs").input_schema["properties"]

    pattern = props["pattern"]["description"]
    assert "foo|bar|baz" in pattern

    path = props["path"]["description"]
    assert "'docs'" in path

    file_pattern = props["file_pattern"]["description"]
    assert "basename" in file_pattern


# --- V0.6 Phase 1 discoverability hardening ----------------------------------


def test_find_usages_description_states_scan_scope() -> None:
    desc = _tool("mcquest_find_usages").description
    # The TS/TSX/JS/JSX-only limitation is now explicit so a 0-result on other
    # languages is not mistaken for "no references anywhere".
    assert ".ts, .tsx, .js, .jsx" in desc
    assert "TypeScript/TSX/JavaScript/JSX" in desc
    assert "other languages report total: 0" in desc
    # Stage 2: the lexical-not-semantic ceiling must be unmistakable.
    assert "lexical word-boundary matches" in desc
    assert "NOT semantic" in desc
    assert "declarations, comments, and string literals" in desc
    assert "no import, alias, module, scope, or language resolution" in desc


def test_find_usages_symbol_parameter_states_lexical_honesty() -> None:
    props = _tool("mcquest_find_usages").input_schema["properties"]
    symbol = props["symbol"]["description"]
    assert "word-boundary" in symbol
    assert "not resolved references" in symbol
    assert "declarations, comments, and string literals" in symbol


def test_find_evidence_description_states_code_stream_language_scope() -> None:
    desc = _tool("mcquest_find_evidence").description
    assert ".ts, .tsx, .js, .jsx, .css" in desc
    assert "docs stream scans Markdown" in desc
    assert "collection_complete=true means the authoritative total/count is known" in desc
    assert "does NOT mean every result was delivered" in desc


def test_phase_and_compare_phases_state_naming_convention() -> None:
    for name in ("mcquest_phase_context", "mcquest_compare_phase"):
        desc = _tool(name).description
        assert "phase-<id>" in desc
        assert "naming convention" in desc
        assert "'phase-61'" in desc


def test_pattern_audit_description_states_summary_first_and_expansion() -> None:
    desc = _tool("mcquest_pattern_audit").description
    assert "summary-first" in desc
    assert "[CATEGORY COUNTS]" in desc
    assert "no uncontrolled category dump" in desc
    assert "'category' parameter" in desc
    assert "4,000-character" in desc
    assert "16,000-character" in desc

    props = _tool("mcquest_pattern_audit").input_schema["properties"]
    assert "category" in props
    for trigger in (
        "overrides 'categories'",
        "sticky-position",
        "Valid values",
        "summary mode",
    ):
        assert trigger in props["category"]["description"]


def test_server_instructions_clarify_collection_complete_semantics() -> None:
    text = mcp.instructions
    assert "collection_complete=true" in text
    assert "NOT mean every result" in text
    assert "'has_more=true'" in text


# --- V0.8 audit tools (DEC-020) ----------------------------------------------


def test_ui_contract_audit_description_is_discoverable_for_prop_drift() -> None:
    """Cline should select mcquest_ui_contract_audit for component-prop drift."""
    desc = _tool("mcquest_ui_contract_audit").description

    assert desc.startswith("READ ONLY.")
    for trigger in (
        "prop contracts",
        ".js/.jsx/.ts/.tsx",
        "missing_prop",
        "stale_prop",
        "mismatched_usage",
        "signature_drift",
        "unverifiable",
        "DEC-022",
        "DEC-023",
        "DEC-031",
        "risk is never emitted",
        "heuristic",
        "A zero result means no lexical findings",
    ):
        assert trigger in desc, f"description missing trigger {trigger!r}"
    assert "MCQuest project" not in desc


def test_server_instructions_mention_the_v0_8_audit_tools() -> None:
    text = mcp.instructions
    assert "mcquest_find_ui_text" in text
    assert "mcquest_ui_contract_audit" in text
    assert "mcquest_doc_gap_audit" in text


def test_doc_gap_audit_description_is_discoverable_for_stale_doc_references() -> None:
    """Cline should select mcquest_doc_gap_audit for stale documentation references."""
    desc = _tool("mcquest_doc_gap_audit").description

    assert desc.startswith("READ ONLY.")
    for trigger in (
        "stale_reference",
        "backtick-delimited",
        "path-like",
        ".md/.markdown/.mdown/.mkd",
        "DEC-033",
        "2000",
        "500",
        "collection_complete",
        "heuristic",
        "NOT EMITTABLE",
        "bounded scan only",
        "repository-global total",
    ):
        assert trigger in desc, f"description missing trigger {trigger!r}"
    assert "MCQuest project" not in desc