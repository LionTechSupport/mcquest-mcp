"""P3 terminal-hygiene analysis primitive tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.facts import Fact, Freshness, Scope, Source, Trust
from mcquest_mcp.shell.hygiene import MAX_INPUT_CHARS, analyze_hygiene
from mcquest_mcp.shell.terminal import SERVER_SUBJECT


def _client_terminal_fact(value: str) -> Fact:
    return Fact(
        observation="terminal.continuation",
        value=value,
        scope=Scope.EPHEMERAL,
        freshness=Freshness.EPHEMERAL,
        observed_at="2026-01-01T00:00:00Z",
        source=Source.CLIENT_DECLARED,
        trust=Trust.UNTRUSTED,
        evidence="declared by client; not verified",
        subject="continuation",
        terminal_session="client-a",
        process_id="42",
    )


def test_chcp_is_an_unnecessary_console_mutation() -> None:
    result = analyze_hygiene("chcp 65001 >nul")
    assert any(
        f.code == "UNNECESSARY_CHCP" and f.severity == "WARNING"
        for f in result.findings
    )


def test_repeated_location_changes_are_flagged() -> None:
    result = analyze_hygiene("Set-Location D:\\repo; Set-Location D:\\repo")
    assert any(f.code == "REPEATED_LOCATION_CHANGE" for f in result.findings)


def test_environment_execution_policy_and_state_mutation_are_flagged() -> None:
    result = analyze_hygiene(
        "$env:NAME = 'x'; Set-ExecutionPolicy Bypass; Set-Item Env:OTHER value"
    )
    codes = {finding.code for finding in result.findings}
    assert {
        "ENVIRONMENT_MUTATION",
        "EXECUTION_POLICY_MUTATION",
        "STATE_ITEM_MUTATION",
    } <= codes


def test_unnecessary_nested_powershell_process_is_flagged() -> None:
    result = analyze_hygiene("powershell.exe -NoProfile -Command Get-Date")
    assert any(f.code == "NESTED_POWERSHELL_PROCESS" for f in result.findings)


def test_continuation_prompt_is_hygiene_evidence() -> None:
    result = analyze_hygiene("Get-Content file.json |")
    assert any(f.code == "UNFINISHED_PIPELINE" for f in result.findings)
    assert result.terminal_state_basis == "COMMAND_TEXT"


def test_client_declared_continuation_fact_is_accepted_with_provenance() -> None:
    result = analyze_hygiene("", terminal_observation=_client_terminal_fact(">>"))
    finding = next(f for f in result.findings if f.code == "TERMINAL_CONTINUATION")
    assert finding.severity == "WARNING"
    assert result.terminal_state_basis == "CLIENT_DECLARED"


def test_server_process_state_is_never_used_as_client_terminal_state() -> None:
    server_fact = Fact(
        observation="terminal.continuation",
        value=">>",
        scope=Scope.PROCESS,
        freshness=Freshness.PROCESS,
        observed_at="2026-01-01T00:00:00Z",
        source=Source.SERVER_OBSERVED,
        trust=Trust.TRUSTED,
        evidence="server process fact",
        subject=SERVER_SUBJECT,
    )
    result = analyze_hygiene("", terminal_observation=server_fact)
    assert result.terminal_state_basis == "UNKNOWN"
    assert not any(f.code == "TERMINAL_CONTINUATION" for f in result.findings)


def test_unknown_declared_terminal_fact_stays_unknown() -> None:
    result = analyze_hygiene("", terminal_observation=_client_terminal_fact("unknown"))
    assert result.terminal_state_basis == "UNKNOWN"


def test_pure_read_has_no_hygiene_finding_and_actual_terminal_is_unknown() -> None:
    result = analyze_hygiene("Get-Content -LiteralPath README.md")
    assert result.findings == ()
    assert result.terminal_state_basis == "UNKNOWN"


def test_hygiene_is_deterministic_and_bounded() -> None:
    assert analyze_hygiene("chcp 65001") == analyze_hygiene("chcp 65001")
    with pytest.raises(ValueError, match="maximum"):
        analyze_hygiene("x" * (MAX_INPUT_CHARS + 1))
