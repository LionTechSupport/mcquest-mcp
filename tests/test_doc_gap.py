"""V0.8 regression: ``mcquest_doc_gap_audit`` lexical documentation-gap audit.

Binding contract: ``Docs/V0.8/01-V0.8-CONTRACT.md`` sections 2.0/2.3/3/4
(DEC-027 path/error table; DEC-026 eligible doc locations, fence handling;
DEC-033 ``stale_reference`` evidence carriers, the ``conflicting_reference``
non-emitting gate, bounded-scan parameters/``total`` semantics; DEC-016/DEC-028
capped-scan completeness/continuation; DEC-022 absence-of-evidence honesty;
DEC-024 no consistency rows;; DEC-025 risk/confidence semantics) and
``Docs/V0.8/04-V0.8-TEST-PLAN.md`` sections  ̂2.3/2.4/2.5/2.7/2.8.
Fixtures are temporary files written under the per-test project root (conftest),
so no assertion depends on live repository contents.

Everything asserted here is lexical: exact-text/token comparisons with no parser,
no symbol resolution, and no semantic inference (DEC-015/DEC-018/DEC-033..
``missing_doc``/``conflicting_reference``/``status_mismatch``, consistency rows,
and ``risk`` are never emitted;; ``feature_scope`` is not an input. The tool uses
the bounded-scan model (``MAX_ENUMERATE_FILES``/``MAX_FILES_ANALYZED``); ``total``
counts findings within the bounded scan only and never claims a repository-global
total when a cap is hit.
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.server import mcp
from mcquest_mcp.tools.ui_doc_gap import (
    MAX_ENUMERATE_FILES,
    MAX_FILES_ANALYZED,
    doc_gap_audit,
)


ROW_HEAD = re.compile(
    r"^(?P<rel>.+):(?P<line>\d+): (?P<category>[a-z_]+) "
    r"\[severity: (?P<severity>\w+) \(heuristic\); "
    r"confidence: (?P<confidence>\w+) \(heuristic\)\]$"
)
CARRIER_LINE = re.compile(r"^    carrier: `(?P<carrier>.*)` \((?P<kind>.*)\)$")
ISSUE_LINE = re.compile(r"^    issue: (?P<issue>.*)$")
EVIDENCE_LINE = re.compile(r"^    evidence: (?P<evidence>.*)$")

# Expected canonical rows (docs relative_path ASC, doc line ASC, token ASC).
A_GUIDE_ROWS = [
    ("docs/a-guide.md", 4, "oldComponent", "inline backtick span", "warning", "high"),
    ("docs/a-guide.md", 4, "staleThing", "inline backtick span", "warning", "high"),
    ("docs/a-guide.md", 6, "src/legacy/util.ts", "path-like token", "warning", "high"),
]
B_SECOND_ROWS = [
    ("docs/b-second.md", 3, "alsoStale", "inline backtick span", "warning", "high"),
    ("docs/b-second.md", 4, "oldComponent", "inline backtick span", "warning", "high"),
    ("docs/b-second.md", 5, "oldComponent", "inline backtick span", "warning", "high"),
]
EXPECTED_A_B_ROWS = A_GUIDE_ROWS + B_SECOND_ROWS

A_GUIDE = "\n".join(
    [
        "# Guide",
        "",
        "The tool returns useful information for comparing old machinery.",
        "`oldComponent` and `staleThing` are documented references.",
        "`presentThing` and path `src/app/inner.ts` are real and current.",
        "Missing path: src/legacy/util.ts had been removed.",
        "Bare prose names: tool, returns, This, oldComponent, restHelper are not carriers.",
        "Directory path: src/legacy and unsupported path: src/legacy.txt are not carriers.",
        "```",
        "`fenceOnly` is excluded by fenced code blocks.",
        "```",
        "```ts",
        "`taggedOnly` is excluded in tagged fences too.",
        "```",
        "~~~",
        "`tildeOnly` is excluded in tilde fences too.",
        "~~~",
    ]
) + "\n"

B_SECOND = "\n".join(
    [
        "# Second",
        "",
        "`alsoStale` appears here again.",
        "`oldComponent` recurs on another line, distinct anchor.",
        "`oldComponent` twice on line5: `oldComponent`.",
    ]
) + "\n"

INNER_TS = (
    "export const presentThing = 1;\n"
    "export function helper() {\n"
    "  const inner = 3;\n"
    "  return inner;\n"
    "}\n"
)

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
    """Parse one page of issue rows into per-row field dictionaries."""
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in output.partition("[EVIDENCE]")[2].splitlines():
        head = ROW_HEAD.match(raw)
        if head:
            current = {
                "rel": head["rel"],
                "line": head["line"],
                "category": head["category"],
                "severity": head["severity"],
                "confidence": head["confidence"],
                "carrier": "",
                "kind": "",
                "issue": "",
                "evidence": "",
            }
            rows.append(current)
            continue

        if current is None:
            continue
        carrier = CARRIER_LINE.match(raw)
        if carrier:
            current["carrier"] = carrier["carrier"]
            current["kind"] = carrier["kind"]
            continue
        issue = ISSUE_LINE.match(raw)
        if issue:
            current["issue"] = issue["issue"]
            continue
        evidence = EVIDENCE_LINE.match(raw)
        if evidence:
            current["evidence"] = evidence["evidence"]
    return rows


def row_keys(output: str) -> list[tuple[str, int, str]]:
    """Return ``(rel, line, carrier token)`` identity keys."""
    return [
        (row["rel"], int(row["line"]), row["carrier"])
        for row in rows_of(output)
    ]


def write_std_fixture(write_file) -> None:
    """Write the canonical docs + code fixture pair (A + B + inner.ts)."""
    write_file("docs/a-guide.md", A_GUIDE)
    write_file("docs/b-second.md", B_SECOND)
    write_file("src/app/inner.ts", INNER_TS)


def assert_std_expected(out: str) -> None:
    """Assert the canonical fixture's exact deterministic ordering (DEC-028)."""
    s = summary_of(out)
    assert s["tool"] == "mcquest_doc_gap_audit"
    assert s["scope"] == 'path="."'
    assert s["PATH"] == "."
    assert s["CODE_PATH"] == "."
    assert s["max_results"] == "50"
    assert s["total"] == "6"
    assert s["files_affected"] == "2"
    assert s["returned"] == "6"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert out.rstrip().endswith("[END]")
    rows = rows_of(out)
    assert [
        (r["rel"], int(r["line"]), r["carrier"], r["kind"], r["severity"], r["confidence"])
        for r in rows
    ] == EXPECTED_A_B_ROWS
    # Every emitted severity/confidence label carries its supporting evidence row
    # (contract sections 2.3/4): no label without its evidence/issue lines..
    assert all(r["evidence"] for r in rows) and all(r["issue"] for r in rows)


