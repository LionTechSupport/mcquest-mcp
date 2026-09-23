"""P1 state tests: deterministic in-memory observation/history store (decision A4; contract §9–§12).

Every test constructs its own ``ObservationStore`` — no shared state, no wall clock,
no filesystem effect. Test-plan §4 (S1–S12) is covered here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcquest_mcp.shell.facts import (
    CostClass,
    Fact,
    Freshness,
    Scope,
    Source,
    Trust,
)
from mcquest_mcp.shell.store import ObservationStore

AT = "2026-01-01T00:00:00Z"


def fact(
    observation: str = "os.name",
    value: object = "Windows",
    scope: Scope = Scope.REPOSITORY,
    freshness: Freshness = Freshness.STATIC,
    *,
    subject: str | None = None,
    terminal_session: str | None = None,
    process_id: str | None = None,
    source: Source = Source.SERVER_OBSERVED,
    trust: Trust = Trust.TRUSTED,
    evidence: str = "platform probe",
) -> Fact:
    """Build a valid fact; SERVER_OBSERVED by default so no identity binding is required."""
    return Fact(
        observation=observation,
        value=value,
        scope=scope,
        freshness=freshness,
        observed_at=AT,
        source=source,
        trust=trust,
        evidence=evidence,
        subject=subject,
        terminal_session=terminal_session,
        process_id=process_id,
    )


def process_fact(
    *,
    terminal_session: str = "A",
    process_id: str = "1",
    cwd: str = "D:\\one",
) -> Fact:
    """A client-declared CWD fact bound to one terminal/process (contract §8)."""
    return Fact(
        observation="terminal.cwd",
        value=cwd,
        scope=Scope.PROCESS,
        freshness=Freshness.PROCESS,
        observed_at=AT,
        source=Source.CLIENT_DECLARED,
        trust=Trust.UNTRUSTED,
        evidence="declared by client; not verified",
        subject="cwd",
        terminal_session=terminal_session,
        process_id=process_id,
    )


def test_record_and_lookup_roundtrip() -> None:
    store = ObservationStore()
    stored = store.record(fact(subject="core.autocrlf"))
    assert stored.revision == 0
    found = store.lookup("os.name", Scope.REPOSITORY, "core.autocrlf")
    assert found == stored


def test_lookup_missing_returns_none() -> None:
    store = ObservationStore()
    assert store.lookup("nope", Scope.REPOSITORY, None) is None


def test_record_stamps_current_revision() -> None:
    store = ObservationStore()
    store.invalidate_scope(Scope.REPOSITORY, "core.autocrlf")  # bump before recording
    stored = store.record(fact(subject="core.autocrlf"))
    assert stored.revision == 1
    assert store.revision_for(Scope.REPOSITORY, "core.autocrlf") == 1


def test_snapshot_is_deterministic_regardless_of_insertion_order() -> None:
    f1 = fact("a.one", subject="s1")
    f2 = fact("b.two", subject="s2")
    f3 = fact("c.three", subject="s3")
    first = ObservationStore()
    second = ObservationStore()
    for item in (f1, f2, f3):
        first.record(item)
    for item in (f3, f1, f2):
        second.record(item)
    assert first.snapshot() == second.snapshot()
    assert first.snapshot() == first.snapshot()  # repeated calls byte-stable


def test_reset_clears_facts_history_and_revisions() -> None:
    store = ObservationStore()
    stored = store.record(process_fact())
    store.record_command("Get-Location", terminal_session="A", process_id="1")
    store.reset()
    assert store.lookup("terminal.cwd", Scope.PROCESS, "cwd") is None
    assert store.snapshot() == ()
    assert store.history.records() == ()
    assert store.revision_for(Scope.EPHEMERAL) == 0
    # A fact from before the restart must not be reusable afterwards (decision S3).
    assert store.reuse_check(stored, terminal_session="A", process_id="1") is False


def test_fresh_store_represents_server_restart_without_carry_over() -> None:
    before = ObservationStore()
    old = before.record(process_fact())
    after = ObservationStore()  # a restart is a brand-new in-memory store
    assert (
        after.lookup("terminal.cwd", Scope.PROCESS, "cwd", terminal_session="A", process_id="1")
        is None
    )
    assert after.reuse_check(old, terminal_session="A", process_id="1") is False


def test_no_cross_session_reuse_for_process_facts() -> None:
    store = ObservationStore()
    stored = store.record(process_fact(terminal_session="A", process_id="1"))
    assert (
        store.lookup("terminal.cwd", Scope.PROCESS, "cwd", terminal_session="A", process_id="1")
        == stored
    )
    # Terminal B must never see Terminal A's CWD (contract §8 rule 1).
    assert (
        store.lookup("terminal.cwd", Scope.PROCESS, "cwd", terminal_session="B", process_id="1")
        is None
    )
    assert store.reuse_check(stored, terminal_session="A", process_id="1") is True
    assert store.reuse_check(stored, terminal_session="B", process_id="1") is False
    assert store.reuse_check(stored) is False  # undeclared requester matches nothing


def test_no_cross_process_reuse_within_one_session() -> None:
    store = ObservationStore()
    stored = store.record(process_fact(terminal_session="A", process_id="1"))
    assert (
        store.lookup("terminal.cwd", Scope.PROCESS, "cwd", terminal_session="A", process_id="2")
        is None
    )
    assert store.reuse_check(stored, terminal_session="A", process_id="2") is False


def test_session_scope_binds_session_and_ignores_process() -> None:
    store = ObservationStore()
    stored = store.record(
        fact(
            "tool.node.version",
            "v22.0.0",
            Scope.SESSION,
            Freshness.SESSION,
            subject="node",
            terminal_session="A",
            process_id="1",
        )
    )
    assert (
        store.lookup(
            "tool.node.version", Scope.SESSION, "node", terminal_session="A", process_id="99"
        )
        == stored
    )
    assert store.lookup("tool.node.version", Scope.SESSION, "node", terminal_session="B") is None
    assert store.reuse_check(stored, terminal_session="A", process_id="99") is True
    assert store.reuse_check(stored, terminal_session="B") is False


def test_repository_scoped_facts_reuse_across_sessions() -> None:
    store = ObservationStore()
    stored = store.record(
        fact(subject="core.autocrlf", terminal_session="A", process_id="1")  # provenance only
    )
    # Contract §10: REPOSITORY/WORKTREE/FILE facts may be reused across sessions
    # while no invalidation has touched their scope/subject.
    assert (
        store.lookup(
            "os.name", Scope.REPOSITORY, "core.autocrlf", terminal_session="B"
        )
        == stored
    )
    assert store.reuse_check(stored) is True
    assert store.reuse_check(stored, terminal_session="B") is True


def test_stale_fact_stays_retrievable_but_not_reusable() -> None:
    store = ObservationStore()
    stored = store.record(fact(subject="core.autocrlf"))
    assert store.reuse_check(stored) is True
    store.invalidate_scope(Scope.REPOSITORY, "core.autocrlf")
    # "Invalidate rather than guess": the record remains for audit, but it may
    # no longer be served as current evidence.
    assert store.lookup("os.name", Scope.REPOSITORY, "core.autocrlf") == stored
    assert store.reuse_check(stored) is False


def test_revision_counter_is_monotonic_per_scope_subject() -> None:
    store = ObservationStore()
    store.invalidate_scope(Scope.REPOSITORY, "core.autocrlf")
    store.invalidate_scope(Scope.REPOSITORY, "core.autocrlf")
    assert store.revision_for(Scope.REPOSITORY, "core.autocrlf") == 2
    assert store.revision_for(Scope.REPOSITORY, "remote.origin.url") == 0


def test_invalidate_scope_returns_sorted_keys() -> None:
    store = ObservationStore()
    store.record(fact("z.last", subject="zs"))
    store.record(fact("a.first", subject="as"))
    bumped = store.invalidate_scope(Scope.REPOSITORY)
    assert bumped == tuple(sorted(bumped, key=lambda k: (k[0].value, k[1])))
    assert len(bumped) == 2


def test_record_command_ids_are_deterministic() -> None:
    store = ObservationStore()
    first = store.record_command("Get-Location", terminal_session="A", process_id="1")
    second = store.record_command("git status", terminal_session="A", process_id="1")
    assert first.command_id == "cmd-0001"
    assert second.command_id == "cmd-0002"
    assert [r.command_id for r in store.history.records()] == ["cmd-0001", "cmd-0002"]


def test_record_command_invalidates_ephemeral_facts_only() -> None:
    store = ObservationStore()
    ephemeral = store.record(
        fact("cmd.out", "old output", Scope.EPHEMERAL, Freshness.EPHEMERAL, subject="out")
    )
    process = store.record(
        fact("proc.env", "x", Scope.PROCESS, Freshness.PROCESS, subject="shell_version")
    )
    assert store.reuse_check(ephemeral) is True
    store.record_command("Get-ChildItem", terminal_session="A", process_id="1")
    # Contract §10: EPHEMERAL facts are never reused across commands.
    assert store.reuse_check(ephemeral) is False
    assert store.reuse_check(process) is True


def test_command_history_filters_by_relevant_identity() -> None:
    store = ObservationStore()
    store.record_command("cd one", terminal_session="A", process_id="1")
    store.record_command("cd two", terminal_session="B", process_id="2")
    store.record_command("git status")  # unbound
    assert [r.text for r in store.history.records(terminal_session="A")] == ["cd one"]
    assert [r.text for r in store.history.records(process_id="2")] == ["cd two"]
    assert len(store.history.records()) == 3
    assert [r.text for r in store.commands(terminal_session="B")] == ["cd two"]


def test_command_history_paging_is_deterministic_and_bounded() -> None:
    store = ObservationStore()
    for index in range(5):
        store.record_command(f"cmd-{index}")
    assert [r.text for r in store.history.page(offset=0, limit=2)] == ["cmd-0", "cmd-1"]
    assert [r.text for r in store.history.page(offset=4, limit=2)] == ["cmd-4"]
    with pytest.raises(ValueError):
        store.history.page(offset=-1)
    with pytest.raises(ValueError):
        store.history.page(offset=0, limit=0)


def test_command_history_normalized_duplicate_lookup_is_exact() -> None:
    store = ObservationStore()
    store.record_command(
        "Get-ChildItem -Recurse",
        normalized=("Get-ChildItem -Recurse", "get-childitem -recurse"),
    )
    store.record_command(
        "Get-ChildItem -Recurse -Force",
        normalized=("Get-ChildItem -Recurse -Force", "get-childitem -recurse -force"),
    )
    store.record_command("git status", normalized=("git status",))
    whole = store.history.find_normalized(("Get-ChildItem -Recurse", "get-childitem -recurse"))
    assert [r.text for r in whole] == ["Get-ChildItem -Recurse"]
    at_level_one = store.history.find_normalized(("ignored", "get-childitem -recurse"), level=1)
    assert [r.text for r in at_level_one] == ["Get-ChildItem -Recurse"]
    with pytest.raises(ValueError):
        store.history.find_normalized(("a",), level=-1)


def test_command_record_accepts_cost_and_mutation_classes() -> None:
    store = ObservationStore()
    record = store.record_command(
        "Remove-Item x",
        cost=CostClass.LOW,
        mutation=CostClass.MEDIUM,
        operation="EDIT",
        verdict="WARNING",
    )
    assert record.cost is CostClass.LOW
    assert record.mutation is CostClass.MEDIUM
    assert record.operation == "EDIT"
    assert record.verdict == "WARNING"
    with pytest.raises(TypeError):
        store.record_command("x", cost="LOW")  # type: ignore[arg-type]


def test_state_operations_create_no_files(repo: str) -> None:
    root = Path(repo)
    before = sorted(str(p) for p in root.rglob("*"))
    store = ObservationStore()
    store.record(process_fact())
    store.record_command("Get-Location", terminal_session="A", process_id="1")
    store.invalidate_scope(Scope.PROCESS, "cwd")
    store.reset()
    after = sorted(str(p) for p in root.rglob("*"))
    assert after == before


def test_state_modules_have_no_persistence_or_execution_imports() -> None:
    """P1 modules are pure state: no FS/process/db imports or write primitives."""
    package = Path(__file__).resolve().parent.parent / "src" / "mcquest_mcp" / "shell"
    state_modules = [
        "__init__.py",
        "facts.py",
        "store.py",
        "invalidate.py",
        "terminal.py",
        "cost.py",
    ]
    forbidden = (
        "write_text",
        "write_bytes",
        "unlink",
        "os.remove",
        "os.rename",
        "shutil.rmtree",
        "subprocess.Popen",
        "os.system",
        "os.popen",
        "import os",
        "import subprocess",
        "import sqlite3",
        "import shelve",
        "pathlib",
    )
    for name in state_modules:
        text = (package / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name} contains {token!r}"

