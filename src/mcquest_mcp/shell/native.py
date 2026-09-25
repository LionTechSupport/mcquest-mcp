"""Native-executable boundary analysis (architecture §6.3; P3).

A pure lexical primitive: it locates documented native executables and the
hazards created by their separate argument grammar. It never executes or probes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

MAX_INPUT_CHARS = 16_384

NATIVE_EXECUTABLES = frozenset({
    "cmd", "dotnet", "findstr", "git", "grep", "more", "node", "npm",
    "npx", "py", "python", "rg", "where",
})


class NativeHazard(str, Enum):
    NATIVE_ARGUMENT_GRAMMAR = "native_argument_grammar"
    QUOTED_WILDCARD = "quoted_wildcard"
    NESTED_SCRIPT = "nested_script"
    PIPELINE = "pipeline"
    REDIRECTION = "redirection"
    OUTPUT_ENCODING = "output_encoding"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class NativeBoundary:
    executable: str
    position: int
    hazards: tuple[NativeHazard, ...]
    nested_language: str | None = None


@dataclass(frozen=True)
class NativeAnalysis:
    boundaries: tuple[NativeBoundary, ...]


def _bounded(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"command must be str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"command exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return text


def _mask_strings_and_comments(text: str) -> str:
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


def _command_head(segment: str) -> tuple[str, int] | None:
    match = re.match(r"\s*(?:&\s*)?(?:\"([^\"]+)\"|'([^']+)'|([^\s;|&]+))", segment)
    if not match:
        return None
    token = next(group for group in match.groups() if group is not None)
    token = token.strip().rstrip(",")
    head = re.split(r"[\\/]", token)[-1].lower()
    if head.endswith(".exe"):
        head = head[:-4]
    return (head, match.start(1) if match.group(1) is not None else match.start(2) if match.group(2) is not None else match.start(3))


def _segment_ranges(masked: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    start = 0
    for match in re.finditer(r"[\n;|]+|&{1,2}", masked):
        ranges.append((start, match.start(), masked[start:match.start()]))
        start = match.end()
    ranges.append((start, len(masked), masked[start:]))
    return ranges


def analyze_native(command: str) -> NativeAnalysis:
    """Identify native boundaries and deterministic grammar risks in text order."""
    text = _bounded(command)
    masked = _mask_strings_and_comments(text)
    has_pipeline = "|" in masked
    has_redirection = bool(re.search(r"(?<![0-9])>>?|<(?![-=])", masked))
    quoted_wildcard = bool(re.search(r"['\"][^'\"]*[?*][^'\"]*['\"]", text))
    boundaries: list[NativeBoundary] = []
    for start, end, segment in _segment_ranges(masked):
        if end <= start:
            continue
        head = _command_head(text[start:end])
        if head is None:
            continue
        executable, relative = head
        if executable not in NATIVE_EXECUTABLES:
            continue
        hazards = [NativeHazard.NATIVE_ARGUMENT_GRAMMAR]
        if quoted_wildcard:
            hazards.append(NativeHazard.QUOTED_WILDCARD)
        if has_pipeline:
            hazards.append(NativeHazard.PIPELINE)
        if has_redirection:
            hazards.append(NativeHazard.REDIRECTION)
        raw_segment = text[start:end]
        nested: str | None = None
        if executable == "node" and re.search(r"(?:^|\s)(?:-e|--eval)(?:\s|=)", raw_segment):
            nested = "JavaScript"
            hazards.append(NativeHazard.NESTED_SCRIPT)
        elif executable in {"python", "py"} and re.search(r"(?:^|\s)-c(?:\s|$)", raw_segment):
            nested = "Python"
            hazards.append(NativeHazard.NESTED_SCRIPT)
        boundaries.append(
            NativeBoundary(executable, start + relative, tuple(hazards), nested)
        )
    return NativeAnalysis(tuple(boundaries))
