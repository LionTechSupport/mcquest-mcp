"""V1.1 Gate 1: ``mcquest_sqlite_read`` contract, security, and bounds tests.

Implements the Gate 0 test matrix (``Docs/V1.1/00-V1.1-GATE-0-SQLITE-AUDIT.md``
section 18): positive SELECT coverage, negative policy coverage where every
mutation attempt proves the database stayed byte-identical (sha256 before vs
after), path-policy coverage, resource bounds, deterministic error mapping,
and routing/discoverability.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from mcquest_mcp.server import mcp
from mcquest_mcp.shell import capabilities as registry
from mcquest_mcp.tools.sqlite_read import SQLITE_QUERY_MAX_CHARS, sqlite_read


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def evidence_db(repo: str) -> str:
    """PocketBase-shaped SQLite database inside the temporary project root."""
    relative = "pb_data/data.db"
    path = Path(repo) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE _collections (
                name TEXT PRIMARY KEY, listRule TEXT, viewRule TEXT
            );
            CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT);
            CREATE TABLE quizzes (
                id TEXT PRIMARY KEY, title TEXT, price_status TEXT,
                admin_price_override TEXT, created_by TEXT, published INTEGER
            );
            CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT);
            CREATE TABLE blobs (id INTEGER PRIMARY KEY, data BLOB);
            """
        )
        connection.execute(
            "INSERT INTO _collections VALUES (?, ?, ?)",
            ("quizzes", "@request.auth.id != ''", ""),
        )
        connection.executemany(
            "INSERT INTO users VALUES (?, ?)",
            [("u1", "alice@example.com"), ("u2", "bob@example.com")],
        )
        connection.executemany(
            "INSERT INTO quizzes VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    f"q{i:02d}",
                    f"Quiz {i:02d}",
                    "free" if i % 2 else "paid",
                    None,
                    "u1" if i <= 6 else "u2",
                    i % 2,
                )
                for i in range(1, 11)
            ],
        )
        connection.executemany(
            "INSERT INTO notes VALUES (?, ?)",
            [
                (1, "café 日本語 \U0001f680"),
                (2, "it's a -- comment; SELECT nothing"),
                (3, None),
                (4, ""),
            ],
        )
        connection.execute(
            "INSERT INTO blobs VALUES (?, ?)", (1, b"\x00\x01\x02\xff")
        )
        connection.commit()
    finally:
        connection.close()
    return relative


@pytest.fixture
def bulk_db(repo: str) -> str:
    """Database with enough wide rows to trip the output ceiling."""
    relative = "bulk.db"
    path = Path(repo) / relative
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE bulk (id INTEGER PRIMARY KEY, body TEXT)")
        connection.executemany(
            "INSERT INTO bulk (body) VALUES (?)",
            [(f"row {i:04d} " + "x" * 280,) for i in range(600)],
        )
        connection.commit()
    finally:
        connection.close()
    return relative


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _digest(repo: str, relative: str) -> str:
    return hashlib.sha256((Path(repo) / relative).read_bytes()).hexdigest()


def _assert_rejected_unchanged(
    repo: str,
    database: str,
    query: str,
    match: str | None = None,
) -> None:
    """A rejected call must leave the target file byte-identical."""
    before = _digest(repo, database)
    if match is None:
        with pytest.raises(ValueError):
            sqlite_read(database, query)
    else:
        with pytest.raises(ValueError, match=match):
            sqlite_read(database, query)
    assert _digest(repo, database) == before, "database bytes changed on rejection"


# ---------------------------------------------------------------------------
# Positive coverage
# ---------------------------------------------------------------------------


