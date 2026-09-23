"""Terminal / session / process identity without privileged access (contract §8; architecture §5.5).

Model: ``session<id> → processes[] → {shell, version, cwd, console_codepage}``.

Only client-declared values populate this tree; server-owned process facts
live under the labeled ``mcp_server`` subject and are never served as client
state (contract §6 rule 2; decision S2). Undeclared fields answer ``unknown``
— degraded mode is first-class, never a failure (decision S1).
"""

from __future__ import annotations

from dataclasses import dataclass

from .facts import (
    EVIDENCE_CLIENT_DECLARED,
    EVIDENCE_UNOBSERVED,
    SUBJECT_CWD,
    SUBJECT_CONSOLE_CODEPAGE,
    VALUE_UNKNOWN,
    Fact,
    Freshness,
    Scope,
    Source,
    Trust,
    require_non_empty_str,
    require_optional_str,
)
from .store import ObservationStore

# Server-owned facts are labeled with this subject and are filtered out of
# every client-facing resolve path (decision S2).
SERVER_SUBJECT = "mcp_server"

SUBJECT_SESSION_ID = "session_id"
SUBJECT_PROCESS_ID = "process_id"
SUBJECT_SHELL = "shell"
SUBJECT_SHELL_VERSION = "shell_version"

# observation → (scope, subject, freshness) for every terminal field.
TERMINAL_FIELDS: dict[str, tuple[Scope, str, Freshness]] = {
    "terminal.session_id": (Scope.SESSION, SUBJECT_SESSION_ID, Freshness.SESSION),
    "terminal.process_id": (Scope.PROCESS, SUBJECT_PROCESS_ID, Freshness.PROCESS),
    "terminal.shell": (Scope.PROCESS, SUBJECT_SHELL, Freshness.PROCESS),
    "terminal.shell_version": (Scope.PROCESS, SUBJECT_SHELL_VERSION, Freshness.PROCESS),
    "terminal.cwd": (Scope.PROCESS, SUBJECT_CWD, Freshness.PROCESS),
    "terminal.console_codepage": (
        Scope.PROCESS,
        SUBJECT_CONSOLE_CODEPAGE,
        Freshness.PROCESS,
    ),
}


@dataclass(frozen=True)
class TerminalIdentity:
    """One terminal's declared identity; every field may be missing (→ unknown)."""

    session_id: str | None = None
    process_id: str | None = None
    shell: str | None = None
    shell_version: str | None = None
    cwd: str | None = None
    console_codepage: str | None = None

    def __post_init__(self) -> None:
        require_optional_str(self.session_id, "session_id")
        require_optional_str(self.process_id, "process_id")
        require_optional_str(self.shell, "shell")
        require_optional_str(self.shell_version, "shell_version")
        require_optional_str(self.cwd, "cwd")
        require_optional_str(self.console_codepage, "console_codepage")


def _field_values(identity: TerminalIdentity) -> tuple[tuple[str, str | None], ...]:
    """(observation, value) pairs in stable field order."""
    return (
        ("terminal.session_id", identity.session_id),
        ("terminal.process_id", identity.process_id),
        ("terminal.shell", identity.shell),
        ("terminal.shell_version", identity.shell_version),
        ("terminal.cwd", identity.cwd),
        ("terminal.console_codepage", identity.console_codepage),
    )


def declare(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[Fact, ...]:
    """Record every field this identity can legally bind.

    A field whose identity half is missing is *skipped*, not guessed: it
    stays undeclared and resolves to ``unknown`` (contract §6/§8). Returns
    the facts actually recorded, in field order.
    """
    require_non_empty_str(observed_at, "observed_at")
    recorded: list[Fact] = []
    for observation, value in _field_values(identity):
        if value is None:
            continue
        scope, subject, freshness = TERMINAL_FIELDS[observation]
        if scope in (Scope.PROCESS, Scope.EPHEMERAL) and (
            identity.session_id is None or identity.process_id is None
        ):
            continue  # a process fact cannot be bound without both ids (§8)
        fact = Fact(
            observation=observation,
            value=value,
            scope=scope,
            freshness=freshness,
            observed_at=observed_at,
            source=Source.CLIENT_DECLARED,
            trust=Trust.UNTRUSTED,
            evidence=EVIDENCE_CLIENT_DECLARED,
            subject=subject,
            terminal_session=identity.session_id,
            process_id=identity.process_id,
        )
        store.record(fact)
        recorded.append(fact)
    return tuple(recorded)


def declare_server(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
    evidence: str,
) -> tuple[Fact, ...]:
    """Record the MCP server's *own* process facts under the ``mcp_server`` subject.

    These are SERVER_OBSERVED/trusted facts about the server — never about a
    client — and ``resolve`` refuses to serve them (decision S2). The
    session/process fields of ``identity`` are ignored: the server is not a
    client terminal and never substitutes its identity for one (contract §8
    rule 4).
    """
    require_non_empty_str(observed_at, "observed_at")
    require_non_empty_str(evidence, "evidence")
    recorded: list[Fact] = []
    for observation, value in _field_values(identity):
        if value is None:
            continue
        scope, _client_subject, freshness = TERMINAL_FIELDS[observation]
        fact = Fact(
            observation=observation,
            value=value,
            scope=scope,
            freshness=freshness,
            observed_at=observed_at,
            source=Source.SERVER_OBSERVED,
            trust=Trust.TRUSTED,
            evidence=evidence,
            subject=SERVER_SUBJECT,
            terminal_session=None,
            process_id=None,
        )
        store.record(fact)
        recorded.append(fact)
    return tuple(recorded)


def resolve(
    store: ObservationStore,
    observation: str,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
    observed_at: str,
) -> Fact:
    """Serve a terminal field for ONE declared identity — or ``unknown``.

    A stored fact is served only when it sits under this exact identity, is
    not server-owned, and still passes the reuse check (present in this
    store, matching revision). Anything else — another terminal's fact, a
    fact invalidated by a restart event, a server-owned fact, or nothing at
    all — yields the contract §6 default:
    ``value=unknown / source=UNKNOWN / trust=untrusted``.
    """
    if observation not in TERMINAL_FIELDS:
        known = ", ".join(sorted(TERMINAL_FIELDS))
        raise ValueError(f"unknown terminal observation {observation!r}; known: {known}")
    require_non_empty_str(observed_at, "observed_at")
    scope, subject, freshness = TERMINAL_FIELDS[observation]
    candidate = store.lookup(
        observation,
        scope,
        subject,
        terminal_session=terminal_session,
        process_id=process_id,
    )
    if candidate is not None and candidate.subject != SERVER_SUBJECT:
        if store.reuse_check(
            candidate,
            scope=scope,
            terminal_session=terminal_session,
            process_id=process_id,
        ):
            return candidate
    return Fact(
        observation=observation,
        value=VALUE_UNKNOWN,
        scope=scope,
        freshness=freshness,
        observed_at=observed_at,
        source=Source.UNKNOWN,
        trust=Trust.UNTRUSTED,
        evidence=EVIDENCE_UNOBSERVED,
        subject=subject,
        terminal_session=terminal_session,
        process_id=process_id,
    )


def resolve_cwd(
    store: ObservationStore,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
    observed_at: str,
) -> Fact:
    """Convenience wrapper for the CWD fact (contract §5; benchmark 1)."""
    return resolve(
        store,
        "terminal.cwd",
        terminal_session=terminal_session,
        process_id=process_id,
        observed_at=observed_at,
    )

