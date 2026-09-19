"""V0.7 Stage 4 regression: ``mcquest_component_inventory`` lexical inventory.

Binding contract: DEC-013 (updated to APPROVED) + DEC-014 (2026-09-18) and
``Docs/V0.7/08-V0.7-STAGE4-SPEC.md``. Lexical-only, metadata-only rows
``<relative_path>:<line>: <Name> (<kind>)`` over ``.js/.jsx/.ts/.tsx`` with
recognised kinds ``function``/``arrow``/``class``. Coverage is FIXTURE-BASED:
the selected repository contains no React components or JSX/TSX, so these
tests validate the defined lexical cases only and are NOT evidence about real
project components (spec sections 1.2/10.3).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from mcquest_mcp.config import (
    IGNORED_DIRECTORIES,
    LINE_CLIP_CHARS,
    MAX_FILE_BYTES,
    MAX_OUTPUT_CHARS,
    MAX_SEARCH_RESULTS,
    NORMAL_OUTPUT_CHARS,
)
from mcquest_mcp.server import mcp
from mcquest_mcp.tools.component_inventory import component_inventory

# The tool module must be fetched from ``sys.modules``: ``tools/__init__.py``
# re-exports a function with the same name as its module, so a plain
# ``from mcquest_mcp.tools import component_inventory`` binds the *function*.
import importlib

ci_module = importlib.import_module("mcquest_mcp.tools.component_inventory")


def summary_of(output: str) -> dict[str, str]:
    """Parse the ``[SUMMARY]`` block into ``{key: value}``."""
    data: dict[str, str] = {}
    for line in output.partition("[EVIDENCE]")[0].splitlines():
        if line.startswith("tool: "):
            data["tool"] = line[6:]
        elif line.startswith("scope: "):
            data["scope"] = line[7:]
        elif ": " in line:
            key, value = line.split(": ", 1)
            data[key] = value
    return data


def rows_of(output: str) -> list[str]:
    """Return the evidence rows (``relative:line: Name (kind)``)."""
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


# --- R-1..R-6 recognition and kind mapping (O-3a/O-3b/O-23) ------------------


def test_r1_r6_recognition_and_kind_mapping(write_file) -> None:
    write_file(
        "src/forms.tsx",
        "function Widget() {}\n"            # R-1 -> function
        "export function Header() {}\n"     # R-1 (export) -> function
        "class Card {}\n"                   # R-2 -> class
        "export class Panel {}\n"           # R-2 (export) -> class
        "const Btn = () => 1;\n"            # R-3 -> arrow
        "const T = function inner() {};\n"  # R-4 -> function
        "const Icon = async () => 2;\n"     # R-5 arrow -> arrow
        "const F = async function () {};\n" # R-5 function -> function
        "export default function Page() {}\n"  # R-6 -> function
        "export default class Layout {}\n"     # R-6 -> class
    )

    out = component_inventory(path="src")

    assert summary_of(out)["tool"] == "mcquest_component_inventory"
    assert summary_of(out)["total"] == "10"
    assert summary_of(out)["collection_complete"] == "true"
    assert rows_of(out) == [
        "src/forms.tsx:1: Widget (function)",
        "src/forms.tsx:2: Header (function)",
        "src/forms.tsx:3: Card (class)",
        "src/forms.tsx:4: Panel (class)",
        "src/forms.tsx:5: Btn (arrow)",
        "src/forms.tsx:6: T (function)",
        "src/forms.tsx:7: Icon (arrow)",
        "src/forms.tsx:8: F (function)",
        "src/forms.tsx:9: Page (function)",
        "src/forms.tsx:10: Layout (class)",
    ]


def test_class_kind_not_gated_on_react_base_class(write_file) -> None:
    """O-3(b): any lexical ``class NAME`` is ``class``; no React gate."""
    write_file("src/c.tsx", "class Plain {}\nclass Reacty extends React.Component {}\n")

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/c.tsx:1: Plain (class)",
        "src/c.tsx:2: Reacty (class)",
    ]


# --- E-1..E-4 guards --------------------------------------------------------


def test_e1_lowercase_names_not_matched(write_file) -> None:
    write_file(
        "src/g.ts",
        "function helper() {}\nconst fs = require('fs');\nlet ts;\nclass lower {}\n",
    )

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "0"
    assert rows_of(out) == []


def test_e2_uppercase_constant_excluded_repository_trap(write_file) -> None:
    """E-2: the real ``const MAX_EMITTED = 500;`` shape must not match."""
    write_file(
        "src/traps.js",
        "const MAX_EMITTED = 500;\n"
        "const NAMES = [];\n"
        "const MAP = {};\n"
        "const SYM = Symbol('x');\n"
        "const REQ = require('fs');\n",
    )

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "0"
    assert rows_of(out) == []


def test_e3_class_expression_excluded(write_file) -> None:
    """E-3/O-7 default: ``const Name = class ...`` is not a candidate."""
    write_file("src/ce.ts", "const Bar = class extends Base {};\n")

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "0"


def test_e4_anonymous_default_skipped(write_file) -> None:
    """O-3(c): anonymous default declarations are skipped, no placeholder."""
    write_file(
        "src/anon.tsx",
        "export default function () {}\n"
        "export default () => 1;\n"
        "export default class {}\n"
        "export default function Named() {}\n",
    )

    out = component_inventory(path="src")

    assert rows_of(out) == ["src/anon.tsx:4: Named (function)"]
    assert summary_of(out)["total"] == "1"
    assert "(default)" not in out


# --- documented false positives / limitations (spec sec 4.4, O-5) -----------


def test_comments_and_strings_are_not_stripped(write_file) -> None:
    """A declaration-shaped match in a comment/string is a documented FP."""
    write_file(
        "src/notes.tsx",
        "// function Commented() {}\n"
        "/* class Blocked {} */\n"
        "const label = 'function Strung() {}';\n",
    )

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/notes.tsx:1: Commented (function)",
        "src/notes.tsx:2: Blocked (class)",
        "src/notes.tsx:3: Strung (function)",
    ]


def test_multiline_declaration_is_not_matched(write_file) -> None:
    """O-5 default: the line model is single-line; split forms are missed."""
    write_file(
        "src/split.tsx",
        "const Wrapped =\n"
        "  () => 1;\n"
        "function\n"
        "  Split() {}\n",
    )

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "0"


def test_non_ascii_name_is_not_matched(write_file) -> None:
    """O-19: name matching is ASCII-only ``[A-Z][A-Za-z0-9_]*``."""
    write_file("src/uni.tsx", "function \u00dcnicode() {}\nfunction Abuja() {}\n")

    out = component_inventory(path="src")

    assert rows_of(out) == ["src/uni.tsx:2: Abuja (function)"]


# --- O-10a / O-10b emission rules ------------------------------------------


def test_same_line_multiple_candidates_all_emitted(write_file) -> None:
    """O-10(a): every distinct same-line candidate is emitted."""
    write_file("src/multi.tsx", "const Zed = () => 1; const Abel = () => 2;\n")

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/multi.tsx:1: Abel (arrow)",
        "src/multi.tsx:1: Zed (arrow)",
    ]
    assert summary_of(out)["total"] == "2"


def test_same_line_distinct_kinds_are_kept_apart(write_file) -> None:
    write_file("src/kinds.tsx", "const A1 = () => 1; const B1 = function () {};\n")

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/kinds.tsx:1: A1 (arrow)",
        "src/kinds.tsx:1: B1 (function)",
    ]


def test_byte_identical_rows_are_deduplicated(write_file) -> None:
    """O-10(b): repeated recogniser hits on ``(path, line, name, kind)`` merge."""
    write_file(
        "src/dup.tsx",
        "const Same = function Same() {};\n"
        "const D = () => 1;\n",
    )

    out = component_inventory(path="src")

    rows = rows_of(out)
    assert rows.count("src/dup.tsx:1: Same (function)") == 1
    assert summary_of(out)["total"] == "2"


def test_same_name_on_different_lines_is_not_a_duplicate(write_file) -> None:
    write_file("src/twin.tsx", "function Twin() {}\nfunction Twin() {}\n")

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/twin.tsx:1: Twin (function)",
        "src/twin.tsx:2: Twin (function)",
    ]
    assert summary_of(out)["total"] == "2"


# --- deterministic ordering and explicit paging -----------------------------


def test_deterministic_ordering_across_files(write_file) -> None:
    """Rows order by (relative_path bytes, line, name, kind)."""
    write_file("src/b.tsx", "function Bravo() {}\n")
    write_file("src/a.tsx", "function Alpha() {}\nfunction Beta() {}\n")
    write_file("src/sub/c.tsx", "function Charlie() {}\n")

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/a.tsx:1: Alpha (function)",
        "src/a.tsx:2: Beta (function)",
        "src/b.tsx:1: Bravo (function)",
        "src/sub/c.tsx:1: Charlie (function)",
    ]


def test_ordering_is_stable_across_runs(write_file) -> None:
    write_file("src/y.tsx", "const Why = () => 1;\nfunction Wye() {}\nclass Wye2 {}\n")
    write_file("src/x.tsx", "function Ex() {}\n")

    assert component_inventory(path="src") == component_inventory(path="src")


def test_pagination_pages_are_explicit_and_stable(write_file) -> None:
    write_file(
        "src/page.tsx",
        "function P1() {}\nfunction P2() {}\nfunction P3() {}\n"
        "function P4() {}\nfunction P5() {}\n",
    )

    first = component_inventory(path="src", max_results=2)
    assert summary_of(first)["total"] == "5"
    assert summary_of(first)["returned"] == "2"
    assert summary_of(first)["has_more"] == "true"
    assert summary_of(first)["next_offset"] == "2"
    assert rows_of(first) == [
        "src/page.tsx:1: P1 (function)",
        "src/page.tsx:2: P2 (function)",
    ]

    second = component_inventory(path="src", max_results=2, offset=2)
    assert summary_of(second)["next_offset"] == "4"
    assert rows_of(second) == [
        "src/page.tsx:3: P3 (function)",
        "src/page.tsx:4: P4 (function)",
    ]

    last = component_inventory(path="src", max_results=2, offset=4)
    assert summary_of(last)["has_more"] == "false"
    assert "next_offset" not in summary_of(last)
    assert rows_of(last) == ["src/page.tsx:5: P5 (function)"]

    beyond = component_inventory(path="src", offset=99)
    assert summary_of(beyond)["returned"] == "0"
    assert summary_of(beyond)["has_more"] == "false"


def test_pagination_does_not_affect_collection_complete(write_file) -> None:
    write_file("src/p.tsx", "function Only() {}\n")

    out = component_inventory(path="src", max_results=1, offset=0)

    assert summary_of(out)["has_more"] == "false"
    assert summary_of(out)["collection_complete"] == "true"


# --- extensions, .d.ts, patterns, ignored paths -----------------------------


def test_supported_extensions_are_scanned_and_others_ignored(write_file) -> None:
    for name in ("a.js", "b.jsx", "c.ts", "d.tsx"):
        write_file(f"src/{name}", "function Comp() {}\n")
    write_file("src/e.mjs", "function Missed1() {}\n")
    write_file("src/f.cjs", "function Missed2() {}\n")
    write_file("src/g.vue", "function Missed3() {}\n")
    write_file("src/h.py", "def missed(): pass\n")

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "4"
    assert summary_of(out)["files_affected"] == "4"
    assert all(row.endswith("Comp (function)") for row in rows_of(out))


def test_d_ts_files_are_excluded_by_suffix(write_file) -> None:
    """O-8: ``.d.ts`` is excluded; other ``.ts`` keeps ``declare`` matches."""
    write_file("src/types.d.ts", "declare function Declared(): void;\n")
    write_file(
        "src/keep.ts",
        "declare function Residual(): void;\nfunction Kept() {}\n",
    )

    out = component_inventory(path="src")

    rows = rows_of(out)
    assert not any("types.d.ts" in row for row in rows)
    assert "src/keep.ts:1: Residual (function)" in rows
    assert "src/keep.ts:2: Kept (function)" in rows


def test_explicit_single_file_is_scanned(write_file) -> None:
    write_file("src/one.tsx", "function Solo() {}\nconst Two = () => 2;\n")

    out = component_inventory(path="src/one.tsx")

    assert summary_of(out)["total"] == "2"
    assert summary_of(out)["collection_complete"] == "true"


def test_single_file_unsupported_extension_rejected(write_file) -> None:
    """O-12: explicit unsupported-extension file paths raise ValueError."""
    write_file("notes.txt", "function Nope() {}\n")

    with pytest.raises(ValueError, match="Unsupported extension"):
        component_inventory(path="notes.txt")


def test_single_file_d_ts_rejected(write_file) -> None:
    write_file("src/only.d.ts", "declare function Nope(): void;\n")

    with pytest.raises(ValueError, match="Unsupported extension"):
        component_inventory(path="src/only.d.ts")


def test_file_pattern_filters_by_basename(write_file) -> None:
    write_file("src/keep.tsx", "function Kept() {}\n")
    write_file("src/skip.tsx", "function Skipped() {}\n")
    write_file("src/other.ts", "function AlsoSkipped() {}\n")

    out = component_inventory(path="src", file_pattern="keep.*")

    assert rows_of(out) == ["src/keep.tsx:1: Kept (function)"]
    assert summary_of(out)["FILE_PATTERN"] == "keep.*"


def test_malformed_file_pattern_is_silent_no_match(write_file) -> None:
    """O-14 (still OPEN): the established fnmatch convention is silent."""
    write_file("src/ok.tsx", "function Found() {}\n")

    out = component_inventory(path="src", file_pattern="[unclosed")

    assert summary_of(out)["total"] == "0"
    assert summary_of(out)["collection_complete"] == "true"


def test_ignored_directories_are_not_scanned(write_file) -> None:
    ignored = sorted(IGNORED_DIRECTORIES - {".git"})[0]
    write_file(f"{ignored}/pkg.tsx", "function Hidden() {}\n")
    write_file("src/visible.tsx", "function Visible() {}\n")

    out = component_inventory(path=".")

    assert rows_of(out) == ["src/visible.tsx:1: Visible (function)"]


# --- approved numeric limits, caps, and completeness ------------------------


def test_approved_stage4_limits_are_exact() -> None:
    """DEC-013/DEC-014: only the two approved limits exist, with exact values."""
    assert ci_module.MAX_ENUMERATE_FILES == 2_000
    assert ci_module.MAX_FILES_ANALYZED == 500

    # O-17: no per-file/global row caps exist at all (no row-cap condition).
    for name in ("MAX_FILE_ROWS", "MAX_ROWS", "MAX_LOCALE_ROWS", "MAX_LOCALE_FILE_ROWS"):
        assert not hasattr(ci_module, name), name

    # O-16: no identity/key-path limits are implemented for a line scan.
    for name in ("MAX_EXACT_PATHS_PER_FILE", "MAX_EXACT_BYTES_PER_FILE", "IDENTITY_UNITS_MAX"):
        assert not hasattr(ci_module, name), name


def test_enumeration_cap_marks_collection_incomplete(write_file, monkeypatch) -> None:
    monkeypatch.setattr(ci_module, "MAX_ENUMERATE_FILES", 2)
    for name in ("a.tsx", "b.tsx", "c.tsx"):
        write_file(f"src/{name}", "function Cap() {}\n")

    out = component_inventory(path="src")

    assert summary_of(out)["collection_complete"] == "false"
    assert "file limit reached" in out
    assert summary_of(out)["total"] == "2"


def test_files_analyzed_cap_bounds_analysis(write_file, monkeypatch) -> None:
    monkeypatch.setattr(ci_module, "MAX_FILES_ANALYZED", 1)
    write_file("src/a.tsx", "function Analyzed() {}\n")
    write_file("src/b.tsx", "function NotAnalyzed() {}\n")

    out = component_inventory(path="src")

    assert rows_of(out) == ["src/a.tsx:1: Analyzed (function)"]
    assert summary_of(out)["collection_complete"] == "false"
    assert "file limit reached" in out


def test_oversized_file_is_skipped_and_marked_incomplete(write_file, monkeypatch) -> None:
    monkeypatch.setattr(ci_module, "MAX_FILE_BYTES", 20)
    write_file("src/big.tsx", "function TooBig() {}\n" + "// padding\n" * 5)
    write_file("src/small.tsx", "function Fits() {}\n")

    out = component_inventory(path="src")

    assert rows_of(out) == ["src/small.tsx:1: Fits (function)"]
    assert summary_of(out)["collection_complete"] == "false"
    assert "file skipped: oversized" in out


def test_unreadable_file_is_skipped_and_marked_incomplete(write_file, monkeypatch) -> None:
    write_file("src/broken.tsx", "function Unreadable() {}\n")
    write_file("src/fine.tsx", "function Fine() {}\n")

    original = ci_module._read_file_text

    def _patched(file_path):
        if file_path.name == "broken.tsx":
            raise OSError("simulated read failure")
        return original(file_path)

    monkeypatch.setattr(ci_module, "_read_file_text", _patched)

    out = component_inventory(path="src")

    assert rows_of(out) == ["src/fine.tsx:1: Fine (function)"]
    assert summary_of(out)["collection_complete"] == "false"
    assert "file skipped: unreadable" in out


def test_oversized_explicit_single_file_raises(write_file, monkeypatch) -> None:
    monkeypatch.setattr(ci_module, "MAX_FILE_BYTES", 10)
    write_file("src/one.tsx", "function TooBig() {}\n")

    with pytest.raises(ValueError, match="byte safety limit"):
        component_inventory(path="src/one.tsx")


# --- decoding, line endings, BOM --------------------------------------------


def test_invalid_utf8_is_replaced_and_still_scanned(write_file, repo) -> None:
    """O-13: ``errors="replace"``; decoding never makes the scan incomplete."""
    write_binary(repo, "src/enc.tsx", b"\xff\xfe function Broken() {}\nfunction Recovered() {}\n")

    out = component_inventory(path="src")

    assert "src/enc.tsx:2: Recovered (function)" in rows_of(out)
    assert summary_of(out)["collection_complete"] == "true"


def test_crlf_line_endings_keep_line_numbers(write_file, repo) -> None:
    write_binary(repo, "src/crlf.tsx", b"function First() {}\r\nclass Second {}\r\n")

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/crlf.tsx:1: First (function)",
        "src/crlf.tsx:2: Second (class)",
    ]


def test_utf8_bom_does_not_shift_match_positions(write_file, repo) -> None:
    write_binary(repo, "src/bom.tsx", "\ufefffunction Bommed() {}\nfunction Plain() {}\n".encode("utf-8"))

    out = component_inventory(path="src")

    assert rows_of(out) == [
        "src/bom.tsx:1: Bommed (function)",
        "src/bom.tsx:2: Plain (function)",
    ]


# --- O-18 approved zero/partial-result wording ------------------------------


def test_zero_result_complete_wording(write_file) -> None:
    write_file("src/empty.tsx", "const nothing = 1;\n")

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "0"
    assert summary_of(out)["collection_complete"] == "true"
    assert "no component candidates matched" in out
    assert "candidates only" in out
    assert "does not prove that no components exist" in out


def test_zero_result_incomplete_wording(write_file, monkeypatch) -> None:
    monkeypatch.setattr(ci_module, "MAX_FILE_BYTES", 10)
    write_file("src/big.tsx", "function TooBig() {}\n")

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "0"
    assert summary_of(out)["collection_complete"] == "false"
    assert "found so far" in out
    assert "not a complete inventory" in out
    assert "does not prove that no components exist" not in out


def test_partial_result_wording(write_file, monkeypatch) -> None:
    monkeypatch.setattr(ci_module, "MAX_FILE_BYTES", 20)
    write_file("src/big.tsx", "function TooBig() {}\n" + "// padding\n" * 5)
    write_file("src/small.tsx", "function Fits() {}\n")

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "1"
    assert summary_of(out)["collection_complete"] == "false"
    assert "scan not exhaustive" in out
    assert "partial inventory" in out


# --- O-24: no numeric files-scanned / files-skipped fields ------------------


def test_no_files_scanned_or_skipped_disclosure_fields(write_file) -> None:
    write_file("src/one.tsx", "function Field1() {}\n")

    out = component_inventory(path="src")

    for forbidden in ("FILES_SCANNED", "FILES_SKIPPED", "files_scanned", "files_skipped"):
        assert forbidden not in out, forbidden


# --- validation, budgets, read-only -----------------------------------------


def test_negative_offset_raises(write_file) -> None:
    write_file("src/one.tsx", "function Off() {}\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        component_inventory(path="src", offset=-1)


def test_empty_path_raises() -> None:
    with pytest.raises(ValueError):
        component_inventory(path="")


def test_missing_path_raises() -> None:
    with pytest.raises(FileNotFoundError):
        component_inventory(path="does/not/exist")


def test_path_outside_project_root_raises() -> None:
    with pytest.raises(ValueError, match="escapes MCQuest project root"):
        component_inventory(path="../outside")


def test_max_results_is_clamped_to_approved_bounds(write_file) -> None:
    write_file("src/clamp.tsx", "function C1() {}\nfunction C2() {}\n")

    lowest = component_inventory(path="src", max_results=0)
    assert summary_of(lowest)["returned"] == "1"
    assert summary_of(lowest)["has_more"] == "true"

    highest = component_inventory(path="src", max_results=10_000)
    assert int(summary_of(highest)["returned"]) <= MAX_SEARCH_RESULTS


def test_default_call_uses_the_normal_presentation_budget(write_file) -> None:
    write_file("src/budget.tsx", "function Small() {}\n")

    out = component_inventory(path="src")

    assert summary_of(out)["budget"] == f"{NORMAL_OUTPUT_CHARS}/{MAX_OUTPUT_CHARS}"


def test_expanded_call_respects_the_absolute_output_ceiling(write_file) -> None:
    lines = "".join(f"function Component{i}() {{}}\n" for i in range(500))
    write_file("src/many.tsx", lines)

    out = component_inventory(path="src", max_results=MAX_SEARCH_RESULTS)

    assert summary_of(out)["total"] == "500"
    assert summary_of(out)["budget"] == f"{MAX_OUTPUT_CHARS}/{MAX_OUTPUT_CHARS}"
    assert len(out) <= MAX_OUTPUT_CHARS
    assert "[OUTPUT TRUNCATED" in out
    assert int(summary_of(out)["returned"]) < 500
    # Truncation is a rendering concern only: identity/completeness are intact.
    assert summary_of(out)["collection_complete"] == "true"
    assert summary_of(out)["truncated"] == "true"


def test_overlong_row_is_clipped_without_changing_identity(write_file) -> None:
    long_dir = "d" * 190
    write_file(f"src/{long_dir}/long.tsx", "function LongNamed() {}\n")

    out = component_inventory(path="src")

    assert summary_of(out)["total"] == "1"
    assert summary_of(out)["collection_complete"] == "true"
    assert summary_of(out)["truncated"] == "true"
    assert "[OUTPUT TRUNCATED" in out
    assert len(rows_of(out)[0]) <= LINE_CLIP_CHARS


def test_scan_is_read_only(write_file, repo) -> None:
    write_file("src/read.tsx", "function ReadOnly() {}\n")
    before = sorted(
        os.path.relpath(os.path.join(root, name), repo).replace(os.sep, "/")
        for root, _, names in os.walk(repo)
        for name in names
    )

    component_inventory(path="src")

    after = sorted(
        os.path.relpath(os.path.join(root, name), repo).replace(os.sep, "/")
        for root, _, names in os.walk(repo)
        for name in names
    )
    assert after == before


def test_tool_is_callable_through_the_mcp_registration(write_file) -> None:
    write_file("src/mcp.tsx", "function ViaMcp() {}\n")

    result = asyncio.run(
        mcp.call_tool("mcquest_component_inventory", {"path": "src"})
    )

    assert not result.is_error
    text = "\n".join(
        block.text for block in result.content if hasattr(block, "text")
    )
    assert "mcquest_component_inventory" in text
    assert "ViaMcp (function)" in text