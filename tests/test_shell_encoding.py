"""P3 encoding/rendering separation primitive tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.encoding import MAX_INPUT_CHARS, analyze_encoding
from mcquest_mcp.shell.facts import Fact, Freshness, Scope, Source, Trust
from mcquest_mcp.shell.terminal import SERVER_SUBJECT


def _fact(*, value: object, source: Source, subject: str | None = None) -> Fact:
    return Fact(
        observation="test.encoding",
        value=value,
        scope=Scope.FILE if subject is None else Scope.PROCESS,
        freshness=Freshness.WORKTREE if subject is None else Freshness.PROCESS,
        observed_at="2026-01-01T00:00:00Z",
        source=source,
        trust=Trust.TRUSTED if source is Source.SERVER_OBSERVED else Trust.UNTRUSTED,
        evidence="test evidence",
        subject=subject,
        terminal_session="client-a" if source is Source.CLIENT_DECLARED else None,
        process_id="42" if source is Source.CLIENT_DECLARED else None,
    )


def test_non_ascii_text_alone_is_not_reported_as_corruption() -> None:
    result = analyze_encoding("Write-Output 'පූරණය වෙමින්'")
    assert result.findings == ()


def test_mojibake_rendering_does_not_claim_source_corruption() -> None:
    result = analyze_encoding(
        "node read.js",
        terminal_rendering=_fact(
            value="Quiz Ã©Ã©", source=Source.CLIENT_DECLARED, subject="terminal"
        ),
    )
    assert any(f.code == "RENDERING_MISMATCH_SUSPECTED" for f in result.findings)
    assert not any("source corruption" in f.message.lower() for f in result.findings)


def test_structured_source_and_bad_rendering_are_kept_as_distinct_stages() -> None:
    result = analyze_encoding(
        "node read.js",
        terminal_rendering=_fact(
            value="Quiz Ã©Ã©", source=Source.CLIENT_DECLARED, subject="terminal"
        ),
        structured_source=_fact(
            value="Quiz පූරණය වෙමින්", source=Source.SERVER_OBSERVED
        ),
    )
    finding = next(f for f in result.findings if f.code == "SOURCE_RENDERING_MISMATCH")
    assert finding.stage == "TERMINAL_RENDERING"
    assert "not evidence of source-file corruption" in finding.message


def test_chcp_is_a_console_stage_mutation_not_file_encoding() -> None:
    result = analyze_encoding("chcp 65001")
    finding = next(f for f in result.findings if f.code == "CONSOLE_CODEPAGE_CHANGE")
    assert finding.stage == "CONSOLE_CODEPAGE"
    assert "file encoding" in finding.message


def test_get_content_without_encoding_is_an_explicit_info_hazard() -> None:
    result = analyze_encoding("Get-Content README.md")
    assert any(
        f.code == "FILE_ENCODING_UNDECLARED" and f.severity == "INFO"
        for f in result.findings
    )


def test_unknown_fact_is_not_promoted_to_evidence() -> None:
    result = analyze_encoding(
        "node read.js",
        terminal_rendering=_fact(value="unknown", source=Source.UNKNOWN),
    )
    assert not any(
        f.code == "RENDERING_MISMATCH_SUSPECTED" for f in result.findings
    )


def test_server_process_terminal_fact_is_not_client_evidence() -> None:
    result = analyze_encoding(
        "node read.js",
        terminal_rendering=_fact(
            value="Quiz Ã©", source=Source.SERVER_OBSERVED, subject=SERVER_SUBJECT
        ),
    )
    assert not any(
        f.code == "RENDERING_MISMATCH_SUSPECTED" for f in result.findings
    )


def test_encoding_analysis_is_deterministic_and_bounded() -> None:
    assert analyze_encoding("chcp 65001") == analyze_encoding("chcp 65001")
    with pytest.raises(ValueError, match="maximum"):
        analyze_encoding("x" * (MAX_INPUT_CHARS + 1))
