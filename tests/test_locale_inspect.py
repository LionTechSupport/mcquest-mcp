"""V0.7 Stage 3 regression: ``mcquest_locale_inspect`` JSON locale inspection.

Binding design: approved V0.7 Stage 3 decisions D-1..D-7 (DEC-012).
JSON only; duplicate-preserving ``_Pairs`` parse; effective last-value
structure (shadowed subtrees never traversed/reported); casefold
collisions (``Straße``/``strasse``); MISSING/EXTRA vs an explicit
reference only when comparison-eligible; typed path display (``"0"`` !=
``[0]``); approved resource limits; per-file cap before global cap;
counting-mode honesty; ``collection_complete=false`` whenever comparisons
are disabled or the scan is incomplete.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from mcquest_mcp.server import mcp
from mcquest_mcp.tools import locales
from mcquest_mcp.tools.locales import locale_inspect


def summary_of(output: str) -> dict[str, str]:
    """Parse the ``[SUMMARY]`` block into ``{key: value}``."""
    text = output.partition("[EVIDENCE]")[0]
    data: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("tool: "):
            data["tool"] = line[6:]
        elif line.startswith("scope: "):
            data["scope"] = line[7:]
        elif ": " in line:
            key, value = line.split(": ", 1)
            data[key] = value
    return data


def rows_of(output: str) -> list[str]:
    """Return the evidence row lines (``relative: ROW``)."""
    body = output.partition("[EVIDENCE]")[2].split("[OUTPUT TRUNCATED")[0]
    return [
        line
        for line in body.splitlines()
        if line.strip() and line.strip() != "[END]"
    ]


def write_binary(repo: str, relative_path: str, content: bytes) -> str:
    full = os.path.join(repo, relative_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as handle:
        handle.write(content)
    return relative_path


DUP_COLLISION_FILE = '{"M":{"S":1,"S":2,"s":3}}'


# --- D-1 structure / duplicate / collision semantics -------------------------


def test_no_reference_structure_inspection(write_file) -> None:
    write_file("locales/en.json", '{"menu":{"save":1,"open":2},"quit":3}')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert s["tool"] == "mcquest_locale_inspect"
    assert s["scope"] == 'path="locales"'
    assert s["REFERENCE"] == "(none)"
    assert s["REFERENCE_STATUS"] == "none"
    assert s["COMPARISON_ELIGIBLE"] == "0"
    assert s["DISCOVERED"] == "1"
    assert s["EXAMINED"] == "1"
    assert s["files_not_examined"] == "0"
    assert s["total"] == "1"
    # Comparisons disabled => collection_complete=false unconditionally.
    assert s["collection_complete"] == "false"
    assert s["budget"] == "4000/16000"
    assert rows_of(out) == [
        'locales/en.json: STRUCTURE root=object keys=2; "menu" keys=2',
    ]
    assert out.rstrip().endswith("[END]")


def test_duplicate_keys_last_value_wins(write_file) -> None:
    write_file("locales/e1.json", '{"a":{"old":1},"a":{"new":2}}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        'locales/e1.json: STRUCTURE root=object keys=1; "a" keys=1',
        'locales/e1.json: DUP "a" (2 occurrences; last value kept)',
    ]
    assert "old" not in out  # shadowed subtree contributes nothing


def test_shadowed_subtree_duplicates_not_reported(write_file) -> None:
    write_file("locales/e2.json", '{"menu":{"x":1,"x":2},"menu":{"x":3},"q":5}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        'locales/e2.json: STRUCTURE root=object keys=2; "menu" keys=1',
        'locales/e2.json: DUP "menu" (2 occurrences; last value kept)',
    ]


def test_strasse_casefold_collision(write_file) -> None:
    write_file("locales/de.json", '{"Straße":1,"strasse":2}')

    out = locale_inspect(path="locales")

    # The colliding keys live at the root node => path <root> (D-5).
    assert rows_of(out) == [
        'locales/de.json: STRUCTURE root=object keys=2',
        'locales/de.json: COLLISION <root> {"Straße","strasse"}',
    ]


def test_collision_and_dup_coexist_e3(write_file) -> None:
    write_file("locales/e3.json", '{"Menu":{"Save":1,"Save":2,"save":3}}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        'locales/e3.json: STRUCTURE root=object keys=1; "Menu" keys=2',
        'locales/e3.json: COLLISION "Menu" {"Save","save"}',
        'locales/e3.json: DUP "Menu"."Save" (2 occurrences; last value kept)',
    ]


def test_object_in_array_dup_path(write_file) -> None:
    write_file("locales/m.json", '{"menu":[{"label":1,"label":2}]}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        (
            'locales/m.json: STRUCTURE root=object keys=1; "menu" len=1; '
            '"menu"[0] keys=1'
        ),
        'locales/m.json: DUP "menu"[0]."label" (2 occurrences; last value kept)',
    ]


def test_array_positions_never_merged(write_file) -> None:
    write_file("locales/arr.json", '[{"x":1},{"x":2}]')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        'locales/arr.json: STRUCTURE root=array len=2; [0] keys=1; [1] keys=1',
    ]
    assert "DUP" not in out  # same key in different branches is not a dup


def test_typed_display_of_ambiguous_keys(write_file) -> None:
    write_file("locales/d.json", '{"0":1,"0":2,"a.b":3,"a.b":4}')

    out = locale_inspect(path="locales")

    rows = rows_of(out)
    assert 'locales/d.json: DUP "0" (2 occurrences; last value kept)' in rows
    assert 'locales/d.json: DUP "a.b" (2 occurrences; last value kept)' in rows


def test_root_array_and_scalar_shapes(write_file) -> None:
    write_file("locales/e5.json", '[{"k":1,"k":2},5]')
    write_file("locales/obj.json", '{"a":1}')
    write_file("locales/scalar.json", "42")

    out = locale_inspect(path="locales")

    rows = rows_of(out)
    assert 'locales/e5.json: STRUCTURE root=array len=2; [0] keys=1' in rows
    assert 'locales/e5.json: DUP [0]."k" (2 occurrences; last value kept)' in rows
    assert 'locales/obj.json: STRUCTURE root=object keys=1' in rows
    assert 'locales/scalar.json: STRUCTURE root=scalar int' in rows


def test_typed_path_order_dominates_rank(write_file) -> None:
    # DUP at the shallow path ("a") sorts before the COLLISION at the
    # deeper path ("a"."x"): typed-path order dominates the type rank.
    write_file("locales/t.json", '{"a":5,"a":{"x":{"b":1,"B":2}}}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        (
            'locales/t.json: STRUCTURE root=object keys=1; "a" keys=1; '
            '"a"."x" keys=2'
        ),
        'locales/t.json: DUP "a" (2 occurrences; last value kept)',
        'locales/t.json: COLLISION "a"."x" {"B","b"}',
    ]


# --- D-3 reference comparison -------------------------------------------------


def test_valid_reference_missing_and_extra(write_file) -> None:
    write_file("locales/en.json", '{"a":1,"b":{"c":2}}')
    write_file("locales/fr.json", '{"a":1,"b":{"c":3,"d":4},"e":5}')

    out = locale_inspect(path="locales", reference="locales/en.json")

    s = summary_of(out)
    assert s["REFERENCE"] == "locales/en.json"
    assert s["REFERENCE_STATUS"] == "VALID"
    assert "REFERENCE_LIMITED" not in s
    assert s["COMPARISON_ELIGIBLE"] == "2"
    assert s["collection_complete"] == "true"
    assert s["total"] == "4"
    assert rows_of(out) == [
        'locales/en.json: STRUCTURE root=object keys=2; "b" keys=1',
        'locales/fr.json: STRUCTURE root=object keys=3; "b" keys=2',
        'locales/fr.json: EXTRA "b"."d"',
        'locales/fr.json: EXTRA "e"',
    ]


def test_missing_rows_present_in_reference_absent_in_target(write_file) -> None:
    write_file("locales/en.json", '{"a":1,"b":2}')
    write_file("locales/fr.json", '{"a":1}')

    out = locale_inspect(path="locales", reference="locales/en.json")

    assert 'locales/fr.json: MISSING "b"' in rows_of(out)
    assert summary_of(out)["collection_complete"] == "true"


def test_string_key_zero_and_array_index_zero_are_distinct(write_file) -> None:
    write_file("locales/en.json", '{"0":1}')
    write_file("locales/fr.json", "[1]")

    out = locale_inspect(path="locales", reference="locales/en.json")

    rows = rows_of(out)
    assert 'locales/en.json: STRUCTURE root=object keys=1' in rows
    assert 'locales/fr.json: STRUCTURE root=array len=1' in rows
    assert 'locales/fr.json: MISSING "0"' in rows
    assert 'locales/fr.json: EXTRA [0]' in rows


def test_object_key_zero_vs_array_index_extra(write_file) -> None:
    write_file("locales/en.json", '{"0":1}')
    write_file("locales/fr.json", '{"0":1,"z":[5,6]}')

    out = locale_inspect(path="locales", reference="locales/en.json")

    rows = rows_of(out)
    assert 'locales/fr.json: EXTRA "z"[0]' in rows
    assert 'locales/fr.json: EXTRA "z"[1]' in rows
    assert summary_of(out)["total"] == "4"


def test_invalid_reference_disables_comparisons(write_file) -> None:
    write_file("locales/bad.json", '{"a":')
    write_file("locales/en.json", '{"a":1}')

    out = locale_inspect(path="locales", reference="locales/bad.json")

    s = summary_of(out)
    assert s["REFERENCE_STATUS"] == "PARSE-ERROR"
    assert s["REFERENCE_LIMITED"] == "parse-error"
    assert s["COMPARISON_ELIGIBLE"] == "0"
    assert s["collection_complete"] == "false"
    # Reference-role failure never enters ERROR_EVENTS (D-3); the same
    # file scanned as a target reports its own PARSE error normally.
    assert s["ERROR_EVENTS"] == "1 (PARSE=1)"
    assert s["FINDINGS_UNKNOWN"] == "1"
    assert s["total"] == "2"
    assert rows_of(out) == [
        'locales/bad.json: ERROR (PARSE): line 1, col 6: Expecting value',
        'locales/en.json: STRUCTURE root=object keys=1',
    ]


def test_nonexistent_reference_disables_comparisons(write_file) -> None:
    write_file("locales/en.json", '{"a":1}')

    out = locale_inspect(path="locales", reference="locales/missing.json")

    s = summary_of(out)
    assert s["REFERENCE_STATUS"] == "READ-ERROR"
    assert s["REFERENCE_LIMITED"] == "read-error"
    assert s["COMPARISON_ELIGIBLE"] == "0"
    assert s["collection_complete"] == "false"
    assert "ERROR_EVENTS" not in s
    assert rows_of(out) == ['locales/en.json: STRUCTURE root=object keys=1']


def test_reference_also_scanned_as_target_dual_role(write_file) -> None:
    write_file("locales/en.json", '{"a":1}')

    out = locale_inspect(path="locales", reference="locales/en.json")

    # Its effective identity equals the reference set => empty diff; the
    # dual role is disclosed without double counting.
    s = summary_of(out)
    assert s["total"] == "1"
    assert "ERROR_EVENTS" not in s
    assert s["collection_complete"] == "true"
    assert rows_of(out) == ['locales/en.json: STRUCTURE root=object keys=1']


# --- Error rows and gates ------------------------------------------------------


def test_malformed_json_error_row(write_file) -> None:
    write_file("locales/bad.json", '{"a":')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert s["total"] == "1"
    assert s["FINDINGS_UNKNOWN"] == "1"
    assert s["ERROR_EVENTS"] == "1 (PARSE=1)"
    assert s["collection_complete"] == "false"
    assert rows_of(out) == [
        'locales/bad.json: ERROR (PARSE): line 1, col 6: Expecting value',
    ]


def test_invalid_utf8_error_row(write_file, repo) -> None:
    write_binary(repo, "locales/bin.json", b'\xff\xfe{"a":1}')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert rows_of(out) == [
        'locales/bin.json: ERROR (DECODE): file is not valid UTF-8',
    ]
    # READ/DECODE/OVERSIZED gate failures are not-examined (D-7 4a), not
    # findings-unknown.
    assert s["ERROR_EVENTS"] == "1 (DECODE=1)"
    assert s["files_not_examined"] == "1"
    assert s["EXAMINED"] == "0"
    assert "FINDINGS_UNKNOWN" not in s


def test_oversized_file_error_row(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_FILE_BYTES", 10)
    write_file("locales/big.json", '{"a":"' + "x" * 50 + '"}')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert rows_of(out) == [
        "locales/big.json: ERROR (OVERSIZED): file exceeds 10 byte safety limit",
    ]
    assert s["ERROR_EVENTS"] == "1 (OVERSIZED=1)"
    assert s["files_not_examined"] == "1"  # oversized => not examined
    assert s["EXAMINED"] == "0"
    assert s["DISCOVERED"] == "1"
    assert "FINDINGS_OMITTED" not in s  # error rows are never ordinary findings


# --- D-2 resource bounds -------------------------------------------------------


def test_depth_limit_error_row(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_JSON_DEPTH", 2)
    write_file("locales/deep.json", '{"a":{"b":{"c":1}}}')
    write_file("locales/ok.json", '{"a":{"b":1}}')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert (
        'locales/deep.json: ERROR (DEPTH): nesting depth 3 exceeds limit 2'
        in rows_of(out)
    )
    assert s["FINDINGS_UNKNOWN"] == "1"
    assert s["ERROR_EVENTS"] == "1 (DEPTH=1)"
    # A file within the depth limit is still processed normally.
    assert 'locales/ok.json: STRUCTURE root=object keys=1; "a" keys=1' in rows_of(out)


def test_depth_precheck_ignores_braces_in_strings(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_JSON_DEPTH", 1)
    write_file("locales/s.json", '{"a":"{[)"}')

    out = locale_inspect(path="locales")

    # The braces live inside a string literal: the real depth is 1.
    assert rows_of(out) == ['locales/s.json: STRUCTURE root=object keys=1']


def test_parse_node_cap_invariant_guard(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_PARSE_NODES_PER_FILE", 3)
    write_file("locales/n.json", '{"a":1,"b":2,"c":3}')

    out = locale_inspect(path="locales")

    # The guard trips mid-walk; the whole working set is discarded (no
    # partial identity, no ordinary rows) — a single ERROR row only.
    assert rows_of(out) == [
        'locales/n.json: ERROR (IDENTITY): parse node count exceeds limit',
    ]
    assert summary_of(out)["FINDINGS_UNKNOWN"] == "1"


def test_identity_path_cap(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_EXACT_PATHS_PER_FILE", 2)
    write_file("locales/p.json", '{"a":1,"b":2}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        'locales/p.json: ERROR (IDENTITY): exact path count exceeds limit',
    ]


def test_identity_units_cap(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "IDENTITY_UNITS_MAX", 10)
    write_file("locales/u.json", '{"a":1,"b":2}')

    out = locale_inspect(path="locales")

    assert rows_of(out) == [
        'locales/u.json: ERROR (IDENTITY): identity units exceed limit',
    ]


# --- D-4/D-7 caps, counting mode, omission/unknown accounting -----------------


def test_per_file_and_global_caps_counting_mode(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_LOCALE_FILE_ROWS", 2)
    monkeypatch.setattr(locales, "MAX_LOCALE_ROWS", 4)
    write_file("f0.json", '{"a":')
    for name in ("f1", "f2", "f3", "f4"):
        write_file(f"{name}.json", DUP_COLLISION_FILE)

    out = locale_inspect(path=".")

    s = summary_of(out)
    # f0: 1 error row collected; f1: 2 of 3 ordinary rows; f2: 1 of 3;
    # f3/f4: counting mode => +3 +3 exact omitted cardinalities.
    assert s["FINDINGS_OMITTED"] == "9"
    assert s["FINDINGS_UNKNOWN"] == "1"
    assert s["ERROR_EVENTS"] == "1 (PARSE=1)"
    assert "ERROR_ROWS_OMITTED" not in s  # 1 event - 1 collected row = 0
    assert s["total"] == "4"
    assert s["ROW_LIMIT"] == "4"
    assert s["FILE_ROW_LIMIT"] == "2"
    assert s["collection_complete"] == "false"
    assert rows_of(out) == [
        'f0.json: ERROR (PARSE): line 1, col 6: Expecting value',
        'f1.json: STRUCTURE root=object keys=1; "M" keys=2',
        'f1.json: COLLISION "M" {"S","s"}',
        'f2.json: STRUCTURE root=object keys=1; "M" keys=2',
    ]


def test_counting_mode_cardinality_matches_materialized_baseline(
    write_file, monkeypatch
) -> None:
    monkeypatch.setattr(locales, "MAX_LOCALE_ROWS", 5)
    for name in ("f1", "f2", "f3", "f4"):
        write_file(f"{name}.json", DUP_COLLISION_FILE)

    monkeypatch.setattr(locales, "MAX_LOCALE_FILE_ROWS", 2)
    capped = locale_inspect(path=".")
    monkeypatch.setattr(locales, "MAX_LOCALE_FILE_ROWS", 3000)
    monkeypatch.setattr(locales, "MAX_LOCALE_ROWS", 5000)
    uncapped = locale_inspect(path=".")

    # Consistency equation (D-4): emitted + omitted == full cardinality.
    # Caps: FILE_ROWS=2 keeps 2 of 3 per file; ROWS=5 → f1:2 (omitted 1),
    # f2:2 (omitted 1), f3:1 (rem0, omitted 2), f4 counting mode (+3).
    baseline = int(summary_of(uncapped)["total"])
    emitted = int(summary_of(capped)["total"])
    omitted = int(summary_of(capped)["FINDINGS_OMITTED"])
    assert baseline == 12
    assert emitted == 5
    assert emitted + omitted == baseline
    assert omitted == 7


def test_error_row_dropped_by_caps_is_disclosed(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_LOCALE_ROWS", 2)
    write_file("a.json", '{"x":')
    write_file("b.json", '{"y":')
    write_file("c.json", '{"z":')

    out = locale_inspect(path=".")

    s = summary_of(out)
    # Three PARSE events; only two error rows collected before the global
    # cap, so one dropped error row stays disclosed (D-7).
    assert s["ERROR_EVENTS"] == "3 (PARSE=3)"
    assert s["ERROR_ROWS_OMITTED"] == "1"
    assert s["FINDINGS_UNKNOWN"] == "3"
    assert s["ROW_LIMIT"] == "2"
    assert s["total"] == "2"


# --- D-6 enumeration / population accounting ----------------------------------


def test_incomplete_enumeration_file_count_limit(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_ENUMERATE_FILES", 2)
    for name in ("a", "b", "c"):
        write_file(f"locales/{name}.json", '{"x":1}')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert "DISCOVERED" not in s
    assert "files_not_examined" not in s
    assert s["files_not_examined_unknown"] == "true"
    assert s["ENUM_LIMIT"] == "2"
    assert s["ENUM_REASON"] == "file-count-limit"
    assert s["collection_complete"] == "false"


def test_tail_beyond_max_locale_files_not_examined(write_file, monkeypatch) -> None:
    monkeypatch.setattr(locales, "MAX_LOCALE_FILES", 1)
    write_file("locales/a.json", '{"x":1}')
    write_file("locales/b.json", '{"x":1}')

    out = locale_inspect(path="locales")

    s = summary_of(out)
    assert s["DISCOVERED"] == "2"
    assert s["EXAMINED"] == "1"
    assert s["files_not_examined"] == "1"
    assert s["collection_complete"] == "false"
    assert s["total"] == "1"


def test_file_pattern_filter_and_non_json_skipped(write_file) -> None:
    write_file("locales/en.json", '{"a":1}')
    write_file("locales/en.backup.json", '{"b":2}')
    write_file("locales/notes.txt", '{"not":"json"}')

    out = locale_inspect(path="locales", file_pattern="en.json")

    s = summary_of(out)
    assert s["DISCOVERED"] == "1"
    assert rows_of(out) == ['locales/en.json: STRUCTURE root=object keys=1']


def test_single_file_path(write_file) -> None:
    write_file("locales/e1.json", '{"a":{"old":1},"a":{"new":2}}')

    out = locale_inspect(path="locales/e1.json")

    s = summary_of(out)
    assert s["DISCOVERED"] == "1"
    assert s["EXAMINED"] == "1"
    assert rows_of(out) == [
        'locales/e1.json: STRUCTURE root=object keys=1; "a" keys=1',
        'locales/e1.json: DUP "a" (2 occurrences; last value kept)',
    ]


# --- Ordering, pagination, rendering -------------------------------------------


def test_pagination_over_collected_rows(write_file) -> None:
    write_file("locales/e3.json", '{"Menu":{"Save":1,"Save":2,"save":3}}')

    page1 = locale_inspect(path="locales", max_results=2)
    s1 = summary_of(page1)
    assert s1["total"] == "3"
    assert s1["returned"] == "2"
    assert s1["has_more"] == "true"
    assert s1["next_offset"] == "2"
    assert s1["budget"] == "4000/16000"
    assert rows_of(page1) == [
        'locales/e3.json: STRUCTURE root=object keys=1; "Menu" keys=2',
        'locales/e3.json: COLLISION "Menu" {"Save","save"}',
    ]

    page2 = locale_inspect(path="locales", max_results=2, offset=2)
    s2 = summary_of(page2)
    assert s2["returned"] == "1"
    assert s2["has_more"] == "false"
    assert "next_offset" not in s2
    assert s2["budget"] == "16000/16000"  # explicit continuation expansion
    assert rows_of(page2) == [
        'locales/e3.json: DUP "Menu"."Save" (2 occurrences; last value kept)',
    ]


def test_deterministic_ordering(write_file) -> None:
    write_file("locales/b.json", '{"k":1,"k":2}')
    write_file("locales/a.json", '{"z":[1,2],"y":3}')

    first = locale_inspect(path="locales")
    second = locale_inspect(path="locales")

    assert first == second
    files = [row.split(": ", 1)[0] for row in rows_of(first)]
    assert files == sorted(files, key=lambda f: f.encode("utf-8"))


def test_output_line_clipping(write_file) -> None:
    # 200 empty-object values make the STRUCTURE row enumerate 200 nodes
    # (far longer than 200 chars); the renderer clips atomically with the
    # explicit marker (D-5).
    write_file(
        "locales/wide.json",
        "{" + ",".join(f'"key{i:03d}":{{}}' for i in range(200)) + "}",
    )

    out = locale_inspect(path="locales")

    assert max(len(line) for line in out.splitlines()) <= 200
    assert "[OUTPUT TRUNCATED" in out
    assert summary_of(out)["truncated"] == "true"


def test_locale_inspect_is_read_only(repo, write_file) -> None:
    write_file("locales/en.json", '{"a":1}')

    def snapshot():
        snaps = {}
        for current, _dirs, files in os.walk(repo):
            for name in files:
                path = os.path.join(current, name)
                stat = os.stat(path)
                snaps[path] = (stat.st_size, stat.st_mtime_ns)
        return snaps

    before = snapshot()
    locale_inspect(path="locales")
    locale_inspect(path="locales/en.json")
    locale_inspect(path=".", reference="locales/en.json")
    assert snapshot() == before


def test_validation_and_confinement(write_file) -> None:
    write_file("locales/en.json", '{"a":1}')

    with pytest.raises(ValueError, match="offset"):
        locale_inspect(path="locales", offset=-1)
    with pytest.raises(ValueError, match="file_pattern"):
        locale_inspect(path="locales", file_pattern="")
    with pytest.raises(FileNotFoundError):
        locale_inspect(path="locales/nope")
    with pytest.raises(ValueError, match="escapes"):
        locale_inspect(path="../outside")
    with pytest.raises(ValueError, match="escapes"):
        locale_inspect(path="locales", reference="../secret.json")


# --- Registration / discoverability --------------------------------------------


def test_registered_with_description_and_parameter_schema() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_locale_inspect")
    desc = tool.description or ""
    assert desc.startswith("READ ONLY.")
    assert ".json" in desc
    assert "reference" in desc
    assert "casefold" in desc
    assert "last occurrence" in desc
    assert "collection_complete" in desc

    properties = tool.input_schema["properties"]
    for param in ("path", "reference", "file_pattern", "max_results", "offset"):
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip()
    assert properties["reference"]["default"] == ""
    assert properties["file_pattern"]["default"] == "*.json"
    assert properties["max_results"]["default"] == 50
    assert properties["offset"]["default"] == 0
    assert tool.input_schema.get("required", []) == []


def test_server_instructions_mention_locale_inspect() -> None:
    assert "mcquest_locale_inspect" in mcp.instructions
    assert "never infers a default locale" in mcp.instructions