# --- bounded-scan constants (DEC-033) ------------------------------

def test_bounded_scan_constants() -> None:
    assert MAX_ENUMERATE_FILES == 2_000
    assert MAX_FILES_ANALYZED == 500


# --- canonical fixture: carriers, ordering, evidence (contract 2.3) ----------

def test_canonical_fixture_rows_summary_and_ordering(write_file) -> None:
    write_std_fixture(write_file)
    assert_std_expected(doc_gap_audit())


def test_eligible_carriers_only_and_prose_never_emitted(write_file) -> None:
    """DEC-033: only inline backtick spans and path-like tokens with a recognized
    extension are carriers; ordinary prose identifiers are never candidates."""
    write_file("docs/a-guide.md", A_GUIDE)
    write_file("src/app/inner.ts", INNER_TS)

    out = doc_gap_audit()
    rows = rows_of(out)

    assert [
        (r["rel"], int(r["line"]), r["carrier"], r["kind"])
        for r in rows
    ] == [
        ("docs/a-guide.md", 4, "oldComponent", "inline backtick span"),
        ("docs/a-guide.md", 4, "staleThing", "inline backtick span"),
        ("docs/a-guide.md", 6, "src/legacy/util.ts", "path-like token"),
    ]
    # The prose identifiers (tool, returns, This, bare "oldComponent", restHelper),
    # no-extension path (src/legacy),and unsupported-extension path
    # (src/legacy.txt) produce no candidates (DEC-033..


def test_fenced_code_excluded_and_language_tags_ignored(write_file) -> None:
    """DEC-026: fenced (backtick/tilde) regions are excluded by default."""
    write_file("docs/a-guide.md", A_GUIDE)
    write_file("src/app/inner.ts", INNER_TS)

    rows = rows_of(doc_gap_audit())
    assert not any(r["carrier"] in {"fenceOnly", "taggedOnly", "tildeOnly"} for r in rows)


