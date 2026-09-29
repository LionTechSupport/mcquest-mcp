from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from .tools import (
    compare_phase,
    component_inventory,
    diagnostics,
    doc_gap_audit,
    feature_impact_audit,
    find_evidence,
    find_files,
    find_imports,
    find_strings,
    find_ui_text,
    find_usages,
    git_context,
    list_docs,
    list_files,
    locale_inspect,
    pattern_audit,
    phase_context,
    project_context,
    project_info,
    read_doc,
    read_file,
    search_docs,
    search_text,
    ui_contract_audit,
)
from .tools.shell_env import (
    shell_capabilities,
    shell_context,
    shell_environment,
    shell_history,
    shell_next,
    shell_observe,
    shell_plan,
    shell_prepare,
    shell_terminal,
    shell_validate,
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
        "Select-String, Get-ChildItem). "
        "ROUTING BY TARGET LOCATION - decide this before choosing a tool. "
        "IN-ROOT: if the requested file or directory is inside the selected "
        "project root, the MCQuest repository tools below are an applicable "
        "branch; prefer bounded, deterministic MCQuest structured evidence "
        "whenever one of their scopes matches the request. OUT-OF-ROOT: if the "
        "requested path lies outside the selected project root, MCQuest "
        "repository tools are NOT the applicable branch - they reject such "
        "paths by design with 'Path escapes MCQuest project root'. Never "
        "bypass, weaken, or work around that project-root confinement, and "
        "never re-request an out-of-root path as if it were in-root. For "
        "local files outside the root, use the host/client's own native file "
        "tools when available (e.g. read_files, search_codebase). Being "
        "out-of-root does NOT imply shell: when a native file tool can read the "
        "target, a shell pipeline (Get-Content, Select-String, findstr, cat, "
        "grep) is unnecessary. Shell and process tooling (mcquest_shell_*) plus "
        "client terminal execution remain the correct branch for environment, "
        "process and terminal state, and for genuine command execution that no "
        "structured read-only tool provides. "
        "SEARCH SCOPE is per-tool and narrower than 'the repository': "
        "mcquest_search and mcquest_search_docs walk only inside the selected "
        "project root, prune generated/dependency directories such as .git, "
        "node_modules, .venv, __pycache__, .pytest_cache, dist, build, coverage, "
        ".next and .turbo, skip binary/large files, and order results "
        "deterministically by (relative_path, line). Their default path is "
        "layout-specific ('frontend/src' and 'docs' respectively), so set path "
        "explicitly when the selected project uses a different layout. "
        "Use mcquest_search_docs for "
        "Markdown/documentation searches, mcquest_search for source-code regex "
        "searches, mcquest_find_files to locate files by name, "
        "mcquest_read_file / mcquest_read_doc to read known files, and "
        "mcquest_find_usages / mcquest_find_imports for dependency/reference occurrence "
        "investigation (textual matches only, not resolved symbols). Use mcquest_find_strings "
        "to inventory quoted string "
        "literals in JS/TS/JSX/TSX sources. Use mcquest_find_ui_text to inventory "
        "quoted string literals and template-literal static segments as lexical "
        "UI-text candidates in .js/.jsx/.ts/.tsx sources with conservative "
        "DEC-032 classification (no-ASCII-letter literals are decorative; "
        "letter-bearing literals are unknown while the brand/admin lists are "
        "unrecorded); JSX text nodes are not extracted and a zero result does "
        "not prove absence. Use mcquest_ui_contract_audit to audit component "
        "prop contracts lexically in .js/.jsx/.ts/.tsx sources: declared "
        "props at component definitions versus prop keys passed at call "
        "sites, with issue categories missing_prop/stale_prop/"
        "mismatched_usage/signature_drift/unverifiable, heuristic severity "
        "and confidence labels, and unverifiable rows for spread or "
        "non-enumerable cases; risk is never emitted. Use mcquest_doc_gap_audit "
        "to audit documentation against the bounded code scan lexically: "
        "eligible stale_reference carriers are inline backtick-span content "
        "and path-like tokens with a recognized source/doc extension (prose "
        "identifiers are never candidates by shape alone); the only currently "
        "emittable issue type is stale_reference (warning, heuristic "
        "confidence); missing_doc/conflicting_reference/status_mismatch, "
        "consistency rows, and risk are never emitted; "
        "collection_complete=false plus a NOTE appears only when a scan cap "
        "or an unterminated fence prevents full inspection. "
        "Use mcquest_feature_impact_audit to review "
        "lexical change-impact evidence for a target across .js/.jsx/.ts/.tsx "
        "code, .md/.markdown/.mdown/.mkd documentation (include_docs, default "
        "true), and .json locale keys/references (include_locales, default "
        "true): impacted files/affected docs/locale keys-or-references rows "
        "with a lexical reason plus a review checklist (suggestions only, "
        "never facts); severity, risk, and confidence are never emitted; "
        "bounded scan (MAX_ENUMERATE_FILES=2000 / MAX_FILES_ANALYZED=500) "
        "sets collection_complete=false plus an incomplete-collection NOTE "
        "only when a scan cap prevents full inspection, and total counts "
        "findings within the bounded scan only. "
        "Use mcquest_locale_inspect to inspect JSON "
        "locale files for structure, duplicate keys, casefold collisions, and (with an "
        "explicit reference file) MISSING/EXTRA key-path differences; with no reference it "
        "performs structure/collision/duplicate inspection only and never infers a default "
        "locale. Use mcquest_component_inventory to inventory lexical React "
        "component candidates (function/arrow/class, path:line:Name + kind only) "
        "in .js/.jsx/.ts/.tsx sources; its results are lexical candidates, not "
        "verified components, and a zero result does not prove that no "
        "components exist. Use mcquest_diagnostics for "
        "TypeScript/TSX/JavaScript/JSX "
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
    exclude_pattern: Annotated[str, Field(description="Optional regular expression applied per line to drop matching lines from results (exclude wins on overlap with pattern; honors case_sensitive; applied to both the count and the page). Supports regex alternation, e.g. 'foo|bar'. Defaults to '' (no exclusion).")] = "",
) -> str:
    """READ ONLY. Search source files in the selected project using a regular expression. Returns a summary (total, files_affected, returned, next_offset, has_more, truncated) followed by matching lines with limited surrounding context, paged deterministically by (path, line). Optionally pass exclude_pattern to filter matching lines out of the results. Use for source-code pattern searches; use mcquest_search_docs for Markdown/documentation searches. SCOPE: in-root only - the walk starts at the project-relative path (default 'frontend/src'; set it explicitly when the selected project uses a different layout) and never leaves the selected project root, so an out-of-root target is an error rather than a wider search. Generated/dependency directories are pruned (.git, .hg, .svn, node_modules, .venv, venv, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, dist, build, coverage, .next, .turbo) and binary/generated extensions plus files over MAX_FILE_BYTES (2 MB) are skipped, so total counts source files, not every file on disk. Case-insensitive by default (set case_sensitive=true for exact case). The pattern is a regex; a literal string is a valid regex. Ordering is deterministic by (relative_path, line) and pages are explicit (max_results default 50, hard cap 500, offset/next_offset); total is an authoritative full count while the delivered rows are one page, so collection_complete=true does NOT mean every row was delivered. For Markdown use mcquest_search_docs; for targets outside the selected project root use the host/client native file tools."""
    return search_text(
        pattern=pattern,
        path=path,
        file_pattern=file_pattern,
        case_sensitive=case_sensitive,
        context_lines=context_lines,
        max_results=max_results,
        offset=offset,
        exclude_pattern=exclude_pattern,
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
def mcquest_find_strings(
    path: Annotated[str, Field(description="Project-relative file or directory to scan for string literals. Defaults to 'frontend/src'.")] = "frontend/src",
    file_pattern: Annotated[str, Field(description="Glob pattern filtering which files to scan by basename (directory mode only). Defaults to '*' (all files).")] = "*",
    min_length: Annotated[int, Field(description="Minimum literal length to report; suppresses short strings such as empty quotes. Defaults to 1 (bounds 0..100).")] = 1,
    max_results: Annotated[int, Field(description="Maximum number of literals to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first literal to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Enumerate quoted string literals in JS/TS/JSX/TSX source files as deterministic bounded evidence. Lexical literal-inventory primitive: finds quoted '...', "...", and template-literal static segments; NOT a hardcoded-UI-string detector and NOT AST-based, so a zero-result response does NOT prove the absence of user-facing text and quoted literals inside comments may be returned. JSX text nodes are out of scope. Returns a summary (total, files_affected, returned, offset, next_offset, has_more, truncated, collection_complete, budget) followed by one page of at most max_results path:line:col: "value" lines ordered deterministically by (path, line, col). collection_complete=true means the authoritative total is known -- it does NOT mean every result was delivered: when has_more=true, continue with next_offset. Use this instead of ad-hoc regex searches when you need exact literal values and positions in .js, .jsx, .ts, .tsx sources."""
    return find_strings(
        path=path,
        file_pattern=file_pattern,
        min_length=min_length,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_find_ui_text(
    path: Annotated[str, Field(description="Project-relative directory or single file to scan. Defaults to the project root '.'.")] = ".",
    file_pattern: Annotated[str, Field(description="Glob pattern filtering which files to scan by basename (directory mode only). Defaults to '*' (all files).")] = "*",
    max_results: Annotated[int, Field(description="Maximum number of candidate rows to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first candidate to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
    classify: Annotated[bool, Field(description="Whether to return classification labels (DEC-032). Defaults to true; when false, rows carry only the location and snippet.")] = True,
) -> str:
    """READ ONLY. Find lexical UI-text candidates (quoted string literals and template-literal static segments) in .js/.jsx/.ts/.tsx sources. Lexical-only per DEC-015/DEC-032: NOT a parser-based or semantic UI-text detector, so a zero-result response does NOT prove the absence of user-facing text; JSX text nodes are not extracted and quoted literals on comment lines may appear (the scanner has no comment awareness). Classification (DEC-032): a literal with no ASCII letter ([A-Za-z]) is decorative (confidence high); a literal with one or more ASCII letters is unknown (confidence medium) with a reason naming the missing brand-token list and admin-marker list; localizable/brand/admin-only are NOT emitted and are never inferred by elimination. When classify=false, rows carry only the location and snippet and the summary is unchanged. Returns a summary (total, files_affected, returned, offset, next_offset, has_more, truncated, collection_complete, budget) followed by one page of at most max_results file:line evidence rows ordered deterministically by (path, line, col). collection_complete=true means the authoritative total is known -- it does NOT mean every result was delivered: when has_more=true, continue with next_offset."""
    return find_ui_text(
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
        offset=offset,
        classify=classify,
    )


@mcp.tool()
def mcquest_ui_contract_audit(
    path: Annotated[str, Field(description="Project-relative directory or single file to scan. Defaults to the project root '.'.")] = ".",
    component_pattern: Annotated[str, Field(description="Glob pattern filtering which files to scan by basename (directory mode only). Defaults to '*' (all files).")] = "*",
    include_callers: Annotated[bool, Field(description="Whether call-site-anchored rows are included. Defaults to true; when false, only definition-anchored rows are reported.")] = True,
    max_results: Annotated[int, Field(description="Maximum number of issue rows to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first issue row to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Audit component prop contracts lexically in .js/.jsx/.ts/.tsx sources: declared props at component definitions versus prop keys passed at call sites, with issue categories missing_prop/stale_prop/mismatched_usage/signature_drift/unverifiable (DEC-018). Strictly lexical (no parser, no symbol resolution); severity and confidence are heuristic labels (DEC-017), never facts: missing_prop is critical only when all in-scope call sites are accounted for, every one omits the prop, and every one is fully evaluable, otherwise warning (DEC-022); stale_prop is warning only against a fully available definition (exactly one definition site, lexically enumerable prop set) and unverifiable otherwise (DEC-023); mismatched_usage and signature_drift are warning (DEC-031); unverifiable is always info severity and low confidence and is never critical. risk is never emitted (DEC-025). A zero result means no lexical findings in the scanned scope and never proves contract correctness. Returns a summary (total, files_affected, returned, offset, next_offset, has_more, truncated, collection_complete, budget) followed by one page of at most max_results multi-line issue rows ordered by (path, line). collection_complete=true means the authoritative total is known -- it does NOT mean every result was delivered: when has_more=true, continue with next_offset."""
    return ui_contract_audit(
        path=path,
        component_pattern=component_pattern,
        include_callers=include_callers,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_doc_gap_audit(
    docs_path: Annotated[str, Field(description="Project-relative Markdown scope (`.md`, `.markdown`, `.mdown`, `.mkd`) to audit, or a single in-boundary Markdown file. Defaults to the project root. Root confinement applies.")] = ".",
    code_path: Annotated[str, Field(description="Project-relative code scope (`.js`, `.jsx`, `.ts`, `.tsx`) to compare documentation tokens against, or a single in-boundary code file. Defaults to the project root. Root confinement applies.")] = ".",
    max_results: Annotated[int, Field(description="Maximum number of issue rows to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first issue row to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Audit documentation tokens against the bounded code scan lexically in .md/.markdown/.mdown/.mkd (docs side) and .js/.jsx/.ts/.tsx (code side). Strictly lexical (no parser, no symbol resolution, no maintained symbol list). Eligible stale_reference carriers (DEC-033) are the content of a backtick-delimited inline Markdown span and path-like tokens containing '/' with a recognized source or documentation extension; the identifier form [A-Za-z_][A-Za-z0-9_]* is a tokenizer WITHIN those carriers only, so ordinary prose words are never candidates by identifier shape alone. The only currently emittable issue type is stale_reference (severity warning, heuristic per DEC-017; confidence high only when the bounded code scan completed uncapped, otherwise medium -- DEC-025/DEC-033). missing_doc/conflicting_reference/status_mismatch, consistency rows, and risk are NOT EMITTABLE. Bounded scan (DEC-016/DEC-033): MAX_ENUMERATE_FILES=2000 / MAX_FILES_ANALYZED=500; collection_complete=false plus an incomplete-collection NOTE only when a scan cap (or an unterminated fence) prevents full inspection; total counts findings within the bounded scan only and never claims a repository-global total when capped. Returns a summary (total, files_affected, returned, offset, next_offset, has_more, truncated, collection_complete, budget) followed by one page of at most max_results multi-line issue rows ordered deterministically by (docs relative_path, doc line, code relative_path)."""
    return doc_gap_audit(
        docs_path=docs_path,
        code_path=code_path,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_feature_impact_audit(
    target: Annotated[str, Field(description="File, symbol, route, or feature name whose change-impact references are audited. Matched lexically (word-boundary, plus import-module and string-literal evidence composed per DEC-019). Required; must be non-empty.")],
    path: Annotated[str, Field(description="Project-relative scope root (directory) or a single in-boundary file (.js/.jsx/.ts/.tsx, .md/.markdown/.mdown/.mkd, or .json). Defaults to the project root. Root confinement applies.")] = ".",
    max_results: Annotated[int, Field(description="Maximum number of impact rows to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first impact row to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
    include_docs: Annotated[bool, Field(description="Whether documentation impact (.md/.markdown/.mdown/.mkd) is included. Defaults to true; when false, documentation impact is excluded (DEC-034).")] = True,
    include_locales: Annotated[bool, Field(description="Whether locale impact (.json keys/references) is included. Defaults to true; when false, locale impact is excluded (DEC-034).")] = True,
) -> str:
    """READ ONLY. Determine which files/docs/locales may be affected by a change to a target, composing existing primitives only (DEC-019): lexical word-boundary find_usages, find_imports, find_strings, locale key-position lookups, and the shared walk/readers over .js/.jsx/.ts/.tsx code, .md/.markdown/.mdown/.mkd documentation, and .json locale files (DEC-019 boundary union). include_docs and include_locales are optional booleans defaulting to true (DEC-034); when false, that impact dimension is excluded. Rows are review items, not asserted issues: no severity field, no issue-type/classification enum, no confidence field, and no risk field (DEC-025); each row carries file:line, a kind (impacted file / affected doc / locale key or reference), a reason (the lexical evidence), and an evidence line, and the summary carries a REVIEW_CHECKLIST that is a review suggestion only, never a fact. Bounded scan (DEC-016/DEC-035): MAX_ENUMERATE_FILES=2000 / MAX_FILES_ANALYZED=500 for the unified scan (no separate code/document/locale caps); collection_complete=false plus an incomplete-collection NOTE only when a scan cap or a skipped file prevents full inspection; total counts findings within the bounded scan only and never claims a repository-global total when capped; truncated (output budget) stays separate from collection_complete (DEC-028). Returns a summary (total, files_affected, returned, offset, next_offset, has_more, truncated, collection_complete, budget, TARGET, PATH, INCLUDE_DOCS, INCLUDE_LOCALES, REVIEW_CHECKLIST) followed by one page of at most max_results rows ordered deterministically by (relative_path, line), with explicit offset pagination only (no automatic page 2). A zero result never proves absence of feature impact."""
    return feature_impact_audit(
        target=target,
        path=path,
        max_results=max_results,
        offset=offset,
        include_docs=include_docs,
        include_locales=include_locales,
    )


@mcp.tool()
def mcquest_find_usages(
    symbol: Annotated[str, Field(description="Identifier to match by whole-word lexical equality (word-boundary). Matches are textual occurrences, not resolved references; declarations, comments, and string literals count. See tool description for scope.")],
    path: Annotated[str, Field(description="Project-relative directory to search. Defaults to 'frontend/src'.")] = "frontend/src",
    file_pattern: Annotated[str, Field(description="Glob pattern filtering which files to search. Defaults to '*' (all files).")] = "*",
    max_results: Annotated[int, Field(description="Maximum number of references to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first result to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Find lexical word-boundary matches for an identifier across the selected project's source files. Textual only, NOT semantic: no import, alias, module, scope, or language resolution; every line containing the identifier as a whole word is a match — declarations, comments, and string literals all count. Scan scope: TypeScript/TSX/JavaScript/JSX source files only (.ts, .tsx, .js, .jsx) under the search path; symbols used only in other languages report total: 0. Returns a summary (total, files_affected, returned, next_offset, has_more) followed by file:line:line-content, paged deterministically by (path, line). Use to locate all spelling occurrences of an identifier; pair with mcquest_find_imports and mcquest_read_file to reason about real reference relationships."""
    return find_usages(
        symbol=symbol,
        path=path,
        file_pattern=file_pattern,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_locale_inspect(
    path: Annotated[str, Field(description="Project-relative directory to inspect JSON locale files under, or a single .json file. Defaults to the project root.")] = ".",
    reference: Annotated[str, Field(description="Project-relative path of the reference locale file for MISSING/EXTRA comparison. Defaults to '' (structure/collision/duplicate inspection only; no default locale is inferred).")] = "",
    file_pattern: Annotated[str, Field(description="Glob pattern filtering which files to include; matches the basename. Defaults to '*.json'.")] = "*.json",
    max_results: Annotated[int, Field(description="Maximum number of rows to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first row to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Inspect JSON locale files (.json only) for structure, duplicate keys, casefold collisions (e.g. 'Strasse' vs 'Straße'), and — only with an explicit reference file — MISSING/EXTRA key-path differences (MISSING = present in reference, absent in target; EXTRA = present in target, absent in reference). reference='' means structure/collision/duplicate inspection only; no default locale is ever inferred. Duplicate-preserving parse: duplicate keys are detected at effective object nodes over the full syntactic pair list, the effective structure follows the last occurrence, and duplicates inside shadowed earlier subtrees are never traversed or reported. Paths render JSON-quoted keys and [i] array indices ('0' is a string key, [0] an array index — never confused); the root renders <root>. Ordered deterministically (files by relative-path bytes; rows by typed path then type STRUCTURE/COLLISION/MISSING/EXTRA/DUP/ERROR) under per-file (3000) and global (5000) row caps; once the global cap is exhausted the tool switches to counting mode and reports exact FINDINGS_OMITTED cardinalities instead of materializing rows. Failed files produce explicit ERROR rows (READ/DECODE/OVERSIZED/DEPTH/PARSE/IDENTITY) and are disclosed via FINDINGS_UNKNOWN / files_not_examined; incomplete enumeration reports files_not_examined_unknown with ENUM_LIMIT or ENUM_REASON instead of exact totals. collection_complete=false whenever comparisons are disabled (no reference or failed reference) or the scan is incomplete — it does NOT mean every row was delivered (see has_more/next_offset). Returns a [SUMMARY] block followed by 'relative: ROW' evidence lines, paged over the collected rows."""
    return locale_inspect(
        path=path,
        reference=reference,
        file_pattern=file_pattern,
        max_results=max_results,
        offset=offset,
    )


@mcp.tool()
def mcquest_component_inventory(
    path: Annotated[str, Field(description="Project-relative directory to scan for component candidates, or a single .js/.jsx/.ts/.tsx file. Defaults to the project root. A single-file path with an unsupported extension (including .d.ts) is rejected.")] = ".",
    file_pattern: Annotated[str, Field(description="Glob pattern filtering which files to include; matches the basename. Defaults to '' (the .js/.jsx/.ts/.tsx allowlist only).")] = "",
    max_results: Annotated[int, Field(description="Maximum number of rows to return on this page. Defaults to 50 (hard cap 500).")] = 50,
    offset: Annotated[int, Field(description="Zero-based index of the first row to return on this page. Use the previous page's next_offset to continue. Defaults to 0. Page 2 is never returned automatically.")] = 0,
) -> str:
    """READ ONLY. Inventory lexical React component candidates in JS/TS sources (.js, .jsx, .ts, .tsx only) and return 'relative_path:line: Name (kind)' rows where kind is one of function, arrow, or class. Results are LEXICAL CANDIDATES, not verified React components: false positives and false negatives are possible, and comments and strings are NOT stripped (a declaration-shaped match inside a comment or string is still emitted). Anonymous default declarations are skipped; class kinds are not gated on a React base class; names must match ASCII [A-Z][A-Za-z0-9_]* case-sensitively. .d.ts files are excluded. A zero result does NOT prove that no components exist — lowercase-named components, HOC wrappers, multi-line declarations, re-exports, and files outside the supported extensions are all missed. Rows are deduplicated and ordered deterministically by (relative_path, line, name, kind) with explicit paging (has_more/next_offset); collection_complete is true only when no in-scope file was skipped (oversized/unreadable) and no file-count cap was reached — it does NOT mean every row was delivered. Returns a [SUMMARY] block followed by 'relative_path:line: Name (kind)' evidence lines, paged over the deduplicated rows."""
    return component_inventory(
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
    """READ ONLY. PREFERRED TOOL FOR DOCUMENTATION SEARCH. Search Markdown documentation in the selected project using regex or text patterns. Use this instead of shell grep, rg, PowerShell Select-String, or manual Markdown scanning when the required operation is documentation search. Returns a summary (total, files_affected, returned, next_offset, has_more, truncated) followed by matching lines with surrounding context, paged deterministically by (path, line). Supports restricting the search to a directory (path), filtering files by filename glob (file_pattern), regex with alternation (pattern, e.g. 'foo|bar|baz'), line numbers with optional surrounding context (context_lines bounded to 0-5), and case sensitivity (case_sensitive). Use mcquest_search for source-code searches. SCOPE: in-root only - the walk starts at the project-relative path (default 'docs'; set it explicitly when documentation lives elsewhere) and never leaves the selected project root, so an out-of-root target is an error rather than a wider search. Only Markdown extensions are scanned (.md, .markdown, .mdown, .mkd), narrowed further by the file_pattern basename glob (default '*.md'); generated/dependency directories are pruned (.git, .hg, .svn, node_modules, .venv, venv, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, dist, build, coverage, .next, .turbo) and files over MAX_FILE_BYTES (2 MB) are skipped, so total counts Markdown documents only. Case-insensitive by default (set case_sensitive=true for exact case). The pattern is a regex; a literal string is a valid regex. Ordering is deterministic by (relative_path, line) and pages are explicit (max_results default 50, hard cap 500, offset/next_offset); total is an authoritative full count while the delivered rows are one page, so collection_complete=true does NOT mean every row was delivered. For source code use mcquest_search; for targets outside the selected project root use the host/client native file tools."""
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


# --- V0.9 P2 shell-intelligence tools (decision A11: registered in phases) --

@mcp.tool()
def mcquest_shell_environment(
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_cwd: Annotated[str, Field(description="Optional client-declared terminal working directory (CLIENT_DECLARED; corroborated only when it resolves inside the project root). Empty string = not declared.")] = "",
    client_shell: Annotated[str, Field(description="Optional client-declared terminal shell family, e.g. 'PowerShell' (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_shell_version: Annotated[str, Field(description="Optional client-declared terminal shell version (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
) -> str:
    """READ ONLY. Assemble the V0.9 Environment Contract with source/trust/scope/freshness labels: project root, OS/Python (stdlib), executable presence (shutil.which), and versions from approved fixed-argv read-only probes (git, node, pwsh -Version, and the fixed PowerShell 5.1 version literal). Probe failures report UNKNOWN, never fabricated or stale values; server process facts are labeled subject=mcp_server and are never presented as the client's terminal state. Returns a summary-first, bounded report."""
    return shell_environment(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )


@mcp.tool()
def mcquest_shell_terminal(
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_cwd: Annotated[str, Field(description="Optional client-declared terminal working directory (CLIENT_DECLARED; corroborated only when it resolves inside the project root). Empty string = not declared.")] = "",
    client_shell: Annotated[str, Field(description="Optional client-declared terminal shell family, e.g. 'PowerShell' (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_shell_version: Annotated[str, Field(description="Optional client-declared terminal shell version (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
) -> str:
    """READ ONLY. Report terminal/session/process identity, clearly separating the MCP server's own process (subject=mcp_server) from the client terminal. Undeclared client fields report value=unknown / source=UNKNOWN / trust=untrusted (degraded cold start, decision S1); identity-scoped facts are never promoted across sessions or processes, and no client terminal state is ever fabricated from server facts. Returns a summary-first, bounded report."""
    return shell_terminal(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )


@mcp.tool()
def mcquest_shell_context(
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_cwd: Annotated[str, Field(description="Optional client-declared terminal working directory (CLIENT_DECLARED; corroborated only when it resolves inside the project root). Empty string = not declared.")] = "",
    client_shell: Annotated[str, Field(description="Optional client-declared terminal shell family, e.g. 'PowerShell' (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_shell_version: Annotated[str, Field(description="Optional client-declared terminal shell version (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
) -> str:
    """READ ONLY. Return the compact V0.9 shell-intelligence context assembled from known P1/P2 state: repository, worktree (explicitly unknown when unobserved), server process (subject=mcp_server), client terminal, environment, freshness/trust counts, explicit unknowns, and standing directives. Unavailable information is reported as UNKNOWN; no confidence score and no completeness claim is produced. Returns a summary-first, bounded report."""
    return shell_context(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )


@mcp.tool()
def mcquest_shell_capabilities(
    offset: Annotated[int, Field(description="Zero-based index of the first capability row to return on this page. Use the previous page's next_offset to continue. Defaults to 0.")] = 0,
    max_results: Annotated[int, Field(description="Maximum number of capability rows (3 lines each) to return on this page. Bounded to 1-10 so one page stays within the 4000-character default budget. Defaults to 10.")] = 10,
) -> str:
    """READ ONLY. Expose the V0.9 capability registry with intent metadata (decision A12): every implemented tool with purpose, family (V0.8 repository intelligence vs V0.9 shell intelligence), phase, read-only status, execution class, operation classes, and prerequisites, followed by clearly labeled PLANNED rows that are not registered and not executable. The pinned EXPECTED_TOOLS list remains the registration authority; this registry never registers anything. Returns summary-first deterministic output, paged."""
    return shell_capabilities(offset=offset, max_results=max_results)


# --- V0.9 P4 validation / observation tools (decision A11: 28 -> 30) --------

@mcp.tool()
def mcquest_shell_validate(
    command: Annotated[str, Field(description="The proposed command text to analyze. It is never executed by V0.9.")],
    mode: Annotated[str, Field(description="Analysis mode: 'validate' (default) or 'lint'. Lint is a MODE of this tool, never a separate tool (decision A11).")] = "validate",
    client_cwd: Annotated[str, Field(description="Optional client-declared terminal working directory (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_shell: Annotated[str, Field(description="Optional client-declared terminal shell family, e.g. 'PowerShell' (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_shell_version: Annotated[str, Field(description="Optional client-declared terminal shell version (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id (CLIENT_DECLARED; not verified). Empty string = not declared.")] = "",
    repository_root: Annotated[str, Field(description="Optional known/declared repository root used for redundancy n3 root-prefix comparison. Empty string = not evaluated.")] = "",
    changed_reasons: Annotated[str, Field(description="Optional comma-separated documented change reasons (file, worktree, terminal, process, cwd, configuration, prior_staleness, prior_failure, scope) that would justify a repeat. Empty string = none.")] = "",
) -> str:
    """READ ONLY. Compose every V0.9 analyzer into one deterministic validation report with a leading machine-readable [SUMMARY] block and the contract's fixed section order (Syntax, Parse completeness, Shell dialect, Native boundary, CWD, Path safety, Redundancy, Operation, Mutation, Encoding, Failure propagation, Stale-variable hazard, Cost, Capability duplication, Recommendation). Verdict tokens are exactly ERROR/WARNING/INFO/PASS with a 'verdict: <ERROR|WARNINGS|PASS>' summary line. Destructive commands are reported from P4's own lexical evidence and are never cleared by a non-mutation-bearing operation classification; UNKNOWN is preserved, no numeric confidence or risk score is produced, output is byte-identical across repeated calls, and the proposed command is analyzed only - never executed, never repaired, and never selected by this tool."""
    return shell_validate(
        command=command,
        mode=mode,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
        client_session=client_session,
        client_process_id=client_process_id,
        repository_root=repository_root,
        changed_reasons=changed_reasons,
    )


@mcp.tool()
def mcquest_shell_observe(
    kind: Annotated[str, Field(description="A14 ingest kind: 'observation' (default) or 'command'.")] = "observation",
    name: Annotated[str, Field(description="A14 'name' - namespaced observation, e.g. mcquest_search.total or locale.quiz.loading.si. Required when kind=observation.")] = "",
    value: Annotated[str, Field(description="A14 'value' - the observed value as text. For kind=command this is the command text.")] = "",
    scope: Annotated[str, Field(description="A14 'scope': REPOSITORY | WORKTREE | FILE | SESSION | PROCESS | EPHEMERAL. Required when kind=observation.")] = "",
    subject: Annotated[str, Field(description="Optional A14 'subject' - path, capability, or query the observation concerns. Also narrows refined invalidation targets.")] = "",
    source: Annotated[str, Field(description="A14 'source' - the tool or command that produced the evidence; kept as the originating source (contract §17).")] = "",
    recorded_at_source: Annotated[str, Field(description="A14 'recorded_at_source': SERVER (tool-derived, SERVER_OBSERVED) or CLIENT (declared, untrusted). Immutable provenance.")] = "CLIENT",
    operation: Annotated[str, Field(description="Optional operation label retained with the observation/command record.")] = "",
    invalidate_event: Annotated[str, Field(description="Optional P1 invalidation event to apply instead of recording, e.g. file_modified, git_checkout, set_location, branch_switch, server_restart. Only its mapped scopes/subjects are invalidated.")] = "",
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id. Required to record SESSION scope; required with client_process_id for PROCESS/EPHEMERAL scope.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id. Required with client_session for PROCESS/EPHEMERAL scope.")] = "",
) -> str:
    """READ ONLY. Record declared observations, ingested tool evidence, and command history through the explicit A14 ingest shape, and apply P1 invalidation to exactly the mapped scopes. Declared evidence keeps the phrase 'declared by client; not verified' for its lifetime; tool-derived evidence is labeled SERVER_OBSERVED and keeps its originating tool as the source; SESSION/PROCESS/EPHEMERAL ingestion is rejected without a declared client identity so no fact is ever promoted across terminals. Freshness is semantic with no wall-clock TTL; the store is in-memory only and nothing is persisted, no command is executed, and no state outside the server process is changed."""
    return shell_observe(
        kind=kind,
        name=name,
        value=value,
        scope=scope,
        subject=subject,
        source=source,
        recorded_at_source=recorded_at_source,
        operation=operation,
        invalidate_event=invalidate_event,
        client_session=client_session,
        client_process_id=client_process_id,
    )


@mcp.tool()
def mcquest_shell_plan(
    intent: Annotated[str, Field(description="The requested task or intent to classify, e.g. 'read the file README.md' or 'check git status'. Classified into the frozen contract §13 operation vocabulary; an unclassifiable intent stays UNKNOWN.")],
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id, used to bind SESSION/PROCESS evidence to the correct terminal. Undeclared identity leaves those observations UNKNOWN.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id, used with client_session for PROCESS-scoped evidence. Undeclared identity leaves those observations UNKNOWN.")] = "",
) -> str:
    """READ ONLY. Classify an intent into the frozen operation vocabulary and return a bounded, deterministic plan: current evidence state (known/unknown/stale/invalidated/insufficient), relevant known facts, required observations, proposed steps on the contract §13 preference ladder (existing evidence, then an existing MCQuest capability, then a structured tool operation, then a targeted shell operation, and a broad scan only as a last resort), rationale and evidence basis, validation requirements, and blockers. A plan is a recommendation, never execution authorization: the server never executes the recommended operation, never mutates any state, and a routed capability is named as a recommendation rather than invoked. No numeric confidence, no numeric risk, and no wall-clock TTL; unknown information stays unknown."""
    return shell_plan(
        intent=intent,
        client_session=client_session,
        client_process_id=client_process_id,
    )


@mcp.tool()
def mcquest_shell_prepare(
    intent: Annotated[str, Field(description="The task to prepare, normalized and classified into the frozen operation vocabulary. When it cannot be safely or sufficiently prepared, a deterministic blocked/insufficient result is returned instead of a guess.")],
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id, used to resolve already-known facts for the correct terminal.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id, used with client_session to resolve process-scoped facts.")] = "",
) -> str:
    """READ ONLY. Prepare a requested task without executing it: normalize and classify the request, resolve already-known facts from the existing in-memory store, identify missing prerequisites and required observations, and emit the preparation as text explicitly labeled PREPARED / NOT EXECUTED. Preparation never executes a command, writes files, installs packages, modifies git or environment state, spawns processes, or invokes arbitrary shell commands. An insufficient or unsafe request returns a deterministic blocked result rather than a guess, and no numeric confidence, numeric risk, or wall-clock TTL is produced."""
    return shell_prepare(
        intent=intent,
        client_session=client_session,
        client_process_id=client_process_id,
    )


@mcp.tool()
def mcquest_shell_history(
    offset: Annotated[int, Field(description="Zero-based index of the first history record to return on this page. Paging is deterministic and never re-sorts.")] = 0,
    limit: Annotated[int, Field(description="Maximum number of history records to return on this page. Defaults to 10 (maximum 50).")] = 10,
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id; when supplied, only records for that terminal are returned and facts are never promoted across sessions.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id; when supplied, only records for that process are returned.")] = "",
) -> str:
    """READ ONLY. Page the command and observation history held by the single existing in-memory ObservationStore/CommandHistory, with no second persistence system and no wall-clock TTL. Every row carries its established scope, freshness, source, trust, identity binding, and the store's own invalidation decision (known, stale, or invalidated). When history is unavailable or empty it is reported explicitly as insufficient/unknown rather than filled in, and nothing is persisted to disk."""
    return shell_history(
        offset=offset,
        limit=limit,
        client_session=client_session,
        client_process_id=client_process_id,
    )


@mcp.tool()
def mcquest_shell_next(
    intent: Annotated[str, Field(description="The task whose next useful step is being determined; classified into the frozen operation vocabulary.")],
    last_command: Annotated[str, Field(description="Optional the last command text considered, used only for n0-n3 duplicate detection. Supplying it enables blind-retry prevention: an unchanged repeat is refused and a different next action is returned.")] = "",
    changed_reasons: Annotated[str, Field(description="Optional comma-separated changed conditions that would justify a repeat, e.g. file, worktree, terminal, process, cwd, configuration, prior_staleness, prior_failure, scope. Without one, a duplicate is never repeated.")] = "",
    repository_root: Annotated[str, Field(description="Optional known/declared repository root; when supplied, the n3 root-prefix normalization level is evaluated, otherwise redundancy is reported as partial.")] = "",
    client_session: Annotated[str, Field(description="Optional client-declared terminal session id, used to bind evidence and history to the correct terminal.")] = "",
    client_process_id: Annotated[str, Field(description="Optional client-declared terminal process id, used with client_session for process-scoped evidence.")] = "",
) -> str:
    """READ ONLY. Determine the next useful observation or planning step for an intent, accounting for existing facts, freshness, invalidation, provenance, trust, scope, prerequisites, validation findings, and missing evidence. Blind-retry prevention follows the contract: a repeat is justified only when a relevant condition changed, otherwise the next action must differ from the previous one. This is a single deterministic bounded recommendation - never an execution, never an autonomous agent loop, and it never repairs anything."""
    return shell_next(
        intent=intent,
        last_command=last_command,
        changed_reasons=changed_reasons,
        repository_root=repository_root,
        client_session=client_session,
        client_process_id=client_process_id,
    )

def main() -> None:
    """
    Start the MCQuest MCP server over stdio for local MCP hosts such as Cline.
    """
    mcp.run()


if __name__ == "__main__":
    main()