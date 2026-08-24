# Project Intelligence MCP

## Core Principle

This MCP answers:

> **What is actually in this project?**

It does not decide:

> **What should I change?**

The AI coding agent remains responsible for:

* interpretation
* diagnosis
* planning
* implementation
* testing
* final decisions

The MCP provides the evidence.

The MCP should remain a **general-purpose, read-only project intelligence layer** that can be used against arbitrary software repositories.

---

# Development Rules

When adding a new tool:

* Keep it read-only.
* Keep it narrowly scoped.
* Enforce project-root security.
* Limit output.
* Return exact evidence.
* Avoid project-specific assumptions.
* Avoid duplicating existing tools.
* Avoid duplicating capabilities provided by specialized MCPs.
* Prefer composable tools that provide evidence useful to an AI coding agent.
* Do not make the MCP responsible for deciding whether a finding requires a code change.
* Clearly distinguish static evidence from runtime evidence.
* Preserve deterministic, inspectable behavior wherever practical.

The MCP must not:

* modify files
* create files
* delete files
* rename files
* execute arbitrary shell commands
* execute arbitrary code
* install packages
* modify Git history
* commit changes
* push changes
* modify the target project

---

# Evidence Principles

Every investigation result should make the evidence source clear.

Use classifications such as:

* `STATIC`
* `DOCUMENTATION`
* `GIT`
* `RUNTIME`
* `UNKNOWN`

Where applicable, findings should distinguish:

* `EXISTING`
* `NEW`
* `RESOLVED`
* `REGRESSION`
* `UNKNOWN`

The MCP should provide evidence.

The AI agent decides what that evidence means.

The MCP must never describe static source analysis as runtime verification.

---

# Current Architecture

The server currently provides repository intelligence through:

* project information
* file discovery
* file reading
* text/regex search
* import discovery
* usage discovery
* pattern auditing
* documentation discovery
* documentation reading
* documentation search
* phase context
* project context
* cross-source evidence search
* Git context
* phase comparison

The current implementation remains packaged as:

`mcquest-mcp`

with Python package:

`mcquest_mcp`

These names are intentionally retained for compatibility during the generalization effort.

---

# v0.1 — Foundation

Initial repository intelligence:

* project information
* file discovery
* file reading
* regex/text search
* import discovery
* usage discovery
* pattern auditing

---

# v0.2 — Project & Documentation Intelligence

Current stable capability set.

Added:

* Markdown/document discovery
* documentation reading
* documentation search
* structured phase context
* project context
* cross-source evidence search
* read-only Git context
* phase comparison

The v0.2 tools allow an AI coding agent to investigate not only the current source tree, but also the project's documented history and Git state.

## v0.2 Tool Categories

### Repository

* `project_info`
* `list_files`
* `read_file`
* `search_text`
* `find_files`
* `find_imports`
* `find_usages`
* `pattern_audit`

### Documentation

* `list_docs`
* `read_doc`
* `search_docs`
* `phase_context`

### Investigation

* `project_context`
* `find_evidence`
* `git_context`
* `compare_phase`

All tools remain read-only.

---

# v0.3 — Advanced Investigation Intelligence

The next improvement should focus on **investigation quality**, rather than simply adding many independent search tools.

The goal is to allow an AI coding agent to answer:

* Where is this implemented?
* What imports it?
* Where is it used?
* What documentation discusses it?
* What changed historically?
* Which audit phases affected it?
* Is a previous finding still present?
* Was a previous issue resolved?
* Is this a regression?
* What other project areas are related?

## Proposed v0.3 Tools

### 1. `trace_component`

Trace a component/module/file through the project.

Given a target such as:

`AdminUsers`

return relevant evidence including:

* source file
* imports
* imported modules/components
* usages
* related files
* relevant documentation
* phase references
* relevant Git history where available

The tool should compose existing investigation capabilities rather than duplicate their implementations.

---

### 2. `audit_evidence`

Perform a structured cross-source investigation for an audit question.

Example:

> Can `UnifiedLayout` cause horizontal overflow?

The tool should be able to combine:

* source-code evidence
* documentation evidence
* phase history
* relevant Git context

The result should clearly separate:

```text
QUESTION

CODE EVIDENCE

DOCUMENTATION EVIDENCE

GIT EVIDENCE

HISTORICAL EVIDENCE

CURRENT STATUS

VERIFICATION STATUS
```

The tool provides evidence only.

It must not decide what implementation should be performed.

---

### 3. Improve `phase_context`

Improve phase investigation so the tool can understand relationships between:

* audit phases
* implementation phases
* verification phases
* documented findings
* resolved findings
* subsequent regressions

Where possible, distinguish:

* `EXISTING`
* `NEW`
* `RESOLVED`
* `REGRESSION`
* `UNKNOWN`

The implementation should remain project-neutral.

---

### 4. `find_related`

Given a file, symbol, component, pattern, or topic, find related project evidence.

Possible relationships include:

* imports
* usages
* same-directory files
* shared components
* documentation references
* phase references
* matching patterns
* relevant Git changes

The tool should avoid pretending that semantic relationships are certain when they are only inferred from naming or textual evidence.

---

### 5. `route_context`

Trace a page or application route through the project.

Where applicable, identify:

* route definition
* page component
* layout
* shared shell
* imported components
* navigation references
* relevant documentation
* relevant tests

The tool must work generically and must not assume React, React Router, Next.js, Vue, Angular, or any other framework.

Framework-specific detection may be used only after the project itself indicates that framework.

---

### 6. `config_context`

Provide a consolidated view of project configuration relevant to an investigation.

Potential sources include:

* package manifests
* build configuration
* TypeScript configuration
* framework configuration
* mobile/Capacitor configuration
* Android configuration
* environment/configuration files

The tool should detect available configuration rather than assume a particular technology stack.

---

### 7. `change_context`

Provide read-only historical context for a specific:

* file
* component
* symbol
* directory

Where Git history is available, return:

* recent relevant commits
* changed files
* relevant commit messages
* current working-tree state
* historical evidence

No Git mutations are permitted.

---

### 8. `verify_finding`

Re-check a previously documented finding against the current project.

For example:

```text
Finding:
UnifiedLayout content wrapper lacked min-w-0.
```

The tool should determine whether current source evidence indicates:

* still present
* apparently resolved
* changed but uncertain
* no longer detectable
* insufficient evidence

It must not claim runtime verification unless runtime evidence is actually available.

---

### 9. `audit_summary`

Aggregate evidence from multiple audit stages.

The goal is to reduce duplication between:

* Stage 1
* Stage 2
* Stage 3
* Stage 4
* Stage 5
* later implementation/verification phases

The result should identify:

* previously established findings
* new findings
* resolved findings
* possible regressions
* duplicate findings
* unresolved findings

The tool should preserve the original evidence rather than silently rewriting conclusions.

---

# v0.4 — Semantic Investigation

Potential future capabilities:

* AST analysis
* TypeScript symbol analysis
* Python AST analysis
* component graphs
* route/component mapping
* dependency graphs
* circular dependency detection
* semantic relationship detection
* framework-aware analysis
* LSP-backed navigation where safely available

These should only be added when they provide substantially better evidence than the existing text-based tools.

---

# v0.5 — Verification Intelligence

Potential future capabilities:

* structured finding verification
* cross-stage regression detection
* implementation-to-audit traceability
* audit-to-verification traceability
* historical finding tracking
* evidence confidence scoring
* duplicate finding detection
* consolidated project health evidence

Runtime verification should remain separate from static investigation unless a safe, explicitly designed runtime integration is introduced.

---

# Generalization Requirements

Because this server is intended to become a **general-purpose Project Intelligence MCP**, all public descriptions and behavior must remain project-neutral.

Do not assume:

* React
* TypeScript
* Tailwind
* PocketBase
* Firebase
* Capacitor
* Android
* Python
* Node.js
* Windows
* MCQuest

unless the tool is explicitly detecting those technologies from the configured project.

The original MCQuest project may remain a development/test project and may be mentioned in historical documentation, but it must not become a runtime dependency or conceptual requirement.

---

# Current Package Naming

The repository currently remains:

`mcquest-mcp`

The Python package currently remains:

`mcquest_mcp`

These names should not be changed casually.

A future distribution/package rename may be considered separately once the generalized architecture is stable.

---

# License

Add the project's chosen license before publishing or distributing the MCP.

---

# Cline Development Task — Generalization

You are maintaining my standalone reusable MCP server at:

`D:\DeveloperTools\mcquest-mcp`

IMPORTANT:

* This MCP is intended to become a GENERAL-PURPOSE read-only codebase/project intelligence MCP.
* It must NOT be conceptually tied to the MCQuest project.
* Do NOT move it into the MCQuest repository.
* Do NOT add any files to the MCQuest project.
* Do NOT add write/edit/delete/shell/code-execution capabilities.
* Keep the current generalization task limited to renaming/generalizing the existing public tool interface.
* Do NOT implement the v0.3 roadmap tools in this task.
* The v0.3 roadmap is documentation/planning only.
* Do not redesign the architecture during the generalization task.