def test_path_tokens_match_paths_and_enumeration_basenames(write_file) -> None:
    """Path-like tokens are matched against code/docs path sets AND their
    basenames, so an existing basename never produces a stale row (DEC-022..
    The basename evidence comes from enumeration, not only analyzed reads."""
    write_file(
        "docs/edge.md",
        "\n".join(
            [
                "Basename match: `vendor/lib/inner.ts` should not be stale.",
                "Absent basename: `deep/uniqueThing.ts` should be stale.",
            ]
        )
        + "\n",
    )
    write_file("src/app/inner.ts", INNER_TS)

    rows = rows_of(doc_gap_audit())
    assert len(rows) == 1
    assert (rows[0]["rel"], rows[0]["line"], rows[0]["carrier"], rows[0]["kind"]) == (
        "docs/edge.md",
        "2",
        "deep/uniqueThing.ts",
        "path-like token",
    )


def test_any_identifier_match_in_span_marks_it_found(write_file) -> None:
    """A backtick span references code when ANY of its identifiers appears in
    the bounded code symbol set (span-level matching; DEC-033.."""
    write_file(
        "docs/edge.md",
        "`presentThing and staleThing` is one span(any identifier match -> found).\n"
        "`onlyAbsent` is a lone absent span.\n",
    )
    write_file("src/app/inner.ts", INNER_TS)

    rows = rows_of(doc_gap_audit())
    assert len(rows) == 1
    assert rows[0]["carrier"] == "onlyAbsent"
    assert rows[0]["line"] == "2"


def test_within_line_deduplication_and_cross_line_occurrences(write_file) -> None:
    """Row identity: one row per (docs file, doc line, token) occurrence;
    repeated spans on the SAME line collapse; a token on another doc line (or
    file) is a distinct doc anchor (DEC-028 pinned sort key)."""
    write_std_fixture(write_file)

    rows = rows_of(doc_gap_audit())
    a4 = [r for r in rows if r["rel"] == "docs/a-guide.md" and r["line"] == "4"]
    b4 = [r for r in rows if r["rel"] == "docs/b-second.md" and r["line"] == "4"]
    b5 = [r for r in rows if r["rel"] == "docs/b-second.md" and r["line"] == "5"]

    assert len(a4) == 2  # oldComponent, staleThing
    assert len(b4) == 1  # oldComponent recurs; distinct anchor vs a-guide:4
    assert len(b5) == 1  # "oldComponent" twice on the same line -> one row


def test_unterminated_fence_produces_incomplete_collection_and_note(write_file) -> None:
    """DEC-026: lines after the opening fence are excluded; the condition is
    reported through the completeness NOTE, never as a finding (DEC-016/033.."""
    write_file(
        "docs/unterm.md",
        "\n".join(
            [
                "# Unterminated",
                "",
                "`preFence` sits before an unterminated fence.",
                "```",
                "`postFence` is excluded after the opening fence.",
            ]
        )
        + "\n",
    )

    out = doc_gap_audit(docs_path="docs/unterm.md")
    s = summary_of(out)
    assert s["collection_complete"] == "false"
    assert s["total"] == "1"
    assert "NOTE" in s
    assert "unterminated fenced code block" in out
    assert "scan not exhaustive" in out

    rows = rows_of(out)
    assert len(rows) == 1
    assert rows[0]["carrier"] == "preFence"
    # A docs-side incompleteness does not downgrade code-absence confidence
    # (code evidence itself completed uncapped; DEC-033/DEC-025..
    assert rows[0]["confidence"] == "high"
    assert not any(r["carrier"] == "postFence" for r in rows)


def test_conflicting_and_deferred_categories_never_emitted(write_file) -> None:
    """DEC-024/DEC-025/DEC-030/DEC-033: conflicting_reference, missing_doc,
    status_mismatch, consistency rows,, and risk are never emitted."""

    write_file("docs/conflict.md", "`staleThing` is both shipped and removed in the same release.\n")
    write_file("src/app/inner.ts", INNER_TS)

    out = doc_gap_audit()
    assert {r["category"] for r in rows_of(out)} == {"stale_reference"}
    for forbidden in ("missing_doc", "conflicting_reference", "status_mismatch", "risk", "consistency"):
        assert forbidden not in out, forbidden


