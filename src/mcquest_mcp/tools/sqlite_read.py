"""Read-only structured SQLite evidence (V1.1 Gate 1).

``mcquest_sqlite_read`` returns rows from a single ``SELECT`` statement
against one project-local SQLite database file. It is evidence
acquisition only: no writes, no administration, no execution.

Layered read-only model (Gate 0 audit sections 8-10):

1. path confinement -- ``resolve_project_path`` + ``validate_readable_file``
   (reused, never forked), caller ``file:`` URIs rejected;
2. server-built read-only connection (``mode=ro``, ``timeout=0``);
3. SQL policy -- single statement, first verb ``SELECT``/read-only ``WITH``,
   depth-0 deny-verbs, ``sqlite3.complete_statement`` cross-check;
4. SQLite authorizer deny-all except read actions;
5. resource bounds -- row cap, output ceiling, deterministic VM-step budget.

No wall-clock timeout is used (V0.9 decision A5); the step budget served
by ``set_progress_handler`` bounds runaway queries deterministically.
"""

from __future__ import annotations

import base64
import json
import sqlite3

from ..config import (
    LINE_CLIP_CHARS,
    MAX_FILE_BYTES,
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
    if file_path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(
            f"Database exceeds {MAX_FILE_BYTES:,} byte safety limit: {cleaned}"
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
            fetched = cursor.fetchmany(page_size + 1)
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
