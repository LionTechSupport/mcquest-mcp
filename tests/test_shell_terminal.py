"""P1 state tests: terminal/session/process identity (contract §8; decisions A2, S1–S3, S5).

The headline guarantee under test: Terminal A's state can never silently become
Terminal B's state, an undeclared field answers ``unknown / UNKNOWN / untrusted``
rather than failing, and server-owned facts are never served as client state.
"""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.facts import (
    EVIDENCE_CLIENT_DECLARED,
    EVIDENCE_UNOBSERVED,
    SUBJECT_CWD,
    VALUE_UNKNOWN,
    Scope,
    Source,
    Trust,
    corroborate,
)
from mcquest_mcp.shell.invalidate import InvalidationEvent, apply_invalidation
from mcquest_mcp.shell.store import ObservationStore
from mcquest_mcp.shell.terminal import (
    SERVER_SUBJECT,
    TerminalIdentity,
    declare,
    declare_server,
    resolve,
    resolve_cwd,
)

AT_A = "2026-01-01T00:00:00Z"
AT_B = "2026-01-02T00:00:00Z"

IDENTITY_A = TerminalIdentity(
    session_id="A",
    process_id="18240",
    shell="PowerShell",
    shell_version="7.6.2",
    cwd="D:\\DeveloperTools\\mcquest-mcp",
    console_codepage="65001",
)
IDENTITY_B = TerminalIdentity(
    session_id="B",
    process_id="19310",
    shell="PowerShell",
    shell_version="5.1.26100",
    cwd="D:\\DeveloperTools",
    console_codepage="437",
)


def test_declare_records_every_declared_field_with_contract_provenance() -> None:
    store = ObservationStore()
    facts = declare(store, IDENTITY_A, observed_at=AT_A)
    assert len(facts) == 6
    for fact in facts:
        assert fact.source is Source.CLIENT_DECLARED
        assert fact.trust is Trust.UNTRUSTED
        assert fact.evidence == EVIDENCE_CLIENT_DECLARED
    scopes = {f.observation: f.scope.value for f in facts}
    assert scopes["terminal.session_id"] == "SESSION"
    assert scopes["terminal.cwd"] == "PROCESS"
    assert scopes["terminal.shell_version"] == "PROCESS"


def test_session_and_process_identities_differ() -> None:
    assert IDENTITY_A.session_id != IDENTITY_B.session_id
    assert IDENTITY_A.process_id != IDENTITY_B.process_id
    assert IDENTITY_A.cwd != IDENTITY_B.cwd


def test_terminal_a_cwd_is_never_served_to_terminal_b() -> None:
    # Only Terminal A has declared anything. Terminal B must receive `unknown`,
    # never Terminal A's path (contract §8 rule 1; test-plan T2/S5).
    store = ObservationStore()
    declare(store, IDENTITY_A, observed_at=AT_A)
    served_to_b = resolve_cwd(
        store,
        terminal_session=IDENTITY_B.session_id,
        process_id=IDENTITY_B.process_id,
        observed_at=AT_B,
    )
    assert served_to_b.value == VALUE_UNKNOWN
    assert served_to_b.source is Source.UNKNOWN
    assert served_to_b.trust is Trust.UNTRUSTED
    assert served_to_b.evidence == EVIDENCE_UNOBSERVED
    assert served_to_b.subject == SUBJECT_CWD


def test_two_declared_terminals_each_resolve_their_own_cwd() -> None:
    store = ObservationStore()
    declare(store, IDENTITY_A, observed_at=AT_A)
    declare(store, IDENTITY_B, observed_at=AT_A)
    for identity in (IDENTITY_A, IDENTITY_B):
        served = resolve_cwd(
            store,
            terminal_session=identity.session_id,
            process_id=identity.process_id,
            observed_at=AT_B,
        )
        assert served.value == identity.cwd
        assert served.source is Source.CLIENT_DECLARED


def test_second_process_in_same_session_does_not_inherit_first_process_cwd() -> None:
    store = ObservationStore()
    declare(store, IDENTITY_A, observed_at=AT_A)
    served = resolve_cwd(store, terminal_session="A", process_id="99999", observed_at=AT_B)
    assert served.value == VALUE_UNKNOWN
    assert served.source is Source.UNKNOWN


