"""P2 MCP-adapter tests: the four ``mcquest_shell_*`` tools (test-plan §5–§6, §12).

Verifies tool names and schemas, summary-first bounded output, byte-identical
repeats, read-only behaviour, the absence of arbitrary execution (only the
approved fixed-argv probes may run), shared-store reuse across tools, and the
terminal/context guarantees: server identity separated from the client
terminal, unknown cold start, no fabricated client CWD, restart semantics.
"""

from __future__ import annotations

import asyncio

import pytest

from mcquest_mcp.server import mcp
from mcquest_mcp.shell import environment
from mcquest_mcp.security import project_root
from mcquest_mcp.tools.shell_env import (
    shell_capabilities,
    shell_context,
    shell_environment,
    shell_terminal,
)

from test_shell_environment import (
    APPROVED_ARGVS,
    DEFAULT_PATHS,
    install_probe_mock,
)

TOOLS = (
    "mcquest_shell_capabilities",
    "mcquest_shell_context",
    "mcquest_shell_environment",
    "mcquest_shell_terminal",
)

DECLARED = {
    "client_session": "A",
    "client_process_id": "1",
    "client_cwd": str(project_root()),
    "client_shell": "PowerShell",
    "client_shell_version": "5.1.26100.9444",
}


@pytest.fixture(autouse=True)
def _clean_store() -> None:
    environment.reset_store()
    yield
    environment.reset_store()


_RECORDED: list = []


@pytest.fixture(autouse=True)
def _probes(monkeypatch) -> list:
    """Every probe is mocked — no test executes a real subprocess."""
    global _RECORDED
    _RECORDED = install_probe_mock(monkeypatch)
    return _RECORDED


def _recorded_calls() -> list:
    return _RECORDED


def _tool(name: str):
    return next(tool for tool in asyncio.run(mcp.list_tools()) if tool.name == name)


def _assert_bounded(text: str) -> None:
    assert len(text) <= 4000, f"default budget exceeded: {len(text)}"
    for line in text.splitlines():
        assert len(line) <= 200, line
    assert text.startswith("[SUMMARY]")
    assert "\n[EVIDENCE]\n" in text


def test_four_shell_tools_are_registered_with_read_only_docstrings() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    for name in TOOLS:
        assert name in names, name
    for name in TOOLS:
        tool = _tool(name)
        assert tool.description.startswith("READ ONLY."), name
        properties = tool.input_schema.get("properties", {})
        for param, spec in properties.items():
            assert spec.get("description", "").strip(), (name, param)
        assert tool.input_schema.get("required", []) == [], name


def test_declared_input_schemas_are_optional_strings() -> None:
    for name in (
        "mcquest_shell_environment",
        "mcquest_shell_terminal",
        "mcquest_shell_context",
    ):
        properties = _tool(name).input_schema["properties"]
        assert set(properties) == {
            "client_session",
            "client_process_id",
            "client_cwd",
            "client_shell",
            "client_shell_version",
        }
        for spec in properties.values():
            assert spec["type"] == "string"
            assert spec["default"] == ""


def test_capabilities_schema_is_paged_and_bounded() -> None:
    properties = _tool("mcquest_shell_capabilities").input_schema["properties"]
    assert set(properties) == {"offset", "max_results"}
    assert properties["offset"]["default"] == 0
    assert properties["max_results"]["default"] == 10
    assert "1-10" in properties["max_results"]["description"]


def test_environment_output_shape_and_read_only_summary() -> None:
    output = shell_environment()
    _assert_bounded(output)
    assert "\n[END]" in output
    assert "read_only: true" in output
    assert "degraded: true" in output  # nothing declared → degraded mode (E1)
    assert "PROBE CONTRACT" in output
    assert "fixed argv lists, shell=False" in output


def test_environment_never_claims_execution_or_verification() -> None:
    for output in (
        shell_environment(),
        shell_terminal(),
        shell_context(),
        shell_capabilities(),
    ):
        lowered = output.lower()
        assert "was executed" not in lowered
        assert "executed by" not in lowered
        assert "verified by" not in lowered


