"""V0.8 regression: ``mcquest_feature_impact_audit`` lexical change-impact audit.

Binding contract: ``Docs/V0.8/01-V0.8-CONTRACT.md`` sections 2.0/2.4/3/4
(DEC-027 path/error table; DEC-019 composed primitives and the file-type
boundary union; DEC-034 ``include_docs``/``include_locales`` optional booleans
defaulting to ``true``; DEC-035 ``MAX_ENUMERATE_FILES = 2000`` /
``MAX_FILES_ANALYZED = 500`` bounded scan with ``total`` counting findings
within the bounded scan only; DEC-028 budgets, explicit pagination, and the
separation of ``truncated`` from ``collection_complete``; DEC-016 capped-scan
completeness; DEC-030 ``feature_scope`` is not an input; DEC-025 no ``risk``,
``confidence``, or ``severity`` field and no issue-type/classification enum --
rows are review items, not asserted issues) and
``Docs/V0.8/04-V0.8-TEST-PLAN.md`` sections 2.1/2.3/2.4/2.5/2.8. Fixtures are
temporary files written under the per-test project root (conftest), so no
assertion depends on live repository contents.

Everything asserted here is lexical: exact-text/token comparisons with no
parser, no symbol resolution, and no semantic inference (DEC-015/DEC-019).
Rows are keyed one per ``(relative_path, line)`` and sorted by
``(relative_path ASC, line ASC)`` (test plan section 2.3 / DEC-018); a line
matched by several composed primitives carries all of its reasons in fixed
order (``find_usages`` usage; ``find_imports`` import module;
``find_strings`` string literal).
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.server import mcp
from mcquest_mcp.tools import ui_feature_impact
from mcquest_mcp.tools.ui_feature_impact import (
    MAX_ENUMERATE_FILES,
    MAX_FILES_ANALYZED,
    feature_impact_audit,
)

ROW_HEAD = re.compile(
    r"^(?P<rel>.+):(?P<line>\d+): (?P<kind>impacted file|affected doc|"
    r"locale key/reference|locale key|locale reference)$"
)
REASON_LINE = re.compile(r"^    reason: (?P<reason>.*)$")
EVIDENCE_LINE = re.compile(r"^    evidence: (?P<evidence>.*)$")

# Contract output vocabulary (section 2.4): impacted file / affected doc /
# locale key or reference.
KIND_IMPACTED = "impacted file"
KIND_DOC = "affected doc"
KIND_LOCALE_KEY = "locale key"
KIND_LOCALE_REF = "locale reference"
KIND_LOCALE_BOTH = "locale key/reference"
KINDS = {
    KIND_IMPACTED,
    KIND_DOC,
    KIND_LOCALE_KEY,
    KIND_LOCALE_REF,
    KIND_LOCALE_BOTH,
}

# Fixed composed-primitive reason strings (DEC-019).
USAGE = "word-boundary usage (find_usages)"
IMPORT = "import module reference (find_imports)"
STRING = "string-literal reference (find_strings)"
DOC_REF = "word-boundary documentation reference"
LOCALE_KEY = "locale key reference"
LOCALE_VALUE = "locale value reference"

# Fields and enum values this tool must never emit (section 2.4/3/4,
# DEC-024/DEC-025/DEC-030/DEC-032/DEC-033).
FORBIDDEN_FIELDS = ("severity", "risk", "confidence", "classification")
FORBIDDEN_ENUM_VALUES = (
    "missing_prop",
    "stale_prop",
    "mismatched_usage",
    "signature_drift",
    "unverifiable",
    "stale_reference",
    "missing_doc",
    "conflicting_reference",
    "status_mismatch",
    "decorative",
    "localizable",
    "admin-only",
)


# --- canonical fixture: every dimension and every composed primitive --------

GUIDE_MD = (
    "# Widget Guide\n"
    "The targetWidget powers many screens.\n"
    "targetWidget and targetWidget on one line.\n"
    "targetWidgets is a different token.\n"
)
EN_JSON = (
    "{\n"
    '  "targetWidget": "static value",\n'
    '  "greeting": "hello targetWidget",\n'
    '  "nested": { "targetWidget": "targetWidget label" }\n'
    "}\n"
)
MAIN_TS = (
    "export function targetWidget() { return null; }\n"
    'import { targetWidget } from "./targetWidget";\n'
)
# Import-module evidence without a word-boundary usage match: the specifier
# contains the lowercased target while neither the identifier nor the module
# text contains a word-boundary occurrence of the case-sensitive target.
IMPORT_ONLY_TS = 'import useTargetWidget from "./usetargetwidget";\n'
WIDGET_JSX = (
    'const label = "targetWidget rocks";\n'
    'const plural = "targetWidgets";\n'
)

FIXTURE = {
    "docs/guide.md": GUIDE_MD,
    "locales/en.json": EN_JSON,
    "src/app/main.ts": MAIN_TS,
    "src/import_only.ts": IMPORT_ONLY_TS,
    "src/widget.jsx": WIDGET_JSX,
}

# (relative_path, line, kind, reason) in the pinned (relative_path ASC,
# line ASC) order; a line matched by several primitives merges them in fixed
# order on a single row.
EXPECTED_ROWS = [
    ("docs/guide.md", 2, KIND_DOC, DOC_REF),
    ("docs/guide.md", 3, KIND_DOC, DOC_REF),
    ("locales/en.json", 2, KIND_LOCALE_KEY, LOCALE_KEY),
    ("locales/en.json", 3, KIND_LOCALE_REF, LOCALE_VALUE),
    ("locales/en.json", 4, KIND_LOCALE_BOTH, f"{LOCALE_KEY}; {LOCALE_VALUE}"),
    ("src/app/main.ts", 1, KIND_IMPACTED, USAGE),
    ("src/app/main.ts", 2, KIND_IMPACTED, f"{USAGE}; {IMPORT}; {STRING}"),
    ("src/import_only.ts", 1, KIND_IMPACTED, IMPORT),
    ("src/widget.jsx", 1, KIND_IMPACTED, f"{USAGE}; {STRING}"),
]
EXPECTED_FILES_AFFECTED = 5


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


def rows_of(output: str) -> list[dict[str, str]]:
    """Parse one page of impact rows into per-row field dictionaries."""
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in output.partition("[EVIDENCE]")[2].splitlines():
        head = ROW_HEAD.match(raw)
        if head:
            current = {
                "rel": head["rel"],
                "line": head["line"],
                "kind": head["kind"],
                "reason": "",
                "evidence": "",
            }
            rows.append(current)
            continue
        if current is None:
            continue
        reason = REASON_LINE.match(raw)
        if reason:
            current["reason"] = reason["reason"]
            continue
        evidence = EVIDENCE_LINE.match(raw)
        if evidence:
            current["evidence"] = evidence["evidence"]
    return rows


def row_keys(output: str) -> list[tuple[str, int, str, str]]:
    """Return ``(rel, line, kind, reason)`` identity tuples."""
    return [
        (row["rel"], int(row["line"]), row["kind"], row["reason"])
        for row in rows_of(output)
    ]


def evidence_body(output: str) -> str:
    """Return the ``[EVIDENCE]`` body of one page."""
    return output.partition("[EVIDENCE]")[2]


def write_std_fixture(write_file) -> None:
    """Write the canonical fixture (docs + locale + code)."""
    for relative, content in FIXTURE.items():
        write_file(relative, content)


def assert_std_expected(out: str) -> None:
    """Assert the canonical fixture's summary and exact deterministic rows."""
    s = summary_of(out)
    assert s["tool"] == "mcquest_feature_impact_audit"
    assert s["scope"] == 'path="."'
    assert s["TARGET"] == "targetWidget"
    assert s["PATH"] == "."
    assert s["INCLUDE_DOCS"] == "true"
    assert s["INCLUDE_LOCALES"] == "true"
    assert s["max_results"] == "50"
    assert s["total"] == str(len(EXPECTED_ROWS))
    assert s["files_affected"] == str(EXPECTED_FILES_AFFECTED)
    assert s["returned"] == str(len(EXPECTED_ROWS))
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert "NOTE" not in s
    assert out.rstrip().endswith("[END]")
    assert row_keys(out) == EXPECTED_ROWS
    assert all(row["evidence"] for row in rows_of(out))