def test_undeclared_identity_resolves_to_unknown_degraded_mode() -> None:
    store = ObservationStore()
    served = resolve_cwd(store, observed_at=AT_B)
    assert served.value == VALUE_UNKNOWN
    assert served.source is Source.UNKNOWN
    assert served.trust is Trust.UNTRUSTED  # decision S1: degraded, never a failure


def test_partial_identity_skips_process_scoped_fields() -> None:
    store = ObservationStore()
    partial = TerminalIdentity(session_id="A", cwd="D:\\should-not-record")
    facts = declare(store, partial, observed_at=AT_A)
    # Only the session identity is recordable: PROCESS facts require BOTH ids.
    assert [f.observation for f in facts] == ["terminal.session_id"]
    served = resolve_cwd(store, terminal_session="A", observed_at=AT_B)
    assert served.value == VALUE_UNKNOWN
    assert served.source is Source.UNKNOWN


def test_redeclare_same_identity_overwrites_with_latest_value() -> None:
    store = ObservationStore()
    declare(store, TerminalIdentity(session_id="A", process_id="1", cwd="D:\\first"), observed_at=AT_A)
    declare(store, TerminalIdentity(session_id="A", process_id="1", cwd="D:\\second"), observed_at=AT_A)
    served = resolve_cwd(store, terminal_session="A", process_id="1", observed_at=AT_B)
    assert served.value == "D:\\second"


def test_server_identity_facts_labeled_and_never_served() -> None:
    store = ObservationStore()
    facts = declare_server(store, IDENTITY_A, observed_at=AT_A, evidence="server process probe")
    assert facts
    for fact in facts:
        assert fact.subject == SERVER_SUBJECT
        assert fact.source is Source.SERVER_OBSERVED
        assert fact.trust is Trust.TRUSTED
        assert fact.terminal_session is None and fact.process_id is None
    # The raw record exists — but only under its labeled server subject…
    stored = store.lookup("terminal.cwd", Scope.PROCESS, SERVER_SUBJECT)
    assert stored is not None and stored.value == IDENTITY_A.cwd
    # …and no client resolve path ever serves it, even with no identity declared
    # (contract §6 rule 2; decision S2 — unknown is preferred over a server value).
    for observation in ("terminal.cwd", "terminal.shell"):
        served = resolve(store, observation, observed_at=AT_B)
        assert served.value == VALUE_UNKNOWN
        assert served.source is Source.UNKNOWN
        assert served.subject != SERVER_SUBJECT


def test_corroborated_cwd_is_served_with_corroborated_trust() -> None:
    store = ObservationStore()
    declare(store, IDENTITY_A, observed_at=AT_A)
    declared = resolve_cwd(store, terminal_session="A", process_id="18240", observed_at=AT_B)
    assert declared.trust is Trust.UNTRUSTED
    assert declared.source is Source.CLIENT_DECLARED
    checked = corroborate(declared, evidence="path resolves inside the known root")
    store.record(checked)
    served = resolve_cwd(store, terminal_session="A", process_id="18240", observed_at=AT_B)
    assert served.trust is Trust.CORROBORATED
    assert served.source is Source.CLIENT_DECLARED  # corroboration never re-labels


def test_terminal_restart_supersedes_previously_declared_facts() -> None:
    store = ObservationStore()
    declare(store, IDENTITY_A, observed_at=AT_A)
    apply_invalidation(store, InvalidationEvent.TERMINAL_RESTART)
    served = resolve_cwd(store, terminal_session="A", process_id="18240", observed_at=AT_B)
    assert served.value == VALUE_UNKNOWN  # invalidated ⇒ unknown, never the old path


def test_fresh_store_reports_unknown_after_restart() -> None:
    first = ObservationStore()
    declare(first, IDENTITY_A, observed_at=AT_A)
    second = ObservationStore()  # server restart = brand-new store (decision S3)
    served = resolve_cwd(second, terminal_session="A", process_id="18240", observed_at=AT_B)
    assert served.value == VALUE_UNKNOWN
    assert served.source is Source.UNKNOWN
    assert second.snapshot() == ()


def test_resolve_rejects_unknown_observation_name() -> None:
    store = ObservationStore()
    with pytest.raises(ValueError):
        resolve(store, "terminal.nope", observed_at=AT_B)
    with pytest.raises(ValueError):
        resolve_cwd(store, observed_at="")

