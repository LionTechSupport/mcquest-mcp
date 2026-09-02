# Project Architecture — General-Purpose Project Intelligence MCP

## 1. Overview

This project is a standalone, read-only Model Context Protocol (MCP) server designed to provide AI coding agents with structured project-intelligence capabilities.

The server is intentionally kept outside individual application repositories so it can be reused across multiple projects.

Primary goals:

- Repository inspection
- Source-file discovery
- Exact file reading
- Regex/code searching
- Import relationship discovery
- Symbol usage discovery
- Static pattern auditing
- Evidence-oriented responses
- Strict read-only operation
- Safe project-root boundaries
- Low-token research for AI coding agents

The MCP does NOT modify the target project.

It does NOT:

- edit files
- create files
- delete files
- execute arbitrary shell commands
- execute project code
- install packages
- modify Git state
- create commits
- push changes
- alter configuration
- run migrations

The MCP is an information/research layer for AI coding agents.

---

# 2. Design Philosophy

The MCP follows five principles.

## 2.1 Read-only by default

All tools inspect the target repository.

No tool should have write access to the target project.

## 2.2 Evidence over interpretation

Tools should return:

- exact paths
- line numbers
- matched text
- relevant context
- structural relationships

The AI agent performs the final interpretation.

## 2.3 Small focused tools

Each MCP tool should perform one well-defined research operation.

Avoid one enormous "analyze everything" tool.

## 2.4 Repository agnostic

The server must not depend on MCQuest-specific assumptions.

It should work with:

- React
- Next.js
- Vue
- Angular
- Node.js
- Python
- Java
- Kotlin
- Android
- Flutter
- Go
- Rust
- PHP
- Ruby
- mixed-language repositories

## 2.5 Safe project boundaries

File access must remain inside the configured project root.

Path traversal such as:

    ../../secret.txt

must never allow access outside the configured project.

---

# 3. High-Level Architecture

    ┌───────────────────────────────┐
    │          AI Client            │
    │                               │
    │  Cline / Claude / MCP Client  │
    └───────────────┬───────────────┘
                    │
                    │ MCP / stdio
                    ▼
    ┌─────────────────────────────────────────┐
    │       Project Intelligence MCP          │
    │                                         │
    │              server.py                  │
    │                  │                      │
    │        ┌─────────┴─────────┐            │
    │        │                   │            │
    │      config             security        │
    │        │                   │            │
    │        └─────────┬─────────┘            │
    │                  │                      │
    │              formatting                 │
    │                  │                      │
    │        ┌─────────┴─────────────┐        │
    │        │                       │        │
    │      tools/                 future/     │
    │        │                       │        │
    │   ┌────┼────┬────┬────┬────┐  │        │
    │   │    │    │    │    │    │  │        │
    │ files search imports project audit ...  │
    │        │                       │        │
    └────────┼───────────────────────┼────────┘
             │
             ▼
    ┌───────────────────────────────┐
    │        Target Repository      │
    │                               │
    │  Source files / configs /     │
    │  project structure            │
    └───────────────────────────────┘

---

# 4. Directory Structure

Current intended structure:

    mcquest-mcp/
    │
    ├── README.md
    ├── project-architecture.md
    ├── pyproject.toml
    │
    ├── dev_server.py
    │
    ├── src/
    │   └── mcquest_mcp/
    │       │
    │       ├── __init__.py
    │       ├── server.py
    │       ├── config.py
    │       ├── formatting.py
    │       ├── security.py
    │       │
    │       └── tools/
    │           ├── __init__.py
    │           ├── project.py
    │           ├── files.py
    │           ├── search.py
    │           ├── imports.py
    │           └── audit.py
    │
    └── .venv/

---

# 5. Component Responsibilities

## 5.1 server.py

Responsible for:

- creating the MCP server
- registering tools
- exposing the MCP transport
- providing the main entry point

It should contain minimal business logic.

Tool implementations belong in `tools/`.

---

## 5.2 config.py

Central configuration.

Responsibilities include:

- maximum output size
- default result limits
- excluded directories
- allowed project root
- security limits
- default search paths
- file-size limits

Configuration should not contain project-specific paths.

---

## 5.3 security.py

Responsible for safe filesystem access.

Responsibilities:

- resolving paths
- preventing path traversal
- enforcing project-root boundaries
- rejecting unsafe paths
- enforcing file-size limits
- filtering excluded directories

Every filesystem-facing tool should use the security layer.

---

## 5.4 formatting.py

Responsible for consistent tool output.

Responsibilities:

- line-number formatting
- context formatting
- result truncation
- output-size protection
- concise evidence formatting

The formatting layer should prevent a single tool call from flooding the AI context.

---

# 6. Tool Architecture

## 6.1 project_info

Purpose:

Provide a compact overview of the target project.

Typical information:

- project root
- top-level directories
- important files
- detected project types
- package manifests
- configuration files

Example:

    project_info()

Returns a concise structural summary.

---

# 7. list_files

Purpose:

List files beneath a project directory.

Inputs:

- path
- pattern
- max_results

Example:

    list_files(
        path="src",
        pattern="*.tsx"
    )

