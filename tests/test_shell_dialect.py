"""P3 PowerShell 5.1/7 and cross-shell dialect primitive tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.dialect import (
    MAX_INPUT_CHARS,
    PowerShellBaseline,
    analyze_dialect,
)


def _codes(command: str, *, version: str | None) -> tuple[str, ...]:
    result = analyze_dialect(
        command,
        shell="PowerShell",
        shell_version=version,
    )
    return tuple(finding.code for finding in result.findings)


def test_powershell_51_rejects_chaining_with_warning() -> None:
    result = analyze_dialect(
        "npm test && npm run build",
        shell="PowerShell",
        shell_version="5.1.26100.9444",
    )
    assert result.baseline is PowerShellBaseline.PS5_1
    assert any(
        f.code == "UNSUPPORTED_CHAINING" and f.severity == "WARNING"
        for f in result.findings
    )


def test_powershell_7_accepts_chaining_with_pass_finding() -> None:
    result = analyze_dialect(
        "npm test && npm run build",
        shell="PowerShell",
        shell_version="7.4.2",
    )
    assert result.baseline is PowerShellBaseline.PS7
    assert any(
        f.code == "SUPPORTED_CHAINING" and f.severity == "PASS"
        for f in result.findings
    )


def test_unknown_baseline_is_info_never_warning() -> None:
    result = analyze_dialect("npm test && npm run build", shell="PowerShell")
    assert result.baseline is PowerShellBaseline.UNKNOWN
    assert result.findings
    assert all(f.severity == "INFO" for f in result.findings)
    assert not any(f.severity == "WARNING" for f in result.findings)


@pytest.mark.parametrize("version", ["5.1", "7.4"])
def test_cmd_null_redirection_is_a_powershell_warning(version: str) -> None:
    result = analyze_dialect(
        "chcp 65001 >nul",
        shell="PowerShell",
        shell_version=version,
    )
    assert any(
        f.code == "CMD_NULL_REDIRECTION" and f.severity == "WARNING"
        for f in result.findings
    )


@pytest.mark.parametrize(
    "command",
    [
        "$x ? $y : $z",
        "$x ?? $fallback",
        "$x ??= $fallback",
        "1..8 | ForEach-Object -Parallel { $_ }",
    ],
)
def test_powershell_7_only_constructs_warn_on_51(command: str) -> None:
    assert "UNSUPPORTED_PS7_CONSTRUCT" in _codes(command, version="5.1.26100.9444")
    assert "UNSUPPORTED_PS7_CONSTRUCT" not in _codes(command, version="7.4.2")


def test_cmd_style_variable_is_known_cross_shell_mismatch() -> None:
    result = analyze_dialect("echo %PATH%", shell="PowerShell", shell_version="7.4")
    assert any(f.code == "CMD_ENV_SYNTAX" for f in result.findings)


def test_pure_powershell_command_has_no_dialect_finding() -> None:
    result = analyze_dialect(
        "Get-Content -LiteralPath README.md",
        shell="PowerShell",
        shell_version="7.4",
    )
    assert result.findings == ()


def test_dialect_analysis_ignores_quoted_and_commented_constructs() -> None:
    result = analyze_dialect(
        "Write-Output 'npm test && npm run build' # >nul",
        shell="PowerShell",
        shell_version="5.1",
    )
    assert result.findings == ()


def test_dialect_analysis_is_deterministic_and_bounded() -> None:
    kwargs = {"shell": "PowerShell", "shell_version": "7.4"}
    assert analyze_dialect("a && b", **kwargs) == analyze_dialect("a && b", **kwargs)
    with pytest.raises(ValueError, match="maximum"):
        analyze_dialect("x" * (MAX_INPUT_CHARS + 1), **kwargs)
