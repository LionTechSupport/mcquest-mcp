"""Lexical documentation-gap audit (V0.8; ``01-V0.8-CONTRACT.md`` §2.3).

Composes the shared markdown/source walkers, the security primitives, and
the ``search_block`` renderer (P016/DEC-019) -- V0.8 adds no extractor
framework, no index, no parser, and no persistent cache. All rules are
exact-text/exact-token comparisons (DEC-018): no semantic symbol resolution
and no maintained symbol list.

Evidence carriers (canonical — DEC-033): eligible ``stale_reference``
evidence is carried ONLY by (a) the content of a backtick-delimited inline
Markdown span, and (b) a path-like token containing ``/`` with a recognized
source or documentation extension. The identifier form
``[A-Za-z_][A-Za-z0-9_]*`` is a tokenizer applied WITHIN those carriers; it
is NOT a standalone carrier over arbitrary Markdown prose, so ordinary
prose words never become code-reference candidates by identifier shape
alone. Backtick-span contents are matched against the identifier set of the
bounded code scan; path-like tokens are matched against the bounded
code/docs path sets (a token found in either in-scope scan is not stale --
reporting a location as absent when the evidence actually read shows it
exists would violate DEC-022). No match within the bounded scan yields
``stale_reference`` (``warning``; confidence per DEC-025 -- ``high`` when
the code scan completed uncapped, ``medium`` when capped, because absence
from a partial scan is not proof of global absence, DEC-022).

Non-emitting categories (fixed enum, DEC-018): ``missing_doc`` (DEC-030 --
no documentation-obligation source), ``conflicting_reference`` (DEC-033 --
no lexical contradiction evidence rule), ``status_mismatch`` (DEC-026 -- no
status/marker lists), and consistency rows (DEC-024). ``risk`` is never
emitted (DEC-025).

Fenced code blocks are excluded by default (lexical line-state scan per
DEC-026): a line whose first non-whitespace characters are three or more
backticks or tildes toggles the fenced state; a language tag is ignored. An
unterminated fence at end-of-file excludes every line after the opening
fence and is reported through the completeness NOTE -- never as a finding.

Bounded scan (DEC-016/DEC-033): ``MAX_ENUMERATE_FILES = 2000`` /
``MAX_FILES_ANALYZED = 500`` following the ``mcquest_component_inventory``
convention. ``total`` counts findings within the bounded scan only and is
never presented as a global repository-wide total when the scan was capped.
``collection_complete=false`` + the incomplete-collection NOTE only when a
cap (or an unterminated fence) prevents full inspection; ``true`` when the
bounded scan completes uncapped. ``truncated`` (presentation budget) stays
separate from ``collection_complete`` (DEC-028); explicit ``offset`` is the
only continuation mechanism and no automatic page 2 is rendered.
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
from .strings import SOURCE_SUFFIXES

# DEC-033 bounded-scan limits (mcquest_component_inventory convention).
MAX_ENUMERATE_FILES = 2_000
MAX_FILES_ANALYZED = 500

_FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})")
_INLINE_SPAN = re.compile(r"`([^`\n]+)`")
_PATH_TOKEN = re.compile(
    r"[A-Za-z0-9_\-.]+(?:/[A-Za-z0-9_\-.]+)+"
    r"\.(?:js|jsx|ts|tsx|md|markdown|mdown|mkd)\b"
)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_STALE_CATEGORY = "stale_reference"


def _eligible_lines(lines: list[str]) -> tuple[list[tuple[int, str]], bool]:
    """Return (non-fenced lines, unterminated-fence flag) per DEC-026.

    A line whose first non-whitespace characters are three or more backticks
    or tildes toggles the fenced state (language tags ignored). If the
    document ends while a fence is open, every line after the opening fence
    is treated as fenced/excluded and the flag is set for the completeness
    NOTE -- never as a finding.
    """
    eligible: list[tuple[int, str]] = []
    fenced = False
    for line_no, line in enumerate(lines, start=1):
        if _FENCE_LINE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        eligible.append((line_no, line))
    return eligible, fenced


def _doc_tokens(line: str) -> list[str]:
    """Eligible carrier tokens on one non-fenced Markdown line (DEC-033).

    Carriers are inline backtick-span content and path-like tokens with a
    recognized source/documentation extension. The identifier tokenizer runs
    WITHIN these carriers; bare prose identifiers are never carriers.
    """
    tokens: list[str] = []
    for span in _INLINE_SPAN.findall(line):
        stripped = span.strip()
        if stripped:
            tokens.append(stripped)
    for token in _PATH_TOKEN.findall(line):
        tokens.append(token)
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def _carrier_kind(token: str) -> str:
    """Human-readable carrier kind for evidence text (DEC-033)."""
    return "path-like token" if "/" in token else "inline backtick span"


def _token_found(
    token: str,
    code_symbols: set[str],
    code_paths: set[str],
    code_basenames: set[str],
    doc_paths: set[str],
    doc_basenames: set[str],
) -> bool:
    """Lexically locate ``token`` in the bounded evidence actually read.

    Path-like tokens are matched against the relative paths and basenames of
    the bounded code scan AND the bounded docs scan: a location that the
    evidence shows exists (in either in-scope tree) is not stale. Backtick
    spans are matched by identifier tokens against the bounded code symbol
    set (the span references code when any of its identifiers appear).
    """
    if "/" in token:
        lowered = token.lower()
        if lowered in code_paths or lowered in doc_paths:
            return True
        base = lowered.rsplit("/", 1)[-1]
        return base in code_basenames or base in doc_basenames
    return any(match in code_symbols for match in _IDENT.findall(token))


def _bounded_files(
    root: Path, suffixes: set[str], reasons: list[str], label: str
) -> tuple[list[Path], bool]:
    """Enumerate in-scope files under ``root``, bounded by MAX_ENUMERATE_FILES.

    Applies the shared walk policy (ignored directories pruned, ignored
    extensions skipped, ignored paths rejected) and stops at
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
                    f"{label} enumeration limit reached "
                    f"({MAX_ENUMERATE_FILES} files); further in-scope files "
                    "were not enumerated"
                )
                return found, True
            found.append(path)
    return found, False


