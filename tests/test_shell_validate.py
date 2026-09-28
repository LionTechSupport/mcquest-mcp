"""P4 behavior tests: validation orchestration (contract §16; A11/A12).

Encodes the frozen report contract, the four verdict tokens, determinism, P3
finding aggregation, and the P4 destructive-command rule that a
non-mutation-bearing operation classification is never proof of safety.
"""

from __future__ import annotations

import pytest

from mcquest_mcp.shell import operations, validate
from mcquest_mcp.shell.facts import (
    EVIDENCE_CLIENT_DECLARED,
    Fact,
    Freshness,
    Scope,
    Source,
    Trust,
)
from mcquest_mcp.shell.redundancy import ChangeReason
from mcquest_mcp.shell.store import ObservationStore

# The post-P3 smoke-test regression command.
DESTRUCTIVE = "Remove-Item -Recurse -Force ./build"


@pytest.fixture()
def store() -> ObservationStore:
    return ObservationStore()


def _codes(report: validate.ValidationReport, section: str) -> set[str]:
    return {finding.code for finding in report.section(section).findings}


# --- frozen report shape (contract §16) -------------------------------------

def test_report_has_the_frozen_section_order(store: ObservationStore) -> None:
    report = validate.validate_command("git status", store)
    assert tuple(s.name for s in report.sections) == validate.FROZEN_SECTIONS
    assert validate.FROZEN_SECTIONS[0] == "Syntax"
    assert validate.FROZEN_SECTIONS[-1] == "Recommendation"
    assert "Mutation" in validate.FROZEN_SECTIONS


def test_report_uses_only_the_four_verdict_tokens(store: ObservationStore) -> None:
    report = validate.validate_command(DESTRUCTIVE, store)
    assert {v.value for v in validate.Verdict} == {"ERROR", "WARNING", "INFO", "PASS"}
    for section in report.sections:
        assert section.verdict in validate.Verdict
        for finding in section.findings:
            assert finding.verdict in validate.Verdict
    assert set(report.counts) == {"ERROR", "WARNING", "INFO", "PASS"}


def test_summary_verdict_tokens_follow_the_contract(store: ObservationStore) -> None:
    assert validate.validate_command(DESTRUCTIVE, store).summary_verdict == "ERROR"
    clean = validate.validate_command("Test-Path README.md", store)
    assert clean.summary_verdict in {"PASS", "WARNINGS"}


def test_repeated_validation_is_byte_identical(store: ObservationStore) -> None:
    assert validate.validate_command(DESTRUCTIVE, store) == validate.validate_command(
        DESTRUCTIVE, store
    )


# --- destructive / mutation rule (P4 authorization §6) ----------------------

def test_remove_item_recursive_force_is_not_a_pass(store: ObservationStore) -> None:
    """The documented P3 false negative must never become a PASS."""
    report = validate.validate_command(DESTRUCTIVE, store)
    assert report.overall is not validate.Verdict.PASS
    assert report.summary_verdict == "ERROR"
    assert "RECURSIVE_FORCED_REMOVAL" in _codes(report, "Mutation")


def test_mutating_false_is_not_treated_as_proof_of_safety(
    store: ObservationStore,
) -> None:
    operation = operations.classify_operation(DESTRUCTIVE)
    # The frozen P3 API still reports exactly what the smoke test observed...
    assert operation is operations.Operation.BUILD
    assert operations.is_mutation_bearing(operation) is False
    # ...and P4 must still refuse to call that command safe.
    report = validate.validate_command(DESTRUCTIVE, store)
    assert report.operation is operations.Operation.BUILD
    assert report.section("Mutation").verdict is validate.Verdict.ERROR


def test_p4_adds_no_delete_operation_to_the_frozen_vocabulary() -> None:
    assert "DELETE" not in {member.value for member in operations.Operation}
    assert {m.value for m in operations.MUTATION_BEARING_OPERATIONS} == {
        "INSTALL", "EDIT",
    }


def test_destructive_evidence_is_independent_of_the_operation_classifier(
    store: ObservationStore,
) -> None:
    for command in (
        "Remove-Item ./notes.txt",
        "rm -rf ./dist",
        "git reset --hard HEAD~1",
        "git push --force origin main",
    ):
        report = validate.validate_command(command, store)
        assert report.section("Mutation").verdict is not validate.Verdict.PASS, command