def test_simple_select(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT id, title FROM quizzes ORDER BY id")
    assert "tool: mcquest_sqlite_read" in output
    assert "[EVIDENCE]" in output
    assert '["q01", "Quiz 01"]' in output
    assert '["q10", "Quiz 10"]' in output
    assert "row_count: 10" in output
    assert "returned: 10" in output
    assert "truncated: false" in output
    assert "collection_complete: true" in output
    assert "read_only: true" in output
    assert output.rstrip().endswith("[END]")


def test_where_clause(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "SELECT id FROM quizzes WHERE price_status = 'free' ORDER BY id",
    )
    assert "row_count: 5" in output
    assert '["q01"]' in output
    assert '["q02"]' not in output


def test_order_by_is_deterministic(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT id FROM quizzes ORDER BY id DESC")
    assert output.index('["q10"]') < output.index('["q09"]')
    assert output.index('["q09"]') < output.index('["q08"]')


def test_limit_clause(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT id FROM quizzes ORDER BY id LIMIT 4")
    assert "row_count: 4" in output
    assert '["q04"]' in output
    assert '["q05"]' not in output


def test_join(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "SELECT q.title, u.email FROM quizzes q "
        "JOIN users u ON q.created_by = u.id "
        "WHERE u.email = 'alice@example.com' ORDER BY q.id",
    )
    assert "row_count: 6" in output
    assert '"alice@example.com"' in output
    assert '"bob@example.com"' not in output


def test_aggregate(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT COUNT(*) AS total FROM quizzes")
    assert 'columns: ["total"]' in output
    assert "\n[10]\n" in output


def test_recursive_cte(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL "
        "SELECT n + 1 FROM c WHERE n < 5) SELECT n FROM c",
    )
    assert "row_count: 5" in output
    assert "\n[5]\n" in output


def test_sqlite_master_schema_read(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
    )
    for table in ("blobs", "notes", "quizzes", "users", "_collections"):
        assert f'["{table}"]' in output


def test_pocketbase_collection_rules_query(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "SELECT name, listRule, viewRule FROM _collections "
        "WHERE name = 'quizzes'",
    )
    assert "row_count: 1" in output
    assert '"quizzes"' in output
    assert "@request.auth.id" in output


def test_pocketbase_user_scoped_query_with_parameters(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "SELECT id, title, price_status, admin_price_override, "
        "created_by, published FROM quizzes WHERE created_by IN "
        "(SELECT id FROM users WHERE email = ?) LIMIT 10",
        parameters=["alice@example.com"],
    )
    assert "row_count: 6" in output
    assert '["q01", "Quiz 01", "free", null, "u1", 1]' in output
    assert '["q07"' not in output


def test_bound_parameters_never_interpolated(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db,
        "SELECT id FROM quizzes WHERE created_by = ? AND published = ? ORDER BY id",
        parameters=["u1", 1],
    )
    assert "row_count: 3" in output
    assert '["q01"]' in output
    # The bound value never appears in the executed-SQL echo in the summary.
    summary = output.split("[EVIDENCE]")[0]
    query_echo = summary.split("QUERY:", 1)[1].split("\n", 1)[0]
    assert "u1" not in query_echo


def test_blob_base64_envelope(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT data FROM blobs")
    assert '"$blob"' in output
    assert '"AAEC/w=="' in output
    assert '"bytes": 4' in output
    # The raw bytes must never be rendered as lossy text.
    assert "\x00" not in output


def test_null_and_empty_string_distinct(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db, "SELECT id, body FROM notes WHERE id IN (3, 4) ORDER BY id"
    )
    assert "\n[3, null]\n" in output
    assert '\n[4, ""]\n' in output


def test_unicode_preserved(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT body FROM notes WHERE id = 1")
    assert "café 日本語 \U0001f680" in output


def test_column_order_deterministic_across_runs(evidence_db: str) -> None:
    query = "SELECT id, title, created_by FROM quizzes WHERE id = 'q01'"
    first = sqlite_read(evidence_db, query)
    second = sqlite_read(evidence_db, query)
    assert first == second
    assert '["id", "title", "created_by"]' in first


def test_trailing_semicolon_accepted(evidence_db: str) -> None:
    output = sqlite_read(evidence_db, "SELECT id FROM quizzes LIMIT 1;")
    assert "row_count: 1" in output


def test_db_byte_identical_after_reads(evidence_db: str, repo: str) -> None:
    before = _digest(repo, evidence_db)
    sqlite_read(evidence_db, "SELECT COUNT(*) FROM quizzes")
    sqlite_read(evidence_db, "SELECT id FROM quizzes ORDER BY id")
    assert _digest(repo, evidence_db) == before


# ---------------------------------------------------------------------------
# Negative coverage: statement policy (each proves byte-identical DB)
# ---------------------------------------------------------------------------

_MUTATIONS = [
    "INSERT INTO quizzes (id) VALUES ('hacked')",
    "UPDATE quizzes SET title = 'hacked'",
    "DELETE FROM quizzes",
    "REPLACE INTO quizzes (id) VALUES ('q01')",
    "CREATE TABLE pwn (x INTEGER)",
    "ALTER TABLE quizzes ADD COLUMN pwn TEXT",
    "DROP TABLE quizzes",
    "ATTACH DATABASE 'other.db' AS other",
    "DETACH DATABASE other",
    "VACUUM",
    "PRAGMA journal_mode",
    "EXPLAIN SELECT * FROM quizzes",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "ANALYZE",
    "REINDEX",
]


@pytest.mark.parametrize("query", _MUTATIONS)
def test_non_select_statement_rejected_unchanged(
    evidence_db: str, repo: str, query: str
) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        query,
        match="read-only SELECT statements are accepted",
    )


def test_comment_prefixed_mutation_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "-- harmless looking comment\nDELETE FROM quizzes",
        match="read-only SELECT statements are accepted",
    )


def test_block_comment_prefixed_mutation_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "/* harmless */ UPDATE quizzes SET title = 'x'",
        match="read-only SELECT statements are accepted",
    )


def test_cte_wrapped_mutation_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "WITH d AS (DELETE FROM quizzes RETURNING id) SELECT * FROM d",
        match="Statement type DELETE is not permitted",
    )


def test_cte_nested_update_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "WITH x AS (SELECT 1), y AS (UPDATE quizzes SET title = 'x') "
        "SELECT * FROM x",
        match="Statement type UPDATE is not permitted",
    )


def test_multiple_statements_rejected(evidence_db: str, repo: str) -> None:
    for query in (
        "SELECT 1; SELECT 2",
        "SELECT id FROM quizzes;\nSELECT title FROM quizzes",
    ):
        _assert_rejected_unchanged(
            repo, evidence_db, query, match="single statement is accepted"
        )


def test_multiple_statements_with_mutation_rejected(
    evidence_db: str, repo: str
) -> None:
    # Deny-verbs are scanned before the semicolon count, so a SELECT;mutation
    # pair reports the statement-type error first; either way it is rejected
    # with a deterministic policy error and an unchanged database.
    for query in (
        "SELECT id FROM quizzes; DELETE FROM quizzes;",
        "SELECT id FROM quizzes;\nDROP TABLE quizzes;",
    ):
        _assert_rejected_unchanged(
            repo, evidence_db, query, match="not permitted"
        )


def test_trailing_garbage_after_semicolon_rejected(
    evidence_db: str, repo: str
) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "SELECT id FROM quizzes; garbage_here",
        match="single statement is accepted",
    )


