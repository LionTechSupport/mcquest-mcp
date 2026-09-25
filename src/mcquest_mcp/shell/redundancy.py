"""Deterministic n0-n3 redundancy analysis (contract §20; decision A9).

The store remains the single owner of command history. This module normalizes
text with the approved four-level ladder and compares against existing records;
it never writes state and never uses aliases, similarity, or semantic
equivalence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .store import ObservationStore

MAX_INPUT_CHARS = 16_384
METHOD_LINE = (
    "levels n0–n3 checked; aliases, abbreviated parameters, parameter reordering, "
    "here-string form, pipeline regrouping, and similarity are not normalized"
)


class ChangeReason(str, Enum):
    """Only explicit, documented conditions can justify a repeat."""

    FILE = "file"
    WORKTREE = "worktree"
    TERMINAL = "terminal"
    PROCESS = "process"
    CWD = "cwd"
    CONFIGURATION = "configuration"
    PRIOR_STALENESS = "prior_staleness"
    PRIOR_FAILURE = "prior_failure"
    SCOPE = "scope"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class RedundancyResult:
    duplicate: bool
    level: str | None
    command_id: str | None
    message: str
    justified: bool = False
    justification: str = ""
    method_line: str = METHOD_LINE


def _bounded(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"text exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return text


def _ascii_lower(text: str) -> str:
    return text.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def _n1(text: str) -> str:
    return _ascii_lower(re.sub(r"\s+", " ", text.strip()))


def _quote_spans(text: str) -> list[tuple[int, int, str, str]]:
    spans: list[tuple[int, int, str, str]] = []
    index = 0
    while index < len(text):
        quote = text[index]
        if quote not in {"'", '"'}:
            index += 1
            continue
        start = index
        index += 1
        content_start = index
        while index < len(text):
            if text[index] == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                spans.append((start, index + 1, quote, text[content_start:index]))
                index += 1
                break
            index += 1
        else:
            break
    return spans


def _safe_quote_span(content: str, quote: str) -> bool:
    other = "'" if quote == '"' else '"'
    return (
        not any(token in content for token in ("`", "$", other))
        and not (len(content) >= 2 and content[0] == quote and content[-1] == quote)
        and quote + quote not in content
    )


def _n2(text: str) -> str:
    spans = _quote_spans(text)
    if not spans:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end, quote, content in spans:
        pieces.append(text[cursor:start])
        pieces.append(
            '"' + content + '"'
            if _safe_quote_span(content, quote)
            else text[start:end]
        )
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:"
    r"[A-Za-z]:[\\/]+[A-Za-z0-9_.$-]+(?:[\\/]+[A-Za-z0-9_.$-]+)*"
    r"|(?<![:])[\\/]{2,}[A-Za-z0-9_.$-]+(?:[\\/]+[A-Za-z0-9_.$-]+)*"
    r"|[A-Za-z0-9_.$-]+[\\/]+[A-Za-z0-9_.$-]+(?:[\\/]+[A-Za-z0-9_.$-]+)*"
    r")"
)




def _strip_root_prefix(text: str, repository_root: str | None) -> str:
    if repository_root is None:
        return text
    root = _path_token(repository_root.strip().strip("'\""))
    match = re.match(
        r"^\s*(?:set-location|cd)\s+"
        r"(?P<target>'(?:[^']|'')+'|\"(?:[^\"]|\"\")+\"|[^\s;]+)\s*;\s*",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text
    target = match.group("target").strip("'\"").replace("''", "'").replace('""', '"')
    if _path_token(target) != root:
        return text
    return text[match.end():]


def normalize_command(
    text: str, *, repository_root: str | None = None
) -> tuple[str, str, str, str]:
    """Return exactly the A9 ``(n0, n1, n2, n3)`` forms."""
    value = _bounded(text)
    if repository_root is not None:
        if not isinstance(repository_root, str):
            raise TypeError("repository_root must be str or None")
        if len(repository_root) > MAX_INPUT_CHARS:
            raise ValueError("repository_root exceeds the maximum input size")
    n0 = value.strip()
    n1 = _n1(n0)
    n2 = _n2(n1)
    n3 = _n3_paths(_strip_root_prefix(n2, repository_root))
    return n0, n1, n2, n3


def analyze_redundancy(
    text: str,
    store: ObservationStore,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
    repository_root: str | None = None,
    changed_reasons: tuple[ChangeReason, ...] = (),
) -> RedundancyResult:
    """Compare against existing history at the first matching n0-n3 level."""
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    for index, reason in enumerate(changed_reasons):
        if not isinstance(reason, ChangeReason):
            raise TypeError(
                f"changed_reasons[{index}] must be ChangeReason, got {type(reason).__name__}"
            )
    forms = normalize_command(text, repository_root=repository_root)
    records = [
        record
        for record in store.commands()
        if record.terminal_session == terminal_session
        and record.process_id == process_id
    ]
    for record in records:
        candidate = normalize_command(record.text, repository_root=repository_root)
        for index, (left, right) in enumerate(zip(forms, candidate)):
            if left == right:
                reason_text = ", ".join(reason.value for reason in changed_reasons)
                return RedundancyResult(
                    duplicate=True,
                    level=f"n{index}",
                    command_id=record.command_id,
                    message=f"duplicate (level n{index}) of {record.command_id}",
                    justified=bool(changed_reasons),
                    justification=reason_text,
                )
    return RedundancyResult(
        duplicate=False,
        level=None,
        command_id=None,
        message="no duplicate found (levels n0–n3 checked)",
    )

def _path_token(value: str) -> str:
    value = _ascii_lower(value.replace("\\", "/"))
    value = re.sub(r"/{2,}", "/", value)
    return re.sub(
        r"^([a-z]):", lambda match: match.group(1) + ":", value
    )


def _n3_paths(text: str) -> str:
    return _PATH_TOKEN.sub(lambda match: _path_token(match.group(0)), text)
