"""P1 state tests: event → scope invalidation with per-scope/subject revisions (contract §12; architecture §5.3).

Rule under test: **invalidate rather than guess** — each event invalidates exactly its
mapped scopes/subjects, unrelated repository facts are never collateral damage, and no
behaviour depends on wall-clock time.
"""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.facts import Fact, Freshness, Scope, Source, Trust
from mcquest_mcp.shell.invalidate import (
    EVENT_TARGETS,
    InvalidationEvent,
    apply_invalidation,
)
from mcquest_mcp.shell.store import ObservationStore

AT = "2026-01-01T00:00:00Z"


def fact(
    observation: str,
    value: object,
    scope: Scope,
    freshness: Freshness,
    subject: str,
) -> Fact:
    """SERVER_OBSERVED fact without identity binding — pure scope/subject matrix tests."""
    return Fact(
        observation=observation,
        value=value,
        scope=scope,
        freshness=freshness,
        observed_at=AT,
        source=Source.SERVER_OBSERVED,
        trust=Trust.TRUSTED,
        evidence="matrix fixture",
        subject=subject,
    )


def build() -> tuple[ObservationStore, dict[str, Fact]]:
    store = ObservationStore()
    facts: dict[str, Fact] = {
        "repo": fact("git.autocrlf", True, Scope.REPOSITORY, Freshness.SESSION, "core.autocrlf"),
        "repo_other": fact("git.remote", "origin", Scope.REPOSITORY, Freshness.SESSION, "remote.origin.url"),
        "worktree": fact("git.branch", "main", Scope.WORKTREE, Freshness.WORKTREE, "HEAD"),
        "file": fact("file.eol", "crlf", Scope.FILE, Freshness.WORKTREE, "a.txt"),
        "file2": fact("file.eol", "lf", Scope.FILE, Freshness.WORKTREE, "b.txt"),
        "session": fact("tool.node", "v22", Scope.SESSION, Freshness.SESSION, "node"),
        "session2": fact("tool.git", "2.45", Scope.SESSION, Freshness.SESSION, "git"),
        "process_env": fact("proc.env", "C:\\bin", Scope.PROCESS, Freshness.PROCESS, "PATH"),
        "process_shell": fact("proc.shell", "7.6", Scope.PROCESS, Freshness.PROCESS, "shell_version"),
        "cwd": fact("terminal.cwd", "D:\\x", Scope.PROCESS, Freshness.PROCESS, "cwd"),
        "codepage": fact(
            "terminal.console_codepage", "65001", Scope.PROCESS, Freshness.PROCESS, "console_codepage"
        ),
        "ephemeral": fact("cmd.out", "old", Scope.EPHEMERAL, Freshness.EPHEMERAL, "out"),
    }
    for item in facts.values():
        store.record(item)
    return store, facts


def fresh(store: ObservationStore, item: Fact) -> bool:
    return store.reuse_check(item)


def test_every_mandated_event_exists() -> None:
    mandated = {
        "set_location",
        "file_modified",
        "git_checkout",
        "git_reset",
        "git_pull",
        "dependency_install",
        "environment_change",
        "configuration_change",
        "process_restart",
        "terminal_restart",
        "repository_worktree_change",
    }
    assert mandated <= {e.value for e in InvalidationEvent}


def test_every_event_has_targets() -> None:
    assert set(EVENT_TARGETS) == set(InvalidationEvent)
    assert all(targets for targets in EVENT_TARGETS.values())


def test_non_enum_event_is_rejected() -> None:
    store, _ = build()
    with pytest.raises(TypeError):
        apply_invalidation(store, "set_location")  # type: ignore[arg-type]


def test_set_location_invalidates_only_the_cwd_subject() -> None:
    store, facts = build()
    bumped = apply_invalidation(store, InvalidationEvent.SET_LOCATION)
    assert bumped == ((Scope.PROCESS, "cwd"),)
    assert fresh(store, facts["cwd"]) is False
    assert fresh(store, facts["process_shell"]) is True  # shell version unaffected
    assert fresh(store, facts["repo"]) is True