def test_load_extension_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "SELECT load_extension('some_ext')",
        match="denied by the read-only authorizer",
    )


def test_empty_query_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        sqlite_read(evidence_db, "   ")


def test_non_string_query_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        sqlite_read(evidence_db, 123)  # type: ignore[arg-type]


def test_unterminated_string_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo,
        evidence_db,
        "SELECT * FROM quizzes WHERE id = 'q01",
        match="Unterminated string literal",
    )


def test_unbalanced_parenthesis_rejected(evidence_db: str, repo: str) -> None:
    _assert_rejected_unchanged(
        repo, evidence_db, "SELECT (1 FROM quizzes", match="Unbalanced parenthesis"
    )


def test_named_parameters_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="Named parameters"):
        sqlite_read(evidence_db, "SELECT * FROM quizzes WHERE id = :id")


def test_parameter_count_mismatch_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="were supplied"):
        sqlite_read(evidence_db, "SELECT id FROM quizzes WHERE created_by = ?", [])


def test_parameters_must_be_list(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="Parameters must be a list"):
        sqlite_read(evidence_db, "SELECT 1", parameters="u1")  # type: ignore[arg-type]


def test_unsupported_parameter_type_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="Unsupported parameter type"):
        sqlite_read(
            evidence_db,
            "SELECT id FROM quizzes WHERE id = ?",
            parameters=[{"nested": "object"}],
        )


def test_non_finite_float_parameter_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="Non-finite float"):
        sqlite_read(
            evidence_db, "SELECT 1 WHERE 1 = ?", parameters=[float("inf")]
        )


# ---------------------------------------------------------------------------
# Path policy
# ---------------------------------------------------------------------------


def test_traversal_path_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="escapes MCQuest project root"):
        sqlite_read("../outside.db", "SELECT 1")
    with pytest.raises(ValueError, match="escapes MCQuest project root"):
        sqlite_read("pb_data/../../escape.db", "SELECT 1")


def test_absolute_path_outside_root_rejected(repo: str) -> None:
    outside = Path(repo).parent / "outside_evidence.db"
    connection = sqlite3.connect(outside)
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.commit()
    connection.close()
    before = hashlib.sha256(outside.read_bytes()).hexdigest()
    try:
        with pytest.raises(ValueError, match="escapes MCQuest project root"):
            sqlite_read(str(outside), "SELECT 1")
        assert hashlib.sha256(outside.read_bytes()).hexdigest() == before
    finally:
        outside.unlink(missing_ok=True)


def test_file_uri_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="SQLite URIs are not accepted"):
        sqlite_read(f"file:{evidence_db}?mode=ro", "SELECT 1")


def test_connection_parameters_rejected(evidence_db: str) -> None:
    for suffix in ("?mode=rw", "?mode=rwc", "?cache=shared"):
        with pytest.raises(ValueError, match="Connection parameters are not accepted"):
            sqlite_read(f"{evidence_db}{suffix}", "SELECT 1")


def test_missing_database_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        sqlite_read("does_not_exist.db", "SELECT 1")


def test_directory_rejected(evidence_db: str) -> None:
    with pytest.raises(ValueError, match="Not a file"):
        sqlite_read("pb_data", "SELECT 1")