def test_environment_repeats_are_byte_identical() -> None:
    assert shell_environment() == shell_environment()
    assert shell_terminal() == shell_terminal()
    assert shell_context() == shell_context()
    assert shell_capabilities() == shell_capabilities()


def test_environment_reports_machine_probes_with_provenance() -> None:
    output = shell_environment()
    assert "environment.version.git:" in output
    assert "environment.version.node:" in output
    assert "environment.version.powershell: 5.1.26100.9444" in output
    assert "SERVER_OBSERVED/trusted" in output
    assert "environment.baseline.powershell: ps5.1" in output
    assert "environment.version.pwsh: 7.6.2" in output
    assert "environment.baseline.pwsh: ps7" in output
    assert "subject=mcp_server" in output  # machine capability labeling (S2/E5)


def test_environment_unknown_is_not_a_warning() -> None:
    output = shell_environment()
    assert "WARNING" not in output
    assert "ERROR" not in output


def test_environment_with_no_executables_reports_unknown_not_failure(
    monkeypatch,
) -> None:
    install_probe_mock(monkeypatch, paths={})
    output = shell_environment()
    _assert_bounded(output)
    assert "environment.which.git: unknown" in output
    assert "UNKNOWN/untrusted" in output


def test_terminal_cold_start_separates_server_from_client() -> None:
    output = shell_terminal()
    _assert_bounded(output)
    assert "SERVER PROCESS (subject=mcp_server - never the client terminal)" in output
    assert "CLIENT TERMINAL (CLIENT_DECLARED only; unknown when not declared)" in output
    assert "terminal.cwd: unknown | UNKNOWN/untrusted" in output
    assert "note: " + environment.DIRECTIVE_MULTI_TERMINAL in output


def test_terminal_never_fabricates_client_cwd_from_server_cwd() -> None:
    output = shell_terminal()
    server_cwd = environment.server_process_facts(environment.get_store())[0].value
    assert f"terminal.cwd: {server_cwd} | SERVER_OBSERVED/trusted" in output
    assert "terminal.cwd: unknown | UNKNOWN/untrusted" in output
    assert environment.DIRECTIVE_EXPLICIT_PATH in output


def test_terminal_declared_identity_is_labeled_and_corroborated() -> None:
    output = shell_terminal(**DECLARED)
    assert "terminal.cwd: " + str(project_root()) in output
    assert "CLIENT_DECLARED/corroborated" in output
    assert "terminal.shell: PowerShell" in output
    assert "terminal.session_id: A" in output


def test_terminal_declared_cwd_outside_root_stays_untrusted() -> None:
    output = shell_terminal(
        client_session="A", client_process_id="1", client_cwd="C:\\outside\\repo"
    )
    assert "terminal.cwd: C:\\outside\\repo | CLIENT_DECLARED/untrusted" in output
    assert "note: " + environment.DIRECTIVE_EXPLICIT_PATH in output


def test_two_declared_sessions_never_share_facts() -> None:
    shell_terminal(client_session="A", client_process_id="1", client_cwd="C:\\outside")
    other = shell_terminal(client_session="B", client_process_id="2")
    assert "C:\\outside" not in other
    assert "terminal.cwd: unknown | UNKNOWN/untrusted" in other


def test_restart_after_reset_reports_unknown() -> None:
    first = shell_terminal(client_session="A", client_process_id="1", client_cwd="C:\\marker\\only")
    assert "C:\\marker\\only" in first
    environment.reset_store()  # server restart discards SESSION/PROCESS facts (S3)
    after = shell_terminal(client_session="A", client_process_id="1")
    assert "C:\\marker\\only" not in after
    assert "terminal.cwd: unknown | UNKNOWN/untrusted" in after


def test_context_contains_the_required_sections() -> None:
    output = shell_context()
    _assert_bounded(output)
    for heading in (
        "REPOSITORY",
        "WORKTREE",
        "SERVER PROCESS (subject=mcp_server - not the client terminal)",
        "CLIENT TERMINAL (declared inputs only; unknown when not declared)",
        "ENVIRONMENT (machine capability - never the client's shell)",
        "FRESHNESS / TRUST",
        "UNKNOWNS",
        "DIRECTIVES",
    ):
        assert heading in output, heading