def test_explicit_offset_pagination_no_auto_page_2(write_file) -> None:
    """DEC-028: explicit offset only; no automatic second page; a multi-page
    walk covers every row exactly once (no gaps/overlaps)."""
    write_std_fixture(write_file)

    out = doc_gap_audit()
    assert out.count("[SUMMARY]") == 1
    assert out.count("[EVIDENCE]") == 1  # no automatic page 2 rendered
    all_keys = row_keys(out)
    assert len(all_keys) == 6

    p1 = doc_gap_audit(max_results=2, offset=0)
    f1 = summary_of(p1)
    assert f1["returned"] == "2"
    assert f1["has_more"] == "true"
    assert f1["next_offset"] == "2"
    assert f1["total"] == "6"

    p2 = doc_gap_audit(max_results=2, offset=2)
    f2 = summary_of(p2)
    assert f2["returned"] == "2"
    assert f2["has_more"] == "true"
    assert f2["next_offset"] == "4"

    p3 = doc_gap_audit(max_results=2, offset=4)
    f3 = summary_of(p3)
    assert f3["returned"] == "2"
    assert f3["has_more"] == "false"
    assert "next_offset" not in f3

    k1,k2,k3 = row_keys(p1),row_keys(p2),row_keys(p3)
    assert len(k1) == len(k2) == len(k3) == 2
    assert len(set(k1) & set(k2)) == 0
    assert len(set(k2) & set(k3)) == 0
    assert set(k1) | set(k2) | set(k3) == set(all_keys)


def dense_docs(count: int = 600) -> str:
    return "".join(f"`absent{i:03d}` " for i in range(count)) + "\n"


def test_budgets_truncation_atomicity_and_honest_total(write_file) -> None:
    """P014/DEC-028: bounded default page, expanded ceiling, atomic rows;>
    ``total`` stays the honest bounded-scan count regardless of page size."""
    write_file("docs/dense.md", dense_docs())
    write_file("src/app/inner.ts", INNER_TS)



    default = doc_gap_audit()
    assert len(default) <= 4000
    s = summary_of(default)
    assert s["budget"] == "4000/16000"
    assert s["total"] == "600"
    assert s["collection_complete"] == "true"
    assert s["truncated"] == "true"
    assert s["has_more"] == "true"
    assert s["next_offset"] == s["returned"]
    assert "[OUTPUT TRUNCATED:" in default
    assert max(len(line) for line in default.splitlines()) <= 200

    # Atomic emission: whole rows only, never a split snippet (P014..
    body = default.partition("[EVIDENCE]")[2]
    heads = sum(1 for line in body.splitlines() if ROW_HEAD.match(line))
    carries = sum(1 for line in body.splitlines() if CARRIER_LINE.match(line))
    issues = sum(1 for line in body.splitlines() if ISSUE_LINE.match(line))
    evidences = sum(1 for line in body.splitlines() if EVIDENCE_LINE.match(line))
    assert heads > 0
    assert heads == issues == carries == evidences

    expanded = doc_gap_audit(max_results=500)
    assert len(expanded) <= 16000
    se = summary_of(expanded)
    assert se["budget"] == "16000/16000"
    assert se["total"] == "600"
    assert se["collection_complete"] == "true"
    assert max(len(line) for line in expanded.splitlines()) <= 200
    assert int(se["returned"]) > int(s["returned"])

    tail = doc_gap_audit(max_results=500, offset=int(se["next_offset"]))
    st = summary_of(tail)
    assert st["total"] == "600"
    assert st["offset"] == se["next_offset"]
    assert st["collection_complete"] == "true"


def test_zero_rows_empty_scope_and_zero_result_note(write_file) -> None:
    """A zero-row response means no match in the scanned scope, not rejection
    (DEC-027); the zero-result NOTE states candidate semantics ((DEC-022.."""
    write_file("src/empty.ts", "")
    out = doc_gap_audit()
    s = summary_of(out)
    assert s["total"] == "0"
    assert s["files_affected"] == "0"
    assert s["returned"] == "0"
    assert s["collection_complete"] == "true"
    assert "no stale-reference candidates matched" in out
    assert "scan not exhaustive" not in out
    assert out.rstrip().endswith("[END]")
    assert len(rows_of(out)) == 0


