# MCQuest MCP — Read-Only Project Intelligence Server

A reusable, read-only MCP server for giving AI coding agents structured access to a software project's source code and architecture.

Originally developed for MCQuest, the server is intentionally maintained as a standalone developer tool outside application repositories.

It can be reused across different projects.

---

## Features

The current version (v0.2) provides **16 read-only tools** organized into categories:

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

## Documentation Awareness

The documentation tools give the AI agent read-only access to project Markdown
documentation (e.g. `docs/`, `memory-bank/`), including previous audit and
implementation phases.

- `mcquest_list_docs` — list Markdown files under a project-relative path.
- `mcquest_read_doc` — read a Markdown file with exact line numbers.
- `mcquest_search_docs` — regex/text search across Markdown docs, returning
  file path, line number, matching line, and surrounding context.
- `mcquest_phase_context` — **Two modes**: `query` mode (free-text: "responsive overflow", "Android")
  and `phase` mode (structured lookup: `phase="61"`). Phase mode returns results grouped by document type.

These tools preserve the original Markdown evidence and line references.
They do **not** summarize, rewrite, or interpret the documentation; they
return the raw evidence so the AI agent can reason about it.

The tools distinguish between documented facts, completed work, audit
findings, recommendations, unresolved issues, and explicitly
unverified/static findings by preserving the original text and line
references. They never convert an unverified/static finding into a
verified fact.

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

The server is designed to provide **evidence**, while the AI coding agent performs the reasoning.

## Recommended Cline Usage Flow

1. **`mcquest_project_context`** — First call for project orientation
2. **`mcquest_phase_context(phase="N")`** — Understand a specific phase
3. **`mcquest_find_evidence(query="...")`** — Cross-search code + docs
4. **`mcquest_read_file` / `mcquest_read_doc`** — Read specific files
5. **`mcquest_git_context`** — Check recent changes before investigation
6. **`mcquest_compare_phase(from_phase="61", to_phase="62")`** — Compare phases

---

## Version History

- **v0.2.0** — Added `project_context`, `find_evidence`, `git_context`, `compare_phase`.
  Improved all tool descriptions. Added `phase` parameter to `phase_context`
  with structured lookup grouped by document type.
- **v0.1.0** — Initial release with 12 read-only tools.

---

# Requirements

- Windows, macOS, or Linux
- Python 3.10+
- `uv`
- MCP Python SDK
- Node.js only if using MCP Inspector

---

# Installation

Clone or place the server somewhere outside your application repositories.

Example:

```text
D:\DeveloperTools\mcquest-mcp