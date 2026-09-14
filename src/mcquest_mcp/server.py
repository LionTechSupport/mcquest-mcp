from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from .tools import (
    compare_phase,
    diagnostics,
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
        "Read-only repository investigation server operating against the selected "
        "project root (set via --project or MCQUEST_PROJECT_ROOT); that root may "
        "be any repository, not necessarily MCQuest. All tools are strictly "
        "read-only: never modify, create, delete, rename, or execute project "
        "files. When an MCP tool provides the required repository evidence, "
        "prefer it over an equivalent shell command (e.g. grep, rg, "
        "Select-String, Get-ChildItem). Use mcquest_search_docs for "
        "Markdown/documentation searches, mcquest_search for source-code regex "
        "searches, mcquest_find_files to locate files by name, "
        "mcquest_read_file / mcquest_read_doc to read known files, and "
        "mcquest_find_usages / mcquest_find_imports for dependency/reference "
        "investigation. Use mcquest_diagnostics for TypeScript/TSX/JavaScript/JSX "
        "parser or compiler diagnostics; when the compiler/parser has already "
        "identified an error location, use it instead of reading the entire "
        "large source file. In every tool output, 'collection_complete=true' "
        "means the collection total/count is complete and authoritative - it does "
        "NOT mean every result was delivered on the current page; treat "
        "'has_more=true', 'next_offset' and 'next_start_line' as continuation "
        "signals and page explicitly. Shell remains acceptable when the MCP does not "
        "provide the required operation or the operation is outside repository "
        "investigation. Perform reasoning in the client."
    ),
)


@mcp.tool()
def mcquest_project_info() -> str:
    """READ ONLY. Get a compact overview of the selected project structure and important files. Returns project root, top-level directories, and key configuration files. Use this as the first context call before a large investigation."""
    return project_info()


