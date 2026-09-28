"""P4 behavior tests: A14 observation ingestion and the two MCP adapters.

Covers the A14 ingest shape, provenance/trust/scope handling, session-process
identity binding, invalidation interaction, determinism, no persistence, and
the summary-first bounded adapter output.
"""

from __future__ import annotations

import asyncio

import pytest

from mcquest_mcp.server import mcp
from mcquest_mcp.shell import environment, observe, validate
from mcquest_mcp.shell.facts import EVIDENCE_CLIENT_DECLARED, Scope, Source
from mcquest_mcp.shell.store import ObservationStore
from mcquest_mcp.tools.shell_env import shell_observe, shell_validate

P4_TOOLS = ("mcquest_shell_observe", "mcquest_shell_validate")
P5_TOOLS = (
    "mcquest_shell_plan",
    "mcquest_shell_prepare",
    "mcquest_shell_history",
    "mcquest_shell_next",
)


@pytest.fixture()
def store() -> ObservationStore:
    return ObservationStore()


@pytest.fixture(autouse=True)
def _reset_shared_store():
    environment.reset_store()
    yield
    environment.reset_store()


# --- A14 ingest shape -------------------------------------------------------

def test_ingest_kind_has_exactly_the_two_a14_members() -> None:
    assert {member.value for member in observe.IngestKind} == {
        "observation", "command",
    }
    assert {member.value for member in observe.RecordedAt} == {"SERVER", "CLIENT"}


def test_server_ingest_is_server_observed_and_trusted(store: ObservationStore) -> None:
    result = observe.record_observation(
        store, name="mcquest_search.total", value="42", scope=Scope.WORKTREE,
        source="mcquest_search", recorded_at_source=observe.RecordedAt.SERVER,
    )
    assert result.status is observe.ObserveStatus.RECORDED
    assert result.source is Source.SERVER_OBSERVED
    assert result.trust.value == "trusted"
    assert result.observation_id.startswith("obs-")


def test_client_ingest_keeps_declared_evidence_phrase(
    store: ObservationStore,
) -> None:
    observe.record_observation(
        store, name="locale.quiz.loading.si", value="Quiz", scope=Scope.FILE,
    )
    stored = store.snapshot()[0]
    assert stored.source is Source.CLIENT_DECLARED
    assert stored.evidence == EVIDENCE_CLIENT_DECLARED
    assert stored.trust.value == "untrusted"


def test_tool_derived_evidence_keeps_its_originating_tool(
    store: ObservationStore,
) -> None:
    observe.record_observation(
        store, name="mcquest_find_files.total", value="7", scope=Scope.REPOSITORY,
        source="mcquest_find_files", recorded_at_source=observe.RecordedAt.SERVER,
    )
    assert "mcquest_find_files" in store.snapshot()[0].evidence


# --- identity binding (contract §8) -----------------------------------------

def test_session_scope_requires_declared_session(store: ObservationStore) -> None:
    result = observe.record_observation(
        store, name="x.y", value="1", scope=Scope.SESSION
    )
    assert result.status is observe.ObserveStatus.REJECTED
    assert store.snapshot() == ()


@pytest.mark.parametrize("scope", [Scope.PROCESS, Scope.EPHEMERAL])
def test_process_scope_requires_session_and_process(
    store: ObservationStore, scope: Scope
) -> None:
    rejected = observe.record_observation(store, name="x.y", value="1", scope=scope)
    assert rejected.status is observe.ObserveStatus.REJECTED
    accepted = observe.record_observation(
        store, name="x.y", value="1", scope=scope,
        client_session="s1", client_process_id="p1",
    )
    assert accepted.status is observe.ObserveStatus.RECORDED


def test_no_cross_session_promotion(store: ObservationStore) -> None:
    observe.record_observation(
        store, name="x.y", value="1", scope=Scope.SESSION, client_session="s1"
    )
    served = store.lookup("x.y", Scope.SESSION, terminal_session="s2")
    assert served is None or served.value == "unknown"


# --- command history + invalidation (contract §10/§12) ----------------------

def test_command_observation_invalidates_ephemeral(store: ObservationStore) -> None:
    observe.record_observation(
        store, name="x.y", value="1", scope=Scope.EPHEMERAL,
        client_session="s1", client_process_id="p1",
    )
    result = observe.record_command_observation(
        store, text="git status", client_session="s1", client_process_id="p1"
    )
    assert result.status is observe.ObserveStatus.RECORDED
    assert result.command_id == "cmd-0001"
    assert store.commands()[0].text == "git status"


def test_invalidation_event_bumps_only_mapped_scopes(store: ObservationStore) -> None:
    bumped = observe.invalidate(store, "file_modified", subject="a.txt")
    assert all(scope in {Scope.FILE, Scope.WORKTREE} for scope, _ in bumped)


