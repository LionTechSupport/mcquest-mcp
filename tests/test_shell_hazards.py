"""P3 stale-variable and exception-unsafe primitive tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.hazards import (
    MAX_INPUT_CHARS,
    HazardCode,
    analyze_stale_variables,
)


def test_failed_assignment_followed_by_dependent_output_is_flagged() -> None:
    result = analyze_stale_variables(
        "$bytes = [IO.File]::ReadAllBytes($p)\n"
        "$count = $bytes.Length\n"
        'Write-Output "$p $count"'
    )
    assert [hazard.code for hazard in result.hazards] == [HazardCode.STALE_VARIABLE]
    hazard = result.hazards[0]
    assert hazard.variable == "bytes"
    assert hazard.consumer_position > hazard.assignment_position


def test_get_content_assignment_and_later_consumer_are_flagged() -> None:
    result = analyze_stale_variables(
        "$text = Get-Content notes.txt\nWrite-Output $text"
    )
    assert result.hazards[0].code is HazardCode.STALE_VARIABLE


def test_guarded_try_catch_with_fail_fast_is_not_flagged() -> None:
    result = analyze_stale_variables(
        "try {\n"
        "  $bytes = [IO.File]::ReadAllBytes($p)\n"
        "  Write-Output $bytes.Length\n"
        "} catch {\n"
        "  throw\n"
        "}"
    )
    assert result.hazards == ()


def test_clearing_variable_before_risky_assignment_prevents_stale_value_hazard() -> None:
    result = analyze_stale_variables(
        "$bytes = $null\n"
        "$bytes = [IO.File]::ReadAllBytes($p)\n"
        "Write-Output $bytes.Length"
    )
    assert result.hazards == ()


def test_independent_operations_have_no_hazard() -> None:
    result = analyze_stale_variables(
        "$a = [IO.File]::ReadAllBytes($aPath)\n"
        "$b = [IO.File]::ReadAllBytes($bPath)\n"
        "Write-Output 'done'"
    )
    assert result.hazards == ()


def test_comments_and_strings_do_not_create_hazard_relationships() -> None:
    result = analyze_stale_variables(
        "# $x = ReadAllBytes($p)\n"
        "Write-Output '$x = [IO.File]::ReadAllBytes($p)'\n"
        "Write-Output 'done'"
    )
    assert result.hazards == ()


def test_hazard_analysis_is_deterministic_and_bounded() -> None:
    command = "$x = Get-Content a\nWrite-Output $x"
    assert analyze_stale_variables(command) == analyze_stale_variables(command)
    with pytest.raises(ValueError, match="maximum"):
        analyze_stale_variables("x" * (MAX_INPUT_CHARS + 1))


def test_hazard_primitive_is_not_a_validation_report() -> None:
    result = analyze_stale_variables("$x = Get-Content a\nWrite-Output $x")
    assert not hasattr(result, "sections")
    assert "[SUMMARY]" not in repr(result)
