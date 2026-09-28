"""Validation / lint orchestrator (contract §16; architecture §7.8; P4).

Composes every P3 analysis primitive into ONE deterministic report whose
composition order is the contract §16 rule 3 frozen section order. This module
is orchestration only:

- it never executes the analysed command, never mutates state, and never
  repairs anything (contract §14, decision A13);
- it never lowers a verdict to make a command pass (architecture §7.8);
- it never plans, selects, or routes a command — that is P5, not P4.

Deliberate P4 responsibility — destructive-command detection
-----------------------------------------------------------
The post-P3 smoke test established that ``Remove-Item -Recurse -Force ./build``
classifies as ``BUILD`` with ``is_mutation_bearing(BUILD) is False``, because
the frozen contract §13 operation vocabulary has no ``DELETE`` member.

P4 therefore does **not** treat ``is_mutation_bearing(op) is False`` as proof
that a command is non-mutating. The frozen vocabulary is left untouched: this
module adds its own bounded, lexical destructive-pattern evidence which is
reported in the Mutation section, independently of the operation
classification.

Deliberately absent (approved decisions, not omissions):
- no numeric confidence and no numeric risk score (contract §7 rule 4);
- no wall-clock TTL (decision A5) — ``observed_at`` is never rendered;
- no second Fact/Observation/store/registry (architecture §5.1, §7.7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from . import dialect, encoding, hazards, hygiene, native, operations, parse, redundancy
from .facts import VALUE_UNKNOWN, Fact
from .redundancy import ChangeReason, RedundancyResult
from .store import ObservationStore

MAX_INPUT_CHARS = 16_384

# The contract §16 rule 3 frozen section order. Composition order IS this
# order; it is not a display preference and is asserted by the P4 tests.
FROZEN_SECTIONS: tuple[str, ...] = (
    "Syntax",
    "Parse completeness",
    "Shell dialect",
    "Native boundary",
    "CWD",
    "Path safety",
    "Redundancy",
    "Operation",
    "Mutation",
    "Encoding",
    "Failure propagation",
    "Stale-variable hazard",
    "Cost",
    "Capability duplication",
    "Recommendation",
)

# Modes. ``lint`` is a MODE of this single analyzer (decision A11); there is no
# separate lint tool (test-plan RT8).
MODE_VALIDATE = "validate"
MODE_LINT = "lint"
MODES: tuple[str, ...] = (MODE_VALIDATE, MODE_LINT)

# Redundancy is only fully evaluated when the caller supplies the
# known/declared repository root (P3 limitation 3, recorded in 05-V0.9-STATE).
SECTION_UNKNOWN_ROOT = (
    "repository root not supplied; n3 root-prefix removal not evaluated"
)


class Verdict(str, Enum):
    """The four contract §16 rule 4 verdict tokens, and nothing else."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    PASS = "PASS"

    def __str__(self) -> str:
        return str(self.value)


ERROR = Verdict.ERROR
WARNING = Verdict.WARNING
INFO = Verdict.INFO
PASS = Verdict.PASS

_SEVERITY_RANK: dict[Verdict, int] = {
    Verdict.PASS: 0,
    Verdict.INFO: 1,
    Verdict.WARNING: 2,
    Verdict.ERROR: 3,
}

# --- P4 destructive-pattern evidence (bounded, lexical, deterministic) -------
# These patterns are P4's own validation evidence for the Mutation section.
# They are NOT an extension of the frozen §13 operation vocabulary: no DELETE
# operation is invented and operations.py is never modified. A match only
# raises severity; it never selects, plans, or executes anything.

_DESTRUCTIVE_RECURSIVE = re.compile(
    r"\b(?:remove-item|rm|rmdir|del|erase|rd)\b", re.IGNORECASE
)
_DESTRUCTIVE_ROOT_TARGET = re.compile(
    r"(?:^|[\s\"'])(?:[a-z]:[\\/]?\*?|/)\s*$", re.IGNORECASE
)

