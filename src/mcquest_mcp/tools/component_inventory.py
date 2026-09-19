"""Component inventory (V0.7 Stage 4, DEC-013 updated + DEC-014).

``mcquest_component_inventory`` is a read-only, metadata-only inventory of
lexical React component *candidates* declared in ``.js``/``.jsx``/``.ts``/
``.tsx`` source, returning for each candidate only
``<relative_posix_path>:<line>: <Name> (<kind>)``.

Approved contract (DEC-013 updated + DEC-014, 2026-09-18; spec
``Docs/V0.7/08-V0.7-STAGE4-SPEC.md``):

- **Recognition rules R-1..R-6** (spec sec 4.3), lexical-only, one physical
  line: ``function NAME(`` with an optional ``export``/``export default``
  prefix -> ``function``; ``class NAME`` (same optional prefix, class
  expressions excluded by the E-3 guard) -> ``class``; ``const NAME = (...)``
  arrow values -> ``arrow``; ``const NAME = function ...`` function values ->
  ``function``; the async forms map to ``arrow``/``function`` (R-5 is
  subsumed by the optional ``async`` in the R-3/R-4 matchers); ``export
  default function NAME`` / ``export default class NAME`` produce exactly the
  same rows as R-1/R-2 and are deduplicated (O-10b).
- **Guards E-1..E-4** (spec sec 3.3): ``NAME`` is ``[A-Z][A-Za-z0-9_]*``
  matched case-sensitively (E-1, ASCII-only per O-19); the variable-form
  initializer on the same line must be function-like (E-2 - the ``=>`` /
  ``function`` requirement, which excludes ``const MAX_EMITTED = 500;``);
  non-function initializers (``require(...)``, numbers, arrays, objects,
  ``Symbol(...)`` and any class expression ``= class ...``) never qualify
  (E-3 / O-7 default); no name => no candidate (E-4, which also implements
  O-3(c): anonymous default exports are skipped, no ``(default)`` placeholder
  kind).
- **O-23:** exactly the R-3..R-5 initializer shapes; no additional shapes.
- **O-3(a)** ``arrow`` is distinct from ``function``; **O-3(b)** ``class`` is
  emitted for any lexical ``class NAME`` (no React-base-class gate, and
  "class" does NOT mean every class is reported - E-1/E-3 still apply).
- **O-8:** ``.d.ts`` files are excluded by suffix; ``declare``-form matches
  inside other ``.ts`` files remain (documented residual false positives).
- **O-12:** an explicit single-file path whose extension is outside the
  supported set (or a ``.d.ts``) is rejected with ``ValueError``.
- **O-13:** files are decoded with ``errors="replace"``; a decoding
  replacement never makes the collection incomplete.
- **O-15:** ``MAX_FILES_ANALYZED = 500`` caps files actually analyzed.
- **O-17:** no per-file/global row caps (no row-cap completeness condition).
- **O-11:** signature ``(path=".", file_pattern="", max_results=50,
  offset=0)``; no ``kind=`` filter. **O-9:** row rendering as above.
  **O-10(a):** all distinct same-line candidates are emitted. **O-10(b):**
  byte-identical rows are deduplicated. **O-18:** approved zero/partial-result
  wording (spec sec 8.2/8.3). **O-19:** ASCII-only names. **O-24:** no numeric
  files-scanned/files-skipped fields in the public output.
Limits (exact, approved): ``MAX_ENUMERATE_FILES = 2000`` and
``MAX_FILE_BYTES`` transfer from the Stage 3 set (spec sec 7.1 YES); the
identity limits (``MAX_EXACT_PATHS_PER_FILE`` etc.) are not implemented
(O-16 remains open and there is no key-path analogue in a line scan);
JSON-only limits are not claimed anywhere.

Remaining OPEN questions are not resolved here: O-14 (malformed
``file_pattern``) follows the established silent ``fnmatch`` convention of
every existing tool; O-20 line-ending/BOM handling follows ``splitlines()``
(newline-agnostic; a BOM does not shift match positions); O-21 fixtures are
written per-test. Comments and strings are NOT stripped (spec sec 4.4): a
declaration-shaped match inside a comment or string is emitted as a
documented false positive.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path

# --- Approved Stage 4 numeric limits (exact; DEC-013/DEC-014) --------------
MAX_ENUMERATE_FILES = 2_000  # transferred from Stage 3 (spec sec 7.1 YES)
MAX_FILES_ANALYZED = 500  # new approved limit (O-15, DEC-014)

SUPPORTED_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}

# ``NAME`` = [A-Z][A-Za-z0-9_]* (E-1 case guard and O-19 ASCII-only are
# baked into the capture; lowercase names never match).
_NAME = r"[A-Z][A-Za-z0-9_]*"

# R-1 + R-6-function: optional export/export default, then ``function NAME(``.
_FUNCTION_DECL_RE = re.compile(
    rf"\b(?:export\s+(?:default\s+)?)?function\s+({_NAME})\s*\("
)
# R-2 + R-6-class: optional export/export default, then ``class NAME``.
_CLASS_DECL_RE = re.compile(
    rf"\b(?:export\s+(?:default\s+)?)?class\s+({_NAME})\b"
)
# R-3 + R-5-arrow: const NAME = (optional async) then a parenthesized or
# bare parameter list followed by ``=>`` on the same line.
_ARROW_VAR_RE = re.compile(
    rf"\bconst\s+({_NAME})\s*=\s*(?:async\s*)?"
    rf"(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>"
)
# R-4 + R-5-function: const NAME = (optional async) function ...
_FUNCTION_VAR_RE = re.compile(
    rf"\bconst\s+({_NAME})\s*=\s*(?:async\s+)?function\b"
)

def _in_scope(file_path: Path) -> bool:
    """True for a candidate file: supported suffix and not a ``.d.ts`` name."""
    if file_path.name.endswith(".d.ts"):  # O-8: excluded by suffix
        return False
    return file_path.suffix.lower() in SUPPORTED_SUFFIXES


def _is_class_expression(line: str, match: re.Match[str]) -> bool:
    """E-3 / O-7 default: ``class NAME`` right after ``=`` is an expression."""
    before = line[: match.start()].rstrip()
    return bool(before) and before[-1] == "="


def _scan_line(line: str) -> list[tuple[str, str]]:
    """Emit ``(name, kind)`` candidates from one physical line (lexical).

    Rules are applied against the full line text (spec sec 4.1: the 200-char
    clip is a rendering concern, never applied before matching). Multiple
    distinct candidates on one line are all returned (O-10a).
    """
    hits: list[tuple[str, str]] = []
    for match in _FUNCTION_DECL_RE.finditer(line):
        hits.append((match.group(1), "function"))
    for match in _CLASS_DECL_RE.finditer(line):
        if _is_class_expression(line, match):
            continue
        hits.append((match.group(1), "class"))
    for match in _ARROW_VAR_RE.finditer(line):
        hits.append((match.group(1), "arrow"))
    for match in _FUNCTION_VAR_RE.finditer(line):
        hits.append((match.group(1), "function"))
    return hits


def _scan_text(relative: str, text: str) -> list[tuple[str, int, str, str]]:
    """Return ``(relative, line, name, kind)`` rows for one file's text."""
    records: list[tuple[str, int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        records.extend(
            (relative, line_no, name, kind)
            for name, kind in _scan_line(line)
        )
    return records


def _read_file_text(file_path: Path) -> str:
    """Read a candidate file; decoding uses ``errors="replace"`` (O-13)."""
    return file_path.read_text(encoding="utf-8", errors="replace")


def _enumerate_candidates(root: Path, file_pattern: str) -> tuple[list[Path], bool]:
    """Collect in-scope candidate files under ``root`` (bounded walk).

    Ignores directories from ``IGNORED_DIRECTORIES``, files whose suffix is
    outside the supported set, ``.d.ts`` names, and ignored paths. An empty
    ``file_pattern`` means the extension allowlist only (spec sec 6.2).
    Reaching exactly ``MAX_ENUMERATE_FILES`` stops the walk and reports
    ``cap_hit`` - the walker cannot prove the tree is exhausted (spec sec
    6.2/7.3 semantics: reaching exactly the cap proves nothing).
    """
    enumerated: list[Path] = []
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        for filename in files:
            file_path = current / filename
            if not _in_scope(file_path):
                continue
            if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                continue
            if is_ignored_path(file_path):
                continue
            enumerated.append(file_path)
            if len(enumerated) >= MAX_ENUMERATE_FILES:
                return enumerated, True
    return enumerated, False
def component_inventory(
    path: str = ".",
    file_pattern: str = "",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """Inventory lexical React component candidates in JS/TS sources.

    Summary-first and explicitly paged: returns a canonical ``[SUMMARY]``
    block (total, files_affected, returned, offset, next_offset, has_more,
    truncated, collection_complete, budget) followed by one page of at most
    ``max_results`` ``<relative_path>:<line>: <Name> (<kind>)`` rows ordered
    deterministically by ``(relative_path, line, name, kind)`` (byte-order
    path comparison; UTF-8 is order-preserving). ``total`` is the exact count
    of deduplicated candidate rows within the bounded scope, independent of
    page size.

    ``collection_complete`` is ``true`` only when no in-scope file was skipped
    (oversized/unreadable) and no file-count cap was reached (spec sec 7.3);
    it does NOT mean every row was delivered on this page (see
    ``has_more``/``next_offset``). The approved zero/partial-result wording is
    emitted through the summary ``NOTE`` field (O-18). This is a lexical
    candidate inventory, not a verified React-component detector.
    """
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    root = resolve_project_path(path)
    if not root.exists():
        raise FileNotFoundError(path)

    records: list[tuple[str, int, str, str]] = []
    files_analyzed = 0
    reasons: list[str] = []

    if root.is_file():
        # Single-file mode (spec sec 6.3, O-12): strict extension + reads.
        if is_ignored_path(root):
            raise ValueError(f"File is inside an ignored directory: {path}")
        if not _in_scope(root):
            raise ValueError(
                "Unsupported extension: path must be .js/.jsx/.ts/.tsx "
                f"(.d.ts excluded): {path}"
            )
        try:
            if root.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(
                    f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {path}"
                )
        except OSError:
            raise ValueError(f"Unreadable file: {path}")
        try:
            text = _read_file_text(root)
        except OSError:
            raise ValueError(f"Unreadable file: {path}")
        files_analyzed = 1
        records = _scan_text(root.relative_to(project_root()).as_posix(), text)
    else:
        enumerated, cap_hit = _enumerate_candidates(root, file_pattern)
        # Deterministic file ordering before the analysis cap (no raw walk
        # order leaks into which files are analyzed or into the row order).
        enumerated.sort(key=lambda p: p.relative_to(project_root()).as_posix())
        analysis_truncated = len(enumerated) > MAX_FILES_ANALYZED
        selected = enumerated[:MAX_FILES_ANALYZED]
        if cap_hit or analysis_truncated:
            reasons.append("file limit reached")
        for file_path in selected:
            relative = file_path.relative_to(project_root()).as_posix()
            try:
                if file_path.stat().st_size > MAX_FILE_BYTES:
                    reasons.append("file skipped: oversized")
                    continue
            except OSError:
                reasons.append("file skipped: unreadable")
                continue
            try:
                text = _read_file_text(file_path)
            except OSError:
                reasons.append("file skipped: unreadable")
                continue
            files_analyzed += 1
            records.extend(_scan_text(relative, text))

    # O-10(b): deduplicate byte-identical identity rows; A-4: deterministic
    # order (relative_path bytes ASC, line ASC, name ASC, kind ASC).
    unique = sorted(set(records))
    total = len(unique)
    files_affected = len({r[0] for r in unique})

    page_size = min(max_results, max(total - offset, 0))
    page = unique[offset : offset + page_size]
    items = [f"{r[0]}:{r[1]}: {r[2]} ({r[3]})" for r in page]

    collection_complete = not reasons

    # O-18 approved wording (spec sec 8.2 / 8.3). ``total`` is already a
    # summary field, so the ``total: 0`` prefixes of the approved sentences
    # are not duplicated in the NOTE value.
    note: str | None = None
    if reasons:
        if total == 0:
            note = (
                "total: 0 found so far \u2014 scan incomplete "
                "(collection_complete: false); further files were not "
                "analyzed, so this is not a complete inventory."
            )
        else:
            note = (
                "scan not exhaustive (reason: "
                + "; ".join(reasons)
                + "); results below are a partial inventory."
            )
    elif total == 0:
        note = (
            "no component candidates matched (lexical scan of "
            f"{files_analyzed} file(s); candidates only \u2014 a zero result "
            "does not prove that no components exist)."
        )

    fields: dict[str, object] = {"PATH": path}
    if file_pattern:
        fields["FILE_PATTERN"] = file_pattern
    if note:
        fields["NOTE"] = note

    return search_block(
        tool="mcquest_component_inventory",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields=fields,
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
        collection_complete=collection_complete,
    )