def dense_code(count: int = 600) -> str:
    """One in-scope file with ``count`` matching lines (budget fixture)."""
    return "".join(
        f'const marker{i:03d} = "denseTarget";\n' for i in range(count)
    )


# --- registration and schema (test plan 2.1 / DEC-034/DEC-035) --------------


def test_registered_with_description_and_schema_defaults() -> None:
    """Six approved inputs, only ``target`` required, no ``feature_scope``."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_feature_impact_audit")
    desc = tool.description or ""

    assert desc.startswith("READ ONLY.")
    for trigger in (
        ".js/.jsx/.ts/.tsx",
        ".md/.markdown/.mdown/.mkd",
        ".json",
        "DEC-019",
        "DEC-025",
        "DEC-034",
        "DEC-035",
        "impacted file / affected doc / locale key or reference",
        "no severity field",
        "no issue-type/classification enum",
        "no confidence field",
        "no risk field",
        "REVIEW_CHECKLIST",
        "review suggestion only, never a fact",
        "2000",
        "500",
        "no separate code/document/locale caps",
        "collection_complete",
        "bounded scan only",
        "repository-global total",
        "no automatic page 2",
        "A zero result never proves absence of feature impact",
    ):
        assert trigger in desc, f"description missing trigger {trigger!r}"
    assert "MCQuest project" not in desc

    properties = tool.input_schema["properties"]
    assert set(properties) == {
        "target",
        "path",
        "max_results",
        "offset",
        "include_docs",
        "include_locales",
    }
    assert "feature_scope" not in properties
    assert tool.input_schema.get("required", []) == ["target"]
    for param in (
        "target",
        "path",
        "max_results",
        "offset",
        "include_docs",
        "include_locales",
    ):
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    assert properties["target"]["type"] == "string"
    assert "default" not in properties["target"]
    assert properties["path"]["type"] == "string"
    assert properties["path"]["default"] == "."
    assert properties["max_results"]["type"] == "integer"
    assert properties["max_results"]["default"] == 50
    assert properties["offset"]["type"] == "integer"
    assert properties["offset"]["default"] == 0
    assert properties["include_docs"]["type"] == "boolean"
    assert properties["include_docs"]["default"] is True
    assert properties["include_locales"]["type"] == "boolean"
    assert properties["include_locales"]["default"] is True


def test_server_instructions_mention_the_tool() -> None:
    assert mcp.instructions is not None
    assert "mcquest_feature_impact_audit" in mcp.instructions


# --- canonical rows, ordering, and composed evidence (section 2.4) ----------


def test_canonical_fixture_summary_rows_and_ordering(write_file) -> None:
    write_std_fixture(write_file)
    assert_std_expected(feature_impact_audit("targetWidget"))


def test_word_boundary_matching_evidence(write_file) -> None:
    """DEC-019: word-boundary matching; ``targetWidgets`` is a different token."""
    write_std_fixture(write_file)

    keys = row_keys(feature_impact_audit("targetWidget"))
    identities = {(rel, line) for rel, line, _kind, _reason in keys}

    assert ("src/app/main.ts", 1, KIND_IMPACTED, USAGE) in keys
    # ``targetWidgets`` has no trailing word boundary and must not match.
    assert ("docs/guide.md", 4) not in identities
    assert ("src/widget.jsx", 2) not in identities


def test_import_only_and_merged_reason_order(write_file) -> None:
    """Composed primitives merge on one row in the fixed reason order."""
    write_std_fixture(write_file)

    keys = row_keys(feature_impact_audit("targetWidget"))

    # find_imports evidence alone (module substring match).
    assert ("src/import_only.ts", 1, KIND_IMPACTED, IMPORT) in keys
    # find_usages + find_imports + find_strings on one row, fixed order.
    merged = [
        key for key in keys if key[:2] == ("src/app/main.ts", 2)
    ]
    assert merged == [
        ("src/app/main.ts", 2, KIND_IMPACTED, f"{USAGE}; {IMPORT}; {STRING}")
    ]


def test_string_literal_evidence_merged_on_one_row(write_file) -> None:
    """find_strings evidence appears on the same row as its usage reason."""
    write_std_fixture(write_file)

    keys = row_keys(feature_impact_audit("targetWidget"))

    assert ("src/widget.jsx", 1, KIND_IMPACTED, f"{USAGE}; {STRING}") in keys


def test_one_row_per_file_and_line(write_file) -> None:
    """Row identity is one row per (relative_path, line) (DEC-028/018)."""
    write_std_fixture(write_file)

    rows = rows_of(feature_impact_audit("targetWidget"))
    identities = [(row["rel"], row["line"]) for row in rows]

    assert len(identities) == len(set(identities))
    # Line 3 mentions the target twice; it stays a single row.
    guide_line3 = [
        row for row in rows if (row["rel"], row["line"]) == ("docs/guide.md", "3")
    ]
    assert len(guide_line3) == 1
    assert len([row for row in rows if row["rel"] == "src/app/main.ts"]) == 2


# --- documentation impact (DEC-034 include_docs) ----------------------------


def test_markdown_extensions_included(write_file) -> None:
    """All four Markdown extensions are documentation-impact scopes."""
    write_file("docs/a.md", "notesTarget is documented here.\n")
    write_file("docs/b.markdown", "notesTarget is documented here.\n")
    write_file("docs/c.mdown", "notesTarget is documented here.\n")
    write_file("docs/d.mkd", "notesTarget is documented here.\n")

    out = feature_impact_audit("notesTarget", path="docs")

    s = summary_of(out)
    assert s["total"] == "4"
    assert s["files_affected"] == "4"
    assert row_keys(out) == [
        ("docs/a.md", 1, KIND_DOC, DOC_REF),
        ("docs/b.markdown", 1, KIND_DOC, DOC_REF),
        ("docs/c.mdown", 1, KIND_DOC, DOC_REF),
        ("docs/d.mkd", 1, KIND_DOC, DOC_REF),
    ]


def test_include_docs_false_excludes_documentation_rows(write_file) -> None:
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget", include_docs=False)

    s = summary_of(out)
    assert s["INCLUDE_DOCS"] == "false"
    assert s["total"] == "7"
    assert s["files_affected"] == "4"
    assert KIND_DOC not in {row["kind"] for row in rows_of(out)}
    assert "docs/guide.md" not in out


def test_default_includes_docs_and_locales(write_file) -> None:
    """DEC-034: both dimensions default to ``true``."""
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget")

    s = summary_of(out)
    assert s["INCLUDE_DOCS"] == "true"
    assert s["INCLUDE_LOCALES"] == "true"
    kinds = {row["kind"] for row in rows_of(out)}
    assert KIND_DOC in kinds
    assert kinds & {KIND_LOCALE_KEY, KIND_LOCALE_REF, KIND_LOCALE_BOTH}


# --- locale impact (DEC-019 key-position lookup; DEC-034) -------------------


def test_locale_key_position_boundary_at_start_of_key(write_file) -> None:
    """A target beginning exactly at the start of a JSON key is a key
    reference (the previously fixed key-position boundary case)."""
    write_file("locales/en.json", '{\n  "targetWidget": "static value"\n}\n')

    out = feature_impact_audit("targetWidget", path="locales")

    assert row_keys(out) == [
        ("locales/en.json", 2, KIND_LOCALE_KEY, LOCALE_KEY)
    ]


def test_locale_value_and_combined_key_reference_detection(write_file) -> None:
    write_file(
        "locales/en.json",
        "{\n"
        '  "greeting": "hello targetWidget",\n'
        '  "nested": { "targetWidget": "targetWidget label" }\n'
        "}\n",
    )

    out = feature_impact_audit("targetWidget", path="locales")

    # Key-position matches precede value matches on the same row.
    assert row_keys(out) == [
        ("locales/en.json", 2, KIND_LOCALE_REF, LOCALE_VALUE),
        ("locales/en.json", 3, KIND_LOCALE_BOTH, f"{LOCALE_KEY}; {LOCALE_VALUE}"),
    ]


def test_include_locales_false_excludes_locale_evidence(write_file) -> None:
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget", include_locales=False)

    s = summary_of(out)
    assert s["INCLUDE_LOCALES"] == "false"
    assert s["total"] == "6"
    assert s["files_affected"] == "4"
    kinds = {row["kind"] for row in rows_of(out)}
    assert not kinds & {KIND_LOCALE_KEY, KIND_LOCALE_REF, KIND_LOCALE_BOTH}
    assert "locales/en.json" not in out


# --- scope and file-type boundaries (DEC-019 / section 2.0) -----------------


def test_code_extensions_included(write_file) -> None:
    """``.js``/``.jsx``/``.ts``/``.tsx`` are code-impact scopes."""
    write_file("src/a.js", "const a = boundaryTarget;\n")
    write_file("src/b.jsx", "const b = boundaryTarget;\n")
    write_file("src/c.ts", "const c = boundaryTarget;\n")
    write_file("src/d.tsx", "const d = boundaryTarget;\n")

    out = feature_impact_audit("boundaryTarget", path="src")

    assert row_keys(out) == [
        ("src/a.js", 1, KIND_IMPACTED, USAGE),
        ("src/b.jsx", 1, KIND_IMPACTED, USAGE),
        ("src/c.ts", 1, KIND_IMPACTED, USAGE),
        ("src/d.tsx", 1, KIND_IMPACTED, USAGE),
    ]


def test_unsupported_files_excluded_from_directory_scan(write_file) -> None:
    write_file("src/ok.ts", "const ok = skippedTarget;\n")
    write_file("src/notes.txt", "skippedTarget\n")
    write_file("src/script.py", "skippedTarget = 1\n")
    write_file("src/data.yaml", "skippedTarget: true\n")

    out = feature_impact_audit("skippedTarget", path="src")

    assert summary_of(out)["total"] == "1"
    assert row_keys(out) == [("src/ok.ts", 1, KIND_IMPACTED, USAGE)]


def test_single_file_scopes_accepted_within_boundary(write_file) -> None:
    """§2.0: an in-boundary single file is accepted for every dimension."""
    write_std_fixture(write_file)

    code = feature_impact_audit("targetWidget", path="src/app/main.ts")
    assert summary_of(code)["PATH"] == "src/app/main.ts"
    assert summary_of(code)["scope"] == 'path="src/app/main.ts"'
    assert row_keys(code) == [
        ("src/app/main.ts", 1, KIND_IMPACTED, USAGE),
        ("src/app/main.ts", 2, KIND_IMPACTED, f"{USAGE}; {IMPORT}; {STRING}"),
    ]

    doc = feature_impact_audit("targetWidget", path="docs/guide.md")
    assert summary_of(doc)["total"] == "2"
    assert {row["kind"] for row in rows_of(doc)} == {KIND_DOC}

    locale = feature_impact_audit("targetWidget", path="locales/en.json")
    assert summary_of(locale)["total"] == "3"
    assert not {row["kind"] for row in rows_of(locale)} & {KIND_IMPACTED, KIND_DOC}


def test_single_file_dimension_disabled_contributes_no_rows(write_file) -> None:
    """DEC-034: a disabled dimension contributes no rows, even for a single
    in-boundary file input (the file itself is still accepted)."""
    write_std_fixture(write_file)

    out = feature_impact_audit(
        "targetWidget", path="docs/guide.md", include_docs=False
    )

    s = summary_of(out)
    assert s["INCLUDE_DOCS"] == "false"
    assert s["total"] == "0"
    assert s["collection_complete"] == "true"
    assert rows_of(out) == []


# --- input, path, and error behavior (section 2.0 / DEC-027) ----------------


def test_path_error_table(write_file) -> None:
    write_file("src/ok.ts", "export const ok = 1;\n")
    write_file("node_modules/pkg.js", "export const ignored = 1;\n")
    write_file("docs/notes.txt", "# not markdown\n")
    write_file("src/script.py", "x = 1\n")

    with pytest.raises(FileNotFoundError):
        feature_impact_audit("ok", path="no/such/dir")
    with pytest.raises(ValueError, match="escapes"):
        feature_impact_audit("ok", path="../outside")
    with pytest.raises(ValueError, match="ignored directory"):
        feature_impact_audit("ok", path="node_modules")
    with pytest.raises(ValueError, match="ignored directory"):
        feature_impact_audit("ok", path="node_modules/pkg.js")
    with pytest.raises(ValueError, match="Unsupported file type"):
        feature_impact_audit("ok", path="docs/notes.txt")
    with pytest.raises(ValueError, match="Unsupported file type"):
        feature_impact_audit("ok", path="src/script.py")


def test_oversized_single_file_rejected(write_file) -> None:
    big = write_file("src/big.ts", "y" * (MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="byte safety limit"):
        feature_impact_audit("y", path=big)


def test_empty_and_whitespace_target_rejected(write_file) -> None:
    write_file("src/ok.ts", "export const ok = 1;\n")

    with pytest.raises(ValueError, match="target is required"):
        feature_impact_audit("")
    with pytest.raises(ValueError, match="target is required"):
        feature_impact_audit("   ")
    # An empty target is rejected rather than reported as an empty result.
    with pytest.raises(ValueError, match="target is required"):
        feature_impact_audit("", path="no/such/dir")


def test_negative_offset_rejected(write_file) -> None:
    write_std_fixture(write_file)

    with pytest.raises(ValueError, match="offset"):
        feature_impact_audit("targetWidget", offset=-1)


def test_empty_path_behaves_as_project_root(write_file) -> None:
    """§2.0: an omitted/empty path scans the project root (equivalent to ".")."""
    write_std_fixture(write_file)

    empty = feature_impact_audit("targetWidget", path="")
    dot = feature_impact_audit("targetWidget", path=".")

    assert summary_of(empty)["PATH"] == "."
    assert summary_of(empty)["scope"] == 'path="."'
    assert summary_of(empty)["total"] == str(len(EXPECTED_ROWS))
    assert empty == dot


# --- determinism and ordering (test plan 2.3) --------------------------------


def test_repeated_calls_are_identical_and_ordered(write_file) -> None:
    write_std_fixture(write_file)

    first = feature_impact_audit("targetWidget")
    second = feature_impact_audit("targetWidget")

    assert first == second
    keys = row_keys(first)
    assert keys == EXPECTED_ROWS
    # Exact (relative_path ASC, line ASC) ordering of the emitted rows.
    assert keys == sorted(keys, key=lambda key: (key[0], key[1]))


def test_traversal_order_independence(write_file) -> None:
    """Emission order never depends on filesystem traversal order."""
    # Files are created in reverse-sorted order on purpose.
    for relative in sorted(FIXTURE, reverse=True):
        write_file(relative, FIXTURE[relative])

    out = feature_impact_audit("targetWidget")

    assert row_keys(out) == EXPECTED_ROWS


# --- pagination (DEC-028: explicit offset only) ------------------------------


def test_explicit_offset_only_no_automatic_page_2(write_file) -> None:
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget", max_results=4)

    assert out.count("[SUMMARY]") == 1
    assert out.count("[EVIDENCE]") == 1
    s = summary_of(out)
    assert s["total"] == str(len(EXPECTED_ROWS))
    assert s["returned"] == "4"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "4"


def test_page_walk_has_no_overlap_or_gaps(write_file) -> None:
    write_std_fixture(write_file)

    first = summary_of(feature_impact_audit("targetWidget", max_results=4))
    assert first["next_offset"] == "4"

    page1 = feature_impact_audit("targetWidget", max_results=4, offset=0)
    page2 = feature_impact_audit("targetWidget", max_results=4, offset=4)
    page3 = feature_impact_audit("targetWidget", max_results=4, offset=8)
    tail = feature_impact_audit("targetWidget", max_results=4, offset=9)

    for page in (page1, page2, page3):
        assert summary_of(page)["total"] == str(len(EXPECTED_ROWS))

    keys1, keys2, keys3 = row_keys(page1), row_keys(page2), row_keys(page3)
    assert len(keys1) == len(keys2) == 4
    assert len(keys3) == 1
    assert not set(keys1) & set(keys2)
    assert not set(keys2) & set(keys3)
    assert not set(keys1) & set(keys3)
    assert keys1 + keys2 + keys3 == EXPECTED_ROWS

    second = summary_of(page2)
    assert second["offset"] == "4"
    assert second["next_offset"] == "8"
    assert second["has_more"] == "true"
    third = summary_of(page3)
    assert third["has_more"] == "false"
    assert "next_offset" not in third

    st = summary_of(tail)
    assert st["returned"] == "0"
    assert st["has_more"] == "false"
    assert row_keys(tail) == []
    assert tail.rstrip().endswith("[END]")


def test_expanded_budget_convention(write_file) -> None:
    """Explicit expansion (offset > 0 or max_results > default) raises the
    presentation budget to the ceiling, per the established convention."""
    write_std_fixture(write_file)

    assert summary_of(feature_impact_audit("targetWidget"))["budget"] == "4000/16000"
    assert (
        summary_of(feature_impact_audit("targetWidget", max_results=500))["budget"]
        == "16000/16000"
    )
    assert (
        summary_of(feature_impact_audit("targetWidget", offset=1))["budget"]
        == "16000/16000"
    )


# --- budgets, clamping, atomicity (DEC-028) ---------------------------------


def test_max_results_clamped_between_1_and_500(write_file) -> None:
    write_std_fixture(write_file)

    clamped_low = summary_of(feature_impact_audit("targetWidget", max_results=0))
    assert clamped_low["max_results"] == "1"
    assert clamped_low["returned"] == "1"

    clamped_high = summary_of(
        feature_impact_audit("targetWidget", max_results=9999)
    )
    assert clamped_high["max_results"] == "500"
    assert clamped_high["returned"] == str(len(EXPECTED_ROWS))


def test_dense_fixture_budget_truncation_and_atomic_rows(write_file) -> None:
    """A large fixture verifies the budget without unreasonable test cost."""
    write_file("src/dense.ts", dense_code())
    write_file("src/other.ts", "export const other = 1;\n")

    default = feature_impact_audit("denseTarget", path="src")
    s = summary_of(default)

    assert s["total"] == "600"
    assert s["files_affected"] == "1"
    assert s["budget"] == "4000/16000"
    assert s["truncated"] == "true"
    assert s["has_more"] == "true"
    assert s["next_offset"] == s["returned"]
    assert s["collection_complete"] == "true"
    assert len(default) <= 4000
    assert "[OUTPUT TRUNCATED:" in default
    assert 1 <= int(s["returned"]) < 50
    # Atomic rows: whole rows only, never a split snippet; the evidence body
    # respects the 200-char per-line clip.
    body = evidence_body(default)
    assert max(len(line) for line in body.splitlines()) <= 200
    rows = rows_of(default)
    assert len(rows) == int(s["returned"])
    assert all(row["reason"] and row["evidence"] for row in rows)

    expanded = feature_impact_audit("denseTarget", path="src", max_results=500)
    se = summary_of(expanded)
    assert se["total"] == "600"
    assert se["budget"] == "16000/16000"
    assert se["collection_complete"] == "true"
    assert len(expanded) <= 16000
    assert int(se["returned"]) > int(s["returned"])
    assert int(se["returned"]) <= 500

    # Explicit continuation reaches the remaining rows.
    tail = feature_impact_audit(
        "denseTarget",
        path="src",
        max_results=500,
        offset=int(se["next_offset"]),
    )
    st = summary_of(tail)
    assert st["total"] == "600"
    assert st["offset"] == se["next_offset"]
    assert st["collection_complete"] == "true"


# --- bounded scan / DEC-035 --------------------------------------------------


def test_bounded_scan_constants_and_no_per_dimension_caps() -> None:
    assert MAX_ENUMERATE_FILES == 2_000
    assert MAX_FILES_ANALYZED == 500
    # Only the two unified caps exist: no separate code/document/locale caps.
    upper_constants = {
        name
        for name in vars(ui_feature_impact)
        if name.isupper() and name.startswith("MAX_")
    }
    assert upper_constants == {
        "MAX_ENUMERATE_FILES",
        "MAX_FILES_ANALYZED",
        "MAX_FILE_BYTES",
        "MAX_SEARCH_RESULTS",
    }


def test_analysis_cap_marks_collection_incomplete(write_file) -> None:
    """DEC-035: ``MAX_FILES_ANALYZED = 500``; ``total`` counts findings within
    the bounded scan only and is never a repository-global total."""
    for i in range(501):
        write_file(f"src/m{i:04d}.ts", f"export const x{i} = {i};\n")
    write_file("src/m0000.ts", "export const capTarget = 1;\n")
    write_file("src/m0500.ts", "export const capTarget = 500;\n")

    out = feature_impact_audit("capTarget", path="src")
    s = summary_of(out)

    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert s["collection_complete"] == "false"
    assert "in-scope analysis limit reached" in out
    assert "scan not exhaustive" in out
    assert "partial inventory" in out
    assert "in-scope enumeration limit reached" not in out
    # The beyond-cap file holds the same reference but is not analyzed, so the
    # bounded total is not presented as a repository-global total.
    assert row_keys(out) == [("src/m0000.ts", 1, KIND_IMPACTED, USAGE)]
    assert not any(row["rel"] == "src/m0500.ts" for row in rows_of(out))


def test_enumeration_cap_marks_collection_incomplete(write_file) -> None:
    """DEC-035: ``MAX_ENUMERATE_FILES = 2000`` with the approved incomplete
    NOTE; ``total`` counts findings within the bounded scan only."""
    for i in range(2001):
        write_file(f"src/e{i:04d}.md", "enumTarget is referenced here.\n")

    out = feature_impact_audit("enumTarget", path="src")
    s = summary_of(out)

    assert s["collection_complete"] == "false"
    assert "in-scope enumeration limit reached" in out
    assert "scan not exhaustive" in out
    assert "partial inventory" in out
    # 2001 in-scope files exist on disk, but the bounded scan analyzes at most
    # MAX_FILES_ANALYZED of the enumerated subset.
    assert s["total"] == str(MAX_FILES_ANALYZED)
    assert s["files_affected"] == str(MAX_FILES_ANALYZED)


def test_uncapped_scan_is_complete_without_incomplete_note(write_file) -> None:
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget")

    s = summary_of(out)
    assert s["collection_complete"] == "true"
    assert "in-scope enumeration limit reached" not in out
    assert "in-scope analysis limit reached" not in out
    assert "scan not exhaustive" not in out


def test_oversized_file_in_scan_marks_collection_incomplete(write_file) -> None:
    """A skipped (oversized) in-scope file prevents full inspection."""
    write_file("src/big.ts", "export const bigSym = 1;\n" + "y" * MAX_FILE_BYTES)
    write_file("src/ok.ts", "export const scanTarget = 1;\n")

    out = feature_impact_audit("scanTarget", path="src")
    s = summary_of(out)

    assert s["total"] == "1"
    assert s["collection_complete"] == "false"
    assert "file skipped: oversized" in out
    assert "scan not exhaustive" in out


# --- completeness vs truncation (DEC-028 / section 3) -----------------------


def test_collection_complete_and_truncated_are_independent(write_file) -> None:
    # (a) complete scan whose page was cut by the presentation budget.
    write_file("src/dense.ts", dense_code())
    complete_but_truncated = summary_of(
        feature_impact_audit("denseTarget", path="src")
    )
    assert complete_but_truncated["truncated"] == "true"
    assert complete_but_truncated["collection_complete"] == "true"

    # (b) incomplete scan that delivered everything it found.
    for i in range(501):
        write_file(f"src/m{i:04d}.ts", f"export const x{i} = {i};\n")
    write_file("src/m0000.ts", "export const capTarget = 1;\n")
    incomplete_but_untruncated = summary_of(
        feature_impact_audit("capTarget", path="src")
    )
    assert incomplete_but_untruncated["truncated"] == "false"
    assert incomplete_but_untruncated["collection_complete"] == "false"


# --- review checklist and output contract (sections 2.4/3/4) -----------------


def test_review_checklist_present_and_framed_as_suggestions(write_file) -> None:
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget")
    s = summary_of(out)

    assert "REVIEW_CHECKLIST" in out.partition("[EVIDENCE]")[0]
    assert s["REVIEW_CHECKLIST"].startswith(
        "REVIEW_CHECKLIST (review suggestions only; not facts)"
    )
    assert "inspect each evidence row" in s["REVIEW_CHECKLIST"]
    assert "targetWidget" in s["REVIEW_CHECKLIST"]
    assert "review suggestions only; not facts" in out


def test_output_vocabulary_evidence_reason_and_no_labels(write_file) -> None:
    write_std_fixture(write_file)

    out = feature_impact_audit("targetWidget")
    rows = rows_of(out)

    assert [row["kind"] for row in rows] == [key[2] for key in EXPECTED_ROWS]
    assert {row["kind"] for row in rows} == KINDS
    # Every row carries its reason (the lexical evidence) and evidence line.
    assert all(row["reason"] for row in rows)
    assert all(row["evidence"] for row in rows)
    # No severity, risk, confidence, or classification field is emitted; rows
    # are review items, not asserted issues (§2.4/§3/§4, DEC-024/DEC-025).
    for forbidden in FORBIDDEN_FIELDS:
        assert forbidden not in out, forbidden
    for label in FORBIDDEN_ENUM_VALUES:
        assert label not in out, label


def test_zero_rows_zero_result_note_and_complete_scan(write_file) -> None:
    """A zero-row response means "no match in the scanned scope", never
    rejection (DEC-027); the NOTE states the lexical-candidate semantics."""
    write_file("src/other.ts", "export const other = 1;\n")

    out = feature_impact_audit("nothingMatchesHere", path="src")
    s = summary_of(out)

    assert s["total"] == "0"
    assert s["files_affected"] == "0"
    assert s["returned"] == "0"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert "zero result does not prove absence of feature impact" in out
    assert "scan not exhaustive" not in out
    assert "scan incomplete" not in out
    assert row_keys(out) == []
    assert out.rstrip().endswith("[END]")


# --- read-only (P014/P016; DEC-014) -----------------------------------------


def test_no_repository_mutation(write_file, repo) -> None:
    write_std_fixture(write_file)

    def snapshot() -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for base, _dirs, files in os.walk(repo):
            for name in files:
                full = os.path.join(base, name)
                stat = os.stat(full)
                snap[os.path.relpath(full, repo)] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )
        return snap

    before = snapshot()
    feature_impact_audit("targetWidget")
    feature_impact_audit("targetWidget", path="docs/guide.md")
    feature_impact_audit("targetWidget", include_docs=False, include_locales=False)
    feature_impact_audit("targetWidget", max_results=500, offset=1)
    assert snapshot() == before
