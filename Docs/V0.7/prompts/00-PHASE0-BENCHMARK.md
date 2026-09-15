# MCQuest v0.7 — Phase 0: Agent Tool-Selection Benchmark (Prompt)

> This is the authorized Phase 0 prompt for MCQuest v0.7. It is a
> **READ-ONLY BENCHMARK** prompt. It does not authorize implementation.
> Do not modify `src/`, `tests/`, `Docs/V0.5/`, or runtime configuration.
> Do not implement MCP changes. Do not commit or push.

---

## 1. Starting state

V0.6 is CLOSED (final HEAD `ecd905c`; full suite 305 passed, 1 skipped).
V0.5 is CLOSED and unchanged. V0.6 contract P001–P008 and observations
(Phase 0 Ledger tasks A–J; live verification T1–T6) are baseline context:
`Docs/V0.6/01-V0.6-CONTRACT.md`, `Docs/V0.6/03-V0.6-STATE.md`,
`Docs/V0.6/06-V0.6-CHANGELOG.md`. Do not alter V0.5 or V0.6 documents.

## 2. Control plane

`Docs/V0.7/` holds `00-V0.7-MASTER.md`, `01-V0.7-CONTRACT.md`,
`02-V0.7-PLAN.md`, `03-V0.7-STATE.md`, `04-V0.7-TEST-PLAN.md`,
`05-V0.7-DECISIONS.md`, `06-V0.7-CHANGELOG.md`, and this prompt.
All describe V0.7 as PRE-IMPLEMENTATION / READ-ONLY BENCHMARK.
Keep the control plane intentionally small.

## 3. Benchmark task classes (execute ≥1 run each)

C01 repository search · C02 targeted file reads · C03 docs evidence ·
C04 imports/usages · C05 bounded/incomplete evidence ·
C06 cross-document evidence · C07 runtime/generated artifacts ·
C08 tests · C09 build/typecheck · C10 process execution ·
C11 stale/failed evidence-tool recovery. Definitions in CONTRACT §2.
Repository evidence → MCQuest (P002); execution/runtime → shell is
correct, not a failure (P003).

## 4. Measurement fields (record every field per run)

primary-tool correctness · MCQuest-primary rate (aggregate) ·
operation correctness · unnecessary shell fallback · broad-read rate
(aggregate) · duplicate evidence · completeness awareness · recovery ·
execution-boundary correctness · context efficiency. Definitions and
allowed values in CONTRACT §3. Never claim complete evidence on
truncated/paged output (P004/P005).

## 5. Thresholds

TBD pending baseline results. Do not invent or gate on thresholds.

## 6. Baseline preservation

Verify read-only: HEAD `ecd905c`; `Docs/V0.5/` untouched;
`src/`/`tests`/runtime config unmodified; working tree clean there.
Record actuals in `03-V0.7-STATE.md`. Report discrepancies; reconcile
nothing silently.

## 7. Output

Record all runs + aggregates in `03-V0.7-STATE.md`; update TEST-PLAN §D
gate boxes only with evidence. No MCP changes. No commits/pushes.

## 8. Completion gate

Phase 0 COMPLETE only when: control plane exists; baselines verified and
recorded; ≥1 run per C01–C11 with all §3 fields; aggregates computed;
thresholds still TBD; no forbidden modifications; nothing committed/pushed.
Else PHASE 0: NOT COMPLETE (with evidence).

END OF V0.7 PHASE 0 PROMPT
