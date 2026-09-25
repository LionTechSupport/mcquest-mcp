"""PowerShell 5.1/7 shell-dialect analysis (architecture §6.2; P3).

The analyzer is a bounded lexical primitive. It reports documented construct
characteristics only; it never claims that a command is valid for a shell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

MAX_INPUT_CHARS = 16_384


class PowerShellBaseline(str, Enum):
    """A8 baseline tags. UNKNOWN is never promoted to a known version."""

    UNKNOWN = "unknown"
    PS5_1 = "ps5.1"
    PS7 = "ps7"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class DialectFinding:
    """One deterministic dialect characteristic; severity is proportional."""

    code: str
    severity: str
    message: str
    position: int


@dataclass(frozen=True)
class DialectAnalysis:
    baseline: PowerShellBaseline
    findings: tuple[DialectFinding, ...]


def _bounded(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"command must be str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"command exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return text


def baseline_for(shell_version: str | None) -> PowerShellBaseline:
    """Derive an A8 baseline from an explicitly supplied client version."""
    if not shell_version:
        return PowerShellBaseline.UNKNOWN
    parts = shell_version.strip().split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else -1
    except (ValueError, IndexError):
        return PowerShellBaseline.UNKNOWN
    if major == 5 and minor == 1:
        return PowerShellBaseline.PS5_1
    if major >= 7:
        return PowerShellBaseline.PS7
    return PowerShellBaseline.UNKNOWN


def _code_mask(text: str) -> str:
    """Blank strings and comments while preserving offsets and newlines."""
    out = list(text)
    index = 0
    quote: str | None = None
    while index < len(text):
        char = text[index]
        if quote is not None:
            out[index] = " "
            if char == "\\" and quote == '"' and index + 1 < len(text):
                out[index + 1] = " "
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            out[index] = " "
            index += 1
            continue
        if char == "#":
            while index < len(text) and text[index] != "\n":
                out[index] = " "
                index += 1
            continue
        index += 1
    return "".join(out)


def analyze_dialect(
    command: str,
    *,
    shell: str | None = None,
    shell_version: str | None = None,
) -> DialectAnalysis:
    """Analyze known dialect constructs against a declared client baseline.

    Baseline-dependent rules emit INFO when the effective baseline is unknown
    (decision S6). No server or machine baseline is substituted for the
    client's shell.
    """
    text = _bounded(command)
    if shell is not None and not isinstance(shell, str):
        raise TypeError("shell must be str or None")
    if shell_version is not None and not isinstance(shell_version, str):
        raise TypeError("shell_version must be str or None")

    shell_name = (shell or "").strip().lower()
    powershell = shell_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    cmd = shell_name in {"cmd", "cmd.exe"}
    baseline = baseline_for(shell_version) if powershell else PowerShellBaseline.UNKNOWN
    masked = _code_mask(text)
    findings: list[DialectFinding] = []

    def add(code: str, severity: str, message: str, position: int) -> None:
        findings.append(DialectFinding(code, severity, message, position))

    null_redirect = masked.lower().find(">nul")
    if null_redirect >= 0 and not cmd:
        severity = "WARNING" if powershell else "INFO"
        add("CMD_NULL_REDIRECTION", severity, "CMD-style null redirection in PowerShell.", null_redirect)

    cmd_env = re.search(r"%[A-Za-z_][A-Za-z0-9_]*%", masked)
    if cmd_env and powershell:
        add("CMD_ENV_SYNTAX", "WARNING", "CMD-style environment expansion in PowerShell.", cmd_env.start())

    for match in re.finditer(r"&&|\|\|", masked):
        if cmd:
            continue
        if baseline is PowerShellBaseline.PS5_1:
            add("UNSUPPORTED_CHAINING", "WARNING", "Chaining requires a PowerShell 7 baseline.", match.start())
        elif baseline is PowerShellBaseline.PS7:
            add("SUPPORTED_CHAINING", "PASS", "Chaining is supported by the declared PowerShell 7 baseline.", match.start())
        else:
            add("UNKNOWN_BASELINE_CHAINING", "INFO", "The client shell baseline is unknown.", match.start())

    ps7 = re.search(
        r"\?\?=|\?\?|(?<!\S)\?(?=\s)|-parallel\b", masked, re.IGNORECASE
    )
    if ps7:
        if baseline is PowerShellBaseline.PS5_1:
            add("UNSUPPORTED_PS7_CONSTRUCT", "WARNING", "Construct requires a PowerShell 7 baseline.", ps7.start())
        elif baseline is not PowerShellBaseline.PS7:
            add("UNKNOWN_BASELINE_PS7_CONSTRUCT", "INFO", "The client shell baseline is unknown.", ps7.start())

    if cmd:
        for pattern, code in ((r"\$env:", "POWERSHELL_ENV_IN_CMD"), (r"\$\(", "POWERSHELL_SUBEXPRESSION_IN_CMD")):
            match = re.search(pattern, masked)
            if match:
                add(code, "WARNING", "PowerShell syntax was found in a declared CMD shell.", match.start())

    findings.sort(key=lambda item: (item.position, item.code))
    return DialectAnalysis(baseline, tuple(findings))
