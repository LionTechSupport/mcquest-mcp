"""Lexical UI-contract audit (V0.8; ``01-V0.8-CONTRACT.md`` section 2.2).

Composes the shared walked/ignored-path/size-guarded source reader and the
``search_block`` renderer (P016/DEC-019) -- V0.8 adds no extractor, no
index, and no parser. All rules are exact-text/exact-token comparisons over
``.js``/``.jsx``/``.ts``/``.tsx`` sources (DEC-018): no symbol resolution,
no semantic inference.

Lexical conventions (implementation choices within the lexical-only
mandate; the contract pins the evidence rules, not recognition syntax):
component names are PascalCase (``[A-Z][A-Za-z0-9]*``); definition sites
are ``function Name(params)``, ``const Name = (params) =>``,
``const Name = props =>``, and ``class Name``; a declared prop-key set is
lexically enumerable only for a destructured object parameter with no
spread/rest element (``(props)`` identifiers and classes are not);
call sites are JSX opening tags (``<Name ...>``) and ``Name({...})``
object-literal calls, fully evaluable only when the argument list
terminates lexically within the file with no spread element; the
immediately-nested generic form ``<Name<`` is skipped, and a ``<Name`` glued
to a preceding identifier (or another ``<``) is skipped as a type-argument
reference (``Array<Chip>``, ``Box<Wrap>``, ``React.FC<Chip>``), so type
parameters and type arguments are not mistaken for JSX usage; comments are not
excluded (no comment awareness -- same documented limitation as the approved
primitive, DEC-026).

Issue categories (fixed enum, DEC-018) and severities (DEC-022/DEC-023/
DEC-031): ``missing_prop`` -- critical only when all in-scope call sites
are accounted for (full scan), every one omits the prop, and every one is
fully evaluable; ``warning`` otherwise (never critical with unevaluable
sites). ``stale_prop`` -- warning only against a fully available
definition. ``mismatched_usage`` -- warning when fully evaluable call
sites disagree and no fully available in-scope definition explains it.
``signature_drift`` -- warning when a fully available definition's
declared list differs lexically from call-site prop keys.
``unverifiable`` -- always severity ``info``, confidence ``low``, never
critical. Severity and confidence are heuristic labels (DEC-017), emitted
only with their supporting evidence rows. ``risk`` is never emitted
(DEC-025). Consistency findings and any new row type are NOT emitted
(DEC-024).

Emission precedence: when a definition is ambiguous or not lexically
enumerable, only ``unverifiable`` rows are emitted -- a verified
``stale_prop``/``missing_prop`` is never asserted from unavailable or
partial definition evidence (DEC-023). ``include_callers`` (default true)
controls whether call-site-anchored rows are reported; when false, call
sites are still scanned but only definition-anchored rows are emitted.
Completeness: full-scan two-pass, ``collection_complete=true`` always
(DEC-016, corrected by DEC-022); sort key ``(relative_path ASC, line ASC)``
(DEC-018/``04`` section 2.3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import (
    IGNORED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path
from .strings import SOURCE_SUFFIXES, _source_files

_COMPONENT_NAME = r"[A-Z][A-Za-z0-9]*"

_DEF_FUNCTION = re.compile(rf"\bfunction\s+({_COMPONENT_NAME})\s*\(([^)]*)\)")
_DEF_ARROW = re.compile(
    rf"\bconst\s+({_COMPONENT_NAME})\s*=\s*\(([^)]*)\)\s*(?::\s*[^=;\n]+)?=>"
)
_DEF_ARROW_BARE = re.compile(
    rf"\bconst\s+({_COMPONENT_NAME})\s*=\s*[A-Za-z_$][\w$]*\s*=>"
)
_DEF_CLASS = re.compile(rf"\bclass\s+({_COMPONENT_NAME})\b")
_JSX_TAG = re.compile(rf"<({_COMPONENT_NAME})\b")
_LITERAL_CALL = re.compile(rf"\b({_COMPONENT_NAME})\s*\(\s*\{{")

_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")

_IDENT_CHAR = re.compile(r"[A-Za-z0-9_$]")
_IDENT_TAIL = re.compile(r"([A-Za-z_$][\w$]*)$")

# Keywords that may legitimately precede a JSX element with no intervening
# whitespace (``return<Chip/>``). An identifier sitting directly before a
# ``<`` is a type-argument reference only when it is NOT one of these.
_JSX_PRECEDING_KEYWORDS = frozenset(
    {
        "await",
        "case",
        "delete",
        "do",
        "else",
        "extends",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }
)


@dataclass
class _DefSite:
    """One in-scope component definition site."""

    rel: str
    line: int
    keys: frozenset[str] | None  # None = prop-key set not lexically enumerable


@dataclass
class _CallSite:
    """One in-scope lexical call site of a component name."""

    rel: str
    line: int
    keys: frozenset[str] | None  # None = not fully evaluable (spread/unterminated)
    snippet: str


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _line_text(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _split_top_level(text: str) -> list[str]:
    """Split on commas at brace/bracket/paren depth zero, honoring quotes."""
    parts: list[str] = []
    depth = 0
    quote = ""
    current: list[str] = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
            current.append(ch)
            continue
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _extract_prop_keys(params: str) -> frozenset[str] | None:
    """Declared prop-key set of a parameter list, or ``None``.

    Enumerable only when the parameter list is a single destructured object
    pattern with no spread/rest element (contract section 2.2: "lexically
    enumerable declared prop-key set"). ``None`` for identifier parameters
    (``props``), spread/rest elements, or unbalanced parameter lists.
    """
    text = params.strip()
    if not text.startswith("{") or text.count("{") != text.count("}"):
        return None
    inner = text[1:-1] if text.endswith("}") else text[1:]
    keys: set[str] = set()
    for part in _split_top_level(inner):
        stripped = part.strip()
        if stripped.startswith("..."):
            return None  # spread/rest element: not lexically enumerable
        match = _IDENTIFIER.match(stripped)
        if match:
            keys.add(match.group(0))
    return frozenset(keys)


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _is_type_argument_reference(text: str, tag_start: int) -> bool:
    """True when ``<Name`` opens a type-argument list, not a JSX element.

    Lexical context rule (no parser): a ``<`` that immediately follows an
    identifier character or another ``<`` sits in type position rather than
    being a JSX tag opener -- ``Array<Chip>``, ``Box<Wrap>``,
    ``React.FC<Chip>``, ``useMemo<Chip>(...)``, ``Array<Array<Chip>>``.

    A JSX tag opener is never glued to a preceding identifier, so this cannot
    suppress a real element, except after a JSX-preceding keyword
    (``return<Chip/>``), which ``_JSX_PRECEDING_KEYWORDS`` excludes. Without
    this guard such references would be enumerated as zero-prop call sites and
    fabricate ``missing_prop``/``signature_drift`` findings (DEC-022: absence
    of evidence is never proof of a defect).
    """
    if tag_start == 0:
        return False
    previous = text[tag_start - 1]
    if previous == "<":
        return True
    if not _IDENT_CHAR.match(previous):
        return False
    tail = _IDENT_TAIL.search(text[:tag_start])
    if tail is None:
        return False
    return tail.group(1) not in _JSX_PRECEDING_KEYWORDS


def _tag_interior(text: str, start: int) -> str | None:
    """Interior of the JSX opening tag whose component name ends at ``start``.

    Returns the text between the name and the terminating ``>`` (exclusive),
    or ``None`` when the tag never terminates (the argument list is not
    lexically complete). Quoted strings are honored, and a ``>`` inside a
    braced expression value does not terminate the tag.
    """
    depth = 0
    quote = ""
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == ">" and depth == 0:
            return text[start:i]
    return None


def _brace_interior(text: str, start: int) -> str | None:
    """Interior of the ``{...}`` object literal whose brace is at ``start``.

    Returns the content between the outer braces, or ``None`` when the
    literal never closes (not lexically complete).
    """
    depth = 0
    quote = ""
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return None


def _jsx_keys(interior: str) -> frozenset[str] | None:
    """Prop keys passed by a JSX opening tag, or ``None`` when not evaluable."""
    if "..." in interior:
        return None
    masked: list[str] = []
    depth = 0
    quote = ""
    for ch in interior:
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            continue
        if depth == 0:
            masked.append(ch)
    keys: set[str] = set()
    for token in "".join(masked).replace("/", " ").split():
        match = re.match(r"([A-Za-z_$][\w$]*)(?:=|$)", token)
        if match:
            keys.add(match.group(1))
    return frozenset(keys)


def _literal_keys(interior: str) -> frozenset[str] | None:
    """Prop keys passed by a ``Name({...})`` object literal, or ``None``."""
    if "..." in interior:
        return None
    keys: set[str] = set()
    for part in _split_top_level(interior):
        match = re.match(r"\s*(?:([A-Za-z_$][\w$]*)\s*:|([A-Za-z_$][\w$]*)\s*$)", part)
        if match:
            keys.add(match.group(1) or match.group(2))
    return frozenset(keys)


def _scan_text(
    rel: str, text: str
) -> tuple[dict[str, list[_DefSite]], dict[str, list[_CallSite]]]:
    """Collect lexical definition and call sites for every PascalCase name."""
    defs_by: dict[str, list[_DefSite]] = {}
    calls_by: dict[str, list[_CallSite]] = {}
    def_spans: list[tuple[int, int]] = []

    for pattern, enumerable in (
        (_DEF_FUNCTION, True),
        (_DEF_ARROW, True),
        (_DEF_ARROW_BARE, False),
        (_DEF_CLASS, False),
    ):
        for match in pattern.finditer(text):
            def_spans.append((match.start(), match.end()))
            keys: frozenset[str] | None = None
            if enumerable:
                keys = _extract_prop_keys(match.group(2))
            defs_by.setdefault(match.group(1), []).append(
                _DefSite(rel, _line_of(text, match.start()), keys)
            )

    for match in _JSX_TAG.finditer(text):
        if text[match.end() : match.end() + 1] == "<":
            continue  # generic parameter, e.g. ``<Array<...>>``: not JSX usage
        if _is_type_argument_reference(text, match.start()):
            continue  # type-argument reference, e.g. ``Array<Chip>``: not a call
        if _in_spans(match.start(), def_spans):
            continue  # a definition site, not a call site
        interior = _tag_interior(text, match.end())
        keys = _jsx_keys(interior) if interior is not None else None
        calls_by.setdefault(match.group(1), []).append(
            _CallSite(
                rel, _line_of(text, match.start()), keys, _line_text(text, match.start())
            )
        )

    for match in _LITERAL_CALL.finditer(text):
        if _in_spans(match.start(), def_spans):
            continue
        interior = _brace_interior(text, text.index("{", match.end() - 1))
        keys = _literal_keys(interior) if interior is not None else None
        calls_by.setdefault(match.group(1), []).append(
            _CallSite(
                rel, _line_of(text, match.start()), keys, _line_text(text, match.start())
            )
        )

    return defs_by, calls_by

def _emit_for_name(
    name: str,
    defs: list[_DefSite],
    calls: list[_CallSite],
    include_callers: bool,
    rows: list[tuple],
) -> None:
    """Append this name's contract rows (contract section 2.2 rules)."""
    if not calls:
        return  # no call-site evidence: nothing to settle
    def_sites = sorted(defs, key=lambda d: (d.rel, d.line))
    evaluable = sorted(
        (call for call in calls if call.keys is not None), key=lambda c: (c.rel, c.line)
    )
    unevaluable = sorted(
        (call for call in calls if call.keys is None), key=lambda c: (c.rel, c.line)
    )

    def add(
        rel: str,
        line: int,
        category: str,
        severity: str,
        confidence: str,
        detail: str,
        evidence: str,
    ) -> None:
        rows.append(
            (rel, line, len(rows), name, category, severity, confidence, detail, evidence)
        )

    if len(def_sites) > 1:
        first = def_sites[0]
        add(
            first.rel,
            first.line,
            "unverifiable",
            "info",
            "low",
            f"{len(def_sites)} in-scope definition sites for this name; the contract is ambiguous (DEC-023)",
            "definition sites: " + ", ".join(f"{d.rel}:{d.line}" for d in def_sites),
        )
        return  # unverifiable precedence: no verified rows from ambiguous evidence

    if def_sites and def_sites[0].keys is None:
        first = def_sites[0]
        add(
            first.rel,
            first.line,
            "unverifiable",
            "info",
            "low",
            "declared prop-key set is not lexically enumerable (identifier parameter, spread/rest, or class component)",
            f"definition {first.rel}:{first.line}",
        )
        if include_callers:
            for call in evaluable + unevaluable:
                add(
                    call.rel,
                    call.line,
                    "unverifiable",
                    "info",
                    "low",
                    "definition's declared prop-key set is not lexically enumerable; this call-site contract cannot be settled",
                    f"call site {call.rel}:{call.line}; definition {first.rel}:{first.line}",
                )
        return

    if def_sites:  # exactly one fully available definition
        definition = def_sites[0]
        declared = definition.keys
        declared_text = ", ".join(sorted(declared)) if declared else ""
        if include_callers:
            for call in unevaluable:
                add(
                    call.rel,
                    call.line,
                    "unverifiable",
                    "info",
                    "low",
                    "argument list is not lexically evaluable (spread element or unterminated tag)",
                    f"call site {call.rel}:{call.line} (usage: {call.snippet}); "
                    f"definition {definition.rel}:{definition.line}",
                )

            for call in evaluable:
                passed_text = ", ".join(sorted(call.keys)) if call.keys else ""
                for key in sorted(call.keys - declared):
                    add(
                        call.rel,
                        call.line,
                        "stale_prop",
                        "warning",
                        "high",
                        f'prop "{key}" is passed at the call site but not declared by the definition',
                        f"call site {call.rel}:{call.line} (usage: {call.snippet}); "
                        f"passes: {passed_text or 'none'}; "
                        f"definition {definition.rel}:{definition.line} (declares: {declared_text})",
                    )
            for key in sorted(declared):
                omitting = [call for call in evaluable if key not in call.keys]
                if not omitting:
                    continue
                all_evaluable = not unevaluable
                critical = all_evaluable and len(omitting) == len(evaluable)
                severity = "critical" if critical else "warning"
                confidence = "high" if all_evaluable else "medium"
                for call in omitting:
                    add(
                        call.rel,
                        call.line,
                        "missing_prop",
                        severity,
                        confidence,
                        f'prop "{key}" is declared by the definition but not passed at this call site'
                        + ("; all in-scope call sites omit it" if critical else ""),
                        f"definition {definition.rel}:{definition.line} (declares: {declared_text}); "
                        f"call site {call.rel}:{call.line} (usage: {call.snippet}); passes: "
                        f"{', '.join(sorted(call.keys)) or 'none'}",
                    )
        differing = [call for call in evaluable if call.keys != declared]
        if differing:
            add(
                definition.rel,
                definition.line,
                "signature_drift",
                "warning",
                "high",
                "declared prop-key list differs lexically from the prop keys passed at in-scope call sites",
                f"definition {definition.rel}:{definition.line} (declares: {declared_text}); "
                "differing call sites: "
                + ", ".join(f"{call.rel}:{call.line}" for call in differing),
            )
    else:
        # No in-scope definition: the only emittable comparison across fully
        # evaluable call sites is mismatched_usage (contract section 2.2).
        if include_callers and len(evaluable) >= 2 and len({c.keys for c in evaluable}) > 1:
            first = evaluable[0]
            add(
                first.rel,
                first.line,
                "mismatched_usage",
                "warning",
                "medium",
                "call sites use differing prop-key sets and no in-scope definition explains the difference",
                "call sites: "
                + "; ".join(
                    f"{call.rel}:{call.line} (passes: {', '.join(sorted(call.keys)) or 'none'})"
                    for call in evaluable
                )
                + f"; first usage: {first.snippet}",
            )
        # Unevaluable call sites with no in-scope definition are not reported:
        # there is no in-scope contract counterpart for them to settle.

def ui_contract_audit(
    path: str = ".",
    component_pattern: str = "*",
    include_callers: bool = True,
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """Audit component prop contracts lexically over .js/.jsx/.ts/.tsx sources.

    Summary-first and explicitly paged: a canonical ``[SUMMARY]`` block
    (total, files_affected, returned, offset, next_offset, has_more,
    truncated, collection_complete, budget) followed by one page of at most
    ``max_results`` multi-line issue rows ordered by
    ``(relative_path ASC, line ASC)`` (DEC-018/``04`` section 2.3). Each row
    names the component, its issue category (fixed enum, DEC-018), a
    heuristic severity and confidence (DEC-017/DEC-022/DEC-023/DEC-031), and
    the supporting evidence locations; ``risk`` is never emitted (DEC-025).
    Full-scan two-pass: ``collection_complete=true`` always (DEC-016).
    """
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    # Contract section 2.0 (DEC-027): an explicitly empty path scans the
    # project root, same as the omitted/default case.
    if not path:
        path = "."

    root = resolve_project_path(path)

    if not root.exists():
        raise FileNotFoundError(path)

    if root.is_file():
        if is_ignored_path(root):
            raise ValueError(f"File is inside an ignored directory: {path}")
        if (
            root.suffix.lower() not in SOURCE_SUFFIXES
            or root.suffix.lower() in IGNORED_EXTENSIONS
        ):
            raise ValueError(f"Unsupported file type: {path}")
        try:
            if root.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(
                    f"File exceeds {MAX_FILE_BYTES:,} byte safety limit: {path}"
                )
            files: list[Path] = [root]
        except OSError:
            raise ValueError(f"Unreadable file: {path}")
    else:
        # Contract section 2.0: an ignored directory input is rejected with
        # ValueError, not silently scanned to an empty result.
        if is_ignored_path(root):
            raise ValueError(f"Directory is inside an ignored directory: {path}")
        files = list(_source_files(root, component_pattern))

    # "In-scope" is the whole scanned scope, not one file: definition sites
    # and call sites are grouped across every scanned file, because the
    # contract section 2.2 rules resolve a component's contract from its
    # in-scope definition site and its in-scope call sites.
    defs_by: dict[str, list[_DefSite]] = {}
    calls_by: dict[str, list[_CallSite]] = {}
    for file_path in files:
        relative = file_path.relative_to(project_root()).as_posix()
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_defs, file_calls = _scan_text(relative, text)
        for name, sites in file_defs.items():
            defs_by.setdefault(name, []).extend(sites)
        for name, sites in file_calls.items():
            calls_by.setdefault(name, []).extend(sites)

    rows: list[tuple] = []
    for name in sorted(set(defs_by) | set(calls_by)):
        _emit_for_name(
            name,
            defs_by.get(name, []),
            calls_by.get(name, []),
            include_callers,
            rows,
        )

    # files_affected: files holding the definition/call evidence of the
    # components that produced findings (authoritative full-scan count,
    # computed before pagination).
    affected: set[str] = set()
    for row in rows:
        affected.update(site.rel for site in defs_by.get(row[3], []))
        affected.update(site.rel for site in calls_by.get(row[3], []))
    files_affected = len(affected)

    # Pass 2: deterministic page window over (relative_path, line, seq); the
    # stable insertion sequence breaks ties within one line deterministically.
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    total = len(rows)
    page_size = min(max_results, max(total - offset, 0))
    page = rows[offset : offset + page_size]

    items = [_render_row(row) for row in page]
    return search_block(
        tool="mcquest_ui_contract_audit",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields={
            "PATH": path,
            "component_pattern": component_pattern,
            "include_callers": "true" if include_callers else "false",
            "max_results": max_results,
        },
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
    )


def _render_row(row: tuple) -> str:
    """Render one issue row as a multi-line search_block item."""
    rel, line, _seq, name, category, severity, confidence, detail, evidence = row
    return "\n".join(
        [
            f"{rel}:{line}: {name} {category} "
            f"[severity: {severity} (heuristic); confidence: {confidence} (heuristic)]",
            f"    issue: {detail}",
            f"    evidence: {evidence}",
        ]
    )