def _analyzed_subset(
    enumerated: list[Path], reasons: list[str], label: str
) -> tuple[list[Path], bool]:
    """Deterministically bound the analyzed subset (MAX_FILES_ANALYZED).

    Sorting by relative path happens BEFORE the analysis cap so raw walk
    order never determines which files are analyzed (component_inventory
    convention).
    """
    ordered = sorted(
        enumerated, key=lambda p: p.relative_to(project_root()).as_posix()
    )
    if len(ordered) > MAX_FILES_ANALYZED:
        reasons.append(
            f"{label} analysis limit reached ({MAX_FILES_ANALYZED} files "
            "analyzed); further in-scope files were not analyzed"
        )
        return ordered[:MAX_FILES_ANALYZED], True
    return ordered, False

def _resolve_scope(raw: str, kind: str) -> tuple[Path, str]:
    """Resolve one scope path per the section 2.0 table (DEC-027)."""
    if not raw:
        raw = "."  # omitted/empty path scans the project root
    resolved = resolve_project_path(raw)
    if not resolved.exists():
        raise FileNotFoundError(raw)
    if is_ignored_path(resolved):
        raise ValueError(f"{kind} path is inside an ignored directory: {raw}")
    return resolved, raw


def _single_file(root: Path, raw: str, suffixes: set[str], kind: str) -> list[Path]:
    """Accept a single in-boundary file input; reject anything else."""
    if is_ignored_path(root):
        raise ValueError(f"File is inside an ignored directory: {raw}")
    if root.suffix.lower() not in suffixes or root.suffix.lower() in IGNORED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {raw}")
    try:
        if root.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(
                f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {raw}"
            )
        return [root]
    except OSError:
        raise ValueError(f"Unreadable file: {raw}")