# State mutations hygiene.py does not report (a P3 gap recorded in the P4 phase
# record); P4 surfaces them so the Mutation section is complete.
_P4_STATE_MUTATION: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bset-content\b", re.IGNORECASE), "SET_CONTENT_WRITE"),
    (re.compile(r"\badd-content\b", re.IGNORECASE), "ADD_CONTENT_WRITE"),
    (re.compile(r"\bnew-item\b", re.IGNORECASE), "NEW_ITEM_CREATE"),
    (re.compile(r"\bout-file\b", re.IGNORECASE), "OUT_FILE_WRITE"),
    (re.compile(r"\bmove-item\b", re.IGNORECASE), "MOVE_ITEM"),
    (re.compile(r"\brename-item\b", re.IGNORECASE), "RENAME_ITEM"),
    (re.compile(r"\bcopy-item\b", re.IGNORECASE), "COPY_ITEM"),
    (re.compile(r"\bclear-content\b", re.IGNORECASE), "CLEAR_CONTENT"),
    (re.compile(r"\bremove-variable\b", re.IGNORECASE), "REMOVE_VARIABLE"),
    (
        re.compile(
            r"\bgit\b[^\n;]*\b(?:reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s)",
            re.IGNORECASE,
        ),
        "GIT_DESTRUCTIVE",
    ),
    (
        re.compile(r"\bgit\b[^\n;]*\bpush\b[^\n;]*\s(?:--force|-f)\b", re.IGNORECASE),
        "GIT_FORCE_PUSH",
    ),
)

# Redirections are state-changing; a trailing operator with no target is a
# parse concern instead and is deliberately not counted as a write here.
_REDIRECTION = re.compile(r"(?<![0-9])>>?")
_RECURSE_FORCE_FLAG = re.compile(r"\s-(?:recurse|force)\b", re.IGNORECASE)
_DYNAMIC_EVALUATION = re.compile(
    r"\b(?:invoke-expression|iex|start-process)\b", re.IGNORECASE
)



@dataclass(frozen=True)
class ValidationFinding:
    """One bounded finding: verdict, message, and location.

    Severity is proportional to evidence (contract §16 rule 5) and describes
    V0.9's analysis only, never a measured runtime fact (§18 rule 6).
    """

    code: str
    verdict: Verdict
    message: str
    position: int | None = None

    def sort_key(self) -> tuple[int, str, str]:
        position = self.position if self.position is not None else -1
        return (position, self.code, self.message)


@dataclass(frozen=True)
class Section:
    """One frozen-order section: a heading plus its findings."""

    name: str
    findings: tuple[ValidationFinding, ...]

    @property
    def verdict(self) -> Verdict:
        """The section verdict is the strongest finding it carries."""
        if not self.findings:
            return Verdict.PASS
        return max((f.verdict for f in self.findings), key=lambda v: _SEVERITY_RANK[v])


@dataclass(frozen=True)
class ValidationReport:
    """The complete deterministic validation result.

    No field here is a numeric confidence or a numeric risk score, and none of
    them depends on wall-clock time (contract §7 rule 4, decision A5).
    """

    command: str
    mode: str
    sections: tuple[Section, ...]
    operation: operations.Operation
    duplicate: bool
    change_reasons: tuple[ChangeReason, ...]

    @property
    def findings(self) -> tuple[ValidationFinding, ...]:
        ordered: list[ValidationFinding] = []
        for section in self.sections:
            ordered.extend(sorted(section.findings, key=ValidationFinding.sort_key))
        return tuple(ordered)

    @property
    def counts(self) -> dict[str, int]:
        """Findings per verdict token. INFO is counted; it is not a warning."""
        tally = {verdict.value: 0 for verdict in Verdict}
        for finding in self.findings:
            tally[finding.verdict.value] += 1
        return tally

    @property
    def overall(self) -> Verdict:
        """The report verdict is the strongest section verdict."""
        return max((s.verdict for s in self.sections), key=lambda v: _SEVERITY_RANK[v])

    @property
    def summary_verdict(self) -> str:
        """Contract §16 rule 4 summary token: ERROR / WARNINGS / PASS."""
        if self.overall is Verdict.ERROR:
            return "ERROR"
        if self.overall is Verdict.WARNING:
            return "WARNINGS"
        return "PASS"

    def section(self, name: str) -> Section:
        for candidate in self.sections:
            if candidate.name == name:
                return candidate
        raise KeyError(name)


