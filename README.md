# MCQuest MCP — Read-Only Project Intelligence Server

A reusable, read-only MCP server that gives AI coding agents structured access to a
software project's source code and documentation.

Built for and battle-tested on the MCQuest codebase, the server is intentionally
maintained as a standalone developer tool outside application repositories so it can
be pointed at **any** repository.

It is an **evidence layer**, not a decision engine: it reports what is actually in a
project, and the AI coding agent performs the reasoning.

---

## Features

Provides **17 read-only tools** organized into categories:

### Project Structure
| Tool | Purpose |
|---|---|
| `mcquest_project_info` | Compact project overview with structure and key files |
| `mcquest_project_context` | High-level understanding: tech stack, directories, source areas |
| `mcquest_list_files` | Recursively list project files with glob pattern filtering |

### Source Code Analysis
| Tool | Purpose |
|---|---|
| `mcquest_read_file` | Read bounded file sections with line numbers |
| `mcquest_search` | Regex-based source code search with context |
| `mcquest_find_files` | Find files by filename (case-insensitive) |
| `mcquest_find_imports` | Find ES module imports referencing a target |
| `mcquest_find_usages` | Find symbol references with word-boundary matching |
| `mcquest_pattern_audit` | Predefined responsive/layout pattern audit |
| `mcquest_diagnostics` | Compact TypeScript/TSX/JS/JSX syntax diagnostics with context |

### Documentation Intelligence
| Tool | Purpose |
|---|---|
| `mcquest_list_docs` | List Markdown documentation files |
| `mcquest_read_doc` | Read Markdown docs with line numbers |
| `mcquest_search_docs` | Regex/text search across docs |
| `mcquest_phase_context` | Locate phase docs (supports `query` and `phase` modes) |
| `mcquest_compare_phase` | Compare documentation between two phases |

### Cross-Evidence & Git
| Tool | Purpose |
|---|---|
| `mcquest_find_evidence` | Search code + docs in one call, grouped by evidence type |
| `mcquest_git_context` | Read-only Git: branch, status, recent commits, changes |

The server does **not** modify the target project.

---

## Quick Start

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Get the code
#    (or clone your fork / place it somewhere outside your app repos)
cd mcquest-mcp

# 2. Install dependencies (runtime dep is only the MCP SDK;
#    pytest is installed as a dev-only dependency)
uv sync

