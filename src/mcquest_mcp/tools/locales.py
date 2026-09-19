"""JSON locale inspection (V0.7 Stage 3, DEC-012).

``mcquest_locale_inspect`` is a read-only JSON locale-file inspector over
``.json`` files under the bounded scope. Design baseline: the approved
V0.7 Stage 3 decisions D-1..D-7.

D-1 duplicate-preserving parse + effective last-value structure:

- ``json.loads(text, object_pairs_hook=_Pairs)`` makes every JSON object a
  ``_Pairs`` list of ``(key, value)`` pairs preserving ALL pairs in source
  order (arrays stay plain lists, scalars stay native). This single tree is
  the source of truth for both syntactic facts and the effective view; no
  second dict-tree is materialized.
- One deterministic walk per file performs, at each effective object node:
  a syntactic DUP scan over the node's FULL pair list (every occurrence of
  every exact key counted, source order), and an effective last-value
  mapping (``key -> its final pair's value``) that alone drives structure
  counts, casefold collisions, identity paths and recursion. Shadowed
  earlier values are never traversed: their keys appear in no identity
  set, structure count, collision or MISSING/EXTRA diff, and their
  internal duplicates are never reported. The shadowing event itself (the
  repeated key at the ancestor) IS a DUP; an effective node's own repeats
  ARE reported.
- Identity = ``{()}`` (root) plus the path of every scalar-valued key or
  array index; container-valued keys contribute their children instead of
  their own path (so ``{"a": {}}`` has identity ``{()}``). Array indices
  are positional and never merged, deduplicated or compared with string
  keys: ``"0"`` (string key) and ``[0]`` (array index) are distinct
  everywhere. Shape differences (scalar/object/array roots) surface in
  STRUCTURE rows, never in MISSING/EXTRA (key-path-set comparison only;
  ``()`` is contained in both sets).
- D-5 path display: object-key segments render JSON-quoted
  (``json.dumps(key, ensure_ascii=False)``), array indices as ``[i]``,
  root as ``<root>``; no mid-path abbreviation — only the renderer's
  200-character atomic line clip with its explicit
  ``[OUTPUT TRUNCATED: N characters omitted]`` marker, which never
  silently merges distinct paths.

D-2 resource bounds (approved limits, exact): the raw-text depth pre-check
rejects nesting > ``MAX_JSON_DEPTH`` before ``json.loads``; the
``MAX_FILE_BYTES`` read cap bounds pair density (a minimum pair ``"":0``
costs 4 source bytes, so <= 500,000 pairs per file);
``MAX_EXACT_PATHS_PER_FILE`` / ``MAX_EXACT_BYTES_PER_FILE`` /
``IDENTITY_UNITS_MAX`` are charged atomically at identity commit and an
over-budget commit rejects and discards the working set (no partial
identity; candidate-path construction is transient and uncharged).
``MAX_PARSE_NODES_PER_FILE`` is a documented invariant guard, NOT a
triggerable runtime bound: under ``MAX_FILE_BYTES`` the node count is
provably <= 1,000,000; it bounds post-parse traversal and identity work
only, does not bound ``json.loads``' own transient allocation, and
provides no RSS or parse-allocation ceiling.

D-3 per-target eligibility, D-4 exact finding/omission accounting, D-6
enumeration/population accounting and D-7 ordering/caps/error-row
handling are implemented in ``locale_inspect`` (see its docstring).
"""

from __future__ import annotations

import fnmatch
import json
import os
from collections import Counter
from pathlib import Path

