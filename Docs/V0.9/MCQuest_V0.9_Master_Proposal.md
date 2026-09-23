# MCQuest MCP v0.9 — Master Proposal

## Environment, Terminal, Shell & Command Intelligence

**Status:** Proposed — specification only; no implementation authorization  
**Target:** MCQuest MCP v0.9  
**Primary environment:** Windows + PowerShell 7 + Git + Node.js  
**Relationship to v0.8:** Complementary capability; does not replace or redefine v0.8 repository-audit responsibilities

---

# 1. Executive Summary

MCQuest MCP v0.8 establishes repository intelligence: it answers questions about project structure, files, imports, strings, locales, UI contracts, documentation gaps, diagnostics, and other repository-level facts.

Observed Cline workflows reveal a different class of problems. Cline can waste substantial effort interacting with the shell and terminal environment:

- repeatedly changing directories;
- forgetting the canonical repository root;
- rediscovering the same Git configuration;
- repeating the same searches;
- rebuilding broad repository scans already covered by MCQuest;
- constructing very long PowerShell one-liners;
- mixing CMD and PowerShell syntax;
- using native Windows tools with their own argument grammars;
- entering incomplete PowerShell parser states;
- introducing unnecessary console-code-page mutations;
- creating multiple PowerShell windows/processes;
- assuming state from one terminal exists in another;
- confusing file encoding with console rendering;
- continuing after exceptions;
- reporting stale values from variables that survived failed operations;
- blindly repeating failed commands.

These are not primarily repository-intelligence failures. They are **environment, terminal, shell, and command-intelligence failures**.

MCQuest MCP v0.9 therefore proposes a complementary intelligence layer.

The central separation is:

> **MCQuest v0.8 answers: “What is true about the repository?”**  
> **MCQuest v0.9 answers: “How should an agent interact with the environment to obtain that information efficiently and reliably?”**  
> **Cline answers: “What should I accomplish?”**

The MVP should remain deterministic wherever practical and should not become an autonomous coding agent.

It should provide:

1. an Environment Contract;
2. terminal/process/session identity;
3. compact trusted shell context;
4. persistent observations with explicit freshness and scope;
5. semantic operation planning;
6. shell-dialect and native-command awareness;
7. PowerShell parse-completeness checking;
8. command validation and linting;
9. environment-mutation minimization;
10. encoding/rendering diagnostics;
11. redundancy and qualitative cost analysis;
12. failure-aware next-action guidance;
13. MCQuest capability discovery and routing;
14. command and observation history;
15. measurable evaluation against real Cline failure patterns.

The core optimization target is:

> **Fewer actions, fewer mutations, fewer repeated observations, fewer blind retries, and more reliable evidence.**

---

# 2. Problem Statement

Current agent workflows often treat the terminal as a stateless text interface.

That assumption is unsafe.

A model may repeatedly execute:

```powershell
Set-Location 'D:\DeveloperTools\mcquest-mcp'
Set-Location 'D:\DeveloperTools'
Set-Location 'D:\DeveloperTools\mcquest-mcp'
```

or rediscover:

```powershell
Get-Location
git rev-parse --show-toplevel
git config --get core.autocrlf
```

It may use a broad repository scan where an existing MCQuest tool already answers the question.

It may also mix shell dialects:

```powershell
chcp 65001 >nul
```

The command contains a Windows `cmd.exe`-style null-redirection assumption while executing inside PowerShell. In PowerShell, `>` is its own redirection operator and is associated with `Out-File`; the intended CMD idiom is therefore not a safe assumption in PowerShell.

This produces errors such as:

```text
out-file : FileStream was asked to open a device that was not a file.
```

Another class occurs when the command is syntactically incomplete:

```text
PS> findstr /n /c:"..." ...
>>
```

The shell has entered continuation mode rather than executing the intended operation.

Another occurs when native tools such as `findstr.exe` are used for structured JSON questions. The operation may technically work, but it introduces another command-line grammar and encoding boundary.

Another occurs when Cline creates multiple PowerShell windows. A fact observed in one PowerShell process cannot automatically be treated as current state in another.

Another occurs when Unicode output appears corrupted:

```text
Quiz ÓÂæÓÂÜ...
```

The visible terminal output alone does not prove that the JSON file is corrupted. File encoding, native-process output encoding, console code page, terminal rendering, and model interpretation are separate layers.

Finally, a file-read exception may be followed by dependent measurements. PowerShell variables can remain populated after failed operations if execution continues, creating stale or misleading output.

v0.9 must therefore reason about the complete interaction chain:

```text
Model
  ↓
Shell syntax
  ↓
Shell parser
  ↓
Native executable boundary
  ↓
Process/session state
  ↓
Encoding/output layer
  ↓
Filesystem / Git / repository
```

---

# 3. Evidence / Triggering Cases

## 3.1 Wrong working directory

The agent changed into a parent directory and subsequently attempted repository-relative paths.

This is an environment-state failure.

## 3.2 Repeated `chcp 65001 >nul`

The agent repeatedly prefixed commands with:

```powershell
chcp 65001 >nul;
```

This created a systematic PowerShell compatibility error and demonstrated unnecessary environment mutation.

## 3.3 Repeated `findstr` searches

The agent repeatedly executed commands such as:

```powershell
findstr /n /c:"takeQuiz" frontend\src\locales\en.json frontend\src\locales\si.json frontend\src\locales\ta.json
findstr /n /c:"competeAndClimb" frontend\src\locales\en.json frontend\src\locales\si.json frontend\src\locales\ta.json
```

The overall workflow showed repeated commands, native executable grammar, PowerShell quoting complexity, encoding/rendering problems, and structured-data questions being treated as text-search questions.

## 3.4 Incomplete command submission

A command ending in:

```text
>>
```

indicates PowerShell is waiting for more input. v0.9 must distinguish incomplete parser state from execution failure.

## 3.5 Multiple PowerShell windows

Three PowerShell windows demonstrate that CWD, environment variables, PowerShell variables, process state, and terminal configuration cannot automatically be treated as global project state.

## 3.6 Unicode rendering confusion

Terminal output showed mojibake while a Node.js JSON read returned valid Sinhala/Tamil Unicode. This demonstrates that terminal rendering is not authoritative evidence of file corruption.

## 3.7 Broad text search for structured data

A request such as:

```text
quiz.loading
```

is fundamentally a JSON lookup. Repeated `findstr` calls are a poor semantic representation compared with a structured JSON read.

## 3.8 Exception followed by stale output

A failed file-read operation can leave dependent calculations operating on old state. v0.9 must prevent failed input from becoming successful-looking evidence.

---

# 4. Product Boundary

## MCQuest v0.8 — Repository Intelligence

> **What is true about the repository?**

Examples:

- What files exist?
- What components exist?
- Where are imports?
- Where are untranslated strings?
- What documentation gaps exist?
- What UI contract violations exist?
- What repository diagnostics exist?

## MCQuest v0.9 — Environment, Terminal, Shell & Command Intelligence

> **How should an agent interact with the machine and repository to obtain reliable information efficiently?**

Examples:

- What shell am I actually running?
- Which terminal/process am I operating in?
- Is the current CWD trusted?
- Has this environment fact already been observed?
- Is this command using CMD syntax inside PowerShell?
- Is a native executable introducing another argument grammar?
- Is the command syntactically complete?
- Is the intended operation really a JSON lookup rather than text search?
- Is this command unnecessarily mutating terminal state?
- Could the output be misleading because of encoding/rendering?
- Is this command redundant?
- Does an existing MCQuest capability already answer the task?
- What is the cheapest correct next action after failure?

## Cline — Task Intelligence

> **What should the agent accomplish?**

Cline remains the task and execution authority.

---

# 5. Core Design Principles

### 5.1 Fewer Actions

Do not generate a command when a fresh observation already answers the question.

### 5.2 Observe Before Mutating

Prefer:

```text
observe → reason → act
```

over:

```text
mutate environment → hope it helps → observe
```

### 5.3 Explicit State Over Assumed State

Never assume a previous terminal's state is current.

### 5.4 Semantic Intent Over Command Text

Reason about operations such as:

```text
READ_JSON
SEARCH_LITERAL
MEASURE_EOL
CHECK_GIT_STATE
```

before selecting PowerShell, Node, Python, `findstr`, or MCQuest.

### 5.5 Deterministic Validation Over Speculative Intelligence

Use deterministic rules wherever possible.

### 5.6 No False Evidence

Failed input must not produce authoritative dependent measurements.

### 5.7 No Blind Retry

A failure should change the next action.

---

# 6. Proposed Architecture

