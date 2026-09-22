"""V0.8 regression: ``mcquest_find_ui_text`` lexical UI-text candidates.

Binding contract: ``Docs/V0.8/01-V0.8-CONTRACT.md`` sections 2.0/2.1/3
(DEC-027 path/error table; DEC-015/DEC-026 extraction boundary; DEC-032
classification rules and ``classify`` semantics; DEC-016 full-scan
two-pass completeness; DEC-028 budgets/continuation) and
``Docs/V0.8/04-V0.8-TEST-PLAN.md`` sections 2.3/2.4/2.5/2.7/2.8. Fixtures
are temporary files written under the per-test project root (conftest), so
no assertion depends on live repository contents.

Classification is lexical-only per DEC-032: a literal with no ASCII letter
(``[A-Za-z]``) is ``decorative`` (confidence ``high``); a literal with at
least one ASCII letter is ``unknown`` (confidence ``medium``) with a reason
naming the missing brand-token list and admin-marker list;
``localizable``/``brand``/``admin-only`` are never emitted and are never
inferred by elimination. JSX text nodes are not extracted; a quoted literal
on a comment line is an incidental candidate; a zero result never proves
absence.
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.server import mcp
from mcquest_mcp.tools.ui_text import find_ui_text

UNKNOWN_REASON = (
    "brand token list and admin marker list are not recorded (DEC-032); "
    "classification unresolved"
)
DECORATIVE_REASON = "no ASCII letter ([A-Za-z]); DEC-032 letter-absence branch"

CLASSIFIED_ROW = re.compile(
    r'^(?P<rel>.+):(?P<line>\d+): "(?P<value>.*)" '
    r"\[classification: (?P<label>[a-z-]+); "
    r"confidence: (?P<confidence>[a-z]+); reason: (?P<reason>.+)\]$"
)
PLAIN_ROW = re.compile(r'^(?P<rel>.+):(?P<line>\d+): "(?P<value>.*)"$')

APP_TSX = (
    '// incidental "Comment note" on a comment line\n'
    'const save = "Save changes";\n'
    'const digits = "12345";\n'
    'const dashes = "-----";\n'
    'const brandLike = "Acme Analytics Pro";\n'
    'const adminLike = "Admin: Delete User";\n'
    "const jsxOnly = <Button>Save changes</Button>;\n"
    'const attr = <Button title="Save" />;\n'
    "const tpl = `Hello ${name}!`;\n"
)

# (relative_path, line, value, label, confidence) in (path, line, col) order.
EXPECTED_APP_ROWS = [
    ("src/app.tsx", 1, "Comment note", "unknown", "medium"),
    ("src/app.tsx", 2, "Save changes", "unknown", "medium"),
    ("src/app.tsx", 3, "12345", "decorative", "high"),
    ("src/app.tsx", 4, "-----", "decorative", "high"),
    ("src/app.tsx", 5, "Acme Analytics Pro", "unknown", "medium"),
    ("src/app.tsx", 6, "Admin: Delete User", "unknown", "medium"),
    ("src/app.tsx", 8, "Save", "unknown", "medium"),
    ("src/app.tsx", 9, "Hello ", "unknown", "medium"),
    ("src/app.tsx", 9, "!", "decorative", "high"),
]

LIST_TS = "".join(
    f'const v{i:02d} = "Item {name}";\n'
    for i, name in enumerate(
        [
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
        ],
        start=1,
    )
)
LIST_VALUES = [f"Item {name}" for name in (
    "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten",
)]


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


def classified_rows(output: str) -> list[tuple[str, int, str, str, str]]:
    """Parse classify=true rows into (rel, line, value, label, confidence)."""
    rows: list[tuple[str, int, str, str, str]] = []
    for raw in output.partition("[EVIDENCE]")[2].splitlines():
        match = CLASSIFIED_ROW.match(raw)
        if match:
            rows.append(
                (
                    match["rel"],
                    int(match["line"]),
                    match["value"],
                    match["label"],
                    match["confidence"],
                )
            )
    return rows


def plain_rows(output: str) -> list[tuple[str, int, str]]:
    """Parse classify=false rows into (rel, line, value)."""
    rows: list[tuple[str, int, str]] = []
    for raw in output.partition("[EVIDENCE]")[2].splitlines():
        match = PLAIN_ROW.match(raw)
        if match:
            rows.append((match["rel"], int(match["line"]), match["value"]))
    return rows


def row_reasons(output: str) -> list[tuple[str, str]]:
    """Parse classify=true rows into (label, reason) pairs."""
    pairs: list[tuple[str, str]] = []
    for raw in output.partition("[EVIDENCE]")[2].splitlines():
        match = CLASSIFIED_ROW.match(raw)
        if match:
            pairs.append((match["label"], match["reason"]))
    return pairs


# --- extraction and DEC-032 classification (contract section 2.1) -----------


def test_classification_phenotypes_and_extraction(write_file) -> None:
    write_file("src/app.tsx", APP_TSX)

    out = find_ui_text(path="src")

    s = summary_of(out)
    assert s["tool"] == "mcquest_find_ui_text"
    assert s["scope"] == 'path="src"'
    assert s["PATH"] == "src"
    assert s["total"] == "9"
    assert s["files_affected"] == "1"
    assert s["returned"] == "9"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert out.rstrip().endswith("[END]")

    assert classified_rows(out) == EXPECTED_APP_ROWS

    # DEC-032: the unknown reason identifies the missing brand-token list
    # and admin-marker list; the decorative reason is the letter-absence.
    assert set(row_reasons(out)) == {
        ("unknown", UNKNOWN_REASON),
        ("decorative", DECORATIVE_REASON),
    }


def test_jsx_text_nodes_not_extracted_attribute_literals_are(write_file) -> None:
    write_file("src/app.tsx", APP_TSX)

    out = find_ui_text(path="src")
    rows = classified_rows(out)

    # Line 7 (`<Button>Save changes</Button>`) contributes no candidate:
    # JSX text nodes are out of scope (DEC-026).
    assert all(row[1] != 7 for row in rows)
    # The only "Save changes" candidate is the quoted literal on line 2 —
    # it is NOT the JSX text node on line 7.
    save_changes = [row for row in rows if row[2] == "Save changes"]
    assert save_changes == [("src/app.tsx", 2, "Save changes", "unknown", "medium")]
    # The attribute string value on line 8 IS a candidate, distinct from the
    # JSX text node (contract section 2.1).
    assert ("src/app.tsx", 8, "Save", "unknown", "medium") in rows


def test_classify_defaults_to_true(write_file) -> None:
    write_file("src/a.ts", 'const s = "Hello";\n')

    out = find_ui_text(path="src")

    assert "[classification:" in out
    assert classified_rows(out) == [("src/a.ts", 1, "Hello", "unknown", "medium")]


def test_classify_false_rows_and_unchanged_summary(write_file) -> None:
    write_file("src/app.tsx", APP_TSX)

    classified = find_ui_text(path="src")
    plain = find_ui_text(path="src", classify=False)

    # Rows carry only the location and snippet (DEC-032).
    assert plain_rows(plain) == [
        (rel, line, value) for rel, line, value, _label, _conf in EXPECTED_APP_ROWS
    ]
    evidence_body = plain.partition("[EVIDENCE]")[2]
    assert "classification:" not in evidence_body
    assert "confidence:" not in evidence_body
    assert "reason:" not in evidence_body

    # The summary is unchanged between modes (DEC-032).
    assert summary_of(classified) == summary_of(plain)


def test_deferred_labels_never_emitted_and_no_severity_or_risk(write_file) -> None:
    write_file("src/app.tsx", APP_TSX)

    out = find_ui_text(path="src")

    # localizable / brand / admin-only are NOT EMITTABLE (DEC-032) and
    # localizable is never inferred by elimination ("Acme Analytics Pro"
    # and "Admin: Delete User" are unknown, not brand/admin-only).
    for deferred in ("localizable", "brand", "admin-only"):
        assert f"[classification: {deferred}]" not in out
    labels = {row[3] for row in classified_rows(out)}
    assert labels == {"unknown", "decorative"}
    # Contract section 3: no severity and no risk fields.
    assert "severity" not in out
    assert "risk" not in out

# --- ordering, pagination, completeness, budgets (contract sections 2.1/3) --


def test_pagination_is_explicit_and_deterministic(write_file) -> None:
    write_file("src/list.ts", LIST_TS)

    page1 = find_ui_text(path="src", max_results=4)
    s1 = summary_of(page1)
    assert s1["total"] == "10"
    assert s1["returned"] == "4"
    assert s1["next_offset"] == "4"
    assert s1["has_more"] == "true"
    assert [row[2] for row in classified_rows(page1)] == LIST_VALUES[:4]

    page2 = find_ui_text(path="src", max_results=4, offset=4)
    s2 = summary_of(page2)
    assert s2["returned"] == "4"
    assert s2["next_offset"] == "8"
    assert s2["has_more"] == "true"
    assert [row[2] for row in classified_rows(page2)] == LIST_VALUES[4:8]

    page3 = find_ui_text(path="src", max_results=4, offset=8)
    s3 = summary_of(page3)
    assert s3["returned"] == "2"
    assert s3["has_more"] == "false"
    assert "next_offset" not in s3
    assert [row[2] for row in classified_rows(page3)] == LIST_VALUES[8:]

    tail = find_ui_text(path="src", max_results=4, offset=10)
    st = summary_of(tail)
    assert st["returned"] == "0"
    assert st["has_more"] == "false"
    assert classified_rows(tail) == []
    assert tail.rstrip().endswith("[END]")


def test_ordering_across_files_and_two_pass_total(write_file) -> None:
    write_file("src/app.tsx", APP_TSX)
    write_file(
        "src/deep/nested/b.ts",
        'const a = "Alpha";\nconst b = "Beta";\nconst c = "Gamma";\n',
    )

    out = find_ui_text(path="src")
    s = summary_of(out)
    # Two-pass honest full count (DEC-016): total is authoritative and
    # collection_complete is always true.
    assert s["total"] == "12"
    assert s["files_affected"] == "2"
    assert s["collection_complete"] == "true"

    rows = classified_rows(out)
    rels = [row[0] for row in rows]
    assert rels == sorted(rels)
    assert rels[:9] == ["src/app.tsx"] * 9
    assert rels[9:] == ["src/deep/nested/b.ts"] * 3
    # Line ASC applies within each relative_path (the sort key is
    # (relative_path ASC, line ASC, col ASC); line numbering restarts per
    # file by design).
    assert [row[1] for row in rows[:9]] == [1, 2, 3, 4, 5, 6, 8, 9, 9]
    assert [row[1] for row in rows[9:]] == [1, 2, 3]
    # Same-line candidates are ordered by column (col ASC in the sort key).
    same_line = [row[2] for row in rows if row[0] == "src/app.tsx" and row[1] == 9]
    assert same_line == ["Hello ", "!"]


def test_budgets_truncation_and_continuation(write_file) -> None:
    write_file(
        "src/dense.ts",
        "".join(f"const s = '{'x' * 180}{i:03d}';\n" for i in range(1000)),
    )

    default = find_ui_text(path="src")
    assert len(default) <= 4000
    s = summary_of(default)
    assert s["budget"] == "4000/16000"
    assert s["total"] == "1000"
    assert s["truncated"] == "true"
    assert "[OUTPUT TRUNCATED" in default
    # The per-line clip marker (199 chars + ellipsis) is distinct from the
    # whole-output truncation marker (DEC-028).
    assert any(line.endswith("…") for line in default.splitlines())

    expanded = find_ui_text(path="src", max_results=500)
    assert len(expanded) <= 16000
    se = summary_of(expanded)
    assert se["budget"] == "16000/16000"
    assert se["max_results"] == "500"
    assert se["has_more"] == "true"
    assert int(se["returned"]) <= 500
    assert max(len(line) for line in expanded.splitlines()) <= 200

    # Explicit continuation under the expanded ceiling.
    tail = find_ui_text(path="src", max_results=500, offset=995)
    st = summary_of(tail)
    assert st["returned"] == "5"
    assert st["has_more"] == "false"

# --- zero rows, empty path, and the path/error table (contract section 2.0) -


def test_zero_rows_mean_no_match_not_rejection(write_file) -> None:
    write_file("src/notes.md", "# not code\n")
    write_file("src/script.py", 'print("hi")\n')
    write_file("src/empty.js", "")

    out = find_ui_text(path="src")
    s = summary_of(out)
    assert s["total"] == "0"
    assert s["files_affected"] == "0"
    assert s["returned"] == "0"
    assert s["collection_complete"] == "true"
    assert out.rstrip().endswith("[END]")


def test_single_file_within_boundary_accepted(write_file) -> None:
    rel = write_file("src/one.ts", 'const s = "Solo";\n')

    out = find_ui_text(path=rel)

    assert summary_of(out)["total"] == "1"
    assert classified_rows(out) == [("src/one.ts", 1, "Solo", "unknown", "medium")]


def test_empty_path_scans_project_root(write_file) -> None:
    write_file("src/a.ts", 'const s = "Root hit";\n')

    out = find_ui_text(path="")
    s = summary_of(out)
    assert s["tool"] == "mcquest_find_ui_text"
    assert s["PATH"] == "."
    assert s["total"] == "1"


def test_path_error_table(write_file) -> None:
    write_file("src/ok.ts", 'const s = "Ok";\n')
    write_file("node_modules/pkg.js", 'const s = "Ignored";\n')
    md = write_file("src/notes.md", "# docs\n")
    py = write_file("src/script.py", "x = 1\n")

    with pytest.raises(FileNotFoundError):
        find_ui_text(path="no/such/dir")
    with pytest.raises(ValueError, match="escapes"):
        find_ui_text(path="../outside")
    with pytest.raises(ValueError, match="ignored directory"):
        find_ui_text(path="node_modules")
    with pytest.raises(ValueError, match="ignored directory"):
        find_ui_text(path="node_modules/pkg.js")
    with pytest.raises(ValueError, match="Unsupported file type"):
        find_ui_text(path=md)
    with pytest.raises(ValueError, match="Unsupported file type"):
        find_ui_text(path=py)


def test_oversized_single_file_rejected(write_file) -> None:
    big = write_file("src/big.ts", "y" * (MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="byte safety limit"):
        find_ui_text(path=big)


def test_negative_offset_rejected_and_max_results_clamped(write_file) -> None:
    write_file("src/list.ts", LIST_TS)

    with pytest.raises(ValueError, match="offset"):
        find_ui_text(path="src", offset=-1)

    clamped_low = find_ui_text(path="src", max_results=0)
    assert summary_of(clamped_low)["max_results"] == "1"
    assert summary_of(clamped_low)["returned"] == "1"

    clamped_high = find_ui_text(path="src", max_results=9999)
    assert summary_of(clamped_high)["max_results"] == "500"


def test_no_repository_mutation(write_file, repo) -> None:
    write_file("src/app.tsx", APP_TSX)
    write_file("src/list.ts", LIST_TS)

    def snapshot() -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for base, _dirs, files in os.walk(repo):
            for name in files:
                full = os.path.join(base, name)
                stat = os.stat(full)
                snap[os.path.relpath(full, repo)] = (stat.st_size, stat.st_mtime_ns)
        return snap

    before = snapshot()
    find_ui_text(path="src")
    find_ui_text(path="src", max_results=500)
    find_ui_text(path="src", classify=False)
    assert snapshot() == before


# --- registration and discoverability (DEC-020) ------------------------------


def test_registered_with_description_schema_and_defaults() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_find_ui_text")
    desc = tool.description or ""
    assert desc.startswith("READ ONLY.")
    assert ".js/.jsx/.ts/.tsx" in desc
    assert "DEC-032" in desc
    assert "decorative" in desc and "unknown" in desc
    assert "localizable/brand/admin-only are NOT emitted" in desc
    assert "JSX text nodes are not extracted" in desc
    assert "collection_complete=true means the authoritative total is known" in desc
    assert "does NOT mean every result was delivered" in desc

    properties = tool.input_schema["properties"]
    for param in ("path", "file_pattern", "max_results", "offset", "classify"):
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )
    assert properties["path"]["default"] == "."
    assert properties["file_pattern"]["default"] == "*"
    assert properties["max_results"]["default"] == 50
    assert properties["offset"]["default"] == 0
    assert properties["classify"]["default"] is True
    assert tool.input_schema.get("required", []) == []


def test_server_instructions_mention_the_tool() -> None:
    assert "mcquest_find_ui_text" in mcp.instructions