def test_read_only_command_raises_no_mutation_finding(store: ObservationStore) -> None:
    report = validate.validate_command("Test-Path README.md", store)
    assert report.section("Mutation").verdict is validate.Verdict.PASS
    assert "NO_MUTATION_EVIDENCE" in _codes(report, "Mutation")




# --- P3 finding aggregation --------------------------------------------------

def test_dialect_findings_are_aggregated(store: ObservationStore) -> None:
    report = validate.validate_command(
        "Get-Item x >nul", store, shell="powershell", shell_version="5.1"
    )
    assert "CMD_NULL_REDIRECTION" in _codes(report, "Shell dialect")


def test_unknown_baseline_is_info_not_warning(store: ObservationStore) -> None:
    report = validate.validate_command("git status; git diff", store)
    for finding in report.section("Shell dialect").findings:
        if finding.code == "UNKNOWN_BASELINE_CHAINING":
            assert finding.verdict is validate.Verdict.INFO


def test_native_boundary_findings_are_aggregated(store: ObservationStore) -> None:
    report = validate.validate_command('findstr /n /c:"loading" file.json', store)
    assert "NATIVE_BOUNDARY" in _codes(report, "Native boundary")


def test_parse_incompleteness_is_not_an_execution_failure(
    store: ObservationStore,
) -> None:
    report = validate.validate_command("Get-Content 'unterminated", store)
    assert "PARSE_INCOMPLETE" in _codes(report, "Parse completeness")
    message = next(
        f.message for f in report.section("Parse completeness").findings
        if f.code == "PARSE_INCOMPLETE"
    )
    assert "never an execution failure" in message


def test_parse_negative_verdict_is_labeled_heuristic(store: ObservationStore) -> None:
    report = validate.validate_command("git status", store)
    assert "PARSE_HEURISTIC" in _codes(report, "Parse completeness")
    # Never a claim of validity/completeness/proof (decision S4).
    for finding in report.findings:
        assert "proven" not in finding.message.lower()


def test_stale_variable_hazard_is_surfaced(store: ObservationStore) -> None:
    command = "$bytes = [IO.File]::ReadAllBytes($p)\n$len = $bytes.Length"
    report = validate.validate_command(command, store)
    assert "STALE_VARIABLE" in _codes(report, "Stale-variable hazard")


# --- redundancy (contract §20) ----------------------------------------------

def test_redundancy_reports_the_levels_checked(store: ObservationStore) -> None:
    report = validate.validate_command("git status", store)
    finding = next(
        f for f in report.section("Redundancy").findings if f.code == "NO_DUPLICATE"
    )
    assert "n0–n3 checked" in finding.message


def test_redundancy_detects_a_repeat_after_recording(store: ObservationStore) -> None:
    store.record_command("git status", terminal_session="s1", process_id="p1")
    report = validate.validate_command(
        "git status", store, terminal_session="s1", process_id="p1"
    )
    assert "REDUNDANT_COMMAND" in _codes(report, "Redundancy")
    assert report.duplicate is True


def test_justified_repeat_names_the_change_reason(store: ObservationStore) -> None:
    store.record_command("git status", terminal_session="s1", process_id="p1")
    report = validate.validate_command(
        "git status", store, terminal_session="s1", process_id="p1",
        changed_reasons=(ChangeReason.FILE,),
    )
    finding = next(
        f for f in report.section("Redundancy").findings if f.code == "REDUNDANT_COMMAND"
    )
    assert "justified: file" in finding.message


def test_missing_repository_root_is_reported_not_guessed(
    store: ObservationStore,
) -> None:
    report = validate.validate_command("git status", store)
    assert "REDUNDANCY_PARTIAL" in _codes(report, "Redundancy")


# --- encoding applicability / severity (P4 authorization §6) ---------------

def test_file_encoding_undeclared_is_info_not_escalated(
    store: ObservationStore,
) -> None:
    report = validate.validate_command("Get-Content -LiteralPath README.md", store)
    finding = next(
        f for f in report.section("Encoding").findings
        if f.code == "FILE_ENCODING_UNDECLARED"
    )
    assert finding.verdict is validate.Verdict.INFO
    assert report.counts["ERROR"] == 0
    assert report.summary_verdict == "PASS"


# --- provenance, UNKNOWN preservation, no numeric precision -----------------

