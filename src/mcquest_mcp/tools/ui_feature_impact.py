"""Feature-impact audit (V0.8; ``01-V0.8-CONTRACT.md`` §2.4).

Single-scan, evidence-based review list for "which files/docs/locales may be
affected by a change to a target" -- never a definitive fix plan. Composes
existing primitives only (P016/DEC-019): the shared walked/ignored-path/
size-guarded readers, the ``mcquest_find_usages`` word-boundary rule, the
``mcquest_find_imports`` import-module rule (``_match_import``), the approved
``mcquest_find_strings`` literal scanner (``_scan_line``), a lexical locale
key-position lookup in the style of ``locale_inspect`` (which keys/references
in ``.json`` text mention the target -- locale_inspect's own parse/duplicate
machinery is NOT reimplemented and no parser, index, framework, or cache is
added), and the ``search_block`` renderer.

File-type boundary (DEC-019): the union of ``.js``/``.jsx``/``.ts``/``.tsx``
sources, ``.md``/``.markdown``/``.mdown``/``.mkd`` documentation, and locale
``.json`` files. A single-file input is accepted against this static union;
``include_docs`` / ``include_locales`` (optional booleans, DEFAULT TRUE --
DEC-034) select the ACTIVE scan dimensions: when false, that dimension's
files are not scanned and contribute no rows. No behavior beyond the
DEC-034 statements is inferred.

Matching (lexical only; the contract pins evidence rules, not recognition
syntax): targets are matched word-boundarily (find_usages semantics --
declarations, comments, and string literals all count); import specifiers
additionally use find_imports' case-insensitive module-substring rule; code
literals are additionally checked with the find_strings scanner; Markdown
lines are matched word-boundarily (documentation reference); ``.json`` lines
are classified lexically by key position (a match inside a quoted run
followed by ``:`` is a ``locale key reference``, otherwise a ``locale value
reference``). Path-like or leading-non-word targets may be under-detected
outside import lines (word-boundary anchoring) -- a lexical limitation, and
a zero result never proves absence of feature impact.

Row model: one row per ``(relative_path, line)``; a line matched by several
composed primitives carries all of its reasons in fixed order. Sort key
``(relative_path ASC, line ASC)`` (pinned by ``04-V0.8-TEST-PLAN.md`` §2.3 /
DEC-018). Rows are review items, NOT asserted issues: no ``severity`` field
(§2.4), no issue-type or classification enum is invented, no ``confidence``
field (§3 ties confidence to an emitted classification/issue category/issue
type -- none is emitted here), and ``risk`` is never emitted (DEC-025). The
contract-required review checklist is emitted as an explicitly labeled
suggestion, never as fact (§2.4 / §3 / §4). Comparison mode remains deferred
(DEC-019); ``feature_scope`` is not an input of this tool (DEC-030).

Bounded scan (DEC-016/DEC-028/DEC-035): ``MAX_ENUMERATE_FILES = 2000`` and
``MAX_FILES_ANALYZED = 500`` for the unified in-scope scan -- no separate
code/document/locale numeric caps. ``collection_complete=false`` plus the
established incomplete-collection NOTE only when a scan cap or a skipped
(oversized/unreadable) file prevents full inspection; ``true`` with no such
NOTE when the bounded scan completes uncapped. ``total`` counts findings
within the bounded scan only and is never presented as repository-global
when the scan was capped. ``truncated`` (output budget) stays separate from
``collection_complete`` (DEC-028); explicit ``offset`` is the only
continuation mechanism and no automatic page 2 is rendered.
§2.0 path/error table applies (DEC-027); read-only, no mutation (DEC-014).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path
from .docs import MARKDOWN_EXTENSIONS
from .imports import _match_import
from .strings import SOURCE_SUFFIXES, _scan_line

# DEC-035 bounded-scan limits for mcquest_feature_impact_audit (single
# unified caps over the active in-scope scan; no separate per-dimension caps).
MAX_ENUMERATE_FILES = 2_000
MAX_FILES_ANALYZED = 500

# DEC-019 static file-type boundary union, used for single-file input
# acceptance regardless of the include_docs / include_locales switches.
BOUNDARY_SUFFIXES = SOURCE_SUFFIXES | MARKDOWN_EXTENSIONS | {".json"}

_CODE_LABEL = "code"
_DOCS_LABEL = "docs"
_LOCALE_LABEL = "locale"


def _dimension(suffix: str) -> str:
    if suffix in SOURCE_SUFFIXES:
        return _CODE_LABEL
    if suffix in MARKDOWN_EXTENSIONS:
        return _DOCS_LABEL
    return _LOCALE_LABEL


def _resolve_scope(raw: str) -> tuple[Path, str]:
    """Resolve the scope path per the §2.0 table (DEC-027)."""
    if not raw:
        raw = "."  # omitted/empty path scans the project root
    resolved = resolve_project_path(raw)
    if not resolved.exists():
        raise FileNotFoundError(raw)
    if is_ignored_path(resolved):
        raise ValueError(f"Scope path is inside an ignored directory: {raw}")
    return resolved, raw


def _single_file(root: Path, raw: str) -> Path:
    """Accept a single in-boundary file input; reject anything else (§2.0)."""
    if is_ignored_path(root):
        raise ValueError(f"File is inside an ignored directory: {raw}")
    if (
        root.suffix.lower() not in BOUNDARY_SUFFIXES
        or root.suffix.lower() in IGNORED_EXTENSIONS
    ):
        raise ValueError(f"Unsupported file type: {raw}")
    try:
        if root.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(
                f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {raw}"
            )
    except OSError:
        raise ValueError(f"Unreadable file: {raw}")
    return root


def _bounded_files(
    root: Path, suffixes: set[str], reasons: list[str]
) -> tuple[list[Path], bool]:
    """Enumerate in-scope files under the shared walk policy, capped at
    ``MAX_ENUMERATE_FILES``. Returns ``(files, capped)``; ``capped`` is true
    only when at least one further in-scope file existed beyond the cap.
    """
    found: list[Path] = []
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        for filename in files:
            path = current / filename
            if path.suffix.lower() not in suffixes:
                continue
            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue
            if is_ignored_path(path):
                continue
            if len(found) >= MAX_ENUMERATE_FILES:
                reasons.append(
                    f"in-scope enumeration limit reached "
                    f"({MAX_ENUMERATE_FILES} files); further in-scope files "
                    "were not enumerated"
                )
                return found, True
            found.append(path)
    return found, False


def _analyzed_subset(enumerated: list[Path], reasons: list[str]) -> list[Path]:
    """Deterministically bound the analyzed subset (``MAX_FILES_ANALYZED``).

    Sorting by relative path happens BEFORE the analysis cap so raw walk
    order never determines which files are analyzed (component_inventory /
    ui_doc_gap convention).
    """
    ordered = sorted(
        enumerated, key=lambda p: p.relative_to(project_root()).as_posix()
    )
    if len(ordered) > MAX_FILES_ANALYZED:
        reasons.append(
            f"in-scope analysis limit reached ({MAX_FILES_ANALYZED} files "
            "analyzed); further in-scope files were not analyzed"
        )
        return ordered[:MAX_FILES_ANALYZED]
    return ordered


def _quote_runs(line: str) -> list[tuple[int, int, bool]]:
    """Lexical quoted-run spans of one line as ``(content_start, content_end,
    is_key)``; ``is_key`` is true when the run's closing quote is followed by
    optional blanks and ``:`` (JSON key position). Backslash escapes are
    honored; an unterminated run consumes the rest of the line (is_key false).
    """
    runs: list[tuple[int, int, bool]] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] != '"':
            i += 1
            continue
        j = i + 1
        terminated = False
        while j < n:
            if line[j] == "\\":
                j += 2
                continue
            if line[j] == '"':
                terminated = True
                break
            j += 1
        if not terminated:
            runs.append((i + 1, n, False))
            break
        k = j + 1
        while k < n and line[k] in " \t":
            k += 1
        is_key = k < n and line[k] == ":"
        runs.append((i + 1, j, is_key))
        i = j + 1
    return runs


def _locale_reasons(line: str, word_re: re.Pattern[str]) -> list[str]:
    """Locale key/value reference reasons for one ``.json`` line (DEC-019's
    locale key lookup, lexical key position only -- no JSON parse)."""
    runs = _quote_runs(line)
    reasons: list[str] = []
    saw_match = False
    for match in word_re.finditer(line):
        saw_match = True
        in_key = any(
            start <= match.start() < end and is_key
            for start, end, is_key in runs
        )
        if in_key:
            if "locale key reference" not in reasons:
                reasons.append("locale key reference")
        elif "locale value reference" not in reasons:
            reasons.append("locale value reference")
    if not saw_match:
        return []
    if not reasons:
        # Matched outside any quoted run (e.g. bare token): value position.
        reasons.append("locale value reference")
    # Deterministic order: key references before value references.
    reasons.sort(key=lambda r: 0 if r.startswith("locale key") else 1)
    return reasons


def _line_reasons(
    dimension: str, line: str, word_re: re.Pattern[str], target_lower: str
) -> list[str]:
    """All composed-primitive reasons for one line, in fixed order."""
    if dimension == _DOCS_LABEL:
        if word_re.search(line):
            return ["word-boundary documentation reference"]
        return []
    if dimension == _LOCALE_LABEL:
        return _locale_reasons(line, word_re)
    reasons: list[str] = []
    if word_re.search(line):
        reasons.append("word-boundary usage (find_usages)")
    if _match_import(line, target_lower):
        reasons.append("import module reference (find_imports)")
    for _col, value in _scan_line(line, 1):
        if word_re.search(value):
            reasons.append("string-literal reference (find_strings)")
            break
    return reasons


def _kind_label(dimension: str, reasons: list[str]) -> str:
    """Contract output vocabulary for the row's first line (§2.4)."""
    if dimension == _CODE_LABEL:
        return "impacted file"
    if dimension == _DOCS_LABEL:
        return "affected doc"
    has_key = "locale key reference" in reasons
    has_value = "locale value reference" in reasons
    if has_key and has_value:
        return "locale key/reference"
    if has_key:
        return "locale key"
    return "locale reference"