# 3. Run it, pointing the server at the repository you want to inspect
# Windows (PowerShell):
uv run mcquest-mcp --project "D:\path\to\your\project"
# macOS / Linux:
uv run mcquest-mcp --project /path/to/your/project
```

> **Important:** you must tell the server which repository to inspect. Either pass
> `--project <PATH>` (absolute or relative), or set the `MCQUEST_PROJECT_ROOT`
> environment variable. If neither is supplied, startup fails with a clear error —
> the server never silently assumes a repository. `--project` takes precedence over
> the environment variable.

The same installed server is safely reused across repositories by changing the
`--project` argument, e.g.:

```bash
uv run mcquest-mcp --project "D:\DeveloperTools\mcquest-mcp"   # this repo
uv run mcquest-mcp --project "D:\Some\Other\Repository"         # anything else
```

---

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `--project` / `MCQUEST_PROJECT_ROOT` | (none — startup fails if unset) | Absolute or relative path to the project root all tools are confined to |

- **Path containment.** Every tool resolves its inputs against `MCQUEST_PROJECT_ROOT`
  and rejects path traversal (`../`, absolute escapes) outside that boundary.
- **Default search paths.** Several tools default to `frontend/src` (source) and
  `docs` (documentation). Pass `path=` / `docs_path=` explicitly for other layouts.
- **Phase docs.** `mcquest_phase_context` and `mcquest_compare_phase` assume docs
  are named like `docs/phase-<N>...md` under the documentation path.

---

## Registering with an MCP client

Wire the `mcquest-mcp` console script into your MCP client's server configuration.
Example (JSON, e.g. Cline/Claude local config):

```json
{
  "mcpServers": {
    "mcquest-mcp": {
      "command": "uv",
      "args": ["run", "mcquest-mcp", "--project", "C:/path/to/your/project"]
    }
  }
}
```

Or run the MCP Inspector during development:

```bash
uv run python -m mcp dev dev_server.py
```

---

## Documentation Awareness

The documentation tools give the AI agent read-only access to project Markdown
documentation (e.g. `docs/`, `memory-bank/`), including previous audit and
implementation phases.

- `mcquest_list_docs` — list Markdown files under a project-relative path.
- `mcquest_read_doc` — read a Markdown file with exact line numbers.
- `mcquest_search_docs` — regex/text search across Markdown docs, returning
  file path, line number, matching line, and surrounding context.
- `mcquest_phase_context` — **Two modes**: `query` mode (free-text) and `phase`
  mode (structured lookup, e.g. `phase="61"`). Phase mode groups results by
  document type.

These tools preserve the original Markdown evidence and line references. They do
**not** summarize, rewrite, or interpret the documentation; they return the raw
evidence so the AI agent can reason about it.

---

## Diagnostics (TypeScript / TSX / JS / JSX)

`mcquest_diagnostics` gives the AI agent compact **syntax diagnostics** for a
single source file without reading the whole file. It is the preferred tool when
a compiler/parser error location is already known (e.g. `'}' expected`,
`')' expected`, `TS1005`, or an error reported at a specific line/column),
especially in large `.tsx` files.

**What it does**

- Runs the selected project's own Node runtime against the project-local
  TypeScript compiler parser (`node_modules/typescript/lib/typescript.js`).
- Uses `ts.createSourceFile` — a **pure parser**: no module resolution, no type
  checking, no `tsconfig`, no application code.
- Returns each diagnostic's code, severity, message, exact 1-based line/column,
  a small line-numbered source context window, and TypeScript-provided related
  locations when available (e.g. the opening `{` that caused a parser mismatch).
- Bounds output: `context_lines` (default 12, max 25) and `max_diagnostics`
  (default 20, max 50). A 1,400+ line file never causes the whole file to be
  returned.

**Parameters**

| Param | Default | Notes |
|---|---|---|
| `path` | (required) | Project-relative `.ts`, `.tsx`, `.js`, or `.jsx` file |
| `context_lines` | 12 | Source lines around each diagnostic (0–25) |
| `max_diagnostics` | 20 | Diagnostics returned (1–50) |
| `line` | `None` | Only diagnostics at this 1-based line |
| `column` | `None` | Only diagnostics at this 1-based column (usually with `line`) |
| `diagnostic_kind` | `"syntax"` | Only `"syntax"` is supported in this version |

**When to use it**

- TypeScript syntax errors, TSX parser errors, `'}'` / `')'` / `']'` expected,
  unexpected tokens, unterminated strings/templates, JSX closing-tag problems.
- A compiler/parser error with a known line/column in a large file — use this
  instead of reading the entire source file.

**When NOT to use it**

- Do not use it for semantic/type errors (e.g. `tsc --noEmit` style type
  mismatches) — this version reports syntax diagnostics only.
- Do not use it to read a file's content; use `mcquest_read_file`.

**TypeScript availability**

The tool requires a Node.js runtime on PATH and a project-local TypeScript
installation in the selected project. It never downloads or installs anything.
If TypeScript is unavailable it returns:

```
TypeScript compiler unavailable in selected project.
```

**Read-only guarantee**

The tool is strictly read-only: it reads the file, parses it, and returns a
report. It never modifies source files, `tsconfig`, `package.json`, lockfiles,
`node_modules`, or generated files, and it never executes application code.

---

## Safety

This MCP is intentionally read-only.

It does not provide:

- file editing
- file creation
- file deletion
- shell execution
- arbitrary code execution
- package installation
- Git mutation
- commits
- pushes
- deployment

The server provides **evidence**; the AI coding agent performs the reasoning. It never
claims runtime verification — static/documentation evidence is always labeled as such
(e.g. `RUNTIME VERIFICATION: NOT PERFORMED` where applicable).

**Narrow subprocess exception.** Two tools invoke a fixed, read-only executable — the
same trust posture as running `git` directly:

- `mcquest_git_context` runs `git --no-pager` with read-only arguments.
- `mcquest_diagnostics` runs the project's own Node runtime against the project-local
  TypeScript compiler parser (`node_modules/typescript/lib/typescript.js`) using
  `ts.createSourceFile` — a pure parser. It never runs `npx`, `npm`, `tsc`, `tsconfig`,
  `createProgram`, a LanguageService, or application code, and never writes files.

This is **not** arbitrary project process execution: the executable name is fixed, no
shell is used, all paths are validated inside the project root, source is passed via
stdin, and a timeout is enforced.

---

## Recommended Cline Usage Flow

1. **`mcquest_project_context`** — First call for project orientation
2. **`mcquest_phase_context(phase="N")`** — Understand a specific phase
3. **`mcquest_find_evidence(query="...")`** — Cross-search code + docs
4. **`mcquest_read_file` / `mcquest_read_doc`** — Read specific files
5. **`mcquest_diagnostics`** — Investigate a TypeScript/TSX/JS/JSX parser or compiler error instead of reading a large file
6. **`mcquest_git_context`** — Check recent changes before investigation
7. **`mcquest_compare_phase(from_phase="61", to_phase="62")`** — Compare phase docs

---

## Development & Testing

- `uv sync` installs runtime + dev dependencies.
- Run the regression suite with:

  ```bash
  uv run pytest -q
  ```

  The suite guards: the exact 17-tool registration, path-security/traversal, the
  read-only guarantee, output bounds, evidence-neutral `compare_phase` output, the
  `find_evidence(scope="phase")` behavior, and the `mcquest_diagnostics`
  syntax-diagnostic tool (registration, schema, context/max limits, large files,
  missing TypeScript, security containment, read-only behavior).
- Runtime dependency is only `mcp[cli]>=2,<3`; `pytest` is a dev-only dependency.
- Live `mcquest_diagnostics` tests are skipped unless `MCQUEST_TEST_TYPESCRIPT_LIB`
  points at a real `typescript.js`; nothing is downloaded to make tests pass.

---

## Known Legacy Defaults

The tool names retain the `mcquest_` prefix and several defaults assume an
MCQuest-style layout (e.g. `frontend/src`, `docs`, specific config filenames in
`mcquest_project_info` / `mcquest_project_context`, responsive-pattern categories in
`mcquest_pattern_audit`). These are intentionally retained for backward
compatibility while the server is progressively generalized. The project root is no
longer hard-coded: it comes from `--project` or `MCQUEST_PROJECT_ROOT`, and startup
fails if neither is supplied. `Git` tools are limited to read-only inspection
commands.

---

## Version History

- **v0.4.0** — Added `mcquest_diagnostics`: read-only, project-local
  TypeScript/TSX/JS/JSX **syntax** diagnostics via the project's own
  `node_modules/typescript` parser (`ts.createSourceFile`), with compact
  line-numbered context, related locations, and strict output bounds.
- **v0.3.0** — Evidence-neutral `compare_phase` vocabulary (`ADDED`/`REMOVED`/`COMMON`,
  `RUNTIME VERIFICATION: NOT PERFORMED`), fixed `find_evidence(scope="phase")`,
  added a dev-only pytest regression suite.
- **v0.2.0** — Added `project_context`, `find_evidence`, `git_context`, `compare_phase`.
  Improved all tool descriptions. Added `phase` parameter to `phase_context` with
  structured lookup grouped by document type.
- **v0.1.0** — Initial release with 12 read-only tools.

---

## Requirements

- Windows, macOS, or Linux
- Python 3.10+
- `uv`
- MCP Python SDK
- Node.js only if using MCP Inspector, or when using `mcquest_diagnostics`
  against a project that has TypeScript installed locally
  (`node_modules/typescript`)

---

## Install

Clone or place the server somewhere outside your application repositories, then see
[Quick Start](#quick-start).