def test_file_modified_refines_to_matching_path_and_worktree() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.FILE_MODIFIED, subject="a.txt")
    assert fresh(store, facts["file"]) is False
    assert fresh(store, facts["file2"]) is True  # other path untouched
    assert fresh(store, facts["worktree"]) is False  # content/search-dependent facts
    assert fresh(store, facts["repo"]) is True


def test_file_modified_without_subject_invalidates_the_file_scope() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.FILE_MODIFIED)
    assert fresh(store, facts["file"]) is False
    assert fresh(store, facts["file2"]) is False
    assert fresh(store, facts["repo"]) is True


def test_git_checkout_invalidates_worktree_not_repository() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.GIT_CHECKOUT)
    assert fresh(store, facts["worktree"]) is False
    assert fresh(store, facts["file"]) is True
    assert fresh(store, facts["repo"]) is True
    assert fresh(store, facts["session"]) is True


def test_git_reset_invalidates_worktree_only() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.GIT_RESET)
    assert fresh(store, facts["worktree"]) is False
    assert fresh(store, facts["file"]) is True
    assert fresh(store, facts["repo"]) is True


def test_git_pull_invalidates_worktree() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.GIT_PULL)
    assert fresh(store, facts["worktree"]) is False
    assert fresh(store, facts["repo"]) is True


def test_branch_switch_invalidates_worktree() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.BRANCH_SWITCH)
    assert fresh(store, facts["worktree"]) is False
    assert fresh(store, facts["repo"]) is True


def test_dependency_install_invalidates_session_facts_only() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.DEPENDENCY_INSTALL)
    assert fresh(store, facts["session"]) is False
    assert fresh(store, facts["session2"]) is False
    assert fresh(store, facts["repo"]) is True
    assert fresh(store, facts["worktree"]) is True


def test_environment_change_refines_process_subject_and_ephemeral() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.ENVIRONMENT_CHANGE, subject="PATH")
    assert fresh(store, facts["process_env"]) is False
    assert fresh(store, facts["process_shell"]) is True  # not the changed variable
    assert fresh(store, facts["ephemeral"]) is False  # output may depend on env
    assert fresh(store, facts["repo"]) is True


def test_environment_change_without_subject_invalidates_process_scope() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.ENVIRONMENT_CHANGE)
    assert fresh(store, facts["process_env"]) is False
    assert fresh(store, facts["process_shell"]) is False
    assert fresh(store, facts["cwd"]) is False
    assert fresh(store, facts["session"]) is True
    assert fresh(store, facts["repo"]) is True


def test_configuration_change_refines_matching_subjects_only() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.CONFIGURATION_CHANGE, subject="core.autocrlf")
    assert fresh(store, facts["repo"]) is False
    assert fresh(store, facts["repo_other"]) is True  # different config key
    assert fresh(store, facts["session"]) is True
    assert fresh(store, facts["file"]) is True
    assert fresh(store, facts["worktree"]) is True  # not a configuration scope


def test_configuration_change_without_subject_hits_config_scopes_not_worktree() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.CONFIGURATION_CHANGE)
    assert fresh(store, facts["repo"]) is False
    assert fresh(store, facts["repo_other"]) is False
    assert fresh(store, facts["file"]) is False
    assert fresh(store, facts["session"]) is False
    assert fresh(store, facts["worktree"]) is True


def test_process_restart_invalidates_process_not_session() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.PROCESS_RESTART)
    assert fresh(store, facts["process_env"]) is False
    assert fresh(store, facts["cwd"]) is False
    assert fresh(store, facts["session"]) is True
    assert fresh(store, facts["repo"]) is True