def _render_row(
    rel: str, line_no: int, kind: str, reasons: list[str], evidence: str
) -> str:
    """Render one impact row as a multi-line search_block item (atomic).

    Rows are review items, not asserted issues: no severity, no confidence,
    and no risk label appears (§2.4 / DEC-025); the reason line is the
    lexical evidence for the row (§2.4).
    """
    return "\n".join(
        [
            f"{rel}:{line_no}: {kind}",
            f"    reason: {'; '.join(reasons)}",
            f"    evidence: {evidence.strip()}",
        ]
    )


def feature_impact_audit(
    target: str,
    path: str = ".",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
    include_docs: bool = True,
    include_locales: bool = True,
) -> str:
    """Lexical single-scan feature-impact review list (§2.4).

    Summary-first and explicitly paged: a canonical ``[SUMMARY]`` block
    (total, files_affected, returned, offset, next_offset, has_more,
    truncated, collection_complete, budget) plus scope metadata (TARGET,
    PATH, INCLUDE_DOCS, INCLUDE_LOCALES) and the contract-required
    REVIEW_CHECKLIST (review suggestions only; never facts), followed by one
    page of at most ``max_results`` rows ordered by ``(relative_path ASC,
    line ASC)``. ``include_docs`` / ``include_locales`` default to ``true``
    (DEC-034); when false, that impact dimension is excluded. No severity,
    no confidence, no risk, and no issue-type/classification enum is emitted.
    Bounded scan (DEC-035): ``MAX_ENUMERATE_FILES = 2000`` /
    ``MAX_FILES_ANALYZED = 500``; ``collection_complete=false`` plus the
    incomplete-collection NOTE only when a cap or a skipped file prevents
    full inspection; ``total`` counts findings within the bounded scan only.
    """
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not target.strip():
        # Required non-empty input (compare_phase precedent): an empty target
        # must never be scanned as a match-everything set or reported as an
        # empty result (DEC-027).
        raise ValueError("target is required.")

    try:
        word_re = re.compile(rf"\b{re.escape(target)}\b")
    except re.error as exc:
        raise ValueError(str(exc)) from exc
    target_lower = target.lower()

    root, raw = _resolve_scope(path)

    active: set[str] = {_CODE_LABEL}
    if include_docs:
        active.add(_DOCS_LABEL)
    if include_locales:
        active.add(_LOCALE_LABEL)

    reasons: list[str] = []
    if root.is_file():
        single_file = _single_file(root, raw)
        # Static DEC-019 boundary accepts the file; the include switches
        # decide whether its dimension is part of the active scan (DEC-034).
        scan_files = (
            [single_file]
            if _dimension(single_file.suffix.lower()) in active
            else []
        )
    else:
        suffixes: set[str] = set(SOURCE_SUFFIXES)
        if include_docs:
            suffixes |= MARKDOWN_EXTENSIONS
        if include_locales:
            suffixes |= {".json"}
        enumerated, _enum_capped = _bounded_files(root, suffixes, reasons)
        scan_files = _analyzed_subset(enumerated, reasons)

    files_analyzed = 0
    # One row per (relative_path, line); reasons merge in fixed order.
    findings: dict[tuple[str, int], tuple[str, list[str], str]] = {}
    for file_path in scan_files:
        relative = file_path.relative_to(project_root()).as_posix()
        dimension = _dimension(file_path.suffix.lower())
        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                reasons.append(
                    f"{dimension} file skipped: oversized ({relative})"
                )
                continue
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            reasons.append(
                f"{dimension} file skipped: unreadable ({relative})"
            )
            continue
        files_analyzed += 1
        for line_no, line in enumerate(text.splitlines(), start=1):
            line_reasons = _line_reasons(
                dimension, line, word_re, target_lower
            )
            if not line_reasons:
                continue
            findings[(relative, line_no)] = (
                _kind_label(dimension, line_reasons),
                line_reasons,
                line,
            )

    ordered = sorted(findings.items())  # (relative_path ASC, line ASC)
    total = len(ordered)
    files_affected = len({key[0] for key, _value in ordered})

    page_size = min(max_results, max(total - offset, 0))
    page = ordered[offset : offset + page_size]
    items = [
        _render_row(key[0], key[1], value[0], value[1], value[2])
        for key, value in page
    ]

    # Approved incomplete-collection NOTE (established O-18 wording, mirrored
    # from mcquest_component_inventory / mcquest_doc_gap_audit): emitted ONLY
    # when the bounded scan was incomplete, never merely because the tool is
    # conceptually bounded (DEC-016/DEC-035). A zero-result NOTE with a
    # complete scan records the lexical-candidate semantics -- a zero result
    # never proves absence of feature impact.
    note: str | None = None
    if reasons:
        if total == 0:
            note = (
                "total: 0 found so far \u2014 scan incomplete "
                "(collection_complete: false); further files were not "
                "analyzed, so this is not a complete audit."
            )
        else:
            note = (
                "scan not exhaustive (reason: "
                + "; ".join(reasons)
                + "); results below are a partial inventory."
            )
    elif total == 0:
        note = (
            "no impact references matched '<target>' (lexical bounded scan "
            f"of {files_analyzed} file(s) in the active scope; word-boundary, "
            "import, string-literal, and locale-key evidence only \u2014 a "
            "zero result does not prove absence of feature impact)."
        )

    checklist = (
        "REVIEW_CHECKLIST (review suggestions only; not facts): inspect each "
        "evidence row, then verify callers/usages, documentation, and "
        f"locale keys/references related to '{target}' before changing it"
    )

    fields: dict[str, object] = {
        "TARGET": target,
        "PATH": raw,
        "INCLUDE_DOCS": "true" if include_docs else "false",
        "INCLUDE_LOCALES": "true" if include_locales else "false",
        "REVIEW_CHECKLIST": checklist,
        "max_results": max_results,
    }
    if note:
        fields["NOTE"] = note

    return search_block(
        tool="mcquest_feature_impact_audit",
        path=raw,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields=fields,
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
        collection_complete=not bool(reasons),
    )