from ..config import (
    IGNORED_DIRECTORIES,
    MAX_FILE_BYTES,
    MAX_SEARCH_RESULTS,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import search_block
from ..security import is_ignored_path, project_root, resolve_project_path

JSON_SUFFIX = ".json"

# --- Approved Stage 3 numeric limits (exact; none may be invented) ---------
MAX_ENUMERATE_FILES = 2_000
MAX_LOCALE_FILES = 500
MAX_JSON_DEPTH = 200
MAX_EXACT_PATHS_PER_FILE = 100_000
MAX_EXACT_BYTES_PER_FILE = 8_000_000
IDENTITY_UNITS_MAX = 64_000_000
MAX_LOCALE_FILE_ROWS = 3_000
MAX_LOCALE_ROWS = 5_000
MAX_PARSE_NODES_PER_FILE = 1_000_000

# Row ranks (approved ordering: STRUCTURE0 COLLISION1 MISSING2 EXTRA3
# DUP4 ERROR5; typed-path order dominates the rank).
_RANK_STRUCTURE = 0
_RANK_COLLISION = 1
_RANK_MISSING = 2
_RANK_EXTRA = 3
_RANK_DUP = 4
_RANK_ERROR = 5


class _Pairs(list):
    """Every JSON object becomes a list[(key, value)] preserving ALL pairs
    in source order (``object_pairs_hook``); arrays stay plain lists and
    scalars stay native."""


class _IdentityError(Exception):
    """A per-file identity bound failed; the whole working set is discarded
    (no partial identity is ever retained)."""


# --- D-5 typed paths: identity keys, display, ordering ----------------------


def _display_segment(key: str) -> str:
    """JSON-quoted object-key segment (control chars/quotes escaped,
    Unicode preserved)."""
    return json.dumps(key, ensure_ascii=False)


def _display_path(path: tuple) -> str:
    """Render a typed path (D-5): JSON-quoted keys and ``[i]`` indices,
    where an index segment attaches directly to the previous segment
    (``"menu"[0]."label"``) and the root renders ``<root>``. No mid-path
    abbreviation."""
    if not path:
        return "<root>"
    rendered = ""
    for seg in path:
        if type(seg) is int:
            rendered += f"[{seg}]"
        else:
            if rendered:
                rendered += "."
            rendered += _display_segment(seg)
    return rendered


def _typed_key(path: tuple):
    """Deterministic typed-path ordering key (D-7).

    Segments compare element-wise: string keys (rank 0, UTF-8 bytes then
    the string itself) before numeric indices (rank 1, numeric value); a
    path that is a prefix of another sorts first."""
    key = []
    for seg in path:
        if type(seg) is int:
            key.append((1, b"", seg))
        else:
            key.append((0, seg.encode("utf-8"), seg))
    return tuple(key)


# --- D-2 depth pre-check (pre-parse recursion safety) -----------------------


def _max_nesting(text: str) -> int:
    """Maximum ``{``/``[`` nesting in raw JSON text.

    Braces/brackets inside string literals are ignored (escape-aware), so
    for valid JSON this equals the parse-tree depth."""
    depth = max_depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{" or ch == "[":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch == "}" or ch == "]":
            depth -= 1
    return max_depth


# --- D-1 flatten: one walk, syntactic DUP scan + effective view -------------


def _segment_units(seg) -> int:
    """Identity-unit cost of one path segment (key bytes + bookkeeping)."""
    if type(seg) is int:
        return 8
    return len(seg.encode("utf-8")) + 8


def _flatten(tree):
    """One deterministic walk over the effective tree (D-1 section 1.2).

    Returns ``(identity, structure, collisions, dups)``:

    - ``identity``: ``{()}`` plus the path of every scalar-valued key or
      array index in the effective view (container-valued keys contribute
      their children instead of their own path).
    - ``structure``: ``(path, count, is_array)`` per container node —
      effective key counts for objects, lengths for arrays (root first).
    - ``collisions``: ``(node_path, sorted_members)`` per effective node
      whose distinct keys collide under ``str.casefold()``.
    - ``dups``: ``(key_path, occurrences)`` per exact duplicate key at an
      effective object node (full syntactic pair list, all occurrences).

    Shadowed earlier values are never traversed. Every per-file bound
    (node count, exact-path count/bytes, identity units) is charged
    atomically at commit; a failed charge raises :class:`_IdentityError`
    and the caller discards the whole working set (no partial identity)."""
    identity: set = {()}
    structure: list[tuple[tuple, int, bool]] = []
    collisions: list[tuple[tuple, list[str]]] = []
    dups: list[tuple[tuple, int]] = []
    state = {"nodes": 0, "path_bytes": 0, "units": 0}

    def commit(path: tuple) -> None:
        """Atomic unit charge at commit to the retained identity set."""
        if path in identity:
            return
        identity.add(path)
        units = 8  # fixed per-path bookkeeping
        path_bytes = 0
        for seg in path:
            units += _segment_units(seg)
            if type(seg) is str:
                path_bytes += len(seg.encode("utf-8")) + 4
            else:
                path_bytes += 4
        state["path_bytes"] += path_bytes
        state["units"] += units
        if len(identity) > MAX_EXACT_PATHS_PER_FILE:
            raise _IdentityError("exact path count exceeds limit")
        if state["path_bytes"] > MAX_EXACT_BYTES_PER_FILE:
            raise _IdentityError("exact path bytes exceed limit")
        if state["units"] > IDENTITY_UNITS_MAX:
            raise _IdentityError("identity units exceed limit")

    def visit(node, path: tuple) -> None:
        state["nodes"] += 1
        if state["nodes"] > MAX_PARSE_NODES_PER_FILE:
            raise _IdentityError("parse node count exceeds limit")
        if type(node) is _Pairs:
            # Syntactic scan (DUP only): the node's FULL pair list, source
            # order, every occurrence of every exact key counted.
            occurrences: dict = {}
            for key, _value in node:
                occurrences[key] = occurrences.get(key, 0) + 1
            for key, count in occurrences.items():
                if count >= 2:
                    dups.append((path + (key,), count))
            # Effective scan: the ordered last-value mapping alone drives
            # structure, collisions, identity and recursion; shadowed
            # earlier values are never traversed.
            effective: dict = {}
            for key, value in node:
                effective[key] = value
            structure.append((path, len(effective), False))
            groups: dict = {}
            for key in effective:
                groups.setdefault(key.casefold(), []).append(key)
            for members in groups.values():
                if len(members) >= 2:
                    collisions.append(
                        (
                            path,
                            sorted(members, key=lambda m: (m.encode("utf-8"), m)),
                        )
                    )
            for key, value in effective.items():
                child = path + (key,)
                if type(value) is _Pairs or type(value) is list:
                    visit(value, child)
                else:
                    commit(child)
                    visit(value, child)
        elif type(node) is list:
            # Arrays are positional only: indices are never merged or
            # deduplicated, regardless of value equality.
            structure.append((path, len(node), True))
            for index, value in enumerate(node):
                child = path + (index,)
                if type(value) is _Pairs or type(value) is list:
                    visit(value, child)
                else:
                    commit(child)
                    visit(value, child)
        # Scalar leaves contribute no paths of their own.

    visit(tree, ())
    return identity, structure, collisions, dups


# --- Row rendering (display only; identity/order never depend on it) --------


def _scalar_type(value) -> str:
    if value is None:
        return "null"
    kind = type(value)
    if kind is bool:
        return "bool"
    if kind is int:
        return "int"
    if kind is float:
        return "float"
    return "string"


def _structure_text(payload) -> str:
    """STRUCTURE row text: root shape plus every container node's
    effective key count / array length in typed-path order."""
    root_desc, structure = payload
    parts = [root_desc]
    for path, count, is_array in sorted(structure, key=lambda n: _typed_key(n[0])):
        if path == ():
            continue
        label = _display_path(path)
        parts.append(f"{label} len={count}" if is_array else f"{label} keys={count}")
    return "STRUCTURE " + "; ".join(parts)


def _render_row(row) -> str:
    """Render one collected row to its display text (D-5)."""
    kind, payload = row[4], row[5]
    if kind == "STRUCTURE":
        return _structure_text(payload)
    if kind == "COLLISION":
        node_path, members = payload
        rendered = ",".join(_display_segment(m) for m in members)
        return f"COLLISION {_display_path(node_path)} {{{rendered}}}"
    if kind == "DUP":
        dup_path, count = payload
        return f"DUP {_display_path(dup_path)} ({count} occurrences; last value kept)"
    if kind == "MISSING":
        return f"MISSING {_display_path(payload)}"
    if kind == "EXTRA":
        return f"EXTRA {_display_path(payload)}"
    error_kind, message = payload
    return f"ERROR ({error_kind}): {message}"


# --- Reference parsing (comparison input; failures never enter the target
# error counters — D-3) -------------------------------------------------------


def _reference_identity(ref_path: Path):
    """Parse the reference file with the same gates as a target.

    Returns ``(status, limited_reason, identity)``: status is ``VALID`` or
    one of ``READ-ERROR`` / ``DECODE-ERROR`` / ``OVERSIZED`` / ``DEPTH`` /
    ``PARSE-ERROR`` / ``IDENTITY``; identity is the reference's effective
    last-value path set when valid, else ``None``."""
    try:
        if not ref_path.is_file():
            return "READ-ERROR", "read-error", None
        if ref_path.stat().st_size > MAX_FILE_BYTES:
            return "OVERSIZED", "oversized", None
        data = ref_path.read_bytes()
    except OSError:
        return "READ-ERROR", "read-error", None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "DECODE-ERROR", "decode-error", None
    if _max_nesting(text) > MAX_JSON_DEPTH:
        return "DEPTH", "depth", None
    try:
        tree = json.loads(text, object_pairs_hook=_Pairs)
    except (ValueError, RecursionError):
        return "PARSE-ERROR", "parse-error", None
    try:
        identity, _structure, _collisions, _dups = _flatten(tree)
    except _IdentityError:
        return "IDENTITY", "identity", None
    return "VALID", "", identity


# --- Bounded enumeration (D-6) -----------------------------------------------


def _locale_files(root: Path, file_pattern: str, enum_state: dict) -> list[Path]:
    """Enumerate ``.json`` locale files under ``root`` (bounded walk).

    Ignored directories are pruned, ``file_pattern`` matches the basename,
    ignored paths are skipped, and undecodable path components are skipped
    while flagging ``encoding_error``. Directory-listing failures flag
    ``walk_error``. The walk stops (conservatively incomplete) as soon as
    ``MAX_ENUMERATE_FILES`` files are discovered: reaching exactly the cap
    proves nothing about the rest of the tree."""
    discovered: list[Path] = []

    def on_walk_error(_err: OSError) -> None:
        enum_state["walk_error"] = True

    for current_root, dirs, files in os.walk(root, onerror=on_walk_error):
        current = Path(current_root)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        for filename in files:
            if len(discovered) >= MAX_ENUMERATE_FILES:
                return discovered
            if not fnmatch.fnmatch(filename, file_pattern):
                continue
            path = current / filename
            if path.suffix.lower() != JSON_SUFFIX:
                continue
            if is_ignored_path(path):
                continue
            try:
                relative = path.relative_to(project_root()).as_posix()
                relative.encode("utf-8", "strict")
            except (ValueError, UnicodeEncodeError):
                enum_state["encoding_error"] = True
                continue
            discovered.append(path)
    return discovered


def _rel_bytes(path: Path) -> bytes:
    """Deterministic file ordering key: relative POSIX path as UTF-8."""
    return path.relative_to(project_root()).as_posix().encode("utf-8")


def _rel_str(path: Path) -> str:
    """Relative POSIX path string for row display prefixes."""
    return path.relative_to(project_root()).as_posix()


def _analyze(target: Path) -> dict:
    """Gate one target through read/decode/depth/parse/flatten (D-7 4a-4d).

    Returns a dict with ``status`` (``complete`` or ``error``) and, on
    success, the flatten products; on failure the approved error kind,
    message and accounting gate (``rdo`` = read/decode/oversized, which
    makes the file not-examined; ``unknown`` = depth/parse/identity,
    which makes it examined-but-findings-unknown). A failed or partially
    flattened target never generates ordinary comparison rows."""
    try:
        size = target.stat().st_size
    except OSError:
        size = -1
    if size >= 0 and size > MAX_FILE_BYTES:
        return {
            "status": "error",
            "gate": "rdo",
            "error_kind": "OVERSIZED",
            "error_message": f"file exceeds {MAX_FILE_BYTES:,} byte safety limit",
        }
    try:
        data = target.read_bytes()
    except OSError as exc:
        return {
            "status": "error",
            "gate": "rdo",
            "error_kind": "READ",
            "error_message": f"unreadable file ({exc.__class__.__name__})",
        }
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": "error",
            "gate": "rdo",
            "error_kind": "DECODE",
            "error_message": "file is not valid UTF-8",
        }
    depth = _max_nesting(text)
    if depth > MAX_JSON_DEPTH:
        return {
            "status": "error",
            "gate": "unknown",
            "error_kind": "DEPTH",
            "error_message": f"nesting depth {depth} exceeds limit {MAX_JSON_DEPTH}",
        }
    try:
        tree = json.loads(text, object_pairs_hook=_Pairs)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "gate": "unknown",
            "error_kind": "PARSE",
            "error_message": f"line {exc.lineno}, col {exc.colno}: {exc.msg}",
        }
    except (ValueError, RecursionError) as exc:
        return {
            "status": "error",
            "gate": "unknown",
            "error_kind": "PARSE",
            "error_message": str(exc) or exc.__class__.__name__,
        }
    try:
        identity, structure, collisions, dups = _flatten(tree)
    except _IdentityError as exc:
        return {
            "status": "error",
            "gate": "unknown",
            "error_kind": "IDENTITY",
            "error_message": str(exc),
        }
    if not structure:
        root_desc = f"root=scalar {_scalar_type(tree)}"
    else:
        _path, count, is_array = structure[0]
        root_desc = (
            f"root=array len={count}" if is_array else f"root=object keys={count}"
        )
    return {
        "status": "complete",
        "identity": identity,
        "structure": structure,
        "collisions": collisions,
        "dups": dups,
        "root_desc": root_desc,
    }


