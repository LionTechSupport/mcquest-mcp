"""Encoding/rendering separation analysis (architecture §7.1; P3).

Encoding is modelled as separate stages. Terminal rendering is never promoted
to source-file evidence, and this module neither changes console state nor runs
a command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .facts import VALUE_UNKNOWN, Fact, Freshness, Source, Trust
from .terminal import SERVER_SUBJECT

MAX_INPUT_CHARS = 16_384


@dataclass(frozen=True)
class EncodingFinding:
    code: str
    severity: str
    stage: str
    message: str
    source: Source | None = None
    trust: Trust | None = None
    freshness: Freshness | None = None


@dataclass(frozen=True)
class EncodingAnalysis:
    findings: tuple[EncodingFinding, ...]


def _usable(fact: Fact | None, *, exclude_server_subject: bool = False) -> bool:
    if fact is None or fact.source is Source.UNKNOWN or fact.value == VALUE_UNKNOWN:
        return False
    if not isinstance(fact.value, str):
        return False
    return not (exclude_server_subject and fact.subject == SERVER_SUBJECT)


def _looks_mojibake(text: str) -> bool:
    return any(marker in text for marker in ("Ã", "Â", "â€", "ðŸ", "�"))


def _command_mask(text: str) -> str:
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


def analyze_encoding(
    command: str,
    *,
    terminal_rendering: Fact | None = None,
    structured_source: Fact | None = None,
) -> EncodingAnalysis:
    """Report deterministic stage-specific hazards without inferring corruption."""
    if not isinstance(command, str):
        raise TypeError(f"command must be str, got {type(command).__name__}")
    if len(command) > MAX_INPUT_CHARS:
        raise ValueError(f"command exceeds the maximum of {MAX_INPUT_CHARS} characters")
    for label, fact in (("terminal_rendering", terminal_rendering), ("structured_source", structured_source)):
        if fact is not None and not isinstance(fact, Fact):
            raise TypeError(f"{label} must be Fact or None")

    findings: list[EncodingFinding] = []
    masked = _command_mask(command)
    if re.search(r"\bchcp(?:\.exe)?\b", masked, re.IGNORECASE):
        findings.append(EncodingFinding(
            "CONSOLE_CODEPAGE_CHANGE", "WARNING", "CONSOLE_CODEPAGE",
            "Console code page changes; this is not a file encoding fact.",
        ))
    if re.search(r"\bget-content\b", masked, re.IGNORECASE) and not re.search(
        r"(?:^|\s)-encoding(?:\s|=)", masked, re.IGNORECASE
    ):
        findings.append(EncodingFinding(
            "FILE_ENCODING_UNDECLARED", "INFO", "FILE_ENCODING",
            "Get-Content has no explicit file encoding.",
        ))

    terminal_usable = _usable(terminal_rendering, exclude_server_subject=True)
    source_usable = _usable(structured_source)
    if terminal_usable and _looks_mojibake(str(terminal_rendering.value)):
        fact = terminal_rendering
        if source_usable:
            findings.append(EncodingFinding(
                "SOURCE_RENDERING_MISMATCH", "WARNING", "TERMINAL_RENDERING",
                "Structured source evidence and terminal rendering disagree; the rendering is not evidence of source-file corruption.",
                fact.source, fact.trust, fact.freshness,
            ))
        else:
            findings.append(EncodingFinding(
                "RENDERING_MISMATCH_SUSPECTED", "WARNING", "TERMINAL_RENDERING",
                "Terminal rendering looks altered; no source-file corruption is established.",
                fact.source, fact.trust, fact.freshness,
            ))
    findings.sort(key=lambda item: (item.stage, item.code, item.message))
    return EncodingAnalysis(tuple(findings))
