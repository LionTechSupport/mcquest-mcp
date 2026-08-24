from __future__ import annotations

from mcp.server import MCPServer

from .tools import (
    compare_phase,
    find_evidence,
    find_files,
    find_imports,
    find_usages,
    git_context,
    list_docs,
    list_files,
    pattern_audit,
    phase_context,
    project_context,
    project_info,
    read_doc,
    read_file,
    search_docs,
    search_text,
)


mcp = MCPServer(
    "MCQuest Read-Only MCP",
    instructions=(
        "MCQuest repository intelligence server. "
        "All tools are strictly read-only. "
        "Never modify, create, delete, rename, or execute project files. "
        "Use these tools for deterministic source-code evidence. "
        "Perform architectural reasoning in the client."
    ),
)


@mcp.tool()
def mcquest_project_info() -> str:
    """READ ONLY. Get a compact overview of the MCQuest project structure and important files. Returns project root, top-level directories, and key configuration files. Use this as the first context call before a large investigation."""
    return project_info()


@mcp.tool()
def mcquest_list_files(
    path: str = ".",
    pattern: str = "*",
    max_results: int = 200,
) -> str:
    """READ ONLY. List source files under a project directory. Excludes node_modules, .git, build output, virtual environments, and other generated/dependency directories. Returns relative file paths. Prefer this over searching when you know which directory to inspect."""
    return list_files(
        path=path,
        pattern=pattern,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_read_file(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    """READ ONLY. Read a source file with exact line numbers. Use line ranges whenever possible instead of requesting entire files to reduce token consumption. Returns line-numbered content."""
    return read_file(
        path=path,
        start_line=start_line,
        end_line=end_line,
    )


@mcp.tool()
def mcquest_search(
    pattern: str,
    path: str = "frontend/src",
    file_pattern: str = "*",
    case_sensitive: bool = False,
    context_lines: int = 1,
    max_results: int = 200,
) -> str:
    """READ ONLY. Search MCQuest source files using a regular expression. Returns exact relative file paths, line numbers, matching lines, and limited surrounding context. Prefer this for locating code patterns."""
    return search_text(
        pattern=pattern,
        path=path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        context_lines=context_lines,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_find_files(
    query: str,
    path: str = ".",
    max_results: int = 200,
) -> str:
    """READ ONLY. Find project files by filename using case-insensitive substring matching. Returns relative file paths. Use when you know a filename but not its location."""
    return find_files(
        query=query,
        path=path,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_find_imports(
    target: str,
    path: str = "frontend/src",
    max_results: int = 200,
) -> str:
    """READ ONLY. Find ES module imports that reference a target component/module. Searches .ts, .tsx, .js, .jsx files. Returns file:line:import-statement. Useful for discovering which files depend on a module."""
    return find_imports(
        target=target,
        path=path,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_find_usages(
    symbol: str,
    path: str = "frontend/src",
    file_pattern: str = "*",
    max_results: int = 200,
) -> str:
    """READ ONLY. Find references to a symbol across MCQuest source files using word-boundary matching. Returns file:line:line-content. Use for discovering where a component, function, or variable is used."""
    return find_usages(
        symbol=symbol,
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_pattern_audit(
    path: str = "frontend/src",
    categories: str = "all",
    max_results_per_category: int = 100,
) -> str:
    """READ ONLY. Run predefined MCQuest responsive/layout pattern searches. Categories include: viewport-width, large-min-width, large-fixed-width, nowrap, negative-horizontal-margin, horizontal-transform, negative-position, overflow-x, min-width, fixed-position, sticky-position, or 'all'. Returns evidence only — no modifications. Use for auditing potential mobile/responsive issues."""
    return pattern_audit(
        path=path,
        categories=categories,
        max_results_per_category=max_results_per_category,
    )


@mcp.tool()
def mcquest_list_docs(
    path: str = "docs",
    pattern: str = "*.md",
    max_results: int = 200,
) -> str:
    """READ ONLY. List Markdown documentation files under a project directory. Excludes dependency/generated directories and non-Markdown files. Returns relative file paths. Use to discover available documentation before reading specific files."""
    return list_docs(
        path=path,
        pattern=pattern,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_read_doc(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    """READ ONLY. Read a Markdown documentation file with exact line numbers. Use line ranges whenever possible instead of requesting huge files. Returns line-numbered Markdown content."""
    return read_doc(
        path=path,
        start_line=start_line,
        end_line=end_line,
    )


@mcp.tool()
def mcquest_search_docs(
    pattern: str,
    path: str = "docs",
    file_pattern: str = "*.md",
    case_sensitive: bool = False,
    context_lines: int = 1,
    max_results: int = 200,
) -> str:
    """READ ONLY. Search Markdown documentation using a regex or text pattern. Returns exact file paths, line numbers, matching lines, and limited surrounding context. Prefer this for finding specific topics across all documentation."""
    return search_docs(
        pattern=pattern,
        path=path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        context_lines=context_lines,
        max_results=max_results,
    )


@mcp.tool()
def mcquest_phase_context(
    query: str = "",
    phase: str = "",
    path: str = "docs",
    max_results: int = 50,
    context_lines: int = 2,
    include_implementation: bool = True,
    include_audits: bool = True,
) -> str:
    """READ ONLY. Locate relevant phase/stage documentation. Use EITHER 'query' (free-text search, e.g. 'responsive overflow', 'Android') OR 'phase' (phase number, e.g. '61', '61-Part-II-A'). When 'phase' is provided, results are grouped by document type (implementation reports, audits, completions). Returns each match with its nearest heading, line numbers, and surrounding context. Preserves original evidence. Works for past and future phases."""
    return phase_context(
        query=query,
        phase=phase,
        path=path,
        max_results=max_results,
        context_lines=context_lines,
        include_implementation=include_implementation,
        include_audits=include_audits,
    )


@mcp.tool()
def mcquest_project_context() -> str:
    """READ ONLY. Provide a compact high-level understanding of the MCQuest project. Returns technology stack, major directories, important source areas, documentation paths, and key configuration files. Use this as the first context call before a large investigation."""
    return project_context()


@mcp.tool()
def mcquest_find_evidence(
    query: str,
    phase: str = "",
    scope: str = "all",
    path: str = "frontend/src",
    docs_path: str = "docs",
    max_results: int = 50,
    context_lines: int = 1,
) -> str:
    """READ ONLY. Search across code, documentation, and phase evidence in a single call. Returns results grouped by CODE EVIDENCE and DOCUMENTATION EVIDENCE. Scope can be 'code', 'docs', 'phase', or 'all'. Optionally filter by phase. Use this instead of separately searching code and docs."""
    return find_evidence(
        query=query,
        phase=phase,
        scope=scope,
        path=path,
        docs_path=docs_path,
        max_results=max_results,
        context_lines=context_lines,
    )


@mcp.tool()
def mcquest_git_context(
    max_commits: int = 10,
    max_changes: int = 50,
) -> str:
    """READ ONLY. Provide read-only Git investigation information. Returns current branch, working-tree status, recent commits, and recently changed files. Does NOT perform commits, adds, resets, checkouts, merges, rebases, pushes, or pulls. Use to understand recent changes and current branch state."""
    return git_context(
        max_commits=max_commits,
        max_changes=max_changes,
    )


@mcp.tool()
def mcquest_compare_phase(
    from_phase: str,
    to_phase: str,
    path: str = "docs",
    max_results: int = 50,
) -> str:
    """READ ONLY. Compare documentation evidence between two phases. Returns differences in document sets using terminology: EXISTING, RESOLVED, NEW, POTENTIAL REGRESSION, UNKNOWN. Use to understand what changed between phases."""
    return compare_phase(
        from_phase=from_phase,
        to_phase=to_phase,
        path=path,
        max_results=max_results,
    )


def main() -> None:
    """
    Start the MCQuest MCP server over stdio for local MCP hosts such as Cline.
    """
    mcp.run()


if __name__ == "__main__":
    main()