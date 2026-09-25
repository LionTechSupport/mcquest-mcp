"""P3 native-command boundary primitive tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.native import MAX_INPUT_CHARS, NativeHazard, analyze_native


def test_findstr_is_a_native_boundary_with_its_own_grammar() -> None:
    result = analyze_native('findstr /n /c:"loading" file.json')
    assert len(result.boundaries) == 1
    boundary = result.boundaries[0]
    assert boundary.executable == "findstr"
    assert NativeHazard.NATIVE_ARGUMENT_GRAMMAR in boundary.hazards


def test_quoted_wildcard_is_a_deterministic_boundary_hazard() -> None:
    result = analyze_native('findstr "*.json" src')
    assert NativeHazard.QUOTED_WILDCARD in result.boundaries[0].hazards


def test_node_inline_script_is_a_nested_javascript_boundary() -> None:
    result = analyze_native('node -e "console.log(1)"')
    boundary = result.boundaries[0]
    assert boundary.executable == "node"
    assert boundary.nested_language == "JavaScript"
    assert NativeHazard.NESTED_SCRIPT in boundary.hazards


def test_python_inline_script_is_a_nested_python_boundary() -> None:
    result = analyze_native('python -c "print(1)"')
    assert result.boundaries[0].nested_language == "Python"


def test_pure_cmdlet_is_not_misreported_as_native() -> None:
    result = analyze_native("Get-Content -LiteralPath README.md")
    assert result.boundaries == ()


def test_pipeline_and_redirection_are_boundary_risks() -> None:
    result = analyze_native("findstr loading src | Select-Object -First 5")
    hazards = result.boundaries[0].hazards
    assert NativeHazard.PIPELINE in hazards
    redirected = analyze_native("git status > status.txt")
    assert NativeHazard.REDIRECTION in redirected.boundaries[0].hazards


def test_multiple_native_boundaries_are_reported_in_source_order() -> None:
    result = analyze_native("git status; node script.js; python script.py")
    assert [b.executable for b in result.boundaries] == ["git", "node", "python"]


def test_native_analysis_is_deterministic_and_bounded() -> None:
    command = 'findstr /c:"x" file.txt | more'
    assert analyze_native(command) == analyze_native(command)
    with pytest.raises(ValueError, match="maximum"):
        analyze_native("x" * (MAX_INPUT_CHARS + 1))