def test_context_states_worktree_is_unknown_not_absent() -> None:
    output = shell_context()
    assert "worktree: unknown - no WORKTREE-scoped observation exists in P2" in output


def test_context_lists_explicit_unknowns_without_warning_severity() -> None:
    output = shell_context()
    assert "UNKNOWNS" in output
    assert "terminal.cwd: unknown" in output
    assert "trust: trusted=" in output
    assert "freshness: STATIC=" in output
    assert "WARNING" not in output
    assert "ERROR" not in output


def test_context_carries_no_confidence_or_wall_clock_content() -> None:
    output = shell_context()
    lowered = output.lower()
    assert "confidence" not in lowered
    assert "ttl" not in lowered
    assert "expires" not in lowered
    assert "observed_at=" not in lowered  # no clock-dependent rendered content


def test_context_preserves_source_and_trust_for_declared_facts() -> None:
    output = shell_context(**DECLARED)
    assert "CLIENT_DECLARED/corroborated" in output
    assert "SERVER_OBSERVED/trusted" in output


def test_capabilities_tool_summary_names_the_authority() -> None:
    output = shell_capabilities()
    _assert_bounded(output)
    assert "implemented: 34" in output
    assert "planned: 0" in output
    assert "authority: EXPECTED_TOOLS" in output
    assert "total: 34" in output
    assert "has_more: true" in output
    assert "next_offset: 10" in output
    assert "collection_complete: true" in output


def test_capabilities_tool_pages_cover_implemented_and_planned_rows() -> None:
    seen: list[str] = []
    offset = 0
    while True:
        output = shell_capabilities(offset=offset)
        _assert_bounded(output)
        seen.extend(
            line.split(" | ")[0][2:]
            for line in output.splitlines()
            if line.startswith("- ")
        )
        if "has_more: true" not in output:
            break
        offset = int(
            next(
                line.split(": ")[1]
                for line in output.splitlines()
                if line.startswith("next_offset: ")
            )
        )
    assert len(seen) == 34
    assert len(set(seen)) == 34
    assert "mcquest_shell_environment" in seen
    assert "mcquest_shell_validate" in seen  # implemented at P4
    assert "mcquest_shell_observe" in seen  # implemented at P4
    assert "mcquest_shell_plan" in seen  # implemented at P5
    assert "mcquest_shell_next" in seen  # implemented at P5


def test_capabilities_tool_advertises_nothing_as_planned_after_p5() -> None:
    # P5 completed the approved ten-tool surface: no row may still be rendered
    # under the PLANNED / NOT EXECUTABLE heading.
    output = shell_capabilities(offset=34, max_results=10)
    assert "PLANNED - NOT REGISTERED / NOT IMPLEMENTED / NOT EXECUTABLE" not in output
    assert "status=PLANNED" not in output
    assert "has_more: false" in output


def test_only_approved_fixed_argvs_are_ever_executed() -> None:
    shell_environment()
    shell_terminal()
    shell_context()
    shell_capabilities()
    calls = _recorded_calls()
    assert calls, "expected the approved probes to run"
    for argv, _kwargs in calls:
        assert tuple(argv) in APPROVED_ARGVS, argv
    command_argvs = [
        argv for argv, _kwargs in calls if "-Command" in argv
    ]
    for argv in command_argvs:
        assert tuple(argv) == environment.POWERSHELL_VERSION_ARGV


def test_terminal_and_capabilities_tools_never_probe() -> None:
    shell_terminal(**DECLARED)
    shell_capabilities()
    assert _recorded_calls() == []


def test_shared_store_prevents_reprobe_across_tools() -> None:
    shell_environment()
    after_environment = len(_recorded_calls())
    assert after_environment > 0
    shell_context()
    assert len(_recorded_calls()) == after_environment  # reused, not repeated


def test_environment_degraded_is_false_once_cwd_is_declared() -> None:
    output = shell_environment(**DECLARED)
    assert "degraded: false" in output
    assert "CLIENT_DECLARED/corroborated" in output