def test_single_file_docs_and_code_scopes(write_file) -> None:
    """Single in-boundary files are accepted (§2.0); the code scope is exactly
    the selected file, so tokens referencing files outside it are stale."""
    write_std_fixture(write_file)

    # Docs single-file scope: only docs/a-guide.md is scanned, so the
    # b-second.md tokens are excluded; code scope is the whole root (which at
    # this point holds only src/app/inner.ts, so util.ts basenames do not yet
    # shadow src/legacy/util.ts).
    docs_only = doc_gap_audit(docs_path="docs/a-guide.md")
    s = summary_of(docs_only)
    assert s["PATH"] == "docs/a-guide.md"
    assert s["scope"] == 'path="docs/a-guide.md"'
    assert s["total"] == "3"
    assert s["collection_complete"] == "true"
    assert not any(r["rel"] == "docs/b-second.md" for r in rows_of(docs_only))

    # Code single-file scope: only src/app/inner.ts forms the code evidence,
    # so tokens referencing another on-disk file are stale (scope semantics).
    write_file("src/other/util.ts", "export const utilSym = 1;\n")
    write_file(
        "docs/scope.md",
        "`presentThing` is in the selected code scope.\n"
        "`utilSym` lives in another file outside the selected code scope.\n"
        "Path: src/other/util.ts.\n",
    )
    code_only = doc_gap_audit(docs_path="docs/scope.md", code_path="src/app/inner.ts")
    rows = rows_of(code_only)
    assert [
        (r["carrier"], r["kind"]) for r in rows
    ] == [
        ("utilSym", "inline backtick span"),
        ("src/other/util.ts", "path-like token"),
    ]
    assert summary_of(code_only)["total"] == "2"


def test_path_error_table(write_file) -> None:
    """DEC-027 §2.0 table: invalid inputs are rejected explicitly, never as
    an empty result set;; oversized single files are rejected;; unsupported
    extensions are rejected;; out-of-root and ignored paths are rejected."""
    write_file("src/ok.ts", "export const ok = 1;\n")
    write_file("node_modules/pkg.js", "export const ignored = 1;\n")
    write_file("docs/notes.txt", "# not markdown\n")
    write_file("src/script.py", "x = 1\n")
    write_file("docs/big.md", "y" * (MAX_FILE_BYTES + 1))
    write_file("src/big.ts", "y" * (MAX_FILE_BYTES + 1))

    with pytest.raises(FileNotFoundError): doc_gap_audit(docs_path="no/such/dir")
    with pytest.raises(FileNotFoundError): doc_gap_audit(code_path="no/such/dir")
    with pytest.raises(ValueError, match="escapes"): doc_gap_audit(docs_path="../outside")
    with pytest.raises(ValueError, match="ignored directory"): doc_gap_audit(docs_path="node_modules")
    with pytest.raises(ValueError, match="ignored directory"): doc_gap_audit(code_path="node_modules/pkg.js")
    with pytest.raises(ValueError, match="Unsupported file type"): doc_gap_audit(docs_path="docs/notes.txt")
    with pytest.raises(ValueError, match="Unsupported file type"): doc_gap_audit(code_path="src/script.py")
    with pytest.raises(ValueError, match="byte safety limit"): doc_gap_audit(docs_path="docs/big.md")
    with pytest.raises(ValueError, match="byte safety limit"): doc_gap_audit(code_path="src/big.ts")


def test_negative_offset_rejected_and_max_results_clamped(write_file) -> None:
    write_std_fixture(write_file)



    with pytest.raises(ValueError, match="offset"): doc_gap_audit(offset=-1)

    clamped_low = doc_gap_audit(max_results=0)
    assert summary_of(clamped_low)["max_results"] == "1"
    assert summary_of(clamped_low)["returned"] == "1"

    clamped_high = doc_gap_audit(max_results=9999)
    assert summary_of(clamped_high)["max_results"] == "500"
    assert summary_of(clamped_high)["returned"] == "6"


def test_no_repository_mutation(write_file, repo) -> None:
    """The tool is strictly read-only: no file may be created, modified, or
    deleted under the project root (P005/DEC-014.."""
    write_std_fixture(write_file)

    def snapshot() -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for base, _dirs, files in os.walk(repo):
            for name in files:
                full = os.path.join(base, name)
                stat = os.stat(full)
                snap[os.path.relpath(full, repo)] = (stat.st_size, stat.st_mtime_ns)
        return snap

    before = snapshot()
    doc_gap_audit()
    doc_gap_audit(docs_path="docs/a-guide.md", code_path="src")
    doc_gap_audit(max_results=1, offset=1)
    assert snapshot() == before