```text
┌──────────────────────────────────────────────────────┐
│              MCQuest Shell Intelligence             │
├──────────────────────────────────────────────────────┤
│ Environment Contract                                 │
│ Terminal / Process Identity                          │
│ Observation Store                                    │
│ Freshness + Scope + Invalidation                     │
│                                                      │
│ Intent / Operation Classifier                        │
│ Command Planner                                      │
│ Shell Dialect Analyzer                               │
│ Native Command Boundary Analyzer                     │
│ Parse Completeness Analyzer                          │
│ Command Validator / Linter                           │
│ Terminal Hygiene Analyzer                            │
│ Encoding / Rendering Analyzer                        │
│ Failure / Recovery Analyzer                          │
│ MCQuest Capability Router                            │
│                                                      │
│ Command / Observation History                        │
└───────────────────────┬──────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      PowerShell     MCQuest MCP    Git / FS / Node
      environment    repository     environment
                     intelligence
```

---

# 7. Environment Contract

Example:

```text
SHELL CONTEXT

OS: Windows
Shell: PowerShell 7
Repo: D:\DeveloperTools\mcquest-mcp
CWD: untrusted

Terminal:
  session = abc123
  process = 18240

Git:
  core.autocrlf = true

Known capabilities:
  mcquest_doc_gap_audit
  mcquest_component_inventory
  mcquest_diagnostics

Rules:
  prefer targeted operations
  prefer structured reads for structured data
  use explicit repository paths when CWD is uncertain
  use -SimpleMatch for literal searches
  avoid unnecessary chcp
  fail fast on dependent reads
  do not emit measurements after failed input
  do not repeat fresh observations
  do not trust observations from another terminal process
```

Potential fields include OS, shell family/version, repository identity, terminal session, process ID, Git configuration, executable versions, console encoding, and project-specific capabilities.

---

# 8. Terminal and Process Identity

v0.9 must distinguish:

```text
logical agent session
        ↓
terminal session
        ↓
PowerShell process
        ↓
CWD / environment / variables
```

Example:

```json
{
  "terminal": {
    "session_id": "abc123",
    "process_id": 18240,
    "shell": "pwsh",
    "version": "7.x",
    "cwd": "D:\App Development\Education_app\MCQuest"
  }
}
```

A new PowerShell process must receive a new process/session identity. Process-scoped observations must not automatically transfer.

---

# 9. Observation Model

Observations must be structured, attributable, and scoped.

Example:

```json
{
  "observation": "git.autocrlf",
  "value": true,
  "scope": "repository",
  "repository": "D:\DeveloperTools\mcquest-mcp",
  "observed_at": "...",
  "source": "git config core.autocrlf",
  "confidence": 1.0,
  "freshness": "session"
}
```

Locale observation:

```json
{
  "observation": "locale.quiz.loading.si",
  "value": "Quiz පූරණය වෙමින්...",
  "scope": "file",
  "file": "frontend/src/locales/si.json",
  "operation": "READ_JSON",
  "terminal_session": "abc123",
  "confidence": 1.0
}
```

Every observation should answer:

- what was observed;
- what value was obtained;
- where it applies;
- when it was observed;
- how it was obtained;
- in which terminal/process;
- how confident the system should be;
- how long it remains valid.

---

# 10. Observation Scope

## REPOSITORY

Stable repository facts.

## WORKTREE

Facts affected by source or Git changes.

## SESSION

Facts valid for a development session.

## PROCESS

Facts belonging to one shell process.

Examples:

- CWD;
- PowerShell variables;
- process-local environment.

## EPHEMERAL

Short-lived command-specific state.

This prevents accidental promotion of process state into global project truth.

---

# 11. Freshness and Invalidation

Freshness classes:

- **STATIC** — repository root, repository identity.
- **SESSION** — discovered tool versions and configuration.
- **WORKTREE** — Git status, file inventories, diagnostics.
- **PROCESS** — CWD, shell variables, process-local state.
- **EPHEMERAL** — command output and temporary state.

Examples of invalidation:

| Event | Potentially stale |
|---|---|
| File modified | content, searches, diagnostics |
| File created/deleted | inventories, path existence |
| Git checkout | worktree observations |
| Branch switch | Git state |
| CWD changes | process CWD |
| New PowerShell process | process state |
| Dependency installation | executable/package facts |
| Configuration change | corresponding observations |
| Console code-page change | encoding observations |

Principle:

> **Invalidate rather than guess.**

---

# 12. Semantic Operation Classification

v0.9 should classify the intended operation before selecting a command.

Initial taxonomy:

```text
READ_FILE
READ_JSON
SEARCH_LITERAL
SEARCH_REGEX
ENUMERATE_FILES
CHECK_PATH
CHECK_GIT_STATE
CHECK_CONFIG
MEASURE_EOL
RUN_NODE
RUN_PYTHON
RUN_TEST
BUILD
INSTALL
EDIT
```

Example:

```text
Intent:
  Check quiz.loading in en/si/ta JSON files.

Operation:
  READ_JSON

Preferred:
  Parse JSON and inspect the key.

Avoid:
  repeated findstr searches.
```