def test_terminal_restart_invalidates_session_and_process() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.TERMINAL_RESTART)
    assert fresh(store, facts["session"]) is False
    assert fresh(store, facts["process_env"]) is False
    assert fresh(store, facts["repo"]) is True
    assert fresh(store, facts["worktree"]) is True


def test_server_restart_invalidates_session_and_process() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.SERVER_RESTART)
    assert fresh(store, facts["session"]) is False
    assert fresh(store, facts["process_env"]) is False
    assert fresh(store, facts["repo"]) is True


def test_repository_worktree_change_invalidates_both_named_scopes() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.REPOSITORY_WORKTREE_CHANGE)
    assert fresh(store, facts["repo"]) is False
    assert fresh(store, facts["worktree"]) is False
    assert fresh(store, facts["session"]) is True
    assert fresh(store, facts["file"]) is True  # FILE changes arrive via file events


def test_console_codepage_change_is_canonical_not_scope_wide() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.CONSOLE_CODEPAGE_CHANGE)
    assert fresh(store, facts["codepage"]) is False
    assert fresh(store, facts["process_shell"]) is True  # shell version unaffected
    assert fresh(store, facts["ephemeral"]) is False  # rendering-dependent output
    assert fresh(store, facts["repo"]) is True


def test_file_created_deleted_invalidates_inventories_and_matching_path() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.FILE_CREATED_DELETED, subject="a.txt")
    assert fresh(store, facts["worktree"]) is False  # inventories
    assert fresh(store, facts["file"]) is False  # the created/deleted path itself
    assert fresh(store, facts["file2"]) is True  # other paths keep their existence facts
    assert fresh(store, facts["repo"]) is True


def test_repository_facts_survive_every_terminal_scoped_event() -> None:
    terminal_events = [
        InvalidationEvent.SET_LOCATION,
        InvalidationEvent.PROCESS_RESTART,
        InvalidationEvent.TERMINAL_RESTART,
        InvalidationEvent.SERVER_RESTART,
        InvalidationEvent.ENVIRONMENT_CHANGE,
        InvalidationEvent.CONSOLE_CODEPAGE_CHANGE,
        InvalidationEvent.DEPENDENCY_INSTALL,
    ]
    for event in terminal_events:
        store, facts = build()
        apply_invalidation(store, event)
        assert fresh(store, facts["repo"]) is True, event
        assert fresh(store, facts["repo_other"]) is True, event


def test_invalidated_fact_remains_retrievable_for_audit() -> None:
    store, facts = build()
    apply_invalidation(store, InvalidationEvent.SET_LOCATION)
    assert store.lookup("terminal.cwd", Scope.PROCESS, "cwd") == facts["cwd"]
    assert fresh(store, facts["cwd"]) is False


def test_apply_returns_the_same_sorted_keys_on_equivalent_stores() -> None:
    first, _ = build()
    second, _ = build()
    events = [
        (InvalidationEvent.FILE_MODIFIED, "a.txt"),
        (InvalidationEvent.ENVIRONMENT_CHANGE, None),
        (InvalidationEvent.CONFIGURATION_CHANGE, None),
    ]
    results_first = [apply_invalidation(store=first, event=e, subject=s) for e, s in events]
    results_second = [apply_invalidation(store=second, event=e, subject=s) for e, s in events]
    assert results_first == results_second
    for bumped in results_first:
        assert bumped == tuple(sorted(bumped, key=lambda k: (k[0].value, k[1])))


def test_revisions_only_grow_never_reset_without_store_reset() -> None:
    store, _ = build()
    apply_invalidation(store, InvalidationEvent.GIT_CHECKOUT)
    first = store.revision_for(Scope.WORKTREE, "HEAD")
    apply_invalidation(store, InvalidationEvent.GIT_CHECKOUT)
    second = store.revision_for(Scope.WORKTREE, "HEAD")
    assert second > first >= 1
    assert store.revision_for(Scope.REPOSITORY, "core.autocrlf") == 0  # other scopes untouched

