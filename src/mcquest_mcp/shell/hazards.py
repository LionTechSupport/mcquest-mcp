"""Stale-variable and exception-unsafe hazard primitives (architecture §7.2).

This is a bounded lexical hazard classifier. It is not a validator, planner, or
report orchestrator, and it performs no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

MAX_INPUT_CHARS = 16_384


class HazardCode(str, Enum):
    STALE_VARIABLE = "STALE_VARIABLE"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class StaleVariableHazard:
    code: HazardCode
    variable: str
    assignment_position: int
    consumer_position: int


@dataclass(frozen=True)
class HazardAnalysis:
    hazards: tuple[StaleVariableHazard, ...]


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


def _guarded_spans(masked: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pattern = re.compile(r"\btry\s*\{(?P<body>.*?)\}\s*catch\s*\{(?P<catch>.*?)\}", re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(masked):
        if re.search(r"\b(?:throw|exit)\b", match.group("catch"), re.IGNORECASE):
            spans.append((match.start("body"), match.end("body")))
    return spans


def analyze_stale_variables(command: str) -> HazardAnalysis:
    """Find fallible assignments whose variables are consumed unguarded later."""
    if not isinstance(command, str):
        raise TypeError(f"command must be str, got {type(command).__name__}")
    if len(command) > MAX_INPUT_CHARS:
        raise ValueError(f"command exceeds the maximum of {MAX_INPUT_CHARS} characters")
    masked = _mask(command)
    guarded = _guarded_spans(masked)
    fallible = re.compile(
        r"\bio\.file\]::read|\bget-content\b|\bconvertfrom-json\b|"
        r"\bimport-csv\b|\binvoke-(?:restmethod|webrequest)\b",
        re.IGNORECASE,
    )
    assignment = re.compile(
        r"(?m)^\s*\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<rhs>[^\n;]+)"
    )
    hazards: list[StaleVariableHazard] = []
    for match in assignment.finditer(masked):
        if not fallible.search(match.group("rhs")):
            continue
        name = match.group("name")
        if any(start <= match.start() < end for start, end in guarded):
            continue
        line_index = command.count("\n", 0, match.start())
        lines = command.splitlines()
        previous = lines[line_index - 1].strip() if line_index else ""
        cleared = re.fullmatch(
            rf"\${re.escape(name)}\s*=\s*\$null|remove-variable\s+{re.escape(name)}\b",
            previous,
            re.IGNORECASE,
        )
        if cleared:
            continue
        consumer = re.search(rf"\${re.escape(name)}\b", masked[match.end():])
        if consumer is None:
            continue
        consumer_position = match.end() + consumer.start()
        if any(start <= match.start() < end and start <= consumer_position < end for start, end in guarded):
            continue
        hazards.append(StaleVariableHazard(
            HazardCode.STALE_VARIABLE, name, match.start(), consumer_position
        ))
    hazards.sort(key=lambda item: (item.assignment_position, item.variable))
    return HazardAnalysis(tuple(hazards))
