"""P3 bounded parse-completeness heuristic tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.parse import MAX_INPUT_CHARS, ParseVerdict, analyze_parse

INCOMPLETE = "INCOMPLETE (DETECTED, heuristic)"
NO_INCOMPLETENESS = "NO INCOMPLETENESS DETECTED (heuristic — NOT proof of completeness)"


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("Write-Output 'unterminated", "UNMATCHED_SINGLE_QUOTE"),
        ('Write-Output "unterminated', "UNMATCHED_DOUBLE_QUOTE"),
        ("Write-Output (1", "UNBALANCED_DELIMITER"),
        ("$x = [ordered]@{ a = 1", "UNBALANCED_DELIMITER"),
        ("Get-Content file |", "DANGLING_OPERATOR"),
        ("&& npm test", "LEADING_OPERATOR"),
        ("npm test `", "TRAILING_CONTINUATION"),
        ("npm test >", "DANGLING_REDIRECTION"),
        (">>", "CONTINUATION_PROMPT"),
        ("$value = @'\nunfinished", "UNTERMINATED_HERE_STRING"),
    ],
)
def test_documented_incomplete_constructs(command: str, code: str) -> None:
    result = analyze_parse(command)
    assert result.verdict.value == INCOMPLETE
    assert code in {finding.code for finding in result.findings}


def test_negative_heuristic_uses_exact_frozen_wording() -> None:
    result = analyze_parse("Get-Content -LiteralPath README.md")
    assert result.verdict.value == NO_INCOMPLETENESS
    assert "NOT proof" in result.verdict.value


def test_out_of_capability_dynamic_construct_is_undetermined() -> None:
    result = analyze_parse("Invoke-Expression $text")
    assert result.verdict is ParseVerdict.UNDETERMINED
    assert any(f.code == "OUT_OF_SCANNER_CAPABILITY" for f in result.findings)


def test_scanner_ignores_brackets_and_operators_inside_strings_and_comments() -> None:
    result = analyze_parse("Write-Output '[{ ( && >>' # (unclosed comment-looking text")
    assert result.verdict.value == NO_INCOMPLETENESS


def test_doubled_single_quote_is_escaped_not_unmatched() -> None:
    result = analyze_parse("Write-Output 'it''s fine'")
    assert result.verdict.value == NO_INCOMPLETENESS


def test_backslash_escaped_double_quote_is_accounted_for() -> None:
    result = analyze_parse('Write-Output "a\\"b"')
    assert result.verdict.value == NO_INCOMPLETENESS


def test_backtick_escaped_double_quote_is_accounted_for() -> None:
    result = analyze_parse('Write-Output "a`"b"')
    assert result.verdict.value == NO_INCOMPLETENESS


def test_incompleteness_takes_priority_over_undetermined_marker() -> None:
    result = analyze_parse("Invoke-Expression $text |")
    assert result.verdict.value == INCOMPLETE


def test_parse_results_are_deterministic_and_bounded() -> None:
    command = "Get-Content ("
    assert analyze_parse(command) == analyze_parse(command)
    with pytest.raises(ValueError, match="maximum"):
        analyze_parse("x" * (MAX_INPUT_CHARS + 1))


def test_frozen_verdict_vocabulary_never_claims_proof() -> None:
    assert {verdict.value for verdict in ParseVerdict} == {
        INCOMPLETE,
        NO_INCOMPLETENESS,
        "UNDETERMINED",
    }
    forbidden = {"VALID", "COMPLETE", "PROVEN", "SYNTAXALLY CORRECT"}
    assert all(verdict.value not in forbidden for verdict in ParseVerdict)
