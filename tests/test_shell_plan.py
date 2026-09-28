"""P5 behavior tests: planner, preparation, history, and next-step.

Covers determinism, known/unknown/stale/invalidated/insufficient evidence,
the frozen operation vocabulary, capability routing, bounded output, and the
read-only boundary: no execution, no mutation, no numeric confidence, no
numeric risk, and no wall-clock TTL.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mcquest_mcp.shell import capabilities as registry
from mcquest_mcp.shell import environment, invalidate, observe, planner, redundancy
from mcquest_mcp.shell.facts import Scope, Source
from mcquest_mcp.shell.operations import OPERATION_CLASSES, Operation
from mcquest_mcp.shell.store import ObservationStore

SHELL = Path(__file__).resolve().parent.parent / "src" / "mcquest_mcp" / "shell"
PLANNER = SHELL / "planner.py"


@pytest.fixture()
def store() -> ObservationStore:
    return ObservationStore()


@pytest.fixture(autouse=True)
def _reset_shared_store():
    environment.reset_store()
    yield
    environment.reset_store()


def _record_cwd(store: ObservationStore, session: str, process: str) -> None:
    """Record the PROCESS-scoped CWD fact the READ_FILE plan requires."""
    observe.record_observation(
        store, name="terminal.cwd", value="D:\\repo", scope=Scope.PROCESS,
        client_session=session, client_process_id=process,
    )


# --- evidence states (contract §12; no invented state) -----------------------

def test_unknown_evidence_is_preserved_not_guessed(store: ObservationStore) -> None:
    plan = planner.build_plan("read the file README.md", store)
    assert plan.status is planner.PlanStatus.INSUFFICIENT_EVIDENCE
    assert [item.state for item in plan.evidence] == [planner.EvidenceState.UNKNOWN]
    assert [item.source for item in plan.evidence] == [Source.UNKNOWN]
    assert [r.observation for r in plan.required_observations] == ["terminal.cwd"]


def test_known_evidence_yields_a_ready_plan(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    plan = planner.build_plan(
        "read the file README.md", store, terminal_session="t1", process_id="p1"
    )
    assert plan.status is planner.PlanStatus.READY
    assert plan.evidence[0].state is planner.EvidenceState.KNOWN
    assert plan.required_observations == ()


def test_invalidated_evidence_is_reported_and_blocks_reuse(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    observe.invalidate(store, invalidate.InvalidationEvent.PROCESS_RESTART.value)
    plan = planner.build_plan(
        "read the file README.md", store, terminal_session="t1", process_id="p1"
    )
    assert plan.evidence[0].state is planner.EvidenceState.INVALIDATED
    assert plan.status is planner.PlanStatus.INSUFFICIENT_EVIDENCE
    assert any("invalidated" in blocker for blocker in plan.blockers)


def test_evidence_from_another_process_is_never_served(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    plan = planner.build_plan(
        "read the file README.md", store, terminal_session="t1", process_id="p2"
    )
    # Contract §8: an observation from another process is not current state.
    assert plan.evidence[0].state is planner.EvidenceState.UNKNOWN
    assert plan.status is planner.PlanStatus.INSUFFICIENT_EVIDENCE


def test_insufficient_evidence_names_its_missing_observation(store: ObservationStore) -> None:
    plan = planner.build_plan("run node build.js", store)
    assert plan.status is planner.PlanStatus.INSUFFICIENT_EVIDENCE
    assert plan.required_observations
    assert plan.required_observations[0].capability.startswith("mcquest_")


# --- determinism and bounds --------------------------------------------------

def test_plan_is_deterministic(store: ObservationStore) -> None:
    assert planner.build_plan("check git status", store) == planner.build_plan(
        "check git status", store
    )


def test_plan_is_bounded(store: ObservationStore) -> None:
    plan = planner.build_plan("enumerate all files in the repository", store)
    assert len(plan.steps) <= planner.MAX_PLAN_STEPS
    assert len(plan.evidence) <= planner.MAX_REQUIRED_EVIDENCE


def test_oversized_intent_is_rejected(store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        planner.build_plan("x" * (planner.MAX_INPUT_CHARS + 1), store)


def test_empty_intent_is_rejected(store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        planner.build_plan("   ", store)



# --- frozen operation vocabulary ---------------------------------------------

def test_plan_only_emits_frozen_operation_classes(store: ObservationStore) -> None:
    for intent in (
        "read the file a.ts", "check the quiz.loading key in a json file",
        "search for a literal string", "use a regex pattern to find things",
        "enumerate all files", "check whether the path exists", "check git status",
        "check the git config", "measure line endings", "run node x.js",
        "run python x.py", "run the tests", "build the project",
        "install a package", "edit the file",
    ):
        plan = planner.build_plan(intent, store)
        assert plan.operation.value in OPERATION_CLASSES + ("UNKNOWN",)
        for step in plan.steps:
            assert step.operation.value in OPERATION_CLASSES + ("UNKNOWN",)


def test_no_new_operation_class_was_added(store: ObservationStore) -> None:
    # The frozen contract §13 vocabulary is untouched: P5 adds no class.
    assert {operation.value for operation in Operation} == set(OPERATION_CLASSES) | {
        "UNKNOWN"
    }
    for banned in ("DELETE", "REMOVE", "EXECUTE", "COMMAND", "SHELL"):
        assert banned not in OPERATION_CLASSES


def test_unclassifiable_intent_is_blocked_not_guessed(store: ObservationStore) -> None:
    plan = planner.build_plan("qwertyuiop asdfgh", store)
    assert plan.operation is Operation.UNKNOWN
    assert plan.status is planner.PlanStatus.BLOCKED
    assert plan.blockers


# --- preference ladder and capability routing (contract §13, §19) ------------

def test_existing_evidence_outranks_every_new_interaction(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    plan = planner.build_plan(
        "read the file README.md", store, terminal_session="t1", process_id="p1"
    )
    assert plan.steps[0].ladder is planner.PlanLadder.EXISTING_EVIDENCE


def test_capability_routing_names_an_existing_registered_capability() -> None:
    for operation, expected in (
        (Operation.CHECK_GIT_STATE, "mcquest_git_context"),
        (Operation.READ_FILE, "mcquest_read_file"),
        (Operation.READ_JSON, "mcquest_locale_inspect"),
        (Operation.ENUMERATE_FILES, "mcquest_list_files"),
        (Operation.SEARCH_REGEX, "mcquest_search"),
    ):
        assert planner.route_capability(operation) == expected


def test_shell_only_operations_never_route_to_a_capability() -> None:
    # Contract §19 rule 5: routing to a capability that would not answer the
    # intent is a violation, so execution/build/install/edit route to nothing.
    for operation in (Operation.RUN_NODE, Operation.RUN_PYTHON, Operation.RUN_TEST,
                      Operation.BUILD, Operation.INSTALL, Operation.EDIT):
        assert planner.route_capability(operation) is None


def test_routed_capability_is_a_registered_tool() -> None:
    for operation in Operation:
        routed = planner.route_capability(operation)
        if routed is not None:
            assert routed in registry.capability_names()


def test_mutation_bearing_operation_is_flagged_not_performed(store: ObservationStore) -> None:
    plan = planner.build_plan("install a package", store)
    assert plan.operation is Operation.INSTALL


# --- the read-only / recommend-only boundary (contract §14) -----------------

def test_no_result_ever_permits_execution(store: ObservationStore) -> None:
    assert planner.build_plan("check git status", store).execution_permitted is False
    assert planner.prepare_request("check git status", store).execution_permitted is False
    assert planner.next_step("check git status", store).execution_permitted is False


def test_planner_module_has_no_execution_or_mutation_surface() -> None:
    source = PLANNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "subprocess", "socket", "requests", "urllib", "http", "time", "datetime",
        "shutil", "pathlib", "os",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden, node.module
    # Execution is proven absent structurally (above: no execution/clock/network
    # imports) and textually for the dangerous call forms. A bare `subprocess`
    # word may appear in prose that *forbids* it, so only the call shapes are
    # matched literally.
    for token in ("shell=True", "os.system", "os.popen", "eval(", "exec(",
                  "Popen(", "subprocess.run", "subprocess.Popen", "check_output"):
        assert token not in source, token
    for token in ("write_text", "write_bytes", "unlink", "rmtree", "mkdir"):
        assert token not in source, token


def test_planner_defines_no_second_state_model() -> None:
    source = PLANNER.read_text(encoding="utf-8")
    # It consumes the P1/P2/P3 models; it never redefines them.
    for banned in ("class Fact", "class Observation", "class ObservationStore",
                   "class Scope", "class Trust", "class Source", "class Freshness"):
        assert banned not in source, banned


def test_no_numeric_confidence_or_risk_is_produced(store: ObservationStore) -> None:
    plan = planner.build_plan("check git status", store)
    preparation = planner.prepare_request("check git status", store)
    step = planner.next_step("check git status", store)
    for result in (plan, preparation, step):
        rendered = repr(result)
        for banned in ("confidence", "risk_score", "score=", "risk="):
            assert banned not in rendered, banned


def test_no_wall_clock_ttl_is_used(store: ObservationStore) -> None:
    source = PLANNER.read_text(encoding="utf-8")
    for banned in ("time.time()", "timedelta", "expires", "expire", "max_age"):
        assert banned not in source, banned


def test_observed_at_is_never_rendered(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    plan = planner.build_plan(
        "read the file README.md", store, terminal_session="t1", process_id="p1"
    )
    assert "observed_at" not in repr(plan)


# --- preparation (contract §14: text only, never executed) -------------------

def test_preparation_with_full_prerequisites_is_prepared(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    preparation = planner.prepare_request(
        "read the file README.md", store, terminal_session="t1", process_id="p1"
    )
    assert preparation.status is planner.PrepareStatus.PREPARED
    assert "NOT EXECUTED" in preparation.prepared_text


def test_preparation_with_missing_prerequisites_is_not_guessed(store: ObservationStore) -> None:
    preparation = planner.prepare_request("read the file README.md", store)
    assert preparation.status is planner.PrepareStatus.INSUFFICIENT_PREREQUISITES
    assert preparation.missing_prerequisites
    assert "No command is proposed" in preparation.prepared_text




# --- history (reuses the P1 store; no second persistence) -------------------

def test_empty_history_is_reported_as_insufficient(store: ObservationStore) -> None:
    view = planner.history_view(store)
    assert view.status is planner.PlanStatus.INSUFFICIENT
    assert view.total == 0
    assert view.rows == ()


def test_history_reuses_the_existing_store_records(store: ObservationStore) -> None:
    record = store.record_command("git status", operation="CHECK_GIT_STATE",
                                  terminal_session="t1", process_id="p1")
    view = planner.history_view(store, terminal_session="t1", process_id="p1")
    assert view.total == 1
    assert view.rows[0].record_id == record.command_id
    assert view.rows[0].kind == "command"


def test_history_rows_carry_provenance_trust_scope_and_binding(store: ObservationStore) -> None:
    store.record_command("git status", operation="CHECK_GIT_STATE",
                         terminal_session="t1", process_id="p1")
    row = planner.history_view(store).rows[0]
    assert row.source and row.trust and row.scope and row.freshness
    assert row.binding == "session+process"


def test_history_observation_rows_report_invalidation(store: ObservationStore) -> None:
    _record_cwd(store, "t1", "p1")
    key = f"{Scope.PROCESS.value}:terminal.cwd"
    rows = {
        row.record_id: row
        for row in planner.history_view(store, terminal_session="t1", process_id="p1").rows
    }
    assert rows[key].state is planner.EvidenceState.KNOWN
    observe.invalidate(store, invalidate.InvalidationEvent.PROCESS_RESTART.value)
    rows = {
        row.record_id: row
        for row in planner.history_view(store, terminal_session="t1", process_id="p1").rows
    }
    assert rows[key].state is planner.EvidenceState.INVALIDATED


def test_history_paging_is_deterministic(store: ObservationStore) -> None:
    for index in range(5):
        store.record_command(f"git status {index}", operation="CHECK_GIT_STATE",
                             terminal_session="t1", process_id="p1")
    first = planner.history_view(store, offset=0, limit=2)
    assert first.rows == planner.history_view(store, offset=0, limit=2).rows
    assert first.has_more is True
    assert first.next_offset == 2
    assert [
        row.record_id for row in planner.history_view(store, offset=2, limit=2).rows
    ] == ["cmd-0003", "cmd-0004"]


def test_history_rejects_invalid_paging(store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        planner.history_view(store, offset=-1)
    with pytest.raises(ValueError):
        planner.history_view(store, limit=0)
    with pytest.raises(ValueError):
        planner.history_view(store, limit=planner.MAX_HISTORY_LIMIT + 1)


def test_history_does_not_mutate_the_store(store: ObservationStore) -> None:
    store.record_command("git status", operation="CHECK_GIT_STATE")
    before = store.snapshot()
    planner.history_view(store)
    assert store.snapshot() == before
    assert len(store.commands()) == 1


# --- next step (contract §22; differentiated, never a loop) -----------------

def test_next_step_asks_for_the_missing_observation_first(store: ObservationStore) -> None:
    step = planner.next_step("read the file README.md", store)
    assert step.action is planner.NextAction.OBSERVE
    assert "terminal.cwd" in step.detail


def test_next_step_refuses_a_blind_retry(store: ObservationStore) -> None:
    store.record_command("git status", operation="CHECK_GIT_STATE",
                         terminal_session="t1", process_id="p1")
    step = planner.next_step(
        "check git status", store, terminal_session="t1", process_id="p1",
        last_command="git status",
    )
    # F1: nothing changed since the last command, so the repeat is refused and
    # the response differs rather than repeating the same action.
    assert step.action is planner.NextAction.DIFFERENTIATE
    assert "refused" in step.detail
    assert step.step is None


def test_next_step_permits_a_retry_when_a_condition_changed(store: ObservationStore) -> None:
    store.record_command("git status", operation="CHECK_GIT_STATE",
                         terminal_session="t1", process_id="p1")
    step = planner.next_step(
        "check git status", store, terminal_session="t1", process_id="p1",
        last_command="git status", changed_reasons=(redundancy.ChangeReason.FILE,),
    )
    assert step.action is not planner.NextAction.DIFFERENTIATE
    assert step.changed_conditions == ("file",)


def test_next_step_stops_on_an_unclassifiable_intent(store: ObservationStore) -> None:
    assert planner.next_step("qwertyuiop", store).action is planner.NextAction.STOP


def test_next_step_is_deterministic_and_bounded(store: ObservationStore) -> None:
    first = planner.next_step("check git status", store, last_command="git status")
    assert first == planner.next_step("check git status", store, last_command="git status")
    assert len(first.plan.steps) <= planner.MAX_PLAN_STEPS


def test_next_step_does_not_mutate_or_execute(store: ObservationStore) -> None:
    before = store.snapshot()
    planner.next_step("check git status", store, last_command="git status")
    assert store.snapshot() == before

def test_preparation_of_unclassifiable_request_is_blocked(store: ObservationStore) -> None:
    assert planner.prepare_request("qwertyuiop", store).status is planner.PrepareStatus.BLOCKED


def test_preparation_is_deterministic(store: ObservationStore) -> None:
    assert planner.prepare_request("read the file a.md", store) == (
        planner.prepare_request("read the file a.md", store)
    )


def test_preparation_does_not_mutate_the_store(store: ObservationStore) -> None:
    before = store.snapshot()
    planner.prepare_request("read the file a.md", store)
    assert store.snapshot() == before
    assert store.commands() == ()
