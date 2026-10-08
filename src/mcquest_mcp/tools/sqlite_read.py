"""Read-only structured SQLite evidence (V1.1 Gate 1; V1.2 boundary update).

``mcquest_sqlite_read`` returns rows from a single ``SELECT`` statement
against one project-local SQLite database file. It is evidence
acquisition only: no writes, no administration, no execution.

Layered read-only model (Gate 0 audit sections 8-10; V1.2 adds 6-7):

1. path confinement -- ``resolve_project_path`` + ``validate_readable_file``
   (reused, never forked), caller ``file:`` URIs rejected;
2. server-built read-only connection (``mode=ro``, ``timeout=0``);
3. SQL policy -- single statement, first verb ``SELECT``/read-only ``WITH``,
   depth-0 deny-verbs, ``sqlite3.complete_statement`` cross-check;
4. SQLite authorizer deny-all except read actions;
5. resource bounds -- row cap, output ceiling, deterministic VM-step budget;
6. value-materialization bounds (V1.2) -- SQLite-side per-value length limit
   (``setlimit(SQLITE_LIMIT_LENGTH)``), result-column guard, and a Python-side
   per-page byte budget counted row by row;
7. file-size gate (V1.2) -- SQLite-specific ``SQLITE_MAX_FILE_BYTES``
   (32,000,000 decimal bytes, inclusive), replacing the shared generic
   ``MAX_FILE_BYTES`` for this tool only.

No wall-clock timeout is used (V0.9 decision A5); the step budget served
by ``set_progress_handler`` bounds runaway queries deterministically.

V1.2 keeps four resource dimensions distinct, each with its own control
(see ``Docs/V1.2/``): database file size != query execution cost !=
returned result size != value-materialization cost.
"""

from __future__ import annotations

import base64
import json
import sqlite3

from ..config import (
    LINE_CLIP_CHARS,
    MAX_OUTPUT_CHARS,
    MAX_SEARCH_RESULTS,
    NORMAL_OUTPUT_CHARS,
    SEARCH_DEFAULT_RESULTS,
)
from ..formatting import OutputBudget, summary_block
from ..security import validate_readable_file


SQLITE_MAGIC = b"SQLite format 3\x00"

SQLITE_DEFAULT_ROWS = SEARCH_DEFAULT_RESULTS  # 50
SQLITE_MAX_ROWS = MAX_SEARCH_RESULTS  # 500 hard cap
# 16_384: matches the shared MAX_INPUT_CHARS convention each shell/* module
# defines locally; no config.py constant exists for it.
SQLITE_QUERY_MAX_CHARS = 16_384

# Deterministic runaway-query bound: VM instructions executed before the
# progress handler aborts the query. No wall-clock involved (A5).
SQLITE_MAX_STEPS = 500_000
SQLITE_PROGRESS_EVERY = 1_000

# --- V1.2 HYBRID boundary (Gate 0 approved) -------------------------------
#
# Database file size != query execution cost != returned result size !=
# value-materialization cost. Each dimension gets its own control; none of
# the constants below is caller-configurable (server-side only, no tool
# argument, never influenced by user input).

# SQLite-specific file-size gate (replaces the shared generic MAX_FILE_BYTES
# for this tool only; config.MAX_FILE_BYTES is unchanged for every other
# tool). DECIMAL bytes, inclusive: a file of exactly this size is accepted,
# one byte more is rejected before the magic-header read or any SQLite open.
# Calibration basis (documented honestly, not a universal claim): the largest
# observed in-root PocketBase database at Gate 0 was auxiliary.db =
# 21,745,664 bytes; 32,000,000 gives ~1.47x headroom over that single
# observation. The motivating MCQuest data.db was 2,359,296 bytes.
SQLITE_MAX_FILE_BYTES = 32_000_000