@mcp.tool()
def mcquest_list_files(
    path: Annotated[str, Field(description="Project-relative directory to list files under. Defaults to the project root.")] = ".",
    pattern: Annotated[str, Field(description="Glob pattern filtering which files to include. Defaults to '*' (all files).")] = "*",
    max_results: Annotated[int, Field(description="Maximum number of file paths to return on this page. Defaults to 100 (hard cap 300).")] = 100,
    offset: Annotated[int, Field(description="Zero-based index of the first result to return on this page. Use the previous page's next_offset to continue. Defaults to 0.")] = 0,
) -> str:
    """READ ONLY. List source files under a project directory. Excludes node_modules, .git, build output, virtual environments, and other generated/dependency directories. Returns a summary (total, returned, next_offset, has_more) followed by relative file paths, paged deterministically by path. Prefer this over searching when you know which directory to inspect."""
    return list_files(
        path=path,
        pattern=pattern,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_read_file(
    path: Annotated[str, Field(description="Project-relative path to the source file to read, e.g. 'src/app.ts'.")],
    start_line: Annotated[int, Field(description="1-based line number to start reading from. Defaults to 1.")] = 1,
    end_line: Annotated[
        int | None,
        Field(description="1-based inclusive end line (clamped to a 1,000-line window), or null to read a bounded default window of at most 250 lines starting at start_line."),
    ] = None,
) -> str:
    """READ ONLY. Read a source file with exact line numbers. Use line ranges whenever possible instead of requesting entire files to reduce token consumption. Returns line-numbered content. Unranged reads return a bounded window with continuation metadata (start_line, end_line, total_lines, next_start_line, has_more)."""
    return read_file(
        path=path,
        start_line=start_line,
        end_line=end_line,
    )


@mcp.tool()
def mcquest_diagnostics(
    path: Annotated[str, Field(description="Project-relative source file to diagnose, e.g. 'src/TeacherDashboard.tsx'. Supported file types: .ts, .tsx, .js, .jsx.")],
    context_lines: Annotated[int, Field(description="Number of source lines surrounding each diagnostic to include. Bounded to 0-25. Defaults to 12.")] = 12,
    max_diagnostics: Annotated[int, Field(description="Maximum number of diagnostics to return. Bounded to 1-50. Defaults to 20.")] = 20,
    line: Annotated[int | None, Field(description="When provided, only diagnostics on this 1-based source line are returned. Useful for focusing on one compiler error location.")] = None,
    column: Annotated[int | None, Field(description="When provided (usually together with line), only diagnostics at this 1-based source column are returned.")] = None,
    diagnostic_kind: Annotated[str, Field(description="Kind of diagnostics to return. This version supports only 'syntax'. Defaults to 'syntax'.")] = "syntax",
) -> str:
    """READ ONLY. Use this tool when Cline receives or needs to investigate a TypeScript/TSX/JavaScript/JSX parser or compiler diagnostic. Prefer this tool over reading an entire large source file when the problem can be diagnosed from compiler/parser diagnostics plus a small source context window. Returns compact syntax diagnostics (e.g. TS1005 "'}' expected", "')' expected", "']' expected", unexpected token, unterminated string/template, JSX closing-tag problems, malformed generic/type syntax) with exact 1-based line/column, a small number of surrounding source lines, and TypeScript-provided related locations (such as the opening '{' that caused a parser mismatch). Works on large .tsx files without returning the whole file. Uses the selected project's own Node runtime and project-local TypeScript compiler parser (node_modules/typescript); returns "TypeScript compiler unavailable in selected project." when the project has no TypeScript installation. Strictly read-only: never modifies files and never executes application code. Use this instead of reading the entire source file when the compiler/parser has already identified a location."""
    return diagnostics(
        path=path,
        context_lines=context_lines,
        max_diagnostics=max_diagnostics,
        line=line,
        column=column,
        diagnostic_kind=diagnostic_kind,
    )


@mcp.tool()
def mcquest_search(
    pattern: Annotated[str, Field(description="Regular expression or text pattern to search for in source files. Supports regex alternation, e.g. 'foo|bar|baz'.")],
    path: Annotated[str, Field(description="Project-relative directory to search. Defaults to 'frontend/src'; set it explicitly, e.g. 'src', when the selected project uses a different layout.")] = "frontend/src",
    file_pattern: Annotated[str, Field(description="Filename glob restricting which files are searched; matches the file's basename, not the full path. Defaults to '*' (all files).")] = "*",
    case_sensitive: Annotated[bool, Field(description="When true, matching is case-sensitive. Defaults to false.")] = False,
    context_lines: Annotated[int, Field(description="Number of surrounding context lines to include per match. Bounded to 0-3. Defaults to 1.")] = 1,
    max_results: Annotated[int, Field(description="Maximum number of matches to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first match to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Search source files in the selected project using a regular expression. Returns a summary (total, files_affected, returned, next_offset, has_more, truncated) followed by matching lines with limited surrounding context, paged deterministically by (path, line). Use for source-code pattern searches; use mcquest_search_docs for Markdown/documentation searches."""
    return search_text(
        pattern=pattern,
        path=path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        context_lines=context_lines,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_find_files(
    query: Annotated[str, Field(description="Case-insensitive substring to match against file names.")],
    path: Annotated[str, Field(description="Project-relative directory to search. Defaults to the project root.")] = ".",
    max_results: Annotated[int, Field(description="Maximum number of file paths to return on this page. Defaults to 100 (hard cap 300).")] = 100,
    offset: Annotated[int, Field(description="Zero-based index of the first result to return on this page. Use the previous page's next_offset to continue. Defaults to 0.")] = 0,
) -> str:
    """READ ONLY. Find project files by filename using case-insensitive substring matching. Returns a summary (total, returned, next_offset, has_more) followed by relative file paths, paged deterministically by path. Use when you know a filename but not its location."""
    return find_files(
        query=query,
        path=path,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_find_imports(
    target: Annotated[str, Field(description="Module, component, or file the ES imports must reference.")],
    path: Annotated[str, Field(description="Project-relative directory to search. Defaults to 'frontend/src'.")] = "frontend/src",
    max_results: Annotated[int, Field(description="Maximum number of import statements to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first result to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Find ES module imports that reference a target component/module. Searches .ts, .tsx, .js, .jsx files. Returns a summary (total, files_affected, returned, next_offset, has_more) followed by file:line:import-statement, paged deterministically by (path, line). Useful for discovering which files depend on a module."""
    return find_imports(
        target=target,
        path=path,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_find_usages(
    symbol: Annotated[str, Field(description="Symbol name to find references for (word-boundary matched).")],
    path: Annotated[str, Field(description="Project-relative directory to search. Defaults to 'frontend/src'.")] = "frontend/src",
    file_pattern: Annotated[str, Field(description="Glob pattern filtering which files to search. Defaults to '*' (all files).")] = "*",
    max_results: Annotated[int, Field(description="Maximum number of references to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first result to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Find references to a symbol across the selected project's source files using word-boundary matching. Scan scope: TypeScript/TSX/JavaScript/JSX source files only (.ts, .tsx, .js, .jsx) under the search path; symbols used only in other languages report total: 0. Returns a summary (total, files_affected, returned, next_offset, has_more) followed by file:line:line-content, paged deterministically by (path, line). Use for discovering where a component, function, or variable is used."""
    return find_usages(
        symbol=symbol,
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_pattern_audit(
    path: Annotated[str, Field(description="Project-relative directory to audit for responsive/layout patterns. Defaults to 'frontend/src'.")] = "frontend/src",
    categories: Annotated[str, Field(description="Pattern category group to run, or 'all' for every category. Defaults to 'all' (summary counts + samples).")] = "all",
    max_results_per_category: Annotated[int, Field(description="Maximum number of matches collected per category. Defaults to 100 (hard cap 500). Also bounds the single-category 'category' expansion.")] = 100,
    category: Annotated[str, Field(description="Single pattern category to expand in detail (additive; overrides 'categories'). Valid values: viewport-width, large-min-width, large-fixed-width, nowrap, negative-horizontal-margin, horizontal-transform, negative-position, overflow-x, min-width, fixed-position, sticky-position. Defaults to '' (summary mode).")] = "",
) -> str:
    """READ ONLY. Run predefined responsive/layout pattern searches in the selected project. Default call returns a bounded summary-first report: a [SUMMARY] block plus [CATEGORY COUNTS] for every requested category and up to 2 sample matches per category, under the normal 4,000-character presentation budget (no uncontrolled category dump). collection_complete=true means every category's collected total is known; has_more=true means additional matches exist beyond the displayed samples. Use the additive 'category' parameter to expand a single category into up to max_results_per_category matches under the 16,000-character ceiling. Categories include: viewport-width, large-min-width, large-fixed-width, nowrap, negative-horizontal-margin, horizontal-transform, negative-position, overflow-x, min-width, fixed-position, sticky-position, or 'all'. category and categories values are validated against the fixed category enum. Returns evidence only — no modifications. Use for auditing potential mobile/responsive issues."""
    return pattern_audit(
        path=path,
        categories=categories,
        max_results_per_category=max_results_per_category,
        category=category,
    )


@mcp.tool()
def mcquest_list_docs(
    path: Annotated[str, Field(description="Project-relative directory to list Markdown docs under. Defaults to 'docs'.")] = "docs",
    pattern: Annotated[str, Field(description="Glob pattern filtering which Markdown files to include. Defaults to '*.md'.")] = "*.md",
    max_results: Annotated[int, Field(description="Maximum number of doc paths to return on this page. Defaults to 100 (hard cap 300).")] = 100,
    offset: Annotated[int, Field(description="Zero-based index of the first result to return on this page. Use the previous page's next_offset to continue. Defaults to 0.")] = 0,
) -> str:
    """READ ONLY. List Markdown documentation files under a project directory. Excludes dependency/generated directories and non-Markdown files. Returns a summary (total, returned, next_offset, has_more, doc-type breakdown) followed by relative doc paths, paged deterministically by path. Use to discover available documentation before reading specific files."""
    return list_docs(
        path=path,
        pattern=pattern,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_read_doc(
    path: Annotated[str, Field(description="Project-relative path to the Markdown documentation file to read.")],
    start_line: Annotated[int, Field(description="1-based line number to start reading from. Defaults to 1.")] = 1,
    end_line: Annotated[
        int | None,
        Field(description="1-based inclusive end line (clamped to a 1,000-line window), or null to read a bounded default window of at most 250 lines starting at start_line."),
    ] = None,
) -> str:
    """READ ONLY. Read a Markdown documentation file with exact line numbers. Use line ranges whenever possible instead of requesting huge files. Returns line-numbered Markdown content. Unranged reads return a bounded window with continuation metadata (start_line, end_line, total_lines, next_start_line, has_more)."""
    return read_doc(
        path=path,
        start_line=start_line,
        end_line=end_line,
    )


@mcp.tool()
def mcquest_search_docs(
    pattern: Annotated[str, Field(description="Regular expression or text pattern to search for in Markdown documentation. Supports regex alternation, e.g. 'foo|bar|baz'.")],
    path: Annotated[str, Field(description="Project-relative directory to restrict the search to, e.g. 'docs'. Defaults to 'docs'.")] = "docs",
    file_pattern: Annotated[str, Field(description="Filename glob restricting which Markdown files are searched; matches the file's basename, not the full path. Defaults to '*.md'. Examples: 'README*.md', '0[012]*.md'.")] = "*.md",
    case_sensitive: Annotated[bool, Field(description="When true, matching is case-sensitive. Defaults to false.")] = False,
    context_lines: Annotated[int, Field(description="Number of surrounding context lines to include per match. Bounded to 0-5. Defaults to 1.")] = 1,
    max_results: Annotated[int, Field(description="Maximum number of matches to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first match to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. PREFERRED TOOL FOR DOCUMENTATION SEARCH. Search Markdown documentation in the selected project using regex or text patterns. Use this instead of shell grep, rg, PowerShell Select-String, or manual Markdown scanning when the required operation is documentation search. Returns a summary (total, files_affected, returned, next_offset, has_more, truncated) followed by matching lines with surrounding context, paged deterministically by (path, line). Supports restricting the search to a directory (path), filtering files by filename glob (file_pattern), regex with alternation (pattern, e.g. 'foo|bar|baz'), line numbers with optional surrounding context (context_lines bounded to 0-5), and case sensitivity (case_sensitive). Use mcquest_search for source-code searches."""
    return search_docs(
        pattern=pattern,
        path=path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        context_lines=context_lines,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_phase_context(
    query: Annotated[str, Field(description="Free-text search for relevant phase/stage documentation. Leave empty when using 'phase'.")] = "",
    phase: Annotated[str, Field(description="Phase identifier for structured lookup, e.g. '61' or '61-Part-II-A'. Leave empty when using 'query'.")] = "",
    path: Annotated[str, Field(description="Project-relative documentation directory. Defaults to 'docs'.")] = "docs",
    max_results: Annotated[int, Field(description="Maximum number of matches to return. Defaults to 50.")] = 50,
    context_lines: Annotated[int, Field(description="Number of surrounding context lines to include per match. Bounded to 0-5. Defaults to 1.")] = 1,
    include_implementation: Annotated[bool, Field(description="Include implementation-report documents in results. Defaults to true.")] = True,
    include_audits: Annotated[bool, Field(description="Include audit documents in results. Defaults to true.")] = True,
) -> str:
    """READ ONLY. Locate relevant phase/stage documentation. Use EITHER 'query' (free-text search, e.g. 'responsive overflow', 'Android') OR 'phase' (phase identifier, e.g. '61', '61-Part-II-A'). Phase identifiers follow the project's phase-documentation naming convention: they are matched as 'phase-<id>' tokens in Markdown filenames under the documentation path (default 'docs'), so '61' matches files whose names contain a token like 'phase-61' or 'phase-61-part-ii-a'. When 'phase' is provided, results are grouped by document type (implementation reports, audits, completions). Returns each match with its nearest heading, line numbers, and surrounding context. 'No documentation found' means no filenames matched the phase name pattern. Preserves original evidence. Works for past and future phases."""
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
    """READ ONLY. Provide a compact high-level understanding of the selected project. Returns technology stack, major directories, important source areas, documentation paths, and key configuration files. Use this as the first context call before a large investigation."""
    return project_context()


@mcp.tool()
def mcquest_find_evidence(
    query: Annotated[str, Field(description="Free-text to search for across code, docs, and phase evidence.")],
    phase: Annotated[str, Field(description="Optional phase identifier to scope the phase evidence search. Leave empty for all phases.")] = "",
    scope: Annotated[str, Field(description="Where to search: 'code', 'docs', 'phase', or 'all'. Defaults to 'all'.")] = "all",
    path: Annotated[str, Field(description="Project-relative directory for the code evidence search. Defaults to 'frontend/src'.")] = "frontend/src",
    docs_path: Annotated[str, Field(description="Project-relative directory for the documentation evidence search. Defaults to 'docs'.")] = "docs",
    max_results: Annotated[int, Field(description="Maximum number of matches to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    context_lines: Annotated[int, Field(description="Number of surrounding context lines to include per match. Bounded to 0-5. Defaults to 1.")] = 1,
    offset: Annotated[int, Field(description="Zero-based index of the first match to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Search across code, documentation, and phase evidence in a single call. Returns a summary (total, files_affected, counts, returned, next_offset, has_more, truncated, collection_complete, budget) followed by a deterministic merged stream: code results first, then documentation results, each ordered by (path, line), sharing ONE page budget (never a per-scope limit). The code stream scans .ts, .tsx, .js, .jsx, .css source files only; the docs stream scans Markdown under docs_path. collection_complete=true means the authoritative total/count is known -- it does NOT mean every result was delivered: when has_more=true, continue with next_offset. Scope can be 'code', 'docs', 'phase', or 'all'. Optionally filter by phase (phase results are doc-grouped and not paged). Use this instead of separately searching code and docs."""
    return find_evidence(
        query=query,
        phase=phase,
        scope=scope,
        path=path,
        docs_path=docs_path,
        max_results=max_results,
        context_lines=context_lines,
        offset=offset,
    )


@mcp.tool()
def mcquest_git_context(
    max_commits: Annotated[int, Field(description="Maximum number of recent commits to report. Defaults to 10.")] = 10,
    max_changes: Annotated[int, Field(description="Maximum number of recently changed files to report. Defaults to 50.")] = 50,
) -> str:
    """READ ONLY. Provide read-only Git investigation information. Returns current branch, working-tree status, recent commits, and recently changed files. Does NOT perform commits, adds, resets, checkouts, merges, rebases, pushes, or pulls. Use to understand recent changes and current branch state."""
    return git_context(
        max_commits=max_commits,
        max_changes=max_changes,
    )


@mcp.tool()
def mcquest_compare_phase(
    from_phase: Annotated[str, Field(description="Source phase identifier, e.g. '61', whose documentation set is compared.")],
    to_phase: Annotated[str, Field(description="Target phase identifier, e.g. '62', compared against the source phase.")],
    path: Annotated[str, Field(description="Project-relative documentation directory. Defaults to 'docs'.")] = "docs",
    max_results: Annotated[int, Field(description="Maximum number of documents to report per category. Defaults to 50.")] = 50,
) -> str:
    """READ ONLY. Compare documentation between two phases. Phase identifiers follow the project's phase-documentation naming convention: they are matched as 'phase-<id>' tokens in Markdown filenames under the documentation path (default 'docs'), so '61' matches files whose names contain a token like 'phase-61'. 'No documentation found' means no filenames matched either phase pattern. Returns document-set differences using evidence-neutral terminology: EXISTING, ADDED, REMOVED, COMMON, UNKNOWN. Document-existence/set diff only (not content verification). RUNTIME VERIFICATION: NOT PERFORMED. Use mcquest_read_doc to cross-check document content. Use to understand which documentation documents appear in each phase."""
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