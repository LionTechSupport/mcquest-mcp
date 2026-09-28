"""Observation ingestion and invalidation (contract §9/§12; decision A14; P4).

Implements the explicit A14 ingest shape on top of the existing P1
``ObservationStore`` and ``invalidate.apply_invalidation``. This module adds no
new state model, no second store, and no new trust or scope vocabulary: it
validates the A14 shape, records it into the single P1 store, and applies
invalidation through the P1 mapping table.

Provenance rules enforced here:

- declared evidence keeps the phrase "declared by client; not verified" for its
  whole lifetime (contract §17 rule 2);
- tool-derived evidence keeps its originating tool as the source (§17 rule 5);
- ``SESSION``/``PROCESS``/``EPHEMERAL`` ingestion is rejected without a declared
  client identity, so a fact can never be promoted across terminals (§8);
- nothing is persisted to disk (decision A4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .facts import (
    BINDING_PROCESS_SCOPES,
    BINDING_SESSION_SCOPES,
    EVIDENCE_CLIENT_DECLARED,
    Fact,
    Freshness,
    Observation,
    Scope,
    Source,
    Trust,
)
from .environment import observed_now
from .invalidate import InvalidationEvent, apply_invalidation
from .store import ObservationStore

MAX_NAME_CHARS = 256
MAX_VALUE_CHARS = 4_096


class IngestKind(str, Enum):
    """The A14 ``kind`` discriminator: exactly two members."""

    OBSERVATION = "observation"
    COMMAND = "command"

    def __str__(self) -> str:
        return str(self.value)


class RecordedAt(str, Enum):
    """A14 ``recorded_at_source``; provenance, immutable once recorded."""

    SERVER = "SERVER"
    CLIENT = "CLIENT"

    def __str__(self) -> str:
        return str(self.value)


class ObserveStatus(str, Enum):
    """Outcome vocabulary. ``REJECTED`` never raises across the MCP boundary."""

    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class ObserveResult:
    """One deterministic ingestion outcome."""

    status: ObserveStatus
    kind: IngestKind
    name: str
    detail: str
    observation_id: str | None = None
    scope: Scope | None = None
    source: Source | None = None
    trust: Trust | None = None
    freshness: Freshness | None = None
    invalidated: tuple[tuple[Scope, str], ...] = ()
    command_id: str | None = None


def _require_text(value: str, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be str, got {type(value).__name__}")
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{label} must not be empty")
    if len(candidate) > limit:
        raise ValueError(f"{label} exceeds the maximum of {limit} characters")
    return candidate


def _default_freshness(scope: Scope) -> Freshness:
    """Documented scope -> default freshness pairing (contract §11)."""
    if scope is Scope.REPOSITORY:
        return Freshness.STATIC
    if scope in {Scope.WORKTREE, Scope.FILE}:
        return Freshness.WORKTREE
    if scope is Scope.SESSION:
        return Freshness.SESSION
    if scope is Scope.PROCESS:
        return Freshness.PROCESS
    return Freshness.EPHEMERAL


def record_observation(
    store: ObservationStore,
    *,
    name: str,
    value: str,
    scope: Scope,
    source: str = Source.CLIENT_DECLARED.value,
    recorded_at_source: str = RecordedAt.CLIENT.value,
    subject: str = "",
    operation: str = "",
    client_session: str = "",
    client_process_id: str = "",
) -> ObserveResult:
    """Record one A14-shaped observation into the existing P1 store.

    ``source`` names the tool or command that produced the evidence; trust and
    freshness are derived from scope and provenance, never invented.
    """
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    observation_name = _require_text(name, "name", MAX_NAME_CHARS)
    observation_value = _require_text(value, "value", MAX_VALUE_CHARS)
    if not isinstance(scope, Scope):
        raise TypeError(f"scope must be Scope, got {type(scope).__name__}")
    origin = RecordedAt(recorded_at_source)
    producer = _require_text(source, "source", MAX_NAME_CHARS)

    # Contract §8 / A14: identity-bound scopes are refused without a declared
    # client identity so a fact can never be served to another terminal.
    if scope in BINDING_SESSION_SCOPES and not client_session:
        return ObserveResult(
            ObserveStatus.REJECTED, IngestKind.OBSERVATION, observation_name,
            "SESSION scope requires a declared client_session (contract §8).",
            scope=scope,
        )
    if scope in BINDING_PROCESS_SCOPES and not (client_session and client_process_id):
        return ObserveResult(
            ObserveStatus.REJECTED, IngestKind.OBSERVATION, observation_name,
            "PROCESS/EPHEMERAL scope requires both client_session and "
            "client_process_id (contract §8).",
            scope=scope,
        )

    declared = origin is RecordedAt.CLIENT
    fact_source = Source.CLIENT_DECLARED if declared else Source.SERVER_OBSERVED
    evidence = (
        EVIDENCE_CLIENT_DECLARED if declared
        else f"observed by {producer} (A14 ingest)"
    )
    fact = Fact(
        observation=observation_name,
        value=observation_value,
        scope=scope,
        # Provenance for the reader only; it never triggers expiry (A5) and is
        # never rendered, so report output stays byte-identical across runs.
        observed_at=observed_now(),
        source=fact_source,
        # Server-observed evidence is trusted; declared evidence is untrusted
        # until corroborated, and corroboration is never implied here (S2).
        trust=Trust.UNTRUSTED if declared else Trust.TRUSTED,
        freshness=_default_freshness(scope),
        evidence=evidence,
        subject=subject or None,
        operation=operation or None,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
    )
    observation = Observation.wrap(fact, origin="tool")
    # `store.record` stamps the current revision and returns the stored copy;
    # re-recording the same identity simply refreshes it (contract §12).
    store.record(fact)
    return ObserveResult(
        ObserveStatus.RECORDED,
        IngestKind.OBSERVATION,
        observation_name,
        f"recorded at {fact.scope.value} scope as {fact_source.value}.",
        observation_id=observation.observation_id,
        scope=fact.scope,
        source=fact.source,
        trust=fact.trust,
        freshness=fact.freshness,
    )


def record_command_observation(
    store: ObservationStore,
    *,
    text: str,
    normalized: tuple[str, ...] = (),
    operation: str = "",
    verdict: str = "",
    client_session: str = "",
    client_process_id: str = "",
) -> ObserveResult:
    """Record command history in the store (contract §17 rule 3).

    Recording invalidates EPHEMERAL facts, because command output is never
    reused across commands (contract §10).
    """
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    record = store.record_command(
        _require_text(text, "text", MAX_VALUE_CHARS),
        normalized=normalized,
        operation=operation or None,
        verdict=verdict or None,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
    )
    return ObserveResult(
        ObserveStatus.RECORDED, IngestKind.COMMAND, record.command_id,
        "recorded in the in-memory history; EPHEMERAL facts invalidated.",
        command_id=record.command_id,
    )


def invalidate(
    store: ObservationStore, event: str, *, subject: str = ""
) -> tuple[tuple[Scope, str], ...]:
    """Apply one P1 invalidation event and return the bumped keys.

    The mapping table in ``invalidate.py`` is the only authority; an unknown
    event is never mapped by guesswork.
    """
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    return apply_invalidation(store, InvalidationEvent(event), subject=subject or None)
