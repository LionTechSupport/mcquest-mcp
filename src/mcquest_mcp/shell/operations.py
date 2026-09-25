"""Deterministic semantic-operation classification (contract §13; P3).

This module classifies one requested operation. It does not plan, select, or
route a command, and it owns no state. ``UNKNOWN`` remains the conservative
result for empty, ambiguous, or unrecognised input.
"""

from __future__ import annotations

import re
from enum import Enum

MAX_INPUT_CHARS = 16_384


class Operation(str, Enum):
    """The frozen contract §13 taxonomy plus the required UNKNOWN sentinel."""

    READ_FILE = "READ_FILE"
    READ_JSON = "READ_JSON"
    SEARCH_LITERAL = "SEARCH_LITERAL"
    SEARCH_REGEX = "SEARCH_REGEX"
    ENUMERATE_FILES = "ENUMERATE_FILES"
    CHECK_PATH = "CHECK_PATH"
    CHECK_GIT_STATE = "CHECK_GIT_STATE"
    CHECK_CONFIG = "CHECK_CONFIG"
    MEASURE_EOL = "MEASURE_EOL"
    RUN_NODE = "RUN_NODE"
    RUN_PYTHON = "RUN_PYTHON"
    RUN_TEST = "RUN_TEST"
    BUILD = "BUILD"
    INSTALL = "INSTALL"
    EDIT = "EDIT"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return str(self.value)


OPERATION_CLASSES: tuple[str, ...] = tuple(
    operation.value for operation in Operation if operation is not Operation.UNKNOWN
)
MUTATION_BEARING_OPERATIONS = frozenset({Operation.EDIT, Operation.INSTALL})


def is_mutation_bearing(operation: Operation) -> bool:
    """Return the frozen classification flag only; this selects no action."""
    if not isinstance(operation, Operation):
        raise TypeError(f"operation must be Operation, got {type(operation).__name__}")
    return operation in MUTATION_BEARING_OPERATIONS


def _bounded(text: str, *, label: str = "text") -> str:
    if not isinstance(text, str):
        raise TypeError(f"{label} must be str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"{label} exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return text


def normalize_operation(value: str) -> Operation:
    """Map an exact frozen class name to its enum; never infer aliases."""
    candidate = _bounded(value, label="value").strip().upper()
    try:
        return Operation(candidate)
    except ValueError:
        return Operation.UNKNOWN


def _is_json_read(text: str) -> bool:
    structured = bool(re.search(r"\bjson\b|\.json\b|convertfrom-json", text))
    key_inspection = bool(
        re.search(r"\bkey\b|\bkeys\b|\bproperty\b|\bfield\b|\bparse\b|\binspect\b", text)
        or re.search(r"\b[A-Za-z_][\w-]*\.(?!json\b)[A-Za-z_][\w.-]*\b", text)
    )
    if re.search(r"\bas\s+(?:plain\s+)?text\b|\braw\s+text\b", text):
        return False
    if re.search(r"convertfrom-json", text):
        return True
    return structured and key_inspection


def classify_operation(intent: str) -> Operation:
    """Classify an intent or command deterministically, with UNKNOWN preserved.

    Rules are exact lexical patterns in a fixed precedence order. This is not
    fuzzy/similarity matching and it makes no execution decision.
    """
    text = _bounded(intent, label="intent").strip()
    if not text:
        return Operation.UNKNOWN
    lowered = text.lower()

    if _is_json_read(lowered):
        return Operation.READ_JSON
    if re.search(r"\b(?:line\s+endings?|line\s+eol|eol|crlf|lf)\b", lowered):
        return Operation.MEASURE_EOL
    if re.search(r"\bgit\s+config\b|\bgit\s+-c\b|--get\s+[\w.-]+|core\.autocrlf\b", lowered):
        return Operation.CHECK_CONFIG
    if re.search(r"\bgit\s+(?:status|branch|diff|log|show|rev-parse)\b|\bgit state\b", lowered):
        return Operation.CHECK_GIT_STATE
    if re.search(r"\btest-path\b|\bpath\s+exists?\b|\bwhether\s+[^\n]+\s+exists?\b", lowered):
        return Operation.CHECK_PATH
    if re.search(
        r"\benumerate\b|\blist\s+(?:all\s+)?files?\b|\bget-childitem\b|\bdir(?:ectory)?\s+listing\b",
        lowered,
    ):
        return Operation.ENUMERATE_FILES
    if re.search(
        r"\bregex\b|\bregular\s+expression\b|select-string\s+-pattern\b|\bmcquest_search\b",
        lowered,
    ):
        return Operation.SEARCH_REGEX
    if re.search(
        r"\bliteral\b|\bexact\s+(?:text|string)\b|-simplematch\b|findstr\s+/c:",
        lowered,
    ):
        return Operation.SEARCH_LITERAL
    if re.search(r"\brun\s+node\b", lowered):
        return Operation.RUN_NODE
    if re.search(r"\binstall\b|\bnpm\s+(?:install|ci|add)\b|\bpip3?\s+install\b", lowered):
        return Operation.INSTALL
    if re.search(
        r"\bpytest\b|\bunittest\b|\bunit\s+tests?\b|\bnpm\s+(?:run\s+)?test\b|"
        r"\bjest\b|\bvitest\b|\brun\s+(?:the\s+)?tests?\b",
        lowered,
    ):
        return Operation.RUN_TEST
    if re.search(r"\bnode(?:\.exe)?\s+[^\s]+\s", lowered) or re.search(
        r"\bnode(?:\.exe)?\s*$", lowered
    ):
        return Operation.RUN_NODE
    if re.search(
        r"\bbuild(?![\w.-])|\bcompile\b|\bnpm\s+run\s+build\b|\btsc\b|"
        r"\bwebpack\b|\bdotnet\s+build\b",
        lowered,
    ):
        return Operation.BUILD
    if re.search(r"\bedit\b|\bmodify\b|\bwrite\s+(?:a\s+)?file\b|\bset-content\b|\bapply\s+patch\b", lowered):
        return Operation.EDIT
    if re.search(r"\bnode\b|\bnpm\s+run\b", lowered):
        return Operation.RUN_NODE
    if re.search(r"\bpython\b|\bpy\s+[^\s]+\.py\b", lowered):
        return Operation.RUN_PYTHON
    if re.search(r"\bread\b|\bget-content\b|\bopen\s+file\b|\bcat\b", lowered):
        return Operation.READ_FILE
    if re.search(r"\bfind\b|\bsearch\b|\bselect-string\b|\bfindstr\b", lowered):
        return Operation.SEARCH_LITERAL
    return Operation.UNKNOWN