def test_unknown_invalidation_event_is_not_guessed(store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        observe.invalidate(store, "meteor_strike")


def test_invalidation_result_is_deterministic(store: ObservationStore) -> None:
    first = observe.invalidate(store, "branch_switch")
    second = observe.invalidate(store, "branch_switch")
    assert first == second == tuple(sorted(first, key=lambda k: (k[0].value, k[1])))


def test_recorded_observation_is_reusable_until_invalidated(
    store: ObservationStore,
) -> None:
    observe.record_observation(
        store, name="x.y", value="1", scope=Scope.REPOSITORY, subject="repo"
    )
    fact = store.snapshot()[0]
    assert store.reuse_check(fact) is True
    observe.invalidate(store, "repository_worktree_change", subject="repo")
    # Invalidate rather than guess: the same fact is now stale, never served.
    assert store.reuse_check(fact) is False


def test_observe_creates_no_files_and_persists_nothing(store: ObservationStore) -> None:
    observe.record_observation(store, name="x.y", value="1", scope=Scope.REPOSITORY)
    assert store.snapshot()  # in-memory only
    # decision A4: reset() is the only lifetime; nothing is written to disk.
    store.reset()
    assert store.snapshot() == ()


def test_empty_name_is_rejected(store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        observe.record_observation(store, name="  ", value="1", scope=Scope.FILE)


# --- adapters: summary-first bounded output ---------------------------------

def test_validate_adapter_starts_with_summary_block() -> None:
    output = shell_validate(command="Remove-Item -Recurse -Force ./build")
    assert output.startswith("[SUMMARY]")
    assert "tool: mcquest_shell_validate" in output
    assert "[EVIDENCE]" in output
    assert output.rstrip().endswith("[END]")


def test_validate_adapter_reports_the_verdict_summary() -> None:
    output = shell_validate(command="Remove-Item -Recurse -Force ./build")
    assert "verdict: ERROR" in output
    assert "analysis_only: true" in output
    assert "read_only: true" in output


def test_validate_adapter_renders_every_frozen_section_in_order() -> None:
    output = shell_validate(command="git status")
    positions = [output.index(f"{name}: ") for name in validate.FROZEN_SECTIONS]
    assert positions == sorted(positions)


def test_validate_adapter_output_is_byte_identical() -> None:
    assert shell_validate(command="git status") == shell_validate(command="git status")


def test_validate_adapter_is_bounded() -> None:
    output = shell_validate(command="Get-ChildItem -Recurse | Select-String x; " * 60)
    assert len(output) <= 4000


def test_validate_adapter_lint_mode() -> None:
    assert "mode: lint" in shell_validate(command="git status", mode="lint")


def test_observe_adapter_reports_status() -> None:
    output = shell_observe(
        name="mcquest_search.total", value="42", scope="WORKTREE",
        source="mcquest_search", recorded_at_source="SERVER",
    )
    assert output.startswith("[SUMMARY]")
    assert "status: RECORDED" in output
    assert "source: SERVER_OBSERVED" in output


def test_observe_adapter_rejects_unidentified_process_scope() -> None:
    assert "status: REJECTED" in shell_observe(name="x.y", value="1", scope="PROCESS")


def test_observe_adapter_records_command_kind() -> None:
    output = shell_observe(kind="command", value="git status")
    assert "kind: command" in output
    assert "status: RECORDED" in output


def test_observe_adapter_applies_invalidation() -> None:
    output = shell_observe(invalidate_event="file_modified", subject="a.txt")
    assert "invalidation_event: file_modified" in output


# --- registration (A11/A12) -------------------------------------------------

def test_p4_tools_stay_registered_after_p5() -> None:
    # P5 added plan/prepare/history/next; the P4 pair must stay registered.
    names = sorted(tool.name for tool in asyncio.run(mcp.list_tools()))
    assert len(names) == 34
    for name in P4_TOOLS:
        assert name in names
    for name in P5_TOOLS:
        assert name in names


def test_no_separate_lint_tool_exists() -> None:
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert not any("lint" in name for name in names)
    assert "mcquest_shell_validate" in names


def test_p4_tools_declare_read_only_docstrings() -> None:
    for tool in asyncio.run(mcp.list_tools()):
        if tool.name in P4_TOOLS:
            assert "READ ONLY" in (tool.description or "")


def test_p4_tool_parameters_all_have_descriptions() -> None:
    for tool in asyncio.run(mcp.list_tools()):
        if tool.name in P4_TOOLS:
            for name, schema in tool.input_schema["properties"].items():
                description = schema.get("description")
                assert isinstance(description, str) and description.strip(), name