This is a major architectural improvement over command-only validation.

---

# 13. Shell Dialect Intelligence

The system must distinguish:

```text
PowerShell
CMD
native Windows executable
Node.js
Python
nested shell
```

Example:

```powershell
chcp 65001 >nul
```

contains a CMD-style null-redirection assumption inside PowerShell.

v0.9 should flag:

```text
Cross-shell syntax hazard:
CMD-style null redirection detected in PowerShell.
```

---

# 14. Native Command Boundary

Commands such as:

```powershell
findstr /n /c:"takeQuiz" frontend\src\locales\en.json
```

invoke a native executable with its own argument grammar.

v0.9 should recognize:

```text
PowerShell
   ↓
native executable
   ↓
native argument parser
```

and account for:

- quoting;
- escaping;
- redirection;
- encoding;
- wildcard handling;
- argument boundaries.

---

# 15. Parse Completeness

Before execution, v0.9 should detect:

- unmatched quotes;
- unmatched parentheses;
- incomplete pipelines;
- dangling operators;
- unfinished script blocks;
- continuation prompts.

For example:

```text
>>
```

should be classified as:

```text
Command incomplete.

Do not treat this as an ordinary execution failure.
Complete or replace the command.
```

---

# 16. Command Validation

`shell_validate` should analyze:

1. syntax;
2. parse completeness;
3. shell dialect;
4. native-command boundaries;
5. CWD dependence;
6. path safety;
7. redundancy;
8. semantic operation suitability;
9. environment mutation;
10. encoding risk;
11. failure propagation;
12. stale-variable hazards;
13. qualitative cost;
14. MCQuest capability duplication.

Example result:

```text
COMMAND ANALYSIS

Syntax:
  PASS

Parse completeness:
  PASS

Shell dialect:
  WARNING
  CMD-style `>nul` detected in PowerShell.

Native boundary:
  WARNING
  findstr.exe has its own argument grammar.

Encoding:
  WARNING
  console mutation appears unnecessary.

CWD:
  PASS

Redundancy:
  WARNING
  equivalent search was already executed.

Operation:
  SUBOPTIMAL
  structured JSON lookup is more appropriate.

Cost:
  LOW

Recommendation:
  Use READ_JSON.
```

---

# 17. Terminal Hygiene

Detect:

- unnecessary `chcp`;
- unnecessary `Set-Location`;
- repeated environment initialization;
- unnecessary environment-variable mutation;
- unnecessary PowerShell process creation;
- repeated terminal setup;
- assumptions that state persists across processes.

This is a first-class V0.9 capability, not merely a style check.

---

# 18. Environment Mutation Minimization

State-changing operations should carry additional cost.

Examples:

```text
Set-Location
chcp
$env:NAME = ...
Set-ExecutionPolicy
Set-Item ...
```

Principle:

> **Prefer local explicitness over global shell-state changes.**

If an explicit repository path is sufficient, changing CWD may be unnecessary.

If structured JSON reading solves the problem, changing console code page may be unnecessary.

---

# 19. Encoding and Rendering Intelligence

Encoding must be modeled as separate layers:

```text
File encoding
      ↓
Native executable I/O
      ↓
Process output encoding
      ↓
Console code page
      ↓
Terminal rendering
      ↓
Model interpretation
```

The system must not infer source corruption solely from terminal output.

Example:

```text
Terminal:
  Quiz ÓÂæÓÂÜ...

Node JSON read:
  Quiz පූරණය වෙමින්...
```

The structured source read is stronger evidence about file contents.

v0.9 should distinguish:

```text
SOURCE EVIDENCE
```

from:

```text
TERMINAL RENDERING EVIDENCE
```

---

# 20. Encoding Diagnostic Rules

Potential finding:

```text
Encoding mismatch suspected.

The file was read successfully as UTF-8.
The displayed terminal output appears corrupted.

Do not modify the source file based solely on terminal rendering.
Verify using a structured or encoding-explicit read.
```

Repeated `chcp 65001` should also be recognized as potentially unnecessary.

---

# 21. Exception and Failure Semantics

Unsafe pattern:

```powershell
$bytes = [IO.File]::ReadAllBytes($p)
$count = $bytes.Length
Write-Output "$p $count"
```

If the read fails and execution continues, `$bytes` may retain an earlier value.

Rule:

> **A measurement derived from failed input must never be emitted as authoritative evidence.**

Preferred semantic structure:

```powershell
try {
    $bytes = [IO.File]::ReadAllBytes($p)

    # dependent calculations
}
catch {
    # explicit failure
}
```

---

# 22. Stale Variable Hazard

The validator should detect:

```text
operation A can fail
       ↓
variable X may retain old value
       ↓
operation B uses X
       ↓
output is presented as current evidence
```

Finding:

```text
Potential stale-state hazard.

Variable '$bytes' is used after a potentially failed assignment.

Require explicit success handling before dependent output.
```

---

# 23. Command Planning

Example:

```text
Intent:
  Check EOL for V0.8 documentation.
```

Plan:

```text
1. Check for a fresh EOL observation.
2. If present, return it.
3. Otherwise identify only required documentation files.
4. Measure EOL with explicit failure handling.
5. Record observations.
6. Do not repeat repository-wide scans.
```

---

# 24. Command Redundancy

Detect:

- exact duplicate commands;
- normalized duplicates;
- repeated environment initialization;
- equivalent searches;
- repeated Git checks;
- repeated file reads;
- repeated repository-root discovery.

Repeat only if:

```text
state changed
scope changed
observation expired
previous result failed
```

---

# 25. Cost Model

### Trivial

- observation lookup;
- `Get-Location`;
- single `Test-Path`.

### Low

- targeted file read;
- structured JSON read;
- single-file literal search;
- `git status`.

### Medium

- bounded directory enumeration;
- multiple targeted reads.

### High

- recursive repository scans;
- broad `Select-String`;
- custom Python crawlers.

### Very High

- repeated full scans;
- overlapping repository crawlers.

### Mutation Cost

Operations that change environment state receive additional cost.

The model identifies unnecessary breadth, mutation, and repetition rather than predicting exact wall-clock time.

---

# 26. MCQuest Capability Integration

Example:

```text
Intent:
  Find documentation gaps.

Existing capability:
  mcquest_doc_gap_audit

Recommendation:
  Use the MCQuest capability.

Do not construct:
  Get-ChildItem -Recurse + Select-String + custom parser
```

v0.9 should route semantic intent to existing MCQuest capabilities before constructing custom shell scans.

---

# 27. Proposed MCP Tool Surface

| Tool | Purpose |
|---|---|
| `shell_environment` | Discover OS/shell/environment |
| `shell_terminal` | Identify terminal/process/session state |
| `shell_context` | Return compact trusted context |
| `shell_plan` | Convert intent into operation plan |
| `shell_prepare` | Produce concrete command |
| `shell_validate` | Validate proposed command |
| `shell_observe` | Record observation |
| `shell_next` | Determine next action after failure |
| `shell_history` | Retrieve relevant prior activity |
| `shell_capabilities` | Discover available MCQuest capabilities |

`Shell lint` should initially be a mode of `shell_validate`, not necessarily a separate MCP tool.

---

# 28. Cline Interaction Pattern

```text
1. Cline states task.
        ↓
2. v0.9 identifies terminal/process context.
        ↓
3. v0.9 retrieves compact trusted environment context.
        ↓
4. v0.9 classifies semantic operation.
        ↓
5. v0.9 checks existing observations.
        ↓
6. v0.9 checks MCQuest capabilities.
        ↓
7. If needed, v0.9 creates minimal plan.
        ↓
8. v0.9 validates command.
        ↓
9. Cline executes.
        ↓
10. v0.9 records evidence.
        ↓
11. v0.9 invalidates affected observations.
        ↓
12. On failure, shell_next selects a differentiated next action.
```

---

# 29. Failure-Aware Recovery

Classify failures such as:

```text
syntax failure
parse incompleteness
wrong CWD
missing file
permission failure
encoding/rendering issue
native-command argument issue
PowerShell semantic issue
repository-state issue
tool availability issue
```

Example:

```text
Failure:
  current path does not exist.

Cause:
  repository-relative path was evaluated from an untrusted CWD.

Do not:
  retry the same command.

Next:
  establish repository root or use an explicit repository path.
```

---

# 30. No Blind Retry Policy

A retry requires a changed condition.

Valid reasons:

```text
state changed
scope changed
command corrected
path corrected
encoding method corrected
shell dialect corrected
previous failure was transient
```

Invalid reason:

```text
Try the same command again.
```

---

# 31. Knowledge Base vs MCP

A knowledge base is appropriate for:

- architecture;
- coding conventions;
- documentation;
- workflows.

It is insufficient for:

- current CWD;
- terminal identity;
- process state;
- Git state;
- observation freshness;
- command semantics;
- parser completeness;
- failure propagation;
- terminal encoding.

Therefore the environment layer should use live MCP observations.