# Value-materialization guard, three distinct bounds:
#
# 1) SQLITE_MAX_VALUE_BYTES -- SQLite-side PER-VALUE length limit via
#    connection.setlimit(SQLITE_LIMIT_LENGTH, ...). Runtime-verified
#    (Python 3.13.9 / SQLite 3.50.4): a value over the limit fails inside
#    SQLite as sqlite3.DataError("string or blob too big") BEFORE the value
#    crosses into Python, and the limit applies to values SQLite evaluates
#    (e.g. function arguments). It is NOT an aggregate memory budget: a
#    result row's total, or a whole page's total, may each exceed it, which
#    is why bounds 2 and 3 exist. Calibration: 1,000,000 bytes is ~51x the
#    largest value observed in the Gate 0 target database (19,545 chars).
SQLITE_MAX_VALUE_BYTES = 1_000_000

# 2) SQLITE_MAX_RESULT_COLUMNS -- Python-side width guard. cursor.description
#    is known after execute() and BEFORE any row is fetched, so an over-wide
#    result is rejected with zero rows pulled. This bounds the single-row
#    transient materialization to at most
#    SQLITE_MAX_RESULT_COLUMNS * SQLITE_MAX_VALUE_BYTES (64,000,000 bytes).
SQLITE_MAX_RESULT_COLUMNS = 64

# 3) SQLITE_MAX_FETCH_BYTES -- Python-side cumulative byte budget for one
#    result page, counted row by row while rows are pulled one at a time
#    (never via fetchmany), so Python-side accumulation cannot run past this
#    bound. Trip => deterministic ValueError before any output is built.
#    Calibration: 500 hard-cap rows x the ~19.5 KB largest observed value
#    class stays under it; the materialized page plus one in-flight row is
#    therefore capped well below ~80,000,000 bytes transient.
SQLITE_MAX_FETCH_BYTES = 16_000_000

# Verbs that may never appear as a bare word. Quoted identifiers and
# string literals never reach this set (the scanner only collects words
# outside strings/comments/quotes), while the authorizer remains the
# backstop for anything nested deeper.
_DENY_VERBS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        "CREATE",
        "ALTER",
        "DROP",
        "ATTACH",
        "DETACH",
        "VACUUM",
        "PRAGMA",
        "EXPLAIN",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "RELEASE",
        "REINDEX",
        "ANALYZE",
        "TRANSACTION",
        "VALUES",
        "TABLE",
    }
)

_READ_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
)

_ERROR_HINT = (
    "mcquest_sqlite_read accepts one read-only SELECT statement "
    "(read-only WITH...SELECT included) with optional ? parameters."
)