def doc_gap_audit(
    docs_path: str = ".",
    code_path: str = ".",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """Audit documentation tokens against the bounded code scan lexically.

    Summary-first and explicitly paged: a canonical ``[SUMMARY]`` block
    (total, files_affected, returned, offset, next_offset, has_more,
    truncated, collection_complete, budget) followed by one page of at most
    ``max_results`` issue rows ordered by ``(docs relative_path ASC,
    doc line ASC, code relative_path ASC)`` (DEC-028). The only currently
    emittable issue type is ``stale_reference`` (``warning``; DEC-033):
    an eligible documentation carrier token -- inline backtick-span content
    or a path-like token with a recognized extension -- that is absent from
    the bounded code scan. ``missing_doc`` (DEC-030), ``conflicting_reference``
    (DEC-033), and ``status_mismatch`` (DEC-026) are NOT EMITTABLE;
    consistency rows are not emitted (DEC-024); ``risk`` is never emitted
    (DEC-025). Bounded scan: ``collection_complete=false`` plus the
    incomplete-collection NOTE only when a scan cap (or an unterminated
    fence) prevents full inspection; ``true`` when the bounded scan completes
    uncapped. ``total`` counts findings within the bounded scan only.
    """
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    docs_root, docs_raw = _resolve_scope(docs_path, "Docs")
    code_root, code_raw = _resolve_scope(code_path, "Code")

    reasons: list[str] = []
    if docs_root.is_file():
        docs_files = _single_file(docs_root, docs_raw, MARKDOWN_EXTENSIONS, "Docs")
        docs_enum_capped = False
    else:
        docs_files, docs_enum_capped = _bounded_files(
            docs_root, MARKDOWN_EXTENSIONS, reasons, "docs"
        )
    if code_root.is_file():
        code_files = _single_file(code_root, code_raw, SOURCE_SUFFIXES, "Code")
        code_enum_capped = False
    else:
        code_files, code_enum_capped = _bounded_files(
            code_root, SOURCE_SUFFIXES, reasons, "code"
        )

    docs_analyzed, docs_analysis_capped = _analyzed_subset(
        docs_files, reasons, "docs"
    )
    code_analyzed, code_analysis_capped = _analyzed_subset(
        code_files, reasons, "code"
    )
    code_capped = code_enum_capped or code_analysis_capped

    # Bounded code-side evidence: identifier set from files actually read,
    # plus code/docs path sets. Path and basename sets are derived from the
    # ENUMERATED in-scope lists (lexical; no symbol resolution), because
    # enumeration is itself evidence that a location exists: an in-scope file
    # that was enumerated but not analyzed still exists, so a doc token
    # pointing at it is not stale even when an analysis cap skipped it
    # (DEC-022 -- never report a location as absent when the evidence read
    # shows it exists in either in-scope tree).
    code_symbols: set[str] = set()
    for file_path in code_analyzed:
        relative = file_path.relative_to(project_root()).as_posix()
        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                reasons.append(f"code file skipped: oversized ({relative})")
                continue
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            reasons.append(f"code file skipped: unreadable ({relative})")
            continue
        code_symbols.update(_IDENT.findall(text))

    code_paths = {
        p.relative_to(project_root()).as_posix().lower() for p in code_files
    }
    code_basenames = {p.name.lower() for p in code_files}
    doc_paths = {
        p.relative_to(project_root()).as_posix().lower() for p in docs_files
    }
    doc_basenames = {p.name.lower() for p in docs_files}

    # Bounded docs-side scan: eligible carrier tokens on non-fenced lines.
    doc_tokens: list[tuple[str, int, str]] = []
    for file_path in docs_analyzed:
        relative = file_path.relative_to(project_root()).as_posix()
        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                reasons.append(f"docs file skipped: oversized ({relative})")
                continue
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            reasons.append(f"docs file skipped: unreadable ({relative})")
            continue
        eligible, unterminated = _eligible_lines(lines)
        if unterminated:
            reasons.append(f"unterminated fenced code block ({relative})")
        for line_no, line in eligible:
            for token in _doc_tokens(line):
                doc_tokens.append((relative, line_no, token))

# Findings: one stale_reference row per (docs file, doc line, token)
    # occurrence. The pinned sort key (04-V0.8-TEST-PLAN.md section 2.3 /
    # DEC-028) is anchored on the DOC line, so a token recurring on another
    # doc line is a distinct doc anchor; occurrences on the same line were
    # already deduplicated by _doc_tokens.
    findings: list[tuple[str, int, str, str]] = []
    for rel, line_no, token in doc_tokens:
        if _token_found(
            token,
            code_symbols,
            code_paths,
            code_basenames,
            doc_paths,
            doc_basenames,
        ):
            continue
        findings.append((rel, line_no, token, _carrier_kind(token)))

    # Deterministic order per the pinned sort key (docs relative_path ASC,
    # doc line ASC, code relative_path ASC). For a stale_reference row the
    # code side of the key is constant (the bounded code scan has no matching
    # code path), so the token breaks same-doc-line ties deterministically.
    findings.sort(key=lambda finding: (finding[0], finding[1], finding[2]))
    total = len(findings)
    files_affected = len({rel for rel, _line_no, _token, _kind in findings})

    # Confidence follows the DEC-033/DEC-025 mapping pinned in this module's
    # docstring: absence from the bounded code scan is high-confidence only
    # when the code evidence is complete -- no enumeration/analysis cap and
    # no code file skipped oversized/unreadable. Any partial code evidence
    # downgrades to medium (absence from a partial scan is not proof of
    # global absence). A docs-side reason alone does not lower the confidence
    # of code-absence evidence.
    code_complete = not (
        code_capped
        or any(r.startswith("code file skipped") for r in reasons)
    )
    confidence = "high" if code_complete else "medium"

    page_size = min(max_results, max(total - offset, 0))
    page = findings[offset : offset + page_size]
    items = [
        _render_row(rel, line_no, token, kind, len(code_analyzed), confidence)
        for rel, line_no, token, kind in page
    ]

    # Approved incomplete-collection NOTE (mirrors mcquest_component_inventory
    # O-18): emitted ONLY when reasons exist (a scan cap or an unterminated
    # fence), never merely because the tool is conceptually bounded
    # (DEC-016/DEC-033). A zero-result NOTE with a complete scan records the
    # lexical-candidate semantics -- a zero result never proves absence.
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
            "no stale-reference candidates matched (lexical bounded scan of "
            f"{len(docs_analyzed)} doc file(s) against {len(code_analyzed)} "
            "code file(s); carriers are inline backtick spans and path-like "
            "tokens only \u2014 a zero result does not prove that "
            "documentation is free of stale references)."
        )

    fields: dict[str, object] = {
        "PATH": docs_raw,
        "CODE_PATH": code_raw,
        "max_results": max_results,
    }
    if note:
        fields["NOTE"] = note

    return search_block(
        tool="mcquest_doc_gap_audit",
        path=docs_raw,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields=fields,
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
        collection_complete=not bool(reasons),
    )


def _render_row(
    rel: str,
    line_no: int,
    token: str,
    kind: str,
    code_files_analyzed: int,
    confidence: str,
) -> str:
    """Render one ``stale_reference`` row as a multi-line search_block item.

    Every emitted severity/confidence label carries its supporting evidence
    row (contract section 2.3 / section 4): severity is always ``warning`` --
    ``critical`` requires a positively established observable condition, and
    absence from a scan is never a proof of a defect (DEC-022/DEC-033). The
    confidence label is heuristic (DEC-017) and the evidence line states the
    bounded code-side basis for the absence claim.
    """
    return "\n".join(
        [
            f"{rel}:{line_no}: stale_reference "
            f"[severity: warning (heuristic); confidence: {confidence} (heuristic)]",
            f"    doc file: {rel}:{line_no}",
            "    code file: (no lexical match in the bounded code scan)",
            f"    carrier: `{token}` ({kind})",
            f"    issue: eligible {kind} is absent from the bounded code scan (DEC-033).",
            f"    evidence: {rel}:{line_no} carries `{token}`; {code_files_analyzed} "
            f"code file(s) analyzed; no matching code identifier or path token",
        ]
    )
