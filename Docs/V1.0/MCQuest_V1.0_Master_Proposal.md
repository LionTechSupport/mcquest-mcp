# MCQuest MCP v1.0 — Master Proposal

> STATUS: **PROPOSED — SUPERSEDED IN PART BY P1 MEASUREMENT (2026-09-29)**
>
> This is the source specification for v1.0, kept for traceability in the v0.9 documentation
> style. It records the problem as originally stated **and** the audit-evidenced revision of
> that problem **and** the P1-measured revision of that. It is a **snapshot document**: where it
> disagrees with `01-V1.0-CONTRACT.md`, the contract wins.
>
> **P1 headline:** 0 of 7 scenarios needed a missing tool; the motivating request completed with
> no shell; the recommended V1.0 tool surface is **0 new tools**.

---

## 1. Statement of intent

V0.9 established shell intelligence: environment, terminal identity, context, capabilities,
observation, validation, planning, preparation, history, and next-step reasoning.

V1.0 has a different primary goal:

> **Local repository/document information should be retrieved through structured MCQuest
> evidence tools instead of defaulting to shell commands.**

Core behavioural principle:

> **Structured local evidence first; shell only when genuinely required.**

Out of scope by instruction: VPS, SSH, remote execution, remote files, remote infrastructure.

---

## 2. The problem as originally stated

The motivating observation was a Cline behaviour of this shape:

```powershell
cd 'D:\App Development\Education_app\MCQuest'
$f='docs\phase\PHASE-DRAFT-ITF-001-AUTH-REQUEST-RELIABILITY.md'
$c=Get-Content $f
$n=($c | Select-String -Pattern '^## 13\.' | Select-Object -First 1).LineNumber
$c[($n-14)..($n-1)]
```

For the request *"Find `## 13.` in this Markdown document and return the surrounding lines."*

The desired end state was:

```text
mcquest_file_find
        ↓
match at line 1332
        ↓
mcquest_file_read
        ↓
requested line range
```

with no shell command.

### 2.1 The audit's correction to this problem

The Gate 0 audit established three facts that change the shape of the solution:

| # | Fact | Effect |
| --- | --- | --- |
| 1 | `mcquest_read_file` and `mcquest_search_docs` **already exist and are registered** | Two of the three "future" tools are present tense |
| 2 | The behaviour is achievable **today** with two calls | This is a routing/defaulting problem, not a capability gap |
| 3 | The host agent already owns `read_files` / `search_codebase`, and the example path is **outside** the MCQuest root | The routing tree needs a third branch, and MCQuest tools cannot serve that example |

> **Reframed problem.** Not *"build the file tools"*, but *"make the existing structured
> evidence surface the default route, and prove it"*.

---

## 3. Proposed surface (original) vs proposed surface (audited)

| Tool | Original proposal | Audited resolution | Basis |
| --- | --- | --- | --- |
| `mcquest_file_read` | new bounded read tool | **Reject — use `mcquest_read_file`** | Finding A2 |
| `mcquest_file_find` | new literal-first finder | **Thin alias, or drop** | Finding A3 |
| `mcquest_json_read` | new structured JSON reader | **Add — the one genuine gap** | Finding A5 |

---

## 4. Design constraints (restated as requirements)

| Constraint | Requirement |
| --- | --- |
| Read-only | No write / edit / delete / install / arbitrary execution / arbitrary subprocess |
| Local-only | No SSH, VPS, remote filesystem, remote shell, remote execution |
| Bounded | Every retrieval and search explicitly bounded; no unbounded repository read |
| Deterministic | Same input + same file state ⇒ same result |
| Evidence-oriented | What was inspected, what was returned, completeness, truncation, path, provenance |
| No invented certainty | No numeric confidence; `UNKNOWN` remains `UNKNOWN` |

---

## 5. Explicit non-goals

Embeddings · vector search · fuzzy/similarity search · autonomous crawling · background
indexing · file watchers · automatic edits · shell interception · execution gates ·
remote/VPS tooling.

v1.0 solves one problem well:

> **Reliable, bounded, structured retrieval of local repository information, with routing that
> prefers those tools over shell commands.**

## 6. Tool count ledger

| Reading | Count | Status |
| --- | --- | --- |
| v0.9 live baseline | 34 | EXISTING / LIVE |
| Original proposal ceiling (`+3`) | 37 | **SUPERSEDED by measurement** |
| Gate 0 audited recommendation (`+1`) | 35 | **SUPERSEDED by measurement** |
| Optional alias (`+2`) | 36 | **REJECTED at P1** |
| Zero-new-tool option | 34 | **RECOMMENDED at P1** |
| **Live count at P1** | **34** | **UNCHANGED** |