## Current Tools

The current v0.2 tool set is:

`mcquest_project_info`

`mcquest_list_files`

`mcquest_read_file`

`mcquest_search`

`mcquest_find_files`

`mcquest_find_imports`

`mcquest_find_usages`

`mcquest_pattern_audit`

`mcquest_list_docs`

`mcquest_read_doc`

`mcquest_search_docs`

`mcquest_phase_context`

`mcquest_project_context`

`mcquest_find_evidence`

`mcquest_git_context`

`mcquest_compare_phase`

## Primary Generalization

The first eight original repository tools must use these generic public names:

| Current                 | Target          |
| ----------------------- | --------------- |
| `mcquest_project_info`  | `project_info`  |
| `mcquest_list_files`    | `list_files`    |
| `mcquest_read_file`     | `read_file`     |
| `mcquest_search`        | `search_text`   |
| `mcquest_find_files`    | `find_files`    |
| `mcquest_find_imports`  | `find_imports`  |
| `mcquest_find_usages`   | `find_usages`   |
| `mcquest_pattern_audit` | `pattern_audit` |

The documentation/investigation tools should also use project-neutral public names where the current implementation still exposes `mcquest_` naming.

Do not preserve old names as aliases unless compatibility is explicitly required by the existing architecture.

## Generalization Task

Inspect the entire standalone MCP source tree:

`D:\DeveloperTools\mcquest-mcp\src\mcquest_mcp`

and:

`D:\DeveloperTools\mcquest-mcp\dev_server.py`

`D:\DeveloperTools\mcquest-mcp\pyproject.toml`

`D:\DeveloperTools\mcquest-mcp\project-architecture.md`

Also inspect the README and relevant tests.

Review:

* function names
* docstrings
* tool descriptions
* parameter descriptions
* error messages
* comments
* help text
* public exports
* tool registration
* documentation
* tests

Generalize inappropriate MCQuest-specific terminology where appropriate.

Preserve existing behavior and parameters unless a parameter is explicitly MCQuest-specific.

Do not rename Python implementation functions unnecessarily.

The MCP-visible tool names are the important public interface.

## Security

Preserve project-root security.

Do not weaken path validation.

Do not introduce arbitrary filesystem access outside the configured project boundary.

## Read-Only Requirement

Verify that every MCP tool remains strictly read-only.

No tool may:

* create files
* modify files
* delete files
* rename files
* execute arbitrary shell commands
* execute arbitrary code
* install packages
* modify Git history
* commit
* push
* modify the target project

`git_context` and other Git-related tools may perform read-only Git inspection only.

## Validation

After making changes, validate from:

`D:\DeveloperTools\mcquest-mcp`

Use PowerShell 5.1-compatible syntax.

Do not use `&&`.

Run:

```powershell
Set-Location "D:\DeveloperTools\mcquest-mcp"
uv sync
```

Then verify:

```powershell
uv run python -c "import mcquest_mcp; print('Package import OK')"
```

```powershell
uv run python -c "import mcquest_mcp.server; print('Server import OK')"
```

```powershell
uv run python -c "from mcquest_mcp.server import main; print('Entry point OK')"
```

Then verify the registered MCP tools through the appropriate MCP inspection method.

Confirm that the public tool names are generic and that stale `mcquest_` MCP-visible names are not registered.

Do not modify files merely to make a failed validation appear successful.

## Repository Search

Search the entire standalone MCP repository for:

* old MCP-visible tool names
* inappropriate hard-coded MCQuest references
* `D:\App Development\Education_app\MCQuest`
* other assumptions that prevent reuse against arbitrary repositories

Classify remaining MCQuest references as:

* required development/test configuration
* historical/documentation reference
* unwanted project-specific dependency

Do not automatically remove a reference that is required for current architecture.

## Do Not Implement v0.3 Yet

The following are roadmap items only:

* `trace_component`
* `audit_evidence`
* `find_related`
* `route_context`
* `config_context`
* `change_context`
* `verify_finding`
* `audit_summary`

Do NOT create these tools during the generalization task.

They should be implemented later as a separate versioned development task.

## Final Response

Return:

A. Files changed

B. Old tool name → new tool name mapping

C. MCQuest-specific references removed/generalized

D. Validation commands and results

E. Final list of registered MCP tools

F. Remaining intentional MCQuest-specific dependencies and why

G. Confirmation that the server remains strictly read-only

H. Confirmation that no v0.3 roadmap tools were implemented

Keep the final response concise.
