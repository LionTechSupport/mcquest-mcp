# Cline Prompt — V0.5 Phase A

## Mission

Implement ONLY Phase A of MCQuest MCP v0.5:

Shared OutputBudget infrastructure.

Do not implement Phase B or later.

---

## Scope

Allowed files:
- `src/mcquest_mcp/config.py` (constants only)
- `src/mcquest_mcp/formatting.py` (OutputBudget + wrappers)
- `tests/test_output_budget.py` (new)

Prohibited files:
- all `tools/*.py` (no tool semantic changes in Phase A)
- `server.py` (no schema changes in Phase A)
- `security.py`, `cli.py`, `pyproject.toml`
- any existing test (additive new test file only)

Prohibited behavior:
- no pagination/offset parameters yet (Phases C–E)
- no per-tool output code changes
- no security-model changes

---

## Read First

Before modifying anything:

1. `Docs/V0.5/00-V0.5-MASTER.md`
2. `Docs/V0.5/01-V0.5-CONTRACT.md`
3. `Docs/V0.5/02-V0.5-IMPLEMENTATION-PLAN.md`
4. `Docs/V0.5/03-V0.5-STATE.md`
5. `Docs/V0.5/04-V0.5-TEST-PLAN.md`
6. `Docs/V0.5/05-V0.5-DECISIONS.md`

Then inspect the actual repository implementation.

Do not assume the design document matches the current code.

---

## Required Investigation

Before editing:

- inspect formatting.py
- inspect config.py
- locate the current 80k formatter cap
- locate every formatter/output path
- identify whether tools bypass the formatter
- inspect existing tests
- inspect server registration/schema code

Report findings before implementation.

---

## Implementation

Implement the smallest architecture that establishes:

1. normal presentation budget = 4000 chars;
2. absolute hard ceiling = 16000 chars;
3. per-line clip = 200 chars;
4. atomic item emission;
5. summary-first compatibility;
6. explicit `truncated` state;
7. no response can exceed 16000 chars.

Context amplification MUST NOT bypass the 4000 normal budget.

Do not modify tool behavior yet unless required to route output
through the shared infrastructure.

---

## Security

Do not modify:

- root confinement;
- resolve_project_path;
- validate_readable_file;
- ignored directory rules;
- symlink rules;
- read-only guarantees;
- subprocess policy.

---

## Tests

Add focused tests proving:

- 4000-char normal budget;
- 16000-char absolute ceiling;
- 200-char line clipping;
- atomic item cutoff;
- summary survives truncation;
- serialized response remains bounded.

Run focused tests first.

Then run the relevant existing tests.

---

## Acceptance Criteria

Phase A is complete only when (per `00-V0.5-MASTER.md` §7 and
`04-V0.5-TEST-PLAN.md` D–H + V-atomic):

1. `test_output_budget.py` proves the 4000 normal budget;
2. no callable path exceeds 16000 chars (raw AND `json.dumps`
   serialized) — the absolute ceiling invariant;
3. lines are clipped at 200 chars;
4. cutoff is atomic (never mid-item) with explicit `truncated` state;
5. the summary/header survives truncation;
6. `[OUTPUT TRUNCATED: N characters omitted]` marker remains present;
7. existing tests pass unchanged except additive new tests;
8. STATE and CHANGELOG updated only with executable evidence.

---

## Documentation

After implementation:

1. update `03-V0.5-STATE.md`;
2. update `06-V0.5-CHANGELOG.md`;
3. record any new decision in `05-V0.5-DECISIONS.md`.

Do not mark Phase A complete unless tests provide evidence.

---

## Final Report

Report:

- files changed;
- tests run;
- tests passed/failed;
- contract requirements satisfied;
- remaining risks;
- exact next phase.

Then stop.

Do NOT continue into Phase B.