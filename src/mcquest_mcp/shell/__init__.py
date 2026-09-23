"""MCQuest V0.9 shell-intelligence state foundations (P1).

This package implements only the P1 state layer approved in
``Docs/V0.9/04-V0.9-PLAN.md`` §3:

- ``facts.py``      — the shared vocabulary (Source, Trust, Scope, Freshness,
  CostClass, the ``Fact`` provenance record, corroboration, observation ids)
- ``store.py``      — the in-memory ``ObservationStore`` + ``CommandHistory``
  (decision A4: memory only, nothing persisted)
- ``invalidate.py`` — event → scope invalidation with per-scope/subject
  revisions (decision A5: no wall-clock expiry)
- ``terminal.py``   — terminal/session/process identity (contract §8;
  decisions A2, S1–S3, S5)
- ``cost.py``       — the qualitative cost vocabulary (contract §21)

No MCP tool is registered from this package (tools arrive phase by phase,
decision A11), and no module here executes anything: analysis stays separate
from execution — Cline remains the execution authority (contract §14).
"""