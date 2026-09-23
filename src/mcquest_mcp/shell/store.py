"""In-memory observation store and command history (contract §9–§12; decision A4).

The single piece of shared state in V0.9. Guarantees:

- nothing is ever persisted — the store lives exactly as long as the server
  process, and ``reset()`` gives restart semantics (decision S3) and tests a
  clean slate;
- identity binding: SESSION/PROCESS/EPHEMERAL facts are keyed by their
  declared ``(session, process)``; repository-family scopes are reusable
  across sessions while uninvalidated (contract §10);
- validity = presence + identity match + revision equality — never a clock
  (decision A5: no wall-clock TTL anywhere);
- ``record_command`` invalidates EPHEMERAL facts, because contract §10 says
  command output is never reused across commands.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .facts import (
    BINDING_PROCESS_SCOPES,
    BINDING_SESSION_SCOPES,
    CostClass,
    Fact,
    Scope,
    require_enum,
    require_non_empty_str,
)


@dataclass(frozen=True)
class CommandRecord:
    """One recorded command with the provenance architecture §5.2 lists."""

    command_id: str
    text: str
    normalized: tuple[str, ...] = ()
    cost: CostClass | None = None
    mutation: CostClass | None = None
    operation: str | None = None
    terminal_session: str | None = None
    process_id: str | None = None
    verdict: str | None = None


class CommandHistory:
    """Ordered, deterministic command records with exact normalized lookup.

    The n0–n3 normalization *policy* belongs to redundancy analysis in a later
    phase; the history only stores the forms it is given and matches them
    exactly — never by similarity (contract §20 rule 3).
    """

    def __init__(self) -> None:
        self._records: list[CommandRecord] = []
        self._counter = 0

    def record(
        self,
        text: str,
        *,
        normalized: Sequence[str] = (),
        cost: CostClass | None = None,
        mutation: CostClass | None = None,
        operation: str | None = None,
        terminal_session: str | None = None,
        process_id: str | None = None,
        verdict: str | None = None,
    ) -> CommandRecord:
        """Append one command and return its record with a deterministic id."""
        require_non_empty_str(text, "text")
        forms = tuple(normalized)
        for index, form in enumerate(forms):
            if not isinstance(form, str):
                raise TypeError(f"normalized[{index}] must be str, got {type(form).__name__}")
        for label, item in (("cost", cost), ("mutation", mutation)):
            if item is not None and not isinstance(item, CostClass):
                raise TypeError(f"{label} must be CostClass or None, got {type(item).__name__}")
        self._counter += 1
        record = CommandRecord(
            command_id=f"cmd-{self._counter:04d}",
            text=text,
            normalized=forms,
            cost=cost,
            mutation=mutation,
            operation=operation,
            terminal_session=terminal_session,
            process_id=process_id,
            verdict=verdict,
        )
        self._records.append(record)
        return record

    def records(
        self,
        *,
        terminal_session: str | None = None,
        process_id: str | None = None,
    ) -> tuple[CommandRecord, ...]:
        """All records in insertion order, optionally filtered by identity."""
        selected = self._records
        if terminal_session is not None:
            selected = [r for r in selected if r.terminal_session == terminal_session]
        if process_id is not None:
            selected = [r for r in selected if r.process_id == process_id]
        return tuple(selected)

    def page(self, offset: int = 0, limit: int | None = None) -> tuple[CommandRecord, ...]:
        """Deterministic bounded page over all records (insertion order)."""
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be an int >= 0")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError("limit must be an int >= 1 when given")
            return tuple(self._records[offset : offset + limit])
        return tuple(self._records[offset:])

    def find_normalized(
        self,
        normalized: Sequence[str],
        *,
        level: int | None = None,
    ) -> tuple[CommandRecord, ...]:
        """Records matching the exact normalized form (whole tuple or one level)."""
        want = tuple(normalized)
        if level is None:
            return tuple(record for record in self._records if record.normalized == want)
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level < len(want):
            raise ValueError("level must index an element of normalized")
        needle = want[level]
        return tuple(
            record
            for record in self._records
            if len(record.normalized) > level and record.normalized[level] == needle
        )

    def reset(self) -> None:
        """Forget everything — used by store reset and between tests."""
        self._records.clear()
        self._counter = 0


class ObservationStore:
    """In-memory facts + revisions + history — the only shared V0.9 state."""

    def __init__(self) -> None:
        self._facts: dict[tuple[str, Scope, str, str | None, str | None], Fact] = {}
        self._revisions: dict[tuple[Scope, str], int] = {}
        self.history = CommandHistory()

    @staticmethod
    def _key(
        observation: str,
        scope: Scope,
        subject: str | None,
        terminal_session: str | None,
        process_id: str | None,
    ) -> tuple[str, Scope, str, str | None, str | None]:
        # Identity binding (contract §10): session-family scopes key on the
        # session; process-family scopes key on session AND process; the
        # repository family keys on nothing terminal-specific, so those facts
        # stay reusable across terminals while uninvalidated. Session/process
        # values recorded on repository-family facts are provenance only.
        if scope in BINDING_SESSION_SCOPES:
            bound_session, bound_process = terminal_session, None
        elif scope in BINDING_PROCESS_SCOPES:
            bound_session, bound_process = terminal_session, process_id
        else:
            bound_session, bound_process = None, None
        return (observation, scope, subject or "", bound_session, bound_process)

    def record(self, fact: Fact) -> Fact:
        """Store ``fact`` stamped with its current revision; returns the stored copy."""
        revision_key = (fact.scope, fact.subject or "")
        current = self._revisions.setdefault(revision_key, 0)
        stored = replace(fact, revision=current)
        key = self._key(
            fact.observation,
            fact.scope,
            fact.subject,
            fact.terminal_session,
            fact.process_id,
        )
        self._facts[key] = stored
        return stored

    def lookup(
        self,
        observation: str,
        scope: Scope,
        subject: str | None = None,
        *,
        terminal_session: str | None = None,
        process_id: str | None = None,
    ) -> Fact | None:
        """Exact-identity lookup; returns None rather than another terminal's fact."""
        require_enum(scope, Scope, "scope")
        key = self._key(observation, scope, subject, terminal_session, process_id)
        return self._facts.get(key)

    def revision_for(self, scope: Scope, subject: str | None = None) -> int:
        """Current revision of one (scope, subject) key — 0 when never bumped."""
        require_enum(scope, Scope, "scope")
        return self._revisions.get((scope, subject or ""), 0)

    def reuse_check(
        self,
        fact: Fact,
        *,
        scope: Scope | None = None,
        terminal_session: str | None = None,
        process_id: str | None = None,
    ) -> bool:
        """True only when scope, identity, presence and revision all match.

        This is the single reuse decision (contract §12; architecture §5.3):
        a fact failing any leg is stale or foreign and must be treated as
        unknown rather than served — invalidate rather than guess.
        """
        if scope is not None:
            require_enum(scope, Scope, "scope")
            if fact.scope is not scope:
                return False
        if fact.scope in BINDING_SESSION_SCOPES or fact.scope in BINDING_PROCESS_SCOPES:
            if terminal_session != fact.terminal_session:
                return False
        if fact.scope in BINDING_PROCESS_SCOPES:
            if process_id != fact.process_id:
                return False
        key = self._key(
            fact.observation, fact.scope, fact.subject, fact.terminal_session, fact.process_id
        )
        if key not in self._facts:
            return False  # not held here (e.g. fresh store after a restart)
        return fact.revision == self.revision_for(fact.scope, fact.subject)

    def invalidate_scope(
        self, scope: Scope, subject: str | None = None
    ) -> tuple[tuple[Scope, str], ...]:
        """Bump revisions: one (scope, subject) key, or every known key in the scope.

        Returns the bumped keys sorted by (scope value, subject) so callers
        always receive deterministic output (contract §16 rule 6). A targeted
        bump creates the key when absent, so a later re-observation of that
        subject is stamped fresh while earlier records turn stale.
        """
        require_enum(scope, Scope, "scope")
        if subject is not None:
            require_non_empty_str(subject, "subject")
            key = (scope, subject)
            self._revisions[key] = self._revisions.get(key, 0) + 1
            return (key,)
        affected = sorted(
            (key for key in self._revisions if key[0] is scope),
            key=lambda key: key[1],
        )
        for key in affected:
            self._revisions[key] = self._revisions[key] + 1
        return tuple(affected)

    def snapshot(self) -> tuple[Fact, ...]:
        """All stored facts in a documented deterministic order."""
        ordered = sorted(
            self._facts.values(),
            key=lambda fact: (
                fact.scope.value,
                fact.subject or "",
                fact.observation,
                fact.terminal_session or "",
                fact.process_id or "",
            ),
        )
        return tuple(ordered)

    def record_command(
        self,
        text: str,
        *,
        normalized: Sequence[str] = (),
        cost: CostClass | None = None,
        mutation: CostClass | None = None,
        operation: str | None = None,
        terminal_session: str | None = None,
        process_id: str | None = None,
        verdict: str | None = None,
    ) -> CommandRecord:
        """Append to history and invalidate EPHEMERAL facts.

        Contract §10: command output and temporary state are never reused
        across commands, so every recorded command supersedes them.
        """
        record = self.history.record(
            text,
            normalized=normalized,
            cost=cost,
            mutation=mutation,
            operation=operation,
            terminal_session=terminal_session,
            process_id=process_id,
            verdict=verdict,
        )
        self.invalidate_scope(Scope.EPHEMERAL)
        return record

    def commands(
        self, *, terminal_session: str | None = None, process_id: str | None = None
    ) -> tuple[CommandRecord, ...]:
        """Relevant command history for one terminal/process (or everything)."""
        return self.history.records(
            terminal_session=terminal_session, process_id=process_id
        )

    def reset(self) -> None:
        """Drop every fact, revision and record — restart semantics (decision S3)."""
        self._facts.clear()
        self._revisions.clear()
        self.history.reset()