def test_analysis_cap_incomplete_collection_and_medium_confidence(write_file) -> None:
    """DEC-033: MAX_FILES_ANALYZED=500; a token whose only code home lies
    beyond the analysis cap is stale with downgraded (medium) confidence;
    total counts findings within the bounded scan only; enumerated paths stay
    existence evidence beyond the cap (DEC-022.."""
    for i in range(501):
        write_file(f"src/m{i:04d}.ts", f"export const x{i} = {i};\n")
    write_file(
        "docs/cap.md",
        "\n".join(
            [
                "# Cap",
                "",
                "Alive: `x42`.",
                "Beyond cap: `x500`.",
                "Path elsehere: src/m0500.ts.",
            ]
        )
        + "\n",
    )

    out = doc_gap_audit(docs_path="docs/cap.md")
    s = summary_of(out)
    assert s["total"] == "1"
    assert s["collection_complete"] == "false"
    assert s["files_affected"] == "1"
    assert "code analysis limit reached" in out

    rows = rows_of(out)
    assert len(rows) == 1
    assert rows[0]["carrier"] == "x500"
    assert rows[0]["confidence"] == "medium"
    assert "src/m0500.ts" not in {r["carrier"] for r in rows}
    assert "x42" not in {r["carrier"] for r in rows}


def test_enumeration_cap_incomplete_collection(write_file) -> None:
    """DEC-033: MAX_ENUMERATE_FILES=2000; docs enumeration is capped and the
    completeness NOTE is emitted;; total counts findings among the bounded scan
    (the single carrier lives inside the enumerated window, so it is counted)."""
    write_file("docs/d0000.md", "`onlyToken` is the single stale carrier.\n")
    for i in range(1, 2001):
        write_file(f"docs/d{i:04d}.md", "")

    out = doc_gap_audit()
    s = summary_of(out)
    assert s["total"] == "1"
    assert s["collection_complete"] == "false"
    assert "docs enumeration limit reached" in out

    rows = rows_of(out)
    assert len(rows) == 1
    assert rows[0]["carrier"] == "onlyToken"
    # Code evidence completed uncapped; a docs-side enumeration cap does not
    # downgrade code-absence confidence (DEC-033/DEC-025..
    assert rows[0]["confidence"] == "high"


def test_oversized_code_file_skipped_downgrades_confidence(write_file) -> None:
    """A code file that was enumerated but could not be read (oversized) retains
    its path existence evidence but contributes no identifiers, sour token only
    defined there is stale with medium confidence (DEC-022/DEC-025.."""
    write_file("src/big.ts", "export const bigSym = 1;\n" + "y" * MAX_FILE_BYTES)
    write_file("src/ok.ts", "export const okSym = 1;\n")
    write_file(
        "docs/ov.md",
        "\n".join(
            [
                "Sym: `bigSym`.",
                "Path: src/big.ts.",
            ]
        )
        + "\n",
    )
    out = doc_gap_audit(docs_path="docs/ov.md")
    s = summary_of(out)
    assert s["collection_complete"] == "false"
    assert "code file skipped: oversized" in out

    rows = rows_of(out)
    assert len(rows) == 1
    assert rows[0]["carrier"] == "bigSym"
    assert rows[0]["confidence"] == "medium"
    assert not any(r["carrier"] == "src/big.ts" for r in rows)


# --- registration and discoverability (DEC-020) ------------------------------

def test_registered_with_description_and_schema_defaults() -> None:
    """DEC-020/DEC-033: four approved inputs only (no feature_scope);>; the
    description records the carrier,#non-emitting#gates,,and bounded-scan model."""
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_doc_gap_audit")
    desc = tool.description or ""
    assert desc.startswith("READ ONLY.")
    for trigger in (
        ".md/.markdown/.mdown/.mkd",
        ".js/.jsx/.ts/.tsx",
        "stale_reference",
        "backtick-delimited",
        "path-like",
        "DEC-033",
        "missing_doc",
        "conflicting_reference",
        "status_mismatch",
        "NOT EMITTABLE",
        "2000",
        "500",
        "collection_complete",
        "heuristic",
        "bounded scan only",
    ):
        assert trigger in desc, f"description missing trigger {trigger!r}"

    properties = tool.input_schema["properties"]
    assert set(properties) == {"docs_path", "code_path", "max_results", "offset"}
    for param in ("docs_path", "code_path", "max_results", "offset"):
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )
    assert properties["docs_path"]["default"] == "."
    assert properties["code_path"]["default"] == "."
    assert properties["max_results"]["default"] == 50
    assert properties["offset"]["default"] == 0
    assert tool.input_schema.get("required", []) == []


def test_server_instructions_mention_the_tool() -> None:
    assert "mcquest_doc_gap_audit" in mcp.instructions