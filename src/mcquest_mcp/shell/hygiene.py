"""Terminal hygiene analysis (architecture §7.3; P3).

Analyzes documented continuation, environment-mutation, and repeated-setup
hazards in text or client-declared evidence. It never mutates a terminal and
never treats the MCP server process as the client's terminal (decision S2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .facts import VALUE_UNKNOWN, Fact, Source
from .terminal import SERVER_SUBJECT

MAX_INPUT_CHARS = 16_384

UNKNOWN = "UNKNOWN"
COMMAND_TEXT = "COMMAND_TEXT"
CLIENT_DECLARED = "CLIENT_DECLARED"


@dataclass(frozen=True)
class HygieneFinding:
    code: str
    severity: str
    message: str
    position: int


@dataclass(frozen=True)
class HygieneAnalysis:
    findings: tuple[HygieneFinding, ...]
    terminal_state_basis: str = UNKNOWN


def _mask(text: str) -> str:
    out = list(text)
    index = 0
    while index < len(text):
        if text[index] in {"'", '"'}:
            quote = text[index]
            out[index] = " "
            index += 1
            while index < len(text):
                current = text[index]
                out[index] = " "
                index += 1
                if current == quote:
                    break
        elif text[index] == "#":
            while index < len(text) and text[index] != "\n":
                out[index] = " "
                index += 1
        else:
            index += 1
    return "".join(out)


def analyze_hygiene(
    command: str,
    *,
    terminal_observation: Fact | None = None,
) -> HygieneAnalysis:
    """Return bounded hygiene findings; command text is never terminal state."""
    if not isinstance(command, str):
        raise TypeError(f"command must be str, got {type(command).__name__}")
    if len(command) > MAX_INPUT_CHARS:
        raise ValueError(f"command exceeds the maximum of {MAX_INPUT_CHARS} characters")
    if terminal_observation is not None and not isinstance(terminal_observation, Fact):
        raise TypeError("terminal_observation must be Fact or None")

    masked = _mask(command)
    findings: list[HygieneFinding] = []

    def add(code: str, severity: str, message: str, position: int) -> None:
        findings.append(HygieneFinding(code, severity, message, position))

    for match in re.finditer(r"\bchcp(?:\.exe)?\b", masked, re.IGNORECASE):
        add("UNNECESSARY_CHCP", "WARNING", "Console code-page mutation without demonstrated need.", match.start())
    locations = list(re.finditer(r"\b(?:set-location|cd)\b", masked, re.IGNORECASE))
    if len(locations) > 1:
        add("REPEATED_LOCATION_CHANGE", "WARNING", "Multiple location mutations in one proposed command.", locations[1].start())
    for match in re.finditer(r"\$env:[A-Za-z_][A-Za-z0-9_]*\s*=", masked, re.IGNORECASE):
        add("ENVIRONMENT_MUTATION", "WARNING", "Process environment mutation is global shell state.", match.start())
    for match in re.finditer(r"\bset-executionpolicy\b", masked, re.IGNORECASE):
        add("EXECUTION_POLICY_MUTATION", "WARNING", "Execution-policy state mutation.", match.start())
    for match in re.finditer(
        r"\bset-item\s+(?:env:|variable:|hk(?:cu|lm|ey_local_machine|ey_classes_root):)",
        masked,
        re.IGNORECASE,
    ):
        add("STATE_ITEM_MUTATION", "WARNING", "State mutation through Set-Item.", match.start())
    for match in re.finditer(r"\b(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b[^\n;]*(?:-command|-encodedcommand)\b", masked, re.IGNORECASE):
        add("NESTED_POWERSHELL_PROCESS", "WARNING", "Nested PowerShell process creation adds a distinct process scope.", match.start())
    if re.search(r"(?:\|\||&&|\||;|`)\s*$", masked):
        add("UNFINISHED_PIPELINE", "WARNING", "Proposed input ends with an unfinished operator.", len(masked.rstrip()))
    if command.strip() == ">>":
        add("TERMINAL_CONTINUATION", "WARNING", "Parser continuation prompt is unfinished input.", 0)

    basis = UNKNOWN
    if terminal_observation is not None and terminal_observation.subject != SERVER_SUBJECT:
        value = terminal_observation.value
        if (
            terminal_observation.source is Source.CLIENT_DECLARED
            and isinstance(value, str)
            and value != VALUE_UNKNOWN
        ):
            basis = CLIENT_DECLARED
            if ">>" in value or value.rstrip().endswith(("|", "`")):
                add("TERMINAL_CONTINUATION", "WARNING", "Client-declared terminal evidence shows continuation.", 0)
    if basis == UNKNOWN and any(finding.code in {"UNFINISHED_PIPELINE", "TERMINAL_CONTINUATION"} for finding in findings):
        basis = COMMAND_TEXT
    findings.sort(key=lambda item: (item.position, item.code))
    return HygieneAnalysis(tuple(findings), basis)