Hybrid architecture:

```text
Project knowledge
       +
Live MCP observations
       +
Deterministic shell validation
       +
MCQuest capability discovery
```

---

# 32. Why Not Just Prompt Instructions?

Prompts are not:

- authoritative state;
- process-scoped;
- freshness-aware;
- deterministic parser analyzers;
- reliable command-provenance stores;
- multi-terminal state trackers.

v0.9 turns these principles into structured machine-readable state and validation.

---

# 33. Why Not a Generic AI Shell Assistant?

The objective is not merely:

> Generate a shell command.

The objective is:

> Understand the environment, identify the semantic operation, select the appropriate execution mechanism, avoid unnecessary mutation, validate shell semantics, preserve evidence provenance, and recover intelligently from failure.

---

# 34. MVP Scope

## Platform

- Windows;
- PowerShell 7;
- Git;
- Node.js-aware workflows.

## Core environment

- Environment Contract;
- terminal/process identity;
- observation store;
- scope and freshness;
- invalidation;
- compact shell context.

## Core planning

- semantic operation classification;
- minimal command planning;
- MCQuest capability routing;
- command preparation.

## Core validation

- CWD trust;
- relative-path dependence;
- shell dialect detection;
- native-command boundaries;
- parse completeness;
- duplicate commands;
- broad scans;
- unnecessary environment mutation;
- encoding/rendering risk;
- exception-unsafe calculations;
- stale-variable hazards;
- cost classification.

## Core recovery

- failure classification;
- differentiated next action;
- blind-retry prevention.

## Explicit non-goals

- autonomous shell execution;
- automatic repository modification;
- vector database;
- broad cross-platform abstraction;
- replacing v0.8 audit tools.

---

# 35. Later Phases

## Phase 2

- PowerShell AST analysis;
- stronger command equivalence;
- filesystem/Git event invalidation;
- reusable workflow templates;
- richer MCQuest capability routing;
- deeper native-command argument analysis.

## Phase 3

- Bash;
- CMD;
- Linux/macOS;
- additional terminal environments.

## Phase 4

- optional local LLM assistance;
- PSReadLine integration;
- learning from corrections;
- provenance-aware adaptive recommendations.

## Phase 5

- optional policy enforcement;
- sandboxing;
- controlled autonomy.

Autonomous execution must remain separately authorized.

---

# 36. Evaluation Plan

Use real Cline failure patterns.

## Benchmark scenarios

1. Wrong CWD.
2. Repeated `Set-Location`.
3. Repeated Git configuration checks.
4. Repeated repository-wide searches.
5. `chcp 65001 >nul` inside PowerShell.
6. Native `findstr` misuse.
7. Incomplete PowerShell command.
8. Multiple PowerShell windows.
9. Stale output after exceptions.
10. Unicode rendering confusion.
11. Shell scan duplicating an MCQuest capability.
12. Overly long PowerShell one-liner.
13. Blind retry after failure.
14. Structured JSON question solved through text search.
15. Unnecessary environment mutation.

## Metrics

Measure:

- commands per task;
- failed commands;
- parse-incomplete commands;
- duplicate commands;
- blind retries;
- command character count;
- environment mutations;
- PowerShell process count;
- terminal/session count;
- filesystem traversal count where measurable;
- model/tool token consumption;
- elapsed execution time;
- successful task completion;
- false-evidence incidents;
- unnecessary MCQuest-duplicating scans.

The comparison should be:

```text
Baseline Cline
      vs.
Cline + MCQuest v0.9
```

Priority:

1. reliability;
2. reduced unnecessary work;
3. evidence correctness;
4. reduced terminal mutation;
5. lower retry rate.

---

# 37. Acceptance Criteria

A release candidate should demonstrate that:

1. repository root can be established and reused;
2. CWD is scoped to the correct terminal/process;
3. observations have explicit scope and freshness;
4. stale observations are invalidated;
5. multiple PowerShell processes are distinguishable;
6. repeated environment discovery is reduced;
7. duplicate commands are detected;
8. broad scans are identified;
9. shell dialect mismatches are detected;
10. native command boundaries are identified;
11. incomplete PowerShell commands are detected;
12. unnecessary `chcp` mutations are detected;
13. structured JSON operations can be distinguished from text searches;
14. encoding/rendering confusion is identified;
15. exception-unsafe measurements are detected;
16. stale-variable hazards are surfaced;
17. existing MCQuest capabilities can be recommended;
18. failures lead to differentiated next actions;
19. blind retries are reduced;
20. command provenance is retained;
21. observations can be safely reused;
22. autonomous shell execution is not required.