Important behavior:

- recursive discovery
- excludes dependency directories
- excludes build artifacts
- bounded result count
- safe path resolution

---

# 8. read_file

Purpose:

Read an exact section of a source file.

Inputs:

- path
- start_line
- end_line

Example:

    read_file(
        path="src/App.tsx",
        start_line=1,
        end_line=80
    )

The tool should always return line numbers.

Prefer bounded reads instead of entire files.

---

# 9. search

Purpose:

Search source files using regular expressions.

Inputs:

- pattern
- path
- file_pattern
- case_sensitive
- context_lines
- max_results

Example:

    search(
        pattern="overflow-x-auto",
        path="src"
    )

Returns:

- file
- line
- matched line
- limited context

---

# 10. find_files

Purpose:

Locate files by filename.

Inputs:

- query
- path
- max_results

Example:

    find_files(
        query="AdminUsers.tsx"
    )

This is optimized for discovering a file when its exact location is unknown.

---

# 11. find_imports

Purpose:

Find ES-module imports referencing a target.

Inputs:

- target
- path
- max_results

Example:

    find_imports(
        target="UnifiedLayout",
        path="src"
    )

The first version primarily targets JavaScript/TypeScript import syntax.

Future versions may add language-specific import parsers.

---

# 12. find_usages

Purpose:

Find references to a symbol across source files.

Inputs:

- symbol
- path
- file_pattern
- max_results

Example:

    find_usages(
        symbol="AdminUsers"
    )

The initial implementation is text-based.

Future versions may add AST/LSP-based semantic analysis.

---

# 13. pattern_audit

Purpose:

Run predefined static searches for potentially important project patterns.

Examples:

- `overflow-x-auto`
- `overflow-x-hidden`
- `whitespace-nowrap`
- fixed widths
- minimum widths
- viewport widths
- negative margins
- transforms
- fixed positioning
- sticky positioning

This tool is useful for focused UI/layout audits.

It returns evidence.

It does not claim that a pattern is necessarily a bug.

The AI agent performs the final interpretation.

---

# 13.1 mcquest_diagnostics

Purpose:

Return compact **syntax diagnostics** for a single TypeScript/TSX/JS/JSX source
file without reading the entire file, so an agent can diagnose a compiler/parser
error (e.g. `'}' expected`, `')' expected`, `']' expected`, `TS1005`, unexpected
token, unterminated string/template, JSX closing-tag problems) from the
diagnostic location plus a small source context window.

Inputs:

- path (project-relative `.ts` / `.tsx` / `.js` / `.jsx` file)
- context_lines (default 12, bounded 0-25)
- max_diagnostics (default 20, bounded 1-50)
- line / column (optional focus filters)
- diagnostic_kind (only `"syntax"` in this version)

Mechanism:

- The selected project's own Node runtime loads the project-local TypeScript
  compiler bundle (`node_modules/typescript/lib/typescript.js`) via a bundled
  driver (`src/mcquest_mcp/ts/diagnose.js`).
- The driver parses the file with `ts.createSourceFile` — a pure parser. No
  module resolution, no type checking, no `tsconfig`, no `createProgram`, no
  LanguageService, and no application code is executed.
- Source text is passed through stdin; all paths are validated inside the
  project root; a timeout is enforced.
- Output is bounded by `max_diagnostics` and `context_lines` and includes
  TypeScript-provided related locations (e.g. the opening `{` that caused a
  parser mismatch) when available — never fabricated.

Semantic/type diagnostics (P3) and bounded project-wide diagnostics (P4) are
deliberately **not** implemented in this version. `diagnostic_kind` accepts only
`"syntax"`; unsupported values are rejected clearly.

If the selected project has no local TypeScript installation, the tool returns:

    TypeScript compiler unavailable in selected project.

It never downloads or installs anything.

---

# 14. Read-Only Security Model

The MCP must remain strictly read-only.

Allowed:

- directory traversal within project root
- file listing
- file reading
- text searching
- static analysis

Forbidden:

- writing files
- deleting files
- renaming files
- shell execution
- arbitrary subprocess execution against the project
- package installation
- Git mutation
- network requests initiated on behalf of the project
- code execution from target files

**Sanctioned narrow subprocess exceptions.** Two tools invoke a fixed,
read-only executable with explicit, non-mutating arguments — the same trust
posture as running `git` directly:

- `mcquest_git_context` runs `git --no-pager` with read-only arguments.
- `mcquest_diagnostics` runs the selected project's own Node runtime against the
  project-local TypeScript compiler parser
  (`node_modules/typescript/lib/typescript.js`) via the bundled driver
  `src/mcquest_mcp/ts/diagnose.js`. The driver parses a single file with
  `ts.createSourceFile` (pure parser) fed through stdin; it never runs `npx`,
  `npm`, `tsc`, `tsconfig`, `createProgram`, a LanguageService, or application
  code. All paths are validated inside the project root, a timeout is enforced,
  and no files are written.

Arbitrary project process execution remains forbidden.

The target project should be treated as untrusted input.

---

# 15. Path Security

Every requested path must be resolved against the configured project root.

