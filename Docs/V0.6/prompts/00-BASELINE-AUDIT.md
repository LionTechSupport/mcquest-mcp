# MCQuest v0.6 — Phase 0: Baseline & Pre-Implementation Audit (Prompt)

> This is the authorized Phase 0 prompt for MCQuest v0.6. It is a
> **BASELINE AUDIT ONLY** prompt. It does not authorize implementation.
> Do not modify `src/` or `tests/`. Do not start Phase 1. Do not redesign
> MCQuest.

---

## 1. Starting state

V0.5 is CLOSED. Final release: HEAD = 0832ec8, origin/main = 0832ec8,
working tree clean. V0.5 Phases A–D COMPLETE; Release Gate PASS. The v0.5
implementation established bounded output (4000 normal / 16000 ceiling / 200
line clip), bounded reads, explicit pagination, honest totals, deterministic
ordering, bounded search, shared find_evidence page budget, ignored/root
security boundaries, and read-only behavior. Do not reopen v0.5.

## 2. Control plane

Create `Docs/V0.6/`: `00-V0.6-MASTER.md`, `01-V0.6-CONTRACT.md`,
`02-V0.6-PLAN.md`, `03-V0.6-STATE.md`, `04-V0.6-TEST-PLAN.md`,
`05-V0.6-DECISIONS.md`, `06-V0.6-CHANGELOG.md`, and
`prompts/00-BASELINE-AUDIT.md`. All documents must initially describe v0.6 as
PRE-IMPLEMENTATION / BASELINE AUDIT. Do not mark any v0.6 implementation phase
complete. Keep the control plane intentionally small.

## 3. Authority

Before any v0.6 design decision, inspect repository reality and the V0.5
document set (MASTER/CONTRACT/IMPLEMENTATION-PLAN/STATE/TEST-PLAN/DECISIONS/
CHANGELOG). Do NOT alter V0.5 documents.

## 4. Resolve old V0.5 E/F

Inspect `Docs/V0.5/02-V0.5-IMPLEMENTATION-PLAN.md` and classify every Phase E/F
item as exactly one of: CARRY FORWARD TO V0.6 / DEFER / RETIRE / SUPERSEDE /
ALREADY SATISFIED BY V0.5 / REQUIRES SEPARATE FUTURE RELEASE. Record evidence
and classification in the v0.6 baseline/decision material. Do not implement.

## 5. Baseline objective

Evaluate: "Can a coding agent reliably use MCQuest as its primary
repository-evidence interface without unnecessary shell fallback, without
treating incomplete evidence as complete, and without consuming unnecessary
context?"

## 6. Tool-selection audit

Representative tasks A–J (requirement in docs; targeted doc section; source
symbol search; references/usages; generated/runtime output; tests/build/
typecheck; ignored/generated path; cross-check two docs; completeness
determination; exact implementation location). For each record appropriate
tool, actually selected tool, correctness, shell fallback, whether MCQuest
could have provided the evidence, and description/discoverability influence.
Repository evidence → MCQuest; execution/runtime → shell is correct, not a
failure.

## 7. Evidence-completeness audit

Test `truncated=true`, `has_more=true`, `next_offset`, `collection_complete
=false`, `returned < total` on a large document and a paginated search.
Record correct/incorrect behavior and the problem class (MCP output, tool
description, or agent behavior). Never claim "complete evidence" on truncated
output. Do not implement a fix.

## 8. Context-efficiency audit

Compare broad doc retrieval vs targeted search → read vs paginated search →
targeted read. Record MCP calls, approximate result size, evidence needed,
unnecessary retrieval, continuation correctness. Objective: minimum sufficient
evidence with reliable completeness.

## 9. Legacy tool audit

Live-test pattern_audit, diagnostics, project_info, project_context,
git_context, compare_phase. For each: current behavior, output size, summary
metadata, pagination, deterministic ordering, truncation visibility,
usefulness, and whether a v0.6 change is justified. Do not change tools.

## 10. Applicability audit

Verify find_imports / find_usages are TS/TSX/JS/JSX only, whether descriptions
convey the limitation, and whether the limitation can cause incorrect tool
selection (→ candidate v0.6 documentation/discoverability fix). Do not broaden
language support.

## 11. Boundary audit

Verify rejection/exclusion of ignored dirs, generated artifacts, dependency
dirs, and out-of-root paths. Do NOT weaken boundaries. Generated/runtime
needs = execution/runtime workflow.

## 12. Live MCP verification

Test the actual MCP endpoint available to the agent. Establish bounded reads,
bounded discovery, bounded search, pagination, deterministic ordering,
truncation metadata, and ignored-path boundaries. Report stale/disconnected
server as an environment/tool-lifecycle issue.

## 13. Metrics

Table with: repository evidence tasks tested, correct MCQuest selection,
unnecessary shell fallback, necessary shell usage, evidence completeness
correct, incorrect "complete evidence" claims, targeted workflows,
broad/unnecessary retrievals, legacy tools needing v0.6 work, boundary
violations. Do not fabricate.

## 14. Scope discipline

Do NOT add semantic/vector search, embeddings, AI summarization, repository
indexing, execution tools, generated artifact access, broad language support,
new security surfaces, or unrelated refactoring. Identify the smallest change
set that materially improves agent evidence efficiency/reliability.

## 15. Output

Produce the V0.6 BASELINE AUDIT REPORT: repository baseline; E/F
classification; tool-selection findings; evidence-completeness findings;
context-efficiency findings; legacy-tool findings; applicability findings;
boundary findings; metrics table; proposed minimal v0.6 scope; items NOT
recommended for v0.6; recommended Phase 1 objective. Do not implement Phase 1.

## 16. Completion gate

Phase 0 is complete only when: control plane exists; V0.5 untouched; baseline
0832ec8; E/F classified; tool-selection / evidence-completeness /
context-efficiency / legacy / applicability / boundary measured; live MCP
verified; minimal scope proposed; no v0.6 implementation started. Final status:
PHASE 0: COMPLETE or PHASE 0: NOT COMPLETE (with evidence).

END OF V0.6 PHASE 0 PROMPT