---

# 38. Development Principles

Primary:

> **Observe once, remember explicitly, validate before execution, invalidate when necessary, and never repeat work without a reason.**

Secondary:

> **Prefer observation over mutation.**

> **Prefer semantic operations over ad-hoc commands.**

> **Prefer explicit local state over implicit shell state.**

> **Never turn failed input into successful-looking evidence.**

> **Never assume state from another terminal process.**

---

# 39. Relationship to V0.8

v0.9 is additive.

V0.8 owns repository intelligence.

V0.9 owns:

- environment intelligence;
- terminal/process intelligence;
- shell dialect intelligence;
- semantic command planning;
- command validation;
- encoding/rendering diagnostics;
- environment mutation analysis;
- observation freshness;
- command history;
- failure-aware recovery;
- MCQuest capability routing.

v0.9 must not duplicate or weaken v0.8 tools.

---

# 40. Decision Records

### DEC-036 — V0.9 Scope and Separation

Define the boundary between repository intelligence and environment/terminal intelligence.

### DEC-037 — Environment Contract and Freshness Classes

Define environment facts, scopes, and trust semantics.

### DEC-038 — Observation Model and Invalidation Rules

Define observation structure, provenance, confidence, scope, freshness, TTL, and invalidation.

### DEC-039 — Initial MCP Tool Surface

Define initial shell-intelligence tools and responsibilities.

### DEC-040 — PowerShell Validation and Stale-Output Safety

Define PowerShell correctness rules, including exception-unsafe calculations.

### DEC-041 — Cost Model and Redundancy Policy

Define operation cost, mutation cost, and redundancy detection.

### DEC-042 — MCQuest Capability Discovery Integration

Define how v0.9 identifies and recommends existing MCQuest capabilities.

### DEC-043 — MVP Evaluation Benchmark and Acceptance Criteria

Define measurable benchmark scenarios and release criteria.

### DEC-044 — Shell Dialect and Native Command Boundaries

Define PowerShell, CMD, native executable, Node.js, Python, and nested-shell boundaries.

### DEC-045 — Terminal and Process Identity

Define terminal-session and process-scoped observations.

### DEC-046 — Command Parse Completeness

Define detection of incomplete PowerShell commands and continuation states.

### DEC-047 — Environment Mutation Minimization

Define policy for `chcp`, `Set-Location`, environment variables, and other state-changing commands.

### DEC-048 — Encoding and Rendering Separation

Define separation of file encoding, process encoding, console code page, terminal rendering, and model interpretation.

### DEC-049 — Semantic Operation Classification

Define the initial operation taxonomy and operation-to-execution planning.

### DEC-050 — Terminal Hygiene and Multi-Terminal Awareness

Define multi-terminal behavior, process lifecycle awareness, and terminal-state hygiene.

---

# 41. Proposed Documentation Package

```text
Docs/
└── V0.9/
    ├── 00-V0.9-MASTER.md
    ├── 01-V0.9-CONTRACT.md
    ├── 02-V0.9-PLAN.md
    ├── 03-V0.9-STATE.md
    ├── 04-V0.9-TEST-PLAN.md
    ├── 05-V0.9-DECISIONS.md
    ├── 06-V0.9-CHANGELOG.md
    ├── 07-V0.9-CONSOLIDATION.md
    └── 08-V0.9-CONSOLIDATED-COVERAGE.md
```

The package should preserve V0.8 discipline.

Implementation should not begin until the V0.9 contract and decisions are explicitly approved.

---

# 42. Proposed V0.9 Status

**MCQuest MCP v0.9 is proposed, not implementation-authorized.**

Immediate next stage: specification.

Before implementation:

- scope approved;
- V0.8/V0.9 boundary confirmed;
- Environment Contract approved;
- terminal/process identity approved;
- observation semantics approved;
- semantic operation model approved;
- shell-dialect rules approved;
- encoding/rendering model approved;
- command validation rules approved;
- evaluation criteria approved.

---

# Appendix A — Conceptual Environment Context

```text
SHELL CONTEXT

OS: Windows
Shell: PowerShell 7
Repo: D:\DeveloperTools\mcquest-mcp
CWD: untrusted

Terminal:
  session = abc123
  process = 18240

Git:
  core.autocrlf = true

Encoding:
  file = UTF-8 where verified
  console = do not assume
  rendering = not authoritative

Known capabilities:
  mcquest_doc_gap_audit
  mcquest_component_inventory
  mcquest_diagnostics

Rules:
  prefer targeted operations
  prefer structured reads for structured data
  use explicit repository paths when CWD is uncertain
  use -SimpleMatch for literal searches
  avoid unnecessary chcp
  avoid unnecessary Set-Location
  fail fast on dependent reads
  do not emit measurements after failed input
  do not repeat fresh observations
  do not trust observations from another terminal process
```

