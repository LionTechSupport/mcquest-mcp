"""Bounded parse-completeness heuristic (architecture §6.4; decisions A6/S4).

This is a lexical scanner, not a parser or shell interpreter. Its three
verdicts are frozen; the negative verdict is explicitly a bounded heuristic and
never a proof of completeness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

MAX_INPUT_CHARS = 16_384


class ParseVerdict(str, Enum):
    INCOMPLETE = "INCOMPLETE (DETECTED, heuristic)"
    NO_INCOMPLETENESS = (
        "NO INCOMPLETENESS DETECTED (heuristic — NOT proof of completeness)"
    )
    UNDETERMINED = "UNDETERMINED"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class ParseFinding:
    code: str
    message: str
    position: int


@dataclass(frozen=True)
class ParseAnalysis:
    verdict: ParseVerdict
    findings: tuple[ParseFinding, ...]
    heuristic: bool = True


def _bounded(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"command must be str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"command exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return text


def _scan(text: str) -> tuple[list[ParseFinding], str]:
    findings: list[ParseFinding] = []
    code = list(text)
    stack: list[tuple[str, int]] = []
    index = 0
    subexpression_start: int | None = None

    def blank(position: int) -> None:
        if position < len(code) and code[position] != "\n":
            code[position] = " "

    while index < len(text):
        if text.startswith("<#", index):
            end = text.find("#>", index + 2)
            for offset in range(index, len(text) if end < 0 else end + 2):
                blank(offset)
            if end < 0:
                findings.append(ParseFinding("UNTERMINATED_BLOCK_COMMENT", "Block comment is unterminated.", index))
                index = len(text)
            else:
                index = end + 2
            continue
        if text[index] == "#":
            while index < len(text) and text[index] != "\n":
                blank(index)
                index += 1
            continue
        if text.startswith("@'", index) or text.startswith('@"', index):
            marker = text[index + 1]
            terminator = f"\n{marker}@"
            end = text.find(terminator, index + 2)
            if end < 0:
                for offset in range(index, len(text)):
                    blank(offset)
                findings.append(ParseFinding("UNTERMINATED_HERE_STRING", "Here-string is unterminated.", index))
                index = len(text)
            else:
                for offset in range(index, end + len(terminator)):
                    blank(offset)
                index = end + len(terminator)
            continue
        char = text[index]
        if char == "'":
            index += 1
            while index < len(text):
                if text[index] == "'":
                    if index + 1 < len(text) and text[index + 1] == "'":
                        index += 2
                        continue
                    break
                blank(index)
                index += 1
            if index >= len(text):
                findings.append(ParseFinding("UNMATCHED_SINGLE_QUOTE", "Single-quoted string is unterminated.", len(text)))
            else:
                blank(index)
                index += 1
            continue
        if char == '"':
            index += 1
            while index < len(text):
                if text[index] == "\\" and index + 1 < len(text) and text[index + 1] == '"':
                    blank(index)
                    blank(index + 1)
                    index += 2
                    continue
                if (
                    text[index] == "`"
                    and index + 1 < len(text)
                    and text[index + 1] in {'"', "`", "$"}
                ):
                    blank(index)
                    blank(index + 1)
                    index += 2
                    continue
                if text[index] == '"':
                    if index + 1 < len(text) and text[index + 1] == '"':
                        blank(index)
                        blank(index + 1)
                        index += 2
                        continue
                    break
                blank(index)
                index += 1
            if index >= len(text):
                findings.append(ParseFinding("UNMATCHED_DOUBLE_QUOTE", "Double-quoted string is unterminated.", len(text)))
            else:
                blank(index)
                index += 1
            continue
        if text.startswith("$(", index):
            subexpression_start = index
        if char in "([{":
            stack.append((char, index))
        elif char in ")]}":
            expected = {")": "(", "]": "[", "}": "{"}[char]
            if not stack or stack[-1][0] != expected:
                findings.append(ParseFinding("UNBALANCED_DELIMITER", f"Unbalanced '{char}'.", index))
            else:
                stack.pop()
                if char == ")" and not stack:
                    subexpression_start = None
        index += 1

    for char, position in stack:
        if subexpression_start is not None and position == subexpression_start + 2:
            findings.append(ParseFinding("UNTERMINATED_SUBEXPRESSION", "Subexpression is unterminated.", subexpression_start))
        else:
            findings.append(ParseFinding("UNBALANCED_DELIMITER", f"Unbalanced '{char}'.", position))
    findings.sort(key=lambda item: (item.position, item.code))
    return findings, "".join(code)


def analyze_parse(command: str) -> ParseAnalysis:
    """Return one frozen heuristic verdict; no grammar or semantic validation."""
    text = _bounded(command)
    if not text.strip():
        return ParseAnalysis(
            ParseVerdict.UNDETERMINED,
            (ParseFinding("EMPTY_INPUT", "No command text was supplied.", 0),),
        )
    if text.strip() == ">>":
        return ParseAnalysis(
            ParseVerdict.INCOMPLETE,
            (ParseFinding("CONTINUATION_PROMPT", "Parser continuation prompt.", 0),),
        )

    findings, masked = _scan(text)
    tail = masked.rstrip()
    if tail.endswith("`"):
        findings.append(ParseFinding("TRAILING_CONTINUATION", "Trailing backtick requests continuation.", len(tail) - 1))
    if re.search(r"(?:\|\||&&|\||;)\s*$", tail):
        findings.append(ParseFinding("DANGLING_OPERATOR", "Operator has no right operand.", len(tail)))
    if re.match(r"^\s*(?:\|\||&&|\|)", tail):
        findings.append(ParseFinding("LEADING_OPERATOR", "Operator has no left operand.", 0))
    if re.search(r"(?:\d*>>?|<)\s*$", tail):
        findings.append(ParseFinding("DANGLING_REDIRECTION", "Redirection has no target.", len(tail)))
    if not findings and re.search(r"\b(?:invoke-expression|iex)\b", masked, re.IGNORECASE):
        findings.append(ParseFinding("OUT_OF_SCANNER_CAPABILITY", "Dynamic evaluation is outside scanner capability.", 0))

    if findings:
        incomplete = any(finding.code != "OUT_OF_SCANNER_CAPABILITY" for finding in findings)
        verdict = ParseVerdict.INCOMPLETE if incomplete else ParseVerdict.UNDETERMINED
    else:
        verdict = ParseVerdict.NO_INCOMPLETENESS
    findings.sort(key=lambda item: (item.position, item.code))
    return ParseAnalysis(verdict, tuple(findings))