def _scan(text: str):
    """Tokenize top-level structure of one SQL text.

    Returns ``(words, semicolons, placeholders, named_params)`` where
    ``words`` is a list of bare upper-cased words outside
    strings/comments/quotes, ``semicolons`` the count of ``;`` outside
    strings/comments, ``placeholders`` the count of bare ``?`` markers,
    and ``named_params`` True when ``:name``/``@name``/``$name`` syntax
    appears. Raises ``ValueError`` on unterminated constructs.
    """
    words: list[str] = []
    semicolons = 0
    placeholders = 0
    named_params = False
    depth = 0
    buf: list[str] = []

    def flush() -> None:
        if buf:
            words.append("".join(buf).upper())
            buf.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        two = text[i : i + 2]
        if two == "--":
            flush()
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if two == "/*":
            flush()
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError(f"Unterminated block comment. {_ERROR_HINT}")
            i = end + 2
            continue
        if ch in ("'", '"', "`"):
            flush()
            j = i + 1
            while j < n:
                if text[j] == ch:
                    if j + 1 < n and text[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise ValueError(f"Unterminated string literal. {_ERROR_HINT}")
            i = j + 1
            continue
        if ch == "(":
            flush()
            depth += 1
            i += 1
            continue
        if ch == ")":
            flush()
            depth -= 1
            if depth < 0:
                raise ValueError(f"Unbalanced parenthesis. {_ERROR_HINT}")
            i += 1
            continue
        if ch == ";":
            flush()
            semicolons += 1
            i += 1
            continue
        if ch == "?":
            flush()
            placeholders += 1
            i += 1
            while i < n and text[i].isdigit():
                i += 1
            continue
        if ch in (":", "@", "$") and i + 1 < n and (
            text[i + 1].isalpha() or text[i + 1] == "_"
        ):
            named_params = True
            flush()
            i += 1
            continue
        if ch.isalpha() or ch == "_" or (buf and ch.isdigit()):
            buf.append(ch)
            i += 1
            continue
        flush()
        i += 1
    flush()
    if depth != 0:
        raise ValueError(f"Unbalanced parenthesis. {_ERROR_HINT}")
    return words, semicolons, placeholders, named_params


def _validate_query(query: str) -> int:
    """Enforce the single-statement read-only policy.

    Returns the ``?`` placeholder count. Raises ``ValueError`` with a
    deterministic policy message otherwise. This is layer 3; the
    authorizer (layer 4) independently denies anything non-read.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"Query must be a non-empty string. {_ERROR_HINT}")
    if len(query) > SQLITE_QUERY_MAX_CHARS:
        raise ValueError(
            f"Query exceeds the maximum of {SQLITE_QUERY_MAX_CHARS} characters. "
            f"{_ERROR_HINT}"
        )
    words, semicolons, placeholders, named_params = _scan(query)
    if named_params:
        raise ValueError(
            "Named parameters (:name/@name/$name) are not supported; "
            f"use ? placeholders with bound parameters. {_ERROR_HINT}"
        )
    if not words:
        raise ValueError(f"Query contains no statement. {_ERROR_HINT}")
    first = words[0]
    if first not in ("SELECT", "WITH"):
        raise ValueError(
            f"Only read-only SELECT statements are accepted (got {first}). "
            f"{_ERROR_HINT}"
        )
    for word in words:
        if word in _DENY_VERBS:
            raise ValueError(
                f"Statement type {word} is not permitted. {_ERROR_HINT}"
            )
    if semicolons > 1:
        raise ValueError(f"Only a single statement is accepted. {_ERROR_HINT}")
    if semicolons == 1 and not query.rstrip().endswith(";"):
        raise ValueError(f"Only a single statement is accepted. {_ERROR_HINT}")
    # complete_statement() is False for any string without a trailing ';',
    # so normalize first: the cross-check's real value is catching
    # unterminated string literals / block comments, not missing semicolons.
    probe = query.rstrip()
    if not probe.endswith(";"):
        probe += ";"
    if not sqlite3.complete_statement(probe):
        raise ValueError(f"Incomplete SQL statement. {_ERROR_HINT}")
    return placeholders


def _validate_database(database: str):
    """Resolve, confine, and gate the database file. Returns the path."""
    if not isinstance(database, str) or not database.strip():
        raise ValueError("Database must be a non-empty repository-relative path.")
    cleaned = database.strip()
    lowered = cleaned.lower()
    if lowered.startswith("file:"):
        raise ValueError(
            "SQLite URIs are not accepted as input; provide a "
            "repository-relative file path and the server opens "
            "its own read-only connection."
        )
    if "mode=" in lowered or "cache=" in lowered:
        raise ValueError(
            "Connection parameters are not accepted; provide a plain "
            "repository-relative file path."
        )
    file_path = validate_readable_file(cleaned)
    # V1.2: SQLite-specific gate (was the shared generic MAX_FILE_BYTES).
    # Runs BEFORE the magic-header read and before any SQLite open, so an
    # oversized file fails at the file-validation stage and never reaches
    # SQLite parsing. Inclusive: reject only when strictly greater.
    if file_path.stat().st_size > SQLITE_MAX_FILE_BYTES:
        raise ValueError(
            f"Database exceeds {SQLITE_MAX_FILE_BYTES:,} byte safety limit: {cleaned}"
        )
    with open(file_path, "rb") as handle:
        header = handle.read(len(SQLITE_MAGIC))
    if header != SQLITE_MAGIC:
        raise ValueError(f"Not a SQLite database file: {cleaned}")
    return file_path


def _check_parameters(parameters, expected: int) -> list:
    """Validate bound values; never interpolate. Returns a plain list."""
    if parameters is None:
        parameters = []
    if not isinstance(parameters, (list, tuple)):
        raise ValueError("Parameters must be a list of bound values.")
    values = list(parameters)
    if len(values) != expected:
        raise ValueError(
            f"Query has {expected} ? placeholder(s) but {len(values)} "
            f"parameter(s) were supplied. {_ERROR_HINT}"
        )
    bound: list = []
    for value in values:
        if value is None or isinstance(value, (str, int)):
            bound.append(value)
        elif isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("Non-finite float parameters are not accepted.")
            bound.append(value)
        elif isinstance(value, bool):
            bound.append(int(value))
        else:
            raise ValueError(
                f"Unsupported parameter type {type(value).__name__}; "
                "use str, int, float, bool, or null."
            )
    return bound


def _encode_value(value):
    """JSON-serializable encoding; BLOBs as base64 envelopes, never text."""
    if value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, bytes):
        return {
            "$blob": base64.b64encode(value).decode("ascii"),
            "bytes": len(value),
        }
    return str(value)


def _value_bytes(value) -> int:
    """Byte count of one materialized SQLite value for the V1.2 fetch budget.

    Counts UTF-8 bytes for TEXT (not code points, so multi-byte input cannot
    under-count the budget), raw length for BLOBs, zero for NULL, and a
    bounded string length for numbers. Values reaching this point are already
    capped at ``SQLITE_MAX_VALUE_BYTES`` by the SQLite-side per-value limit.
    """
    if value is None:
        return 0
    if isinstance(value, (bytes, memoryview)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(str(value))


def _authorizer(action, _arg1, _arg2, _dbname, _source):
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS else sqlite3.SQLITE_DENY


def sqlite_read(
    database: str,
    query: str,
    parameters: list | tuple | None = None,
    max_rows: int = SQLITE_DEFAULT_ROWS,
) -> str:
    """Read structured rows from one SELECT against a project-local database.

    Read-only, deterministic, confined to the project root. Returns a
    summary-first text report (``[SUMMARY]`` / row lines / ``[END]``)
    following the repository output conventions.

    V1.2 validation order (the V1.1 fail-closed order is preserved; the
    materialization guards are added after the connection opens):

    query policy -> bound parameters -> path/readable/file-size/magic ->
    max_rows clamp -> read-only URI connect -> per-value setlimit ->
    authorizer -> progress handler -> execute -> result-column guard ->
    row-by-row fetch under the byte budget -> encode -> output budget.

    A materialization guard trip raises ``ValueError`` before any output is
    built: no partial rows are returned and no ``truncated`` /
    ``collection_complete`` claim is made.
    """
    placeholders = _validate_query(query)
    bound = _check_parameters(parameters, placeholders)
    file_path = _validate_database(database)

    if isinstance(max_rows, bool) or not isinstance(max_rows, int):
        raise ValueError("max_rows must be an int.")
    page_size = min(max(max_rows, 1), SQLITE_MAX_ROWS)

    uri = file_path.as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0)
    except sqlite3.Error as exc:
        raise ValueError(f"Database unavailable: {exc}") from exc
    try:
        # V1.2 layer 6a: SQLite-side PER-VALUE length limit. Runtime-verified
        # behavior (Python 3.13.9 / SQLite 3.50.4): a value over the limit
        # raises sqlite3.DataError("string or blob too big") inside SQLite
        # before the value crosses into Python. The limit is per value only --
        # it does NOT bound the sum of one row or of a result page, so the
        # Python-side guards below remain necessary. Connection.setlimit
        # exists only on Python 3.12+; fail closed rather than silently
        # serving without the per-value bound.
        if not hasattr(connection, "setlimit"):
            raise ValueError(
                "SQLite value-materialization guard requires Python 3.12+ "
                "(Connection.setlimit unavailable); refusing to run without "
                "the per-value safety limit."
            )
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQLITE_MAX_VALUE_BYTES)
        connection.set_authorizer(_authorizer)
        steps = [0]

        def _progress() -> int:
            steps[0] += SQLITE_PROGRESS_EVERY
            return 1 if steps[0] > SQLITE_MAX_STEPS else 0

        connection.set_progress_handler(_progress, SQLITE_PROGRESS_EVERY)
        try:
            cursor = connection.execute(query, bound)
            columns = (
                [d[0] for d in cursor.description] if cursor.description else []
            )
            # V1.2 layer 6b: result-width guard. cursor.description exists
            # after execute() and BEFORE any row is fetched, so an over-wide
            # result is rejected with zero rows pulled; this bounds the
            # single-row transient to columns * SQLITE_MAX_VALUE_BYTES.
            if len(columns) > SQLITE_MAX_RESULT_COLUMNS:
                raise ValueError(
                    f"Query returns {len(columns)} columns; the materialization "
                    f"guard allows at most {SQLITE_MAX_RESULT_COLUMNS}. Select "
                    f"fewer columns. {_ERROR_HINT}"
                )
            # V1.2 layer 6c: Python-side byte budget counted row by row
            # (never fetchmany), so page materialization stops at
            # SQLITE_MAX_FETCH_BYTES instead of accumulating unbounded.
            # The page_size + 1 peek row of the V1.1 row-cap contract is kept.
            fetched: list[tuple] = []
            fetch_bytes = 0
            while len(fetched) <= page_size:
                row = cursor.fetchone()
                if row is None:
                    break
                fetched.append(row)
                for value in row:
                    fetch_bytes += _value_bytes(value)
                if fetch_bytes > SQLITE_MAX_FETCH_BYTES:
                    raise ValueError(
                        f"Query results exceed the {SQLITE_MAX_FETCH_BYTES:,}-byte "
                        f"materialization safety budget. {_ERROR_HINT}"
                    )
        except sqlite3.DataError as exc:
            # SQLITE_TOOBIG from the per-value setlimit above (or a function
            # argument over the limit). Message-gated so any other DataError
            # keeps the generic V1.1 SQLite error shape.
            if "too big" in str(exc):
                raise ValueError(
                    f"SQLite value exceeds the {SQLITE_MAX_VALUE_BYTES:,}-byte "
                    f"materialization safety limit. {_ERROR_HINT}"
                ) from exc
            raise ValueError(f"SQLite error: {exc}") from exc
        except sqlite3.OperationalError as exc:
            message = str(exc)
            if "interrupted" in message:
                raise ValueError(
                    "Query exceeded the deterministic step budget and was aborted."
                ) from exc
            if "locked" in message or "busy" in message:
                raise ValueError(
                    "Database is locked/busy; no retry was attempted."
                ) from exc
            if "denied" in message or "authoriz" in message:
                raise ValueError(
                    f"Statement denied by the read-only authorizer. {_ERROR_HINT}"
                ) from exc
            raise ValueError(f"SQLite error: {message}") from exc
        except sqlite3.Error as exc:
            raise ValueError(f"SQLite error: {exc}") from exc
    finally:
        connection.close()

    row_capped = len(fetched) > page_size
    rows = fetched[:page_size]
    encoded = [[_encode_value(v) for v in row] for row in rows]

    budget = OutputBudget(
        normal=NORMAL_OUTPUT_CHARS, ceiling=MAX_OUTPUT_CHARS, clip=LINE_CLIP_CHARS
    )
    lines: list[str] = [f"columns: {json.dumps(columns, ensure_ascii=False)}"]
    for row in encoded:
        lines.append(json.dumps(row, ensure_ascii=False))
    emitted = 0
    for line in lines:
        if not budget.add_clipped_line(line):
            break
        emitted += 1
    output_cut = emitted < len(lines)
    truncated = row_capped or output_cut
    collection_complete = not truncated

    fields: dict[str, object] = {
        "DATABASE": database.strip(),
        "QUERY": query.strip(),
        "columns": len(columns),
        "row_count": len(rows),
        "returned": len(rows),
        "truncated": "true" if truncated else "false",
        "collection_complete": "true" if collection_complete else "false",
        "read_only": "true",
        "max_rows": page_size,
        "budget": f"{NORMAL_OUTPUT_CHARS}/{MAX_OUTPUT_CHARS}",
    }
    budget.add_header(summary_block("mcquest_sqlite_read", fields))
    if not truncated:
        budget.add_clipped_line("[END]")
    return budget.finalize()