---

# Appendix B — Example Semantic Planning

## Request

```text
Check the quiz.loading translation in English, Sinhala, and Tamil.
```

## Classification

```text
Operation:
  READ_JSON

Files:
  frontend/src/locales/en.json
  frontend/src/locales/si.json
  frontend/src/locales/ta.json

Key:
  quiz.loading
```

## Preferred execution

```text
Parse JSON.
Read quiz.loading from each locale.
```

## Avoid

```text
repeated findstr
repeated chcp
multiple terminal changes
repository-wide scans
```

---

# Appendix C — Example Shell Validation

Proposed command:

```powershell
chcp 65001 >nul; findstr /n /c:"takeQuiz" frontend\src\locales\en.json frontend\src\locales\si.json frontend\src\locales	a.json
```

Expected analysis:

```text
Syntax:
  PASS

Shell:
  PowerShell

Cross-shell compatibility:
  WARNING
  CMD-style `>nul` resembles CMD null redirection.

Environment mutation:
  WARNING
  chcp changes console state.

Native executable:
  WARNING
  findstr.exe has its own argument grammar.

Encoding:
  WARNING
  console mutation may not address source encoding.

Semantic operation:
  SEARCH_LITERAL

Alternative:
  If the goal is a JSON key lookup, prefer READ_JSON.

Redundancy:
  CHECK HISTORY

Cost:
  LOW

Recommendation:
  Avoid repeated chcp.
  Prefer structured JSON access when key/value lookup is intended.
```

---

# Appendix D — Example Failure Recovery

## Failure

```text
out-file : FileStream was asked to open a device that was not a file.
```

## Classification

```text
Failure class:
  shell dialect / redirection semantics

Likely cause:
  CMD-style `>nul` used in PowerShell

Do not:
  repeat the same command

Next:
  remove the CMD-style null redirection or use a PowerShell-appropriate
  output-suppression mechanism only if suppression is actually required.
```

---

# Appendix E — Example Multi-Terminal Handling

Terminal A:

```text
session = A
process = 1001
cwd = D:\App Development\Education_app\MCQuest
```

Terminal B:

```text
session = B
process = 2002
cwd = unknown
```

If Cline executes:

```powershell
Get-Content frontend\src\locales\en.json
```

from Terminal B:

```text
CWD for current terminal is untrusted.

Establish repository context or use an explicit path.
```

Terminal A's CWD must not be silently reused.

---

# Appendix F — Research-Informed Design Notes

The proposal is informed by investigation into:

- PowerShell parsing and redirection;
- native-command argument boundaries;
- common Windows shell workflows;
- AI-assisted shell tools;
- terminal-agent workflows;
- command-generation patterns;
- repository-intelligence integration;
- prototype evaluation approaches.

Current primary documentation should be preferred for implementation decisions.

Relevant PowerShell documentation:

- PowerShell redirection:  
  https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection

- PowerShell parsing:  
  https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing

- Windows `findstr`:  
  https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/findstr

Earlier ecosystem research also considered AIChat, ShellGPT, and Warp as examples of AI-terminal approaches. These are ecosystem context, not architectural dependencies.

---

# Final Proposal Statement

MCQuest MCP v0.9 should not be understood as “more repository auditing.”

It is an intelligence layer for the environment in which repository work happens.

Its responsibility is to make Cline's interaction with Windows, PowerShell, terminals, native commands, files, Git, and MCQuest itself:

- state-aware;
- process-aware;
- shell-dialect-aware;
- operation-aware;
- failure-aware;
- encoding-aware;
- redundancy-aware;
- mutation-aware;
- repository-aware;
- MCQuest-aware;
- and measurably more efficient.

The final architectural separation is:

```text
MCQuest V0.8
Repository Intelligence
        │
        ▼
“What is true?”

MCQuest V0.9
Environment + Terminal + Command Intelligence
        │
        ▼
“How should I interact with it?”

Cline
Task Intelligence
        │
        ▼
“What should I accomplish?”
```

The most important V0.9 principle is:

> **Do not merely validate the command the model generated. Validate whether the command is the right representation of the intended operation, whether it is safe in the current terminal state, whether it will produce trustworthy evidence, and whether the work has already been done.**

This provides a focused path for improving Cline reliability without turning MCQuest into a generic autonomous coding agent.