def test_non_sqlite_file_rejected(write_file, repo: str) -> None:
    relative = write_file("notes.txt", "plain text, not a database")
    before = _digest(repo, relative)
    with pytest.raises(ValueError, match="Not a SQLite database file"):
        sqlite_read(relative, "SELECT 1")
    assert _digest(repo, relative) == before


def test_malformed_database_rejected(repo: str) -> None:
    path = Path(repo) / "broken.db"
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        sqlite_read("broken.db", "SELECT 1")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_symlink_escape_rejected(repo: str) -> None:
    outside = Path(repo).parent / "symlink_target.db"
    connection = sqlite3.connect(outside)
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.commit()
    connection.close()
    link = Path(repo) / "link.db"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        outside.unlink(missing_ok=True)
        pytest.skip("symlink creation not permitted on this platform")
    try:
        with pytest.raises(ValueError, match="escapes MCQuest project root"):
            sqlite_read("link.db", "SELECT 1")
    finally:
        link.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Resource bounds
# ---------------------------------------------------------------------------


def test_row_cap_truncates(evidence_db: str) -> None:
    output = sqlite_read(
        evidence_db, "SELECT id FROM quizzes ORDER BY id", max_rows=3
    )
    assert "row_count: 3" in output
    assert "returned: 3" in output
    assert "max_rows: 3" in output
    assert "truncated: true" in output
    assert "collection_complete: false" in output
    assert not output.rstrip().endswith("[END]")


def test_output_ceiling_truncates(bulk_db: str) -> None:
    # Exactly 500 SQL rows, so truncation can only come from the output budget.
    output = sqlite_read(bulk_db, "SELECT id, body FROM bulk LIMIT 500", max_rows=500)
    assert "row_count: 500" in output
    assert "truncated: true" in output
    assert "collection_complete: false" in output
    assert not output.rstrip().endswith("[END]")


def test_max_rows_clamped_to_hard_cap(bulk_db: str) -> None:
    output = sqlite_read(bulk_db, "SELECT id FROM bulk", max_rows=999_999)
    assert "max_rows: 500" in output


def test_query_length_limit(evidence_db: str) -> None:
    with pytest.raises(
        ValueError, match=f"exceeds the maximum of {SQLITE_QUERY_MAX_CHARS}"
    ):
        sqlite_read(evidence_db, "SELECT 1 " + "x" * SQLITE_QUERY_MAX_CHARS)


def test_max_rows_type_validation(evidence_db: str) -> None:
    for bad in (True, "10", 1.5):
        with pytest.raises(ValueError, match="max_rows must be an int"):
            sqlite_read(evidence_db, "SELECT 1", max_rows=bad)  # type: ignore[arg-type]


def test_step_budget_aborts_runaway_query(evidence_db: str, repo: str) -> None:
    before = _digest(repo, evidence_db)
    with pytest.raises(ValueError, match="step budget"):
        sqlite_read(
            evidence_db,
            "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) "
            "SELECT count(*) FROM c",
        )
    assert _digest(repo, evidence_db) == before


def test_locked_database_is_deterministic_error(evidence_db: str, repo: str) -> None:
    writer = sqlite3.connect(Path(repo) / evidence_db)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute("INSERT INTO quizzes (id) VALUES ('q99')")
        with pytest.raises(ValueError, match="locked/busy; no retry"):
            sqlite_read(evidence_db, "SELECT id FROM quizzes")
    finally:
        writer.rollback()
        writer.close()


# ---------------------------------------------------------------------------
# Registration and discoverability
# ---------------------------------------------------------------------------


def test_tool_registered_with_contract_schema() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_sqlite_read")
    assert tool.input_schema["required"] == ["database", "query"]
    properties = tool.input_schema["properties"]
    assert set(properties) == {"database", "query", "parameters", "max_rows"}
    for name in properties:
        description = properties[name].get("description")
        assert isinstance(description, str) and description.strip()
    assert properties["max_rows"]["default"] == 50
    assert properties["parameters"]["default"] is None


def test_description_states_read_only_evidence_scope() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_sqlite_read")
    assert "READ ONLY" in tool.description
    assert "read-only SELECT" in tool.description
    assert "SQLite" in tool.description


def test_instructions_route_sqlite_reads_away_from_shell() -> None:
    assert mcp.instructions is not None
    assert "mcquest_sqlite_read" in mcp.instructions
    assert "temporary Python/shell" in mcp.instructions


def test_read_sqlite_operation_class_registered() -> None:
    assert "READ_SQLITE" in registry.OPERATION_CLASSES
    row = next(
        r for r in registry.CAPABILITIES if r.name == "mcquest_sqlite_read"
    )
    assert row.read_only is True
    assert row.phase == "V1.1"
    assert "SQLITE_READ" in row.intent_tags
    assert "READ_SQLITE" in row.intent_tags
    assert row.scope == "repository"