def test_unknown_cwd_is_preserved_as_info(store: ObservationStore) -> None:
    report = validate.validate_command("git status", store)
    finding = next(
        f for f in report.section("CWD").findings if f.code == "CWD_UNKNOWN"
    )
    assert finding.verdict is validate.Verdict.INFO
    assert "trust: untrusted" in finding.message


def test_declared_cwd_keeps_its_provenance(store: ObservationStore) -> None:
    fact = Fact(
        observation="terminal.cwd",
        value="D:/repo",
        scope=Scope.PROCESS,
        observed_at="2026-01-01T00:00:00Z",
        source=Source.CLIENT_DECLARED,
        trust=Trust.CORROBORATED,
        freshness=Freshness.PROCESS,
        evidence=EVIDENCE_CLIENT_DECLARED,
        terminal_session="s1",
        process_id="p1",
    )
    report = validate.validate_command("git status", store, client_cwd=fact)
    finding = next(f for f in report.section("CWD").findings if f.code == "CWD_KNOWN")
    assert "CLIENT_DECLARED/corroborated" in finding.message
    assert "PROCESS/PROCESS" in finding.message


def test_relative_path_with_unknown_cwd_is_a_warning(store: ObservationStore) -> None:
    report = validate.validate_command("Get-Content ./README.md", store)
    assert "RELATIVE_PATH_UNDECLARED_CWD" in _codes(report, "Path safety")


def test_report_carries_no_numeric_confidence_or_risk(store: ObservationStore) -> None:
    names = set(validate.ValidationFinding.__dataclass_fields__)
    names |= set(validate.ValidationReport.__dataclass_fields__)
    assert not names & {"confidence", "risk", "score", "probability"}


def test_report_has_no_wall_clock_ttl_field(store: ObservationStore) -> None:
    names = set(validate.ValidationFinding.__dataclass_fields__)
    names |= set(validate.ValidationReport.__dataclass_fields__)
    assert not names & {"ttl", "expires_at", "expiry", "deadline", "observed_at"}


def test_validation_does_not_execute_or_mutate(store: ObservationStore) -> None:
    before = store.snapshot()
    validate.validate_command(DESTRUCTIVE, store)
    assert store.snapshot() == before
    # Analysis must not record the analysed command as history either.
    assert store.commands() == ()


def test_non_string_command_is_rejected(store: ObservationStore) -> None:
    with pytest.raises(TypeError):
        validate.validate_command(["git status"], store)  # type: ignore[arg-type]


def test_non_store_argument_is_rejected() -> None:
    with pytest.raises(TypeError):
        validate.validate_command("git status", object())  # type: ignore[arg-type]



def test_hygiene_findings_are_aggregated(store: ObservationStore) -> None:
    report = validate.validate_command("chcp 65001 >nul", store)
    assert "UNNECESSARY_CHCP" in _codes(report, "Mutation")


def test_dynamic_evaluation_is_flagged(store: ObservationStore) -> None:
    report = validate.validate_command("Invoke-Expression $cmd", store)
    assert "DYNAMIC_EVALUATION" in _codes(report, "Failure propagation")


def test_capability_duplication_is_flagged(store: ObservationStore) -> None:
    report = validate.validate_command(
        "Get-ChildItem -Recurse | Select-String loading", store
    )
    assert "CAPABILITY_DUPLICATION" in _codes(report, "Capability duplication")

def test_mutation_bearing_operation_is_still_reported(store: ObservationStore) -> None:
    report = validate.validate_command("npm install left-pad", store)
    assert "OPERATION_MUTATION_BEARING" in _codes(report, "Mutation")



def test_lint_is_a_mode_not_a_severity(store: ObservationStore) -> None:
    linted = validate.validate_command(DESTRUCTIVE, store, mode="lint")
    assert linted.mode == "lint"
    assert tuple(s.name for s in linted.sections) == validate.FROZEN_SECTIONS
    # lint must never soften the verdict (architecture §7.8).
    assert linted.overall is validate.validate_command(DESTRUCTIVE, store).overall


def test_unknown_mode_is_rejected(store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        validate.validate_command("git status", store, mode="lint-strict")


def test_inputs_are_bounded(store: ObservationStore) -> None:
    assert validate.validate_command("git status; " * 200, store).command
    with pytest.raises(ValueError):
        validate.validate_command("x" * (validate.MAX_INPUT_CHARS + 1), store)
