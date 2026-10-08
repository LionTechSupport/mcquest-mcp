"""V1.2 Gate 1: SQLite size-boundary and value-materialization tests.

Covers the approved HYBRID model on top of the frozen V1.1 suite
(``tests/test_sqlite_read.py`` -- security, policy, path, bounds, and
registration tests, all expected to keep passing unchanged):

- file-size gate: ``SQLITE_MAX_FILE_BYTES = 32_000_000`` decimal bytes with
  inclusive boundary semantics, the old-2 MB database accepted, limit+1
  rejected, validation-order guarantee for oversized non-SQLite files;
- value-materialization guard: SQLite-side per-value limit, Python-side
  result-width and per-page byte budgets, deterministic error semantics
  (error, never fake rows or dishonest ``truncated`` claims), and the
  explicit distinction from output clipping;
- stability: constants pinned, bounds not caller-configurable.

Every rejection path asserts byte identity (sha256 before vs after) using
the V1.1 methodology.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import sqlite3
from pathlib import Path

import pytest

from mcquest_mcp.tools.sqlite_read import (
    SQLITE_MAX_FETCH_BYTES,
    SQLITE_MAX_FILE_BYTES,
    SQLITE_MAX_RESULT_COLUMNS,
    SQLITE_MAX_VALUE_BYTES,
    sqlite_read,
)

# Real module object for monkeypatching (the package re-exports the
# sqlite_read *function* under the same name, which would shadow the module).
sqlite_mod = importlib.import_module("mcquest_mcp.tools.sqlite_read")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_items_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT)")
        connection.executemany(
            "INSERT INTO items (title) VALUES (?)",
            [(f"item {i}",) for i in range(5)],
        )
        connection.commit()
    finally:
        connection.close()


def _pad(path: Path, size: int) -> None:
    """Extend a valid SQLite file to exactly ``size`` bytes (zero padding).

    Runtime-verified: SQLite reads only the pages declared in the header, so
    trailing zero padding keeps the file valid for read-only queries while
    letting tests hit the exact byte boundary without huge fixtures.
    """
    current = path.stat().st_size
    assert current <= size, "padding must never truncate existing pages"
    with open(path, "r+b") as handle:
        handle.truncate(size)


def _make_db_with_text_rows(path: Path, rows: int, width: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT)")
        connection.executemany(
            "INSERT INTO docs (body) VALUES (?)",
            [("x" * width,) for _ in range(rows)],
        )
        connection.commit()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 9. File-size tests
# ---------------------------------------------------------------------------


def test_v12_size_constants_are_pinned() -> None:
    """The approved HYBRID constants, exactly as specified in Gate 1."""
    assert SQLITE_MAX_FILE_BYTES == 32_000_000
    assert SQLITE_MAX_VALUE_BYTES == 1_000_000
    assert SQLITE_MAX_RESULT_COLUMNS == 64
    assert SQLITE_MAX_FETCH_BYTES == 16_000_000
    for value in (
        SQLITE_MAX_FILE_BYTES,
        SQLITE_MAX_VALUE_BYTES,
        SQLITE_MAX_RESULT_COLUMNS,
        SQLITE_MAX_FETCH_BYTES,
    ):
        assert isinstance(value, int) and value > 0


def test_bounds_are_not_caller_configurable() -> None:
    """No V1.2 bound may leak into the tool signature/schema."""
    parameters = inspect.signature(sqlite_read).parameters
    assert list(parameters) == ["database", "query", "parameters", "max_rows"]


def test_database_below_limit_accepted(repo: str) -> None:
    """9.A A valid database below 32,000,000 bytes is accepted."""
    path = Path(repo) / "v12_small.db"
    _make_items_db(path)
    assert path.stat().st_size < SQLITE_MAX_FILE_BYTES
    before = _digest(path)
    output = sqlite_read("v12_small.db", "SELECT id, title FROM items ORDER BY id")
    assert "row_count: 5" in output
    assert "truncated: false" in output
    assert "collection_complete: true" in output
    assert _digest(path) == before


def test_database_above_old_2mb_limit_accepted(repo: str) -> None:
    """9.D The Gate 0 target shape: above old V1.1 2,000,000, below new limit.

    This is the essential real-world regression: the motivating PocketBase
    ``data.db`` was 2,359,296 bytes and must now be readable.
    """
    path = Path(repo) / "v12_above2mb.db"
    _make_db_with_text_rows(path, rows=3, width=800_000)
    size = path.stat().st_size
    assert size > 2_000_000, "fixture must exceed the old V1.1 limit"
    assert size < SQLITE_MAX_FILE_BYTES, "fixture must sit under the V1.2 limit"
    before = _digest(path)
    output = sqlite_read("v12_above2mb.db", "SELECT id FROM docs ORDER BY id")
    assert "row_count: 3" in output
    assert "collection_complete: true" in output
    assert _digest(path) == before


def test_database_exactly_at_real_limit_accepted(repo: str) -> None:
    """9.B Exactly 32,000,000 bytes is accepted (boundary is inclusive)."""
    path = Path(repo) / "v12_exact_limit.db"
    _make_items_db(path)
    _pad(path, SQLITE_MAX_FILE_BYTES)
    assert path.stat().st_size == 32_000_000
    before = _digest(path)
    output = sqlite_read("v12_exact_limit.db", "SELECT title FROM items")
    assert "row_count: 5" in output
    assert "collection_complete: true" in output
    assert _digest(path) == before


def test_database_one_byte_over_real_limit_rejected(repo: str) -> None:
    """9.C 32,000,001 bytes is rejected deterministically at the size gate."""
    path = Path(repo) / "v12_limit_plus_one.db"
    _make_items_db(path)
    _pad(path, SQLITE_MAX_FILE_BYTES + 1)
    assert path.stat().st_size == 32_000_001
    before = _digest(path)
    with pytest.raises(
        ValueError, match="Database exceeds 32,000,000 byte safety limit"
    ):
        sqlite_read("v12_limit_plus_one.db", "SELECT title FROM items")
    assert _digest(path) == before


def test_size_gate_boundary_is_inclusive(repo: str, monkeypatch) -> None:
    """9.B/9.E Inclusive/exclusive semantics proven at a patched boundary."""
    path = Path(repo) / "v12_boundary.db"
    _make_items_db(path)
    size = path.stat().st_size
    # Exactly at (patched) limit -> accepted.
    monkeypatch.setattr(sqlite_mod, "SQLITE_MAX_FILE_BYTES", size)
    output = sqlite_read("v12_boundary.db", "SELECT title FROM items")
    assert "row_count: 5" in output
    # One byte of headroom lost -> rejected with the patched value in the
    # message, proving the gate reads the module constant at call time.
    monkeypatch.setattr(sqlite_mod, "SQLITE_MAX_FILE_BYTES", size - 1)
    before = _digest(path)
    with pytest.raises(
        ValueError, match=f"Database exceeds {size - 1:,} byte safety limit"
    ):
        sqlite_read("v12_boundary.db", "SELECT title FROM items")
    assert _digest(path) == before


def test_oversized_non_sqlite_file_fails_at_size_stage(repo: str, monkeypatch) -> None:
    """9.F Validation order: oversized non-SQLite fails at the SIZE stage.

    The message must be the size-gate error, never the magic-header error,
    and the file must never be handed to SQLite for parsing.
    """
    path = Path(repo) / "v12_not_a_db.bin"
    path.write_bytes(b"NOT A DATABASE " * 100)
    monkeypatch.setattr(sqlite_mod, "SQLITE_MAX_FILE_BYTES", 10)
    before = _digest(path)
    with pytest.raises(
        ValueError, match="Database exceeds 10 byte safety limit"
    ) as excinfo:
        sqlite_read("v12_not_a_db.bin", "SELECT 1")
    assert "Not a SQLite database" not in str(excinfo.value)
    assert "SQLite error" not in str(excinfo.value)
    assert _digest(path) == before


# ---------------------------------------------------------------------------
# 10. Value-materialization tests
# ---------------------------------------------------------------------------


def test_small_text_and_blob_values_succeed(repo: str) -> None:
    """10.A Normal text/BLOB values continue to work under the V1.2 guards."""
    path = Path(repo) / "v12_smallvals.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, label TEXT, data BLOB)"
        )
        connection.execute(
            "INSERT INTO t VALUES (1, ?, ?)", ("café 日本語", b"\x00\x01\x02\xff")
        )
        connection.commit()
    finally:
        connection.close()
    before = _digest(path)
    output = sqlite_read("v12_smallvals.db", "SELECT label, data FROM t")
    assert "row_count: 1" in output
    assert "$blob" in output
    assert "truncated: false" in output
    assert "collection_complete: true" in output
    assert _digest(path) == before


def test_large_text_value_rejected_deterministically(repo: str) -> None:
    """10.B + 10.E A TEXT value over 1,000,000 bytes fails deterministically.

    The failure is an ERROR (no rows, no summary), never a fake success with
    ``truncated``/``collection_complete`` claims, and repeated calls produce
    byte-identical messages.
    """
    path = Path(repo) / "v12_largetext.db"
    _make_db_with_text_rows(path, rows=1, width=1_500_000)
    before = _digest(path)
    with pytest.raises(ValueError, match="materialization safety limit") as first:
        sqlite_read("v12_largetext.db", "SELECT body FROM docs")
    with pytest.raises(ValueError, match="materialization safety limit") as second:
        sqlite_read("v12_largetext.db", "SELECT body FROM docs")
    message = str(first.value)
    assert message == str(second.value), "guard error must be deterministic"
    assert "1,000,000" in message
    assert "truncated" not in message
    assert "collection_complete" not in message
    assert "row_count" not in message
    assert _digest(path) == before


def test_large_blob_value_rejected(repo: str) -> None:
    """10.C A BLOB over the per-value limit never materializes into Python."""
    path = Path(repo) / "v12_largeblob.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, data BLOB)")
        connection.execute("INSERT INTO docs (data) VALUES (?)", (b"\x00" * 1_500_000,))
        connection.commit()
    finally:
        connection.close()
    before = _digest(path)
    with pytest.raises(ValueError, match="materialization safety limit"):
        sqlite_read("v12_largeblob.db", "SELECT data FROM docs")
    assert _digest(path) == before


def test_output_clipping_is_distinct_from_materialization_guard(repo: str) -> None:
    """10.D Output clipping (post-materialization) != materialization guard.

    A 5,000-char value is far above the 200-char line clip but far below the
    1,000,000-byte value limit: it succeeds with clipped output. The guard
    never fires on this path, and the clip path never claims guard behavior.
    """
    path = Path(repo) / "v12_clip.db"
    _make_db_with_text_rows(path, rows=1, width=5_000)
    before = _digest(path)
    output = sqlite_read("v12_clip.db", "SELECT body FROM docs")
    assert "row_count: 1" in output
    assert "…" in output, "line clip marker expected for the 5,000-char value"
    # The row IS returned (not an error path): [END] marks a successful,
    # un-capped collection, and the budget's omission marker discloses the
    # clipped characters -- display-level clipping, never a guard failure.
    assert "[END]" in output
    assert "[OUTPUT TRUNCATED:" in output
    assert "materialization" not in output
    assert _digest(path) == before


def test_fetch_budget_bounds_aggregate_materialization(repo: str, monkeypatch) -> None:
    """10.B/10.E Python-side per-page byte budget, distinct from row caps.

    Under the default 16,000,000-byte budget the page succeeds; with the
    budget patched small the same page trips a deterministic error (not a
    truncation claim) before any output is built.
    """
    path = Path(repo) / "v12_page.db"
    _make_db_with_text_rows(path, rows=60, width=4_000)
    before = _digest(path)
    output = sqlite_read("v12_page.db", "SELECT body FROM docs", max_rows=60)
    assert "row_count: 60" in output
    assert "collection_complete: true" in output
    monkeypatch.setattr(sqlite_mod, "SQLITE_MAX_FETCH_BYTES", 50_000)
    with pytest.raises(ValueError, match="materialization safety budget") as excinfo:
        sqlite_read("v12_page.db", "SELECT body FROM docs", max_rows=60)
    assert "truncated" not in str(excinfo.value)
    assert "row_count" not in str(excinfo.value)
    assert _digest(path) == before


def test_result_column_guard_rejects_over_wide_results(repo: str, monkeypatch) -> None:
    """10.B Result-width guard: over-wide results are rejected pre-fetch."""
    path = Path(repo) / "v12_cols.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE t (a INTEGER, b INTEGER, c INTEGER, d INTEGER, "
            "e INTEGER, f INTEGER)"
        )
        connection.execute("INSERT INTO t VALUES (1, 2, 3, 4, 5, 6)")
        connection.commit()
    finally:
        connection.close()
    before = _digest(path)
    # Default cap (64) accepts the 6-column result.
    output = sqlite_read("v12_cols.db", "SELECT a, b, c, d, e, f FROM t")
    assert "row_count: 1" in output
    # Patched cap rejects the same query before any row is fetched.
    monkeypatch.setattr(sqlite_mod, "SQLITE_MAX_RESULT_COLUMNS", 3)
    with pytest.raises(ValueError, match="materialization guard allows at most 3"):
        sqlite_read("v12_cols.db", "SELECT a, b, c, d, e, f FROM t")
    assert _digest(path) == before


def test_value_limit_is_per_call_and_not_sticky(repo: str, monkeypatch) -> None:
    """The per-value setlimit lives on the connection, never in global state.

    Tripping the guard with a patched limit must not affect the next call:
    proving no state leaks between invocations of the shared MCP process.
    """
    path = Path(repo) / "v12_per_call.db"
    _make_db_with_text_rows(path, rows=1, width=500)
    before = _digest(path)
    monkeypatch.setattr(sqlite_mod, "SQLITE_MAX_VALUE_BYTES", 100)
    with pytest.raises(ValueError, match="materialization safety limit"):
        sqlite_read("v12_per_call.db", "SELECT body FROM docs")
    monkeypatch.undo()  # restore every patch made by this test
    output = sqlite_read("v12_per_call.db", "SELECT body FROM docs")
    assert "row_count: 1" in output
    assert "collection_complete: true" in output
    assert _digest(path) == before