def _bounded(text: str, *, label: str = "command") -> str:
    if not isinstance(text, str):
        raise TypeError(f"{label} must be str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"{label} exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return text


def normalize_mode(mode: str) -> str:
    """Exact mode match only; no aliases are inferred (A9 discipline)."""
    if not isinstance(mode, str):
        raise TypeError(f"mode must be str, got {type(mode).__name__}")
    candidate = mode.strip().lower()
    if candidate not in MODES:
        allowed = ", ".join(MODES)
        raise ValueError(f"mode must be one of: {allowed}")
    return candidate


def _destructive_findings(command: str) -> tuple[ValidationFinding, ...]:
    """P4's own bounded destructive-pattern evidence for the Mutation section.

    This is deliberately independent of the operation classification: a
    destructive lexical pattern raises severity even when
    ``is_mutation_bearing`` reports False for the classified operation.
    """
    findings: list[ValidationFinding] = []
    for match in _DESTRUCTIVE_RECURSIVE.finditer(command):
        findings.append(ValidationFinding(
            "DESTRUCTIVE_REMOVAL", Verdict.WARNING,
            "Removal pattern is irreversible; the frozen operation vocabulary has no "
            "DELETE class, so this is P4 validation evidence independent of it.",
            match.start(),
        ))
        if _DESTRUCTIVE_ROOT_TARGET.search(command):
            findings.append(ValidationFinding(
                "DESTRUCTIVE_ROOT_TARGET", Verdict.ERROR,
                "Removal target resolves to a volume or filesystem root; the blast "
                "radius exceeds the working tree.",
                match.start(),
            ))
        if _RECURSE_FORCE_FLAG.search(command):
            findings.append(ValidationFinding(
                "RECURSIVE_FORCED_REMOVAL", Verdict.ERROR,
                "Recursive/forced removal deletes a whole tree without confirmation.",
                match.start(),
            ))
    for match in _REDIRECTION.finditer(command):
        if command[match.end():].strip():
            findings.append(ValidationFinding(
                "OUTPUT_REDIRECTION_WRITE", Verdict.WARNING,
                "Redirection writes to the target and truncates it; the proposed text "
                "is analysed, never executed.",
                match.start(),
            ))
    for pattern, code in _P4_STATE_MUTATION:
        for match in pattern.finditer(command):
            findings.append(ValidationFinding(
                code, Verdict.WARNING,
                "State-changing construct; V0.9 analyses it and never executes it.",
                match.start(),
            ))
    return tuple(findings)


def _redundancy_section(
    store: ObservationStore,
    command: str,
    *,
    terminal_session: str | None,
    process_id: str | None,
    repository_root: str | None,
    change_reasons: tuple[ChangeReason, ...],
) -> tuple[Section, RedundancyResult]:
    """Redundancy section + the result the caller records.

    The store remains the single owner of command history (contract §20).
    """
    result = redundancy.analyze_redundancy(
        command,
        store,
        terminal_session=terminal_session,
        process_id=process_id,
        repository_root=repository_root,
        changed_reasons=change_reasons,
    )
    if result.duplicate:
        message = result.message
        if result.justified:
            message += f" (justified: {result.justification})"
        findings = (ValidationFinding("REDUNDANT_COMMAND", Verdict.WARNING, message, 0),)
    else:
        # A negative duplicate result states the levels checked, so novelty is
        # never implied (contract §20 rule 4).
        findings = (ValidationFinding("NO_DUPLICATE", Verdict.PASS, result.message, 0),)
    if repository_root is None:
        findings += (
            ValidationFinding("REDUNDANCY_PARTIAL", Verdict.INFO, SECTION_UNKNOWN_ROOT, 0),
        )
    return Section("Redundancy", findings), result


def _cost_class(text: str, operation: operations.Operation) -> str:
    """Deterministic qualitative cost label from documented lexical evidence."""
    if re.search(r"-recurse\b", text, re.IGNORECASE):
        return "HIGH"
    if re.search(r"\b(?:test-path|get-location)\b", text, re.IGNORECASE):
        return "TRIVIAL"
    if re.search(r"\bget-childitem\b|\bgit\b\s+(?:status|diff|log)", text, re.IGNORECASE):
        return "MEDIUM"
    if operation in {operations.Operation.READ_FILE, operations.Operation.READ_JSON}:
        return "LOW"
    if operation is operations.Operation.UNKNOWN:
        return "UNKNOWN"
    return "LOW"



def validate_command(
    command: str,
    store: ObservationStore,
    *,
    mode: str = MODE_VALIDATE,
    shell: str | None = None,
    shell_version: str | None = None,
    client_cwd: Fact | None = None,
    terminal_rendering: Fact | None = None,
    structured_source: Fact | None = None,
    terminal_session: str | None = None,
    process_id: str | None = None,
    repository_root: str | None = None,
    changed_reasons: tuple[ChangeReason, ...] = (),
) -> ValidationReport:
    """Compose every analyzer into one deterministic validation report.

    The proposed command is analysed only: it is never executed, never recorded
    as executed, and never used to choose a different command (contract §14).
    """
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    text = _bounded(command)
    effective_mode = normalize_mode(mode)
    if not isinstance(changed_reasons, tuple):
        raise TypeError("changed_reasons must be a tuple of ChangeReason")
    for label, fact in (
        ("client_cwd", client_cwd),
        ("terminal_rendering", terminal_rendering),
        ("structured_source", structured_source),
    ):
        if fact is not None and not isinstance(fact, Fact):
            raise TypeError(f"{label} must be Fact or None")

    sections: list[Section] = []

    # 1. Parse completeness is computed once and feeds both the Syntax and the
    #    Parse completeness sections; it is never recomputed per section.
    parsed = parse.analyze_parse(text)
    sections.append(Section(
        "Syntax",
        tuple(
            ValidationFinding(f.code, Verdict.ERROR, f.message, f.position)
            for f in parsed.findings
        ),
    ))

    if parsed.verdict is parse.ParseVerdict.INCOMPLETE:
        parse_findings: tuple[ValidationFinding, ...] = (
            ValidationFinding(
                "PARSE_INCOMPLETE", Verdict.WARNING,
                "COMMAND INCOMPLETE (DETECTED, heuristic) — parser incompleteness, "
                "never an execution failure (contract §22).",
                0,
            ),
        )
    elif parsed.verdict is parse.ParseVerdict.UNDETERMINED:
        parse_findings = (
            ValidationFinding(
                "PARSE_UNDETERMINED", Verdict.INFO,
                "UNDETERMINED — the construct is outside scanner capability.",
                0,
            ),
        )
    else:
        parse_findings = (
            ValidationFinding("PARSE_HEURISTIC", Verdict.PASS, str(parsed.verdict), 0),
        )
    sections.append(Section("Parse completeness", parse_findings))

    # 2. Shell dialect — P3 findings pass through unchanged (A8/S6: an unknown
    #    baseline is INFO, never WARNING).
    dialect_result = dialect.analyze_dialect(
        text, shell=shell, shell_version=shell_version
    )
    sections.append(Section(
        "Shell dialect",
        tuple(
            ValidationFinding(f.code, Verdict[f.severity], f.message, f.position)
            for f in dialect_result.findings
        ),
    ))

    # 3. Native boundary.
    native_findings: list[ValidationFinding] = []
    for boundary in native.analyze_native(text).boundaries:
        hazard_text = ", ".join(sorted(str(item) for item in boundary.hazards))
        message = f"native boundary '{boundary.executable}' ({hazard_text})"
        if boundary.nested_language:
            message += f"; nested language: {boundary.nested_language}"
        native_findings.append(ValidationFinding(
            "NATIVE_BOUNDARY", Verdict.WARNING, message, boundary.position
        ))
    sections.append(Section("Native boundary", tuple(native_findings)))

    # 4. CWD — UNKNOWN is preserved (decision S1) and is never a warning.
    cwd_unknown = client_cwd is None or client_cwd.value == VALUE_UNKNOWN
    if cwd_unknown:
        cwd_findings: tuple[ValidationFinding, ...] = (
            ValidationFinding(
                "CWD_UNKNOWN", Verdict.INFO,
                "CWD: unknown / source: UNKNOWN / trust: untrusted — use an explicit "
                "repository path (degraded mode, decision S1).",
                None,
            ),
        )
    else:
        cwd_findings = (
            ValidationFinding(
                "CWD_KNOWN", Verdict.PASS,
                f"CWD: {client_cwd.value} | {client_cwd.source}/{client_cwd.trust} "
                f"| {client_cwd.scope}/{client_cwd.freshness}",
                None,
            ),
        )
    sections.append(Section("CWD", cwd_findings))

    # 5. Path safety — relative-path dependence while the CWD is untrusted.
    path_findings: list[ValidationFinding] = []
    if cwd_unknown and re.search(
        r"(?:^|[\s|;=(])(?:\.{1,2}[\\/]|[A-Za-z0-9_-]+[\\/])", text
    ):
        path_findings.append(ValidationFinding(
            "RELATIVE_PATH_UNDECLARED_CWD", Verdict.WARNING,
            "Relative path depends on an undeclared or untrusted CWD.",
            None,
        ))
    if client_cwd is not None and str(client_cwd.trust) in {"untrusted", "unknown"}:
        path_findings.append(ValidationFinding(
            "CWD_NOT_TRUSTED", Verdict.INFO,
            f"CWD trust is {client_cwd.trust}; relative paths are not anchored.",
            None,
        ))
    sections.append(Section("Path safety", tuple(path_findings)))

    # 6. Redundancy (n0-n3 against the store-owned history).
    sections.append(_redundancy_section(
        store,
        text,
        terminal_session=terminal_session,
        process_id=process_id,
        repository_root=repository_root,
        change_reasons=changed_reasons,
    )[0])

    # 7. Operation.
    operation = operations.classify_operation(text)
    sections.append(Section(
        "Operation",
        (ValidationFinding(
            "OPERATION_CLASSIFIED", Verdict.PASS,
            f"operation: {operation.value}", 0,
        ),),
    ))

    # 8. Mutation — P4 destructive evidence PLUS P3 hygiene findings.
    #    `is_mutation_bearing(op) is False` is NEVER treated as proof of safety.
    mutation_findings: list[ValidationFinding] = list(_destructive_findings(text))
    for finding in hygiene.analyze_hygiene(text).findings:
        mutation_findings.append(ValidationFinding(
            finding.code, Verdict[finding.severity], finding.message, finding.position
        ))
    if operations.is_mutation_bearing(operation):
        mutation_findings.append(ValidationFinding(
            "OPERATION_MUTATION_BEARING", Verdict.WARNING,
            f"operation {operation.value} is mutation-bearing.", 0,
        ))
    if not mutation_findings:
        mutation_findings.append(ValidationFinding(
            "NO_MUTATION_EVIDENCE", Verdict.PASS,
            "No mutation or destructive pattern detected in the proposed text; a "
            "bounded lexical observation, not proof of safety.",
            0,
        ))
    sections.append(Section("Mutation", tuple(mutation_findings)))

    # 9. Encoding — documented applicability/severity is preserved verbatim.
    #    FILE_ENCODING_UNDECLARED stays INFO and is never escalated.
    encoding_result = encoding.analyze_encoding(
        text, terminal_rendering=terminal_rendering, structured_source=structured_source
    )
    sections.append(Section(
        "Encoding",
        tuple(
            ValidationFinding(f.code, Verdict[f.severity], f"[{f.stage}] {f.message}", None)
            for f in encoding_result.findings
        ),
    ))

    # 10. Failure propagation — dynamic evaluation hides its real effect.
    failure_findings: tuple[ValidationFinding, ...] = ()
    if _DYNAMIC_EVALUATION.search(text):
        failure_findings = (
            ValidationFinding(
                "DYNAMIC_EVALUATION", Verdict.WARNING,
                "Dynamic evaluation hides its real effect from static analysis; no "
                "operation or mutation claim can be made for what runs.",
                None,
            ),
        )
    sections.append(Section("Failure propagation", failure_findings))

    # 11. Stale-variable hazard.
    sections.append(Section(
        "Stale-variable hazard",
        tuple(
            ValidationFinding(
                hazard.code.value, Verdict.WARNING,
                f"${hazard.variable} may retain a previous value after a failed "
                "assignment; derived output is not authoritative (contract §18).",
                hazard.consumer_position,
            )
            for hazard in hazards.analyze_stale_variables(text).hazards
        ),
    ))

    # 12. Cost — qualitative class only; no numeric score is produced.
    sections.append(Section(
        "Cost",
        (ValidationFinding(
            "COST_CLASS", Verdict.PASS,
            f"cost: {_cost_class(text, operation)}; qualitative only, no numeric score.",
            0,
        ),),
    ))

    # 13. Capability duplication — a broad shell scan that recreates an existing
    #     MCQuest capability is flagged (contract §19 rule 5).
    duplication: tuple[ValidationFinding, ...] = ()
    if re.search(r"get-childitem\b[^\n|]*-recurse", text, re.IGNORECASE) and re.search(
        r"select-string|findstr", text, re.IGNORECASE
    ):
        duplication = (
            ValidationFinding(
                "CAPABILITY_DUPLICATION", Verdict.WARNING,
                "A recursive shell walk plus text search recreates an existing "
                "MCQuest search capability; V0.9 routes to that capability instead.",
                None,
            ),
        )
    sections.append(Section("Capability duplication", duplication))

    # 14. Recommendation — advice only; P4 never selects or prepares a command.
    analysis_verdict = max(
        (section.verdict for section in sections), key=lambda v: _SEVERITY_RANK[v]
    )
    if analysis_verdict is Verdict.ERROR:
        recommendation = ValidationFinding(
            "RECOMMENDATION", Verdict.INFO,
            "Resolve the ERROR findings before this command is considered. V0.9 "
            "recommends; Cline remains the execution authority.",
            None,
        )
    elif analysis_verdict is Verdict.WARNING:
        recommendation = ValidationFinding(
            "RECOMMENDATION", Verdict.INFO,
            "Review the WARNING findings; this is analysis, not enforcement, and no "
            "command was executed.",
            None,
        )
    else:
        recommendation = ValidationFinding(
            "RECOMMENDATION", Verdict.PASS,
            "No ERROR or WARNING evidence found by these bounded heuristics; this is "
            "not proof of correctness and no command was executed.",
            None,
        )
    sections.append(Section("Recommendation", (recommendation,)))

    if tuple(section.name for section in sections) != FROZEN_SECTIONS:
        raise AssertionError("section order must match the contract §16 frozen order")

    return ValidationReport(
        command=text,
        mode=effective_mode,
        sections=tuple(sections),
        operation=operation,
        duplicate=any(
            finding.code == "REDUNDANT_COMMAND"
            for section in sections
            for finding in section.findings
        ),
        change_reasons=changed_reasons,
    )