# --- mcquest_locale_inspect (Stage 3 tool) -----------------------------------


def locale_inspect(
    path: str = ".",
    reference: str = "",
    file_pattern: str = "*.json",
    max_results: int = SEARCH_DEFAULT_RESULTS,
    offset: int = 0,
) -> str:
    """Inspect JSON locale files: structure, duplicate keys, casefold
    collisions, and — only with an explicit ``reference`` — MISSING/EXTRA
    key-path diffs.

    JSON only (``.json`` files; ``file_pattern`` matches the basename).
    ``reference=""`` means structure/collision/duplicate inspection only;
    no default locale is ever inferred. ``MISSING`` = present in the
    reference, absent in the target; ``EXTRA`` = present in the target,
    absent in the reference; comparisons run only when the reference is
    valid and the target is structurally complete, and are disabled
    globally when the reference fails (``REFERENCE_LIMITED``) — disabled
    comparisons make ``collection_complete=false`` unconditionally, even
    when the omission count is zero (zero omitted findings never implies
    comparisons were performed).

    Duplicate-preserving parse (D-1): duplicate keys are detected at
    effective object nodes over the full syntactic pair list; the
    effective structure follows the last occurrence; duplicates inside
    shadowed earlier subtrees are never traversed and never reported.

    Ordering (D-7): files in relative-path byte order; per-file rows by
    typed-path key then rank (STRUCTURE, COLLISION, MISSING, EXTRA, DUP,
    ERROR); per-file cap (``MAX_LOCALE_FILE_ROWS``) applied before the
    global cap (``MAX_LOCALE_ROWS``); once the global cap is exhausted
    the tool switches to counting mode — later files are fully analyzed
    but materialize nothing, and their exact ordinary-finding
    cardinalities are added to ``FINDINGS_OMITTED`` so the counts stay
    truthful. Population accounting (D-6) reports ``DISCOVERED`` /
    ``EXAMINED`` / ``files_not_examined`` exactly when enumeration
    completed; any truncation (file-count cap, unreadable directory,
    undecodable path component) makes enumeration incomplete and reports
    ``files_not_examined_unknown: true`` with ``ENUM_LIMIT`` or
    ``ENUM_REASON`` instead of exact totals.

    Paths render JSON-quoted keys and ``[i]`` array indices (``"0"`` is a
    string key, ``[0]`` an array index — never confused); the root renders
    ``<root>``. Display clipping is renderer-only (200-character atomic
    line clip) and never merges distinct paths.

    Read-only, deterministic, confined to the project root."""
    max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if not file_pattern:
        raise ValueError("file_pattern must not be empty")

    root = resolve_project_path(path)
    if not root.exists():
        raise FileNotFoundError(path)

    # Reference (D-3): parsed with the same gates as a target; any failure
    # disables comparisons globally and is disclosed via REFERENCE_STATUS /
    # REFERENCE_LIMITED — never via the target error counters.
    ref_status = "none"
    ref_limited = ""
    ref_identity: set | None = None
    if reference:
        ref_path = resolve_project_path(reference)
        ref_status, ref_limited, ref_identity = _reference_identity(ref_path)

    # Enumeration + population accounting (D-6).
    enum_state = {"walk_error": False, "encoding_error": False}
    if root.is_file():
        if is_ignored_path(root):
            raise ValueError(f"File is inside an ignored directory: {path}")
        discovered = [root]
        hit_cap = False
    else:
        discovered = _locale_files(root, file_pattern, enum_state)
        hit_cap = len(discovered) >= MAX_ENUMERATE_FILES
    enum_complete = (
        not hit_cap
        and not enum_state["walk_error"]
        and not enum_state["encoding_error"]
    )

    # Candidates: deterministic byte order, bounded to MAX_LOCALE_FILES.
    candidates = sorted(discovered, key=_rel_bytes)[:MAX_LOCALE_FILES]
    not_examined = (
        max(len(discovered) - MAX_LOCALE_FILES, 0) if enum_complete else 0
    )

    # Single coherent algorithm (D-7): per-file caps before the global cap;
    # counting mode after the global cap is exhausted.
    rows: list[tuple] = []
    remaining = MAX_LOCALE_ROWS
    omitted = 0
    err_events: Counter = Counter()
    err_rows_collected = 0
    unknown_files = 0
    complete_files = 0
    eligible_files = 0
    files_affected = 0
    file_row_cap_engaged = False
    row_limit_engaged = False
    counting = False

    for target in candidates:
        result = _analyze(target)
        if result["status"] == "error":
            err_events[result["error_kind"]] += 1
            if result["gate"] == "rdo":
                not_examined += 1
            else:
                unknown_files += 1
            if counting:
                # Counting mode: accounting only, nothing is materialized.
                continue
            frows = [
                (
                    (),
                    _RANK_ERROR,
                    0,
                    _rel_str(target),
                    "ERROR",
                    (result["error_kind"], result["error_message"]),
                )
            ]
            ordinary_total = 0
        else:
            complete_files += 1
            eligible = ref_identity is not None
            if eligible:
                eligible_files += 1
                missing = sorted(
                    ref_identity - result["identity"], key=_typed_key
                )
                extra = sorted(
                    result["identity"] - ref_identity, key=_typed_key
                )
            else:
                missing = extra = []
            # Exact cardinality without materializing row objects (D-4):
            # 1 (structure) + collisions + dups + (missing + extra iff
            # eligible). Never includes error rows or disabled comparisons.
            ordinary_total = 1 + len(result["collisions"]) + len(result["dups"])
            if eligible:
                ordinary_total += len(missing) + len(extra)
            if counting:
                omitted += ordinary_total
                continue
            rel = _rel_str(target)
            frows = [
                (
                    (),
                    _RANK_STRUCTURE,
                    0,
                    rel,
                    "STRUCTURE",
                    (result["root_desc"], result["structure"]),
                )
            ]
            for node_path, members in result["collisions"]:
                frows.append(
                    (
                        _typed_key(node_path),
                        _RANK_COLLISION,
                        0,
                        rel,
                        "COLLISION",
                        (node_path, members),
                    )
                )
            for p in missing:
                frows.append((_typed_key(p), _RANK_MISSING, 0, rel, "MISSING", p))
            for p in extra:
                frows.append((_typed_key(p), _RANK_EXTRA, 0, rel, "EXTRA", p))
            for dup_path, count in result["dups"]:
                frows.append(
                    (_typed_key(dup_path), _RANK_DUP, 0, rel, "DUP", (dup_path, count))
                )
            frows.sort(key=lambda r: (r[0], r[1], r[2]))

        # Per-file cap, then global cap (D-7 4f/4g). An error row consumes
        # slots like any row; drops stay disclosed via the error counters.
        if len(frows) > MAX_LOCALE_FILE_ROWS:
            file_row_cap_engaged = True
        kept = frows[:MAX_LOCALE_FILE_ROWS]
        take = min(len(kept), remaining)
        taken = kept[:take]
        if taken:
            rows.extend(taken)
            files_affected += 1
        ordinary_emitted = sum(1 for r in taken if r[4] != "ERROR")
        omitted += ordinary_total - ordinary_emitted
        err_rows_collected += sum(1 for r in taken if r[4] == "ERROR")
        remaining -= take
        if remaining <= 0:
            counting = True
            row_limit_engaged = True

    total = len(rows)
    page_size = min(max_results, max(total - offset, 0))
    page = rows[offset : offset + page_size] if page_size > 0 else []
    items = [f"{row[3]}: {_render_row(row)}" for row in page]

    # collection_complete (D-4/D-6): comparisons-disabled => false
    # unconditionally (no reference or failed reference).
    collection_complete = (
        enum_complete
        and not_examined == 0
        and unknown_files == 0
        and ref_identity is not None
        and omitted == 0
    )
    error_rows_omitted = sum(err_events.values()) - err_rows_collected

    fields: dict[str, object] = {
        "PATH": path,
        "FILE_PATTERN": file_pattern,
        "REFERENCE": reference if reference else "(none)",
        "REFERENCE_STATUS": ref_status,
    }
    if ref_limited:
        fields["REFERENCE_LIMITED"] = ref_limited
    fields["COMPARISON_ELIGIBLE"] = eligible_files if ref_identity is not None else 0
    if enum_complete:
        fields["DISCOVERED"] = len(discovered)
        fields["EXAMINED"] = complete_files + unknown_files
        fields["files_not_examined"] = not_examined
    else:
        fields["files_not_examined_unknown"] = "true"
        if hit_cap:
            fields["ENUM_LIMIT"] = MAX_ENUMERATE_FILES
            fields["ENUM_REASON"] = "file-count-limit"
        elif enum_state["walk_error"]:
            fields["ENUM_REASON"] = "unreadable-directory"
        else:
            fields["ENUM_REASON"] = "path-encoding"
    if omitted > 0:
        fields["FINDINGS_OMITTED"] = omitted
    if unknown_files > 0:
        fields["FINDINGS_UNKNOWN"] = unknown_files
    if err_events:
        breakdown = ", ".join(
            f"{kind}={err_events[kind]}" for kind in sorted(err_events)
        )
        fields["ERROR_EVENTS"] = f"{sum(err_events.values())} ({breakdown})"
    if error_rows_omitted > 0:
        fields["ERROR_ROWS_OMITTED"] = error_rows_omitted
    if file_row_cap_engaged:
        fields["FILE_ROW_LIMIT"] = MAX_LOCALE_FILE_ROWS
    if row_limit_engaged:
        fields["ROW_LIMIT"] = MAX_LOCALE_ROWS
    fields["max_results"] = max_results

    return search_block(
        tool="mcquest_locale_inspect",
        path=path,
        items=items,
        total=total,
        files_affected=files_affected,
        offset=offset,
        fields=fields,
        expanded=offset > 0 or max_results > SEARCH_DEFAULT_RESULTS,
        collection_complete=collection_complete,
    )