Conceptually:

    project_root
        │
        ├── src/
        ├── package.json
        └── README.md

Allowed:

    src/App.tsx

Rejected:

    ../../Windows/System32/config/SAM

Rejected:

    C:\Users\...

Rejected:

    \\server\share\...

The resolved path must remain inside the configured project root.

---

# 16. Output Limits

AI coding agents have limited context windows.

Every tool should therefore enforce:

- maximum number of results
- maximum context lines
- maximum file size
- maximum output characters/tokens

Large searches should return bounded evidence.

The agent can request additional focused searches when necessary.

---

# 17. Excluded Directories

Default exclusions should include common generated/dependency directories:

    node_modules
    .git
    .svn
    .hg
    dist
    build
    coverage
    .next
    .nuxt
    .turbo
    .cache
    __pycache__
    .venv
    venv
    target
    bin
    obj

Additional exclusions may be configured later.

---

# 18. MCP Transport

The primary transport is stdio.

Development:

    uv run mcp dev dev_server.py

Smoke test:

    uv run mcp run dev_server.py

The development launcher exists because the MCP CLI loads a filesystem server path directly.

`dev_server.py` imports the actual package server using a normal package import.

---

# 19. Packaging

The project uses:

- Python
- uv
- Hatchling
- MCP Python SDK

The project follows a `src/` layout:

    src/mcquest_mcp/

This prevents accidental import behavior caused by the repository root being placed directly on `sys.path`.

---

# 20. Development Launcher

`dev_server.py` is intentionally thin.

Conceptually:

    from mcquest_mcp.server import mcp

Its purpose is to provide an MCP CLI-compatible filesystem entry point while preserving normal package imports.

It should not contain duplicated server logic.

---

# 21. Client Integration

Example Cline configuration:

    {
      "mcpServers": {
        "project-intelligence": {
          "command": "uv",
          "args": [
            "--directory",
            "D:\\DeveloperTools\\mcquest-mcp",
            "run",
            "mcquest-mcp"
          ],
          "disabled": false
        }
      }
    }

The MCP server itself should not hard-code the target application.

The target project is supplied through configuration/environment/client context.

---

# 22. Relationship With Other MCPs

This server is intended to complement, not replace, other development MCPs.

Recommended architecture:

    Cline
      │
      ├── Project Intelligence MCP
      │     └── repository research
      │
      ├── Serena
      │     └── semantic/code navigation
      │
      ├── Playwright MCP
      │     └── browser/UI verification
      │
      └── Context7
            └── current library/framework documentation

Each MCP should have a focused responsibility.

---

# 23. Current v0.2 Tool Set

    project_info
    project_context           (new in v0.2)
    list_files
    read_file
    search
    find_files
    find_imports
    find_usages
    pattern_audit
    list_docs
    read_doc
    search_docs
    phase_context             (enhanced in v0.2 with phase mode)
    find_evidence             (new in v0.2)
    git_context               (new in v0.2)
    compare_phase             (new in v0.2)

All tools are read-only.

---

# 24. Future v0.2 Candidates

Potential additions:

- dependency inspection
- package manifest analysis
- route discovery
- component hierarchy discovery
- CSS/Tailwind class analysis
- environment/config discovery
- duplicate-code detection
- TODO/FIXME discovery
- API endpoint discovery
- database schema inspection
- test discovery
- test-to-source mapping
- framework detection
- project health summary
- git read-only inspection
- architecture dependency graph
- circular dependency detection

These should be added incrementally.

---

# 25. Future v0.3 Candidates

More advanced semantic capabilities:

- AST analysis
- TypeScript symbol analysis
- Python AST analysis
- dependency graph generation
- component relationship graph
- route/component mapping
- LSP-backed symbol navigation
- semantic call hierarchy
- architecture rule checking

These should remain read-only.

---

# 26. Non-Goals

This project is NOT intended to become:

- an autonomous coding agent
- a shell execution MCP
- a deployment tool
- a Git automation tool
- a package manager
- a build server
- a CI/CD system
- a browser automation server

Those responsibilities belong to other tools.

---

# 27. Design Rule for New Tools

Every new tool should answer:

1. Is it read-only?
2. Does it provide information unavailable through an existing tool?
3. Can the operation be narrowly scoped?
4. Can the output be bounded?
5. Does it respect the project-root security boundary?
6. Is it useful across multiple project types?
7. Does it avoid duplicating Serena, Playwright, or Context7?

If the answer is no, do not add the tool.

---

# 28. Versioning

Current version:

    0.2.0

v0.2 focuses on:
- project-level context (project_context)
- cross-evidence search (find_evidence)
- read-only Git inspection (git_context)
- phase comparison (compare_phase)
- improved tool descriptions
- enhanced phase_context with structured phase mode

v0.1 focused on:
- filesystem inspection
- source search
- lightweight static analysis
- safe evidence retrieval

Future versions should preserve backward compatibility where practical.

---

# 29. Core Principle

The MCP should answer:

    "What is actually in this project?"

It should not answer:

    "What should I change?"

The AI coding agent remains responsible for interpretation, reasoning, planning, and modification.