`EXPECTED_TOOLS` remains unchanged. The live count remains 34. **P1 recommends it stays 34.**

---

## 6a. P1-measured resolution of §8

The central open question in §8 was *"Is a routing contract enough, or is new tooling
required?"* — answered on 2026-09-29:

| Question | Answer |
| --- | --- |
| Is a routing contract enough? | **Yes** — 0 of 7 scenarios failed for want of a tool |
| Is new tooling required? | **No** — all measured defects are vocabulary, labelling, or policy |
| What *is* missing? | (a) an in-root/out-of-root branch in the instructions; (b) scope labelling; (c) a VCS operation class — **all three need no new tool** |
| Where is the real gap? | **Client-side policy** — `project-rules.md` has no read-side rule, and it is outside this repository |

> **Reframed again.** Gate 0 said *"build the file tools"*. P1 says *"the file tools exist; the
> routing contract needs two clarifications and the client rules need one line."*

---

## 7. Acceptance model

Acceptance is behavioural, not tool-existence:

| Test | Definition |
| --- | --- |
| A — exact heading lookup | structured search; **not** `Select-String` |
| B — surrounding lines | structured bounded read; **not** a `Get-Content` pipeline |
| C — JSON | JSON tool; **not** a shell JSON pipeline |
| D — genuine shell need | v0.9 shell intelligence still used |
| E — no false shell routing | a documented suite never routes to shell |

Full definitions: `06-V1.0-TEST-PLAN.md` §6.

---

## 8. The central open question

> **Is a routing contract enough, or is new tooling required?**

The audit's answer is that routing is the problem and most of the tooling already exists —
but that answer is **untested against a live client**, because tool availability is not tool
selection (contract §5.3). Phase P3 exists to measure this, and phase P2 is explicitly
**optional** and should be justified by P3's evidence rather than by this proposal.

---

## 9. Relationship to the v0.9 package

| Item | Treatment |
| --- | --- |
| `Docs/V0.9/*` | **UNCHANGED.** Not modified, renamed, or deleted. |
| V0.9 frozen vocabularies | Inherited verbatim; v1.0 adds concepts additively only |
| Decision A12 (no duplication) | **Binding constraint** on the v1.0 tool surface |
| V0.9 §13 preference ladder | **Normative** for v1.0; v1.0 operationalizes it |
| `EXPECTED_TOOLS` | Unchanged registration authority |

---

## 10. Proposal status

```text
Status ................. PROPOSED — NOT IMPLEMENTATION-AUTHORIZED
Phase .................. Gate 0 (documentation only) — COMPLETE
Source changes ......... 0
Test changes ........... 0
Live tool count ........ 34 (unchanged)
Commits ................ 0
Owner decisions ........ OD-1 … OD-4 required before P1
```

---

## 8. P2 status (added 2026-09-29)

| Item | Value |
| --- | --- |
| Phase | **P2 — COMPLETE (`PASS`)** |
| Nature | routing contract + discoverability regression |
| Source changed | 1 (`server.py` — guidance text only) |
| Test changed | 1 (`test_discoverability.py`, +6) |
| **Tools added** | **0** (live remains 34) |
| Behaviour changed | **NONE** |
| Tests | `966 passed, 1 skipped` (was `960 / 1`) |
| Commits / pushes | 0 / 0 |

### 8.1 Delivered

1. **In-root / out-of-root routing branch** stated in the MCP `instructions` — the only
   server-side lever available, since MCQuest cannot observe or veto client tool selection.
2. **Search scope semantics** exposed in-band on `mcquest_search` and
   `mcquest_search_docs`, and specified normatively in contract §5.4a.1 with source citations.
3. **Six discoverability tests**, including one behavioural test that proves the scope
   descriptions are true rather than merely present.

### 8.2 The central result

> **Routing clarity, scope clarity, and discoverability regression were all achievable with
> zero new tools.** The three rejected/deferred tools remain rejected/deferred on evidence,
> not on preference.

### 8.3 Still open

| ID | Status |
| --- | --- |
| D-V1-09 — VCS operation class | **OPEN** (frozen vocabulary; not modified) |
| D-V1-10 — client read-side rule | **OPEN** (external repository; not modified) |
| OQ-1 — `encoding` field | **OPEN** |
| OQ-2 — search defaults | **REFRAMED** at P2; **resolved by explanation** at P3 |
| OQ-3 — file-path-to-`mcquest_search` returns `total: 0` | **NEW at P2**; still **OPEN** |
| L1 — adoption unverified | **OPEN**; addressed by P3 — verdict **PARTIALLY CONFIRMED** |

---

## 9. P3 status (added 2026-09-29)

| Item | Value |
| --- | --- |
| Phase | **P3 — COMPLETE** |
| Nature | **measurement only** |
| Source / test / tool changes | **0 / 0 / 0** |
| Scenarios executed | 7 (A–G) + 3 root/path trials |
| Shell used unnecessarily | **0 of 7** (same as P1) |
| Scenarios using a structured tool | **7 of 7** |
| Scenarios where routing changed | **1 of 7** (Scenario C) |
| Adoption verdict | **`PARTIALLY CONFIRMED`** |
| Commits / pushes | 0 / 0 |

### 9.1 The measured result

P2's guidance was **adopted partially, not reliably**:

- **Adopted (1 of 7):** the client used P2's scope text to set an explicit `path="."`,
  turning a confusing 9-match result into a clean 92-match answer (Scenario C).
- **Not adopted (1 of 7):** in Scenario A the client still probed MCQuest with an
  out-of-root path **first**, which P2's instructions explicitly forbid (P3-F2).
- **Unchanged (5 of 7):** including the P1 git-routing defect, which reproduced verbatim.

### 9.2 A correction to P2

P2 stated that out-of-root files route to native tools, naming `read_files` **and
`search_codebase`**. P3 measured that **only the native *read* branch reaches out-of-root**;
`search_codebase` returned in-root results for an out-of-root pattern. Contract §5.4a.2
corrects this. **No tool was missing** — the defect was in v1.0's own description.

> ⚠️ **§9.2 was itself superseded at P4.** P3 generalised from a single out-of-root file located
> in a third tree. P4 measured native search reaching **two** repositories outside the MCQuest
> root (27 + 1 results) and established the true bound as the **client workspace root**, which is
> larger than the MCQuest root. Contract **§5.4a.3** and **§10** are authoritative. The
> *"only the native read branch reaches out-of-root"* sentence above is **retracted**; it is
> preserved unedited as the P3 record.

### 9.3 The conclusion that matters

> **0 of 7 scenarios failed for a missing MCP tool.** Routing clarity, scope clarity, and
> discoverability were all achievable — and were achieved — with **zero new tools**.
> The remaining lever is client-side policy (D-V1-10), which is outside this repository.

### 9.4 Still open

D-V1-09 · D-V1-10 (strengthened) · OQ-1 · OQ-3 · **P3-OQ-1** (new) — all **`OPEN`**, none
resolved by P3.

Full record: `11-V1.0-P3-ROUTING-ADOPTION-REPORT.md`.

---

## 10. P4 status (added 2026-09-29)

| Item | Value |
| --- | --- |
| Phase | **P4 — COMPLETE** |
| Nature | **investigation / documentation only** |
| Source / test / tool changes | **0 / 0 / 0** |
| Probes run | 17 (9 `read_files`, 8 `search_codebase`) |
| **P3-OQ-1** | **RESOLVED** |
| **P3-F1 conclusion** | **RETRACTED** |
| Commits / pushes | 0 / 0 |

### 10.1 The measured boundary

| Capability | Reach | Class |
| --- | --- | --- |
| MCQuest tools | `DEFAULT_PROJECT_ROOT`; out-of-root = error | **GUARANTEED** |
| Host file **read** | any local absolute path; no root check | **OBSERVED** |
| Host file **search** | workspace root `D:\DeveloperTools`; no path param; outside → silent zero | **OBSERVED** |

The workspace root is **larger** than the MCQuest project root, so native search reaches two
sibling repositories that MCQuest cannot. P3's contrary conclusion came from testing a single
file in a third location.

### 10.2 Correction

Contract **§5.4a.3** now supersedes §5.4a.2: reach is normative **per capability**, not per
category. A zero-result native search for an out-of-workspace target is documented as a
**boundary limitation, not a negative finding**.

### 10.3 Still open

D-V1-09 · D-V1-10 · OQ-1 · OQ-3 — all **`OPEN`**. P4 produced **no new evidence** for any of
them: it measured what capabilities can reach, not what a client chooses or how an operation
classifies.

### 10.4 The ceiling

MCQuest can state precisely where its tools apply and what host tools were observed to do. It
cannot change the workspace root, cannot widen native search, and cannot influence the client's
first choice. Those are properties of the environment, not gaps in this codebase.

Full record: `12-V1.0-P4-NATIVE-SEARCH-BOUNDARY.md`.
