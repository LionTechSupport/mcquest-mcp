"""MCQuest V0.9 shell-intelligence modules (P1 state + P2 discovery).

P1 (``Docs/V0.9/04-V0.9-PLAN.md`` §3) established the state layer:

- ``facts.py``      — the shared vocabulary (Source, Trust, Scope, Freshness,
  CostClass, the ``Fact`` provenance record, corroboration, observation ids)
- ``store.py``      — the in-memory ``ObservationStore`` + ``CommandHistory``
  (decision A4: memory only, nothing persisted)
- ``invalidate.py`` — event → scope invalidation with per-scope/subject
  revisions (decision A5: no wall-clock expiry)
- ``terminal.py``   — terminal/session/process identity (contract §8;
  decisions A2, S1–S3, S5)
- ``cost.py``       — the qualitative cost vocabulary (contract §21)

P2 (plan §4) added environment + capability discovery:

- ``environment.py``  — Environment Contract assembly plus the closed
  fixed-argv read-only probe allowlist (contract §5/§15; decisions A3, S1, S2)
- ``capabilities.py`` — capability registry with intent metadata; the pinned
  ``EXPECTED_TOOLS`` list stays the registration authority (decisions A12, S5)

No module here executes anything beyond the approved probes, analysis stays
separate from execution — Cline remains the execution authority (contract §14),
and tool registration happens phase by phase in ``server.py`` (decision A11).
"""