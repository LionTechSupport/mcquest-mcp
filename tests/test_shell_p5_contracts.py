"""P5 adapter and registration tests for the four new shell tools.

Covers the summary-first bounded output of each adapter, the deterministic
blocking/insufficient results, the "not executed" labelling, and the A11/A12
registration invariants at the final count of 34.
"""

from __future__ import annotations

import asyncio

import pytest

from mcquest_mcp.server import mcp
from mcquest_mcp.shell import environment, planner
from mcquest_mcp.tools.shell_env import (
    shell_history,
    shell_next,
    shell_plan,
    shell_prepare,
)

P5_TOOLS = (
    "mcquest_shell_plan",
    "mcquest_shell_prepare",
    "mcquest_shell_history",
    "mcquest_shell_next",
)


@pytest.fixture(autouse=True)
def _reset_shared_store():
    environment.reset_store()
    yield
    environment.reset_store()


def _live_names() -> list[str]:
    return sorted(tool.name for tool in asyncio.run(mcp.list_tools()))


# --- adapters: summary-first, bounded, deterministic -------------------------

# Each adapter declares its own inputs as keyword parameters, so the shared
# summary/budget/determinism assertions are driven by per-adapter keyword
# samples rather than positional arguments.
ADAPTER_SAMPLES = (
    (shell_plan, {"intent": "check git status"}),
    (shell_prepare, {"intent": "check git status"}),
    (shell_history, {}),
    (shell_next, {"intent": "check git status"}),
)


@pytest.mark.parametrize("render,kwargs", ADAPTER_SAMPLES)
def test_adapters_emit_summary_first_output(render, kwargs) -> None:
    output = render(**kwargs)
    assert output.startswith("[SUMMARY]")
    assert "[EVIDENCE]" in output
    assert output.rstrip().endswith("[END]")


@pytest.mark.parametrize("render,kwargs", ADAPTER_SAMPLES)
def test_adapters_are_byte_identical_across_repeats(render, kwargs) -> None:
    assert render(**kwargs) == render(**kwargs)


@pytest.mark.parametrize("render,kwargs", ADAPTER_SAMPLES)
def test_adapters_respect_the_default_budget(render, kwargs) -> None:
    assert len(render(**kwargs)) <= 4000


def test_plan_adapter_reports_operation_and_status() -> None:
    output = shell_plan("check git status")
    assert "tool: mcquest_shell_plan" in output
    assert "operation: CHECK_GIT_STATE" in output
    assert "status: " in output


def test_plan_adapter_states_execution_is_not_permitted() -> None:
    output = shell_plan("check git status")
    assert "execution_permitted: false" in output
    assert "read_only: true" in output


def test_prepare_adapter_labels_output_as_not_executed() -> None:
    output = shell_prepare("read the file README.md")
    assert "executed: false" in output
    assert "NOT EXECUTED" in output


def test_prepare_adapter_blocks_rather_than_guesses() -> None:
    output = shell_prepare("qwertyuiop")
    assert "status: BLOCKED" in output


def test_history_adapter_reports_insufficient_when_empty() -> None:
    output = shell_history()
    assert "status: INSUFFICIENT" in output
    assert "persistence: in-memory only" in output


def test_next_adapter_reports_an_action() -> None:
    output = shell_next("read the file README.md")
    assert "tool: mcquest_shell_next" in output
    assert "action: OBSERVE" in output
    assert "execution_permitted: false" in output


def test_next_adapter_refuses_a_blind_retry() -> None:
    shell_prepare("read the file README.md")
    output = shell_next("check git status", last_command="git status")
    assert "action: " in output
    assert "executed: false" in output


# --- registration (A11/A12) -------------------------------------------------

def test_exactly_four_p5_tools_are_registered() -> None:
    names = _live_names()
    assert len(names) == 34
    for name in P5_TOOLS:
        assert name in names


def test_p5_tools_declare_read_only_docstrings() -> None:
    for tool in asyncio.run(mcp.list_tools()):
        if tool.name in P5_TOOLS:
            assert "READ ONLY" in (tool.description or "")


def test_p5_tool_parameters_all_have_descriptions() -> None:
    for tool in asyncio.run(mcp.list_tools()):
        if tool.name in P5_TOOLS:
            for name, schema in tool.input_schema["properties"].items():
                description = schema.get("description")
                assert isinstance(description, str) and description.strip(), name


def test_registry_and_live_server_agree() -> None:
    from mcquest_mcp.shell import capabilities as registry

    assert sorted(registry.capability_names()) == _live_names()


def test_planned_and_live_tools_are_disjoint() -> None:
    from mcquest_mcp.shell import capabilities as registry

    planned = set(registry.planned_capability_names())
    assert planned.isdisjoint(set(_live_names()))
    assert planned.isdisjoint(set(registry.capability_names()))


def test_p5_tools_are_implemented_shell_capabilities() -> None:
    from mcquest_mcp.shell import capabilities as registry

    rows = {row.name: row for row in registry.CAPABILITIES}
    for name in P5_TOOLS:
        assert rows[name].status is registry.CapabilityStatus.IMPLEMENTED
        assert rows[name].phase == "P5"
        assert rows[name].execution == registry.EXECUTION_NONE
        assert rows[name].read_only is True


def test_p5_adds_no_execution_capability() -> None:
    from mcquest_mcp.shell import capabilities as registry

    rows = {row.name: row for row in registry.CAPABILITIES}
    for name in P5_TOOLS:
        assert rows[name].execution == registry.EXECUTION_NONE
        assert rows[name].mutation_cost is None
