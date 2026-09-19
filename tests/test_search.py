"""Phase D regression: ``mcquest_search`` summary-first, explicitly paged.

The search tools now emit a canonical ``[SUMMARY]`` block (total,
files_affected, returned, offset, next_offset, has_more, truncated,
collection_complete, budget) followed by one explicit page of at most
``max_results`` snippets ordered deterministically by
``(relative_path ASC, line ASC)`` (D003/D008/D009/D016). ``max_results``
defaults to ``SEARCH_DEFAULT_RESULTS`` (50) with a hard cap of 500, the
per-match context is capped at ``SEARCH_CONTEXT_CAP_CODE`` (3), lines are
clipped at 200 chars, and oversized (>2MB) files are skipped.

Stage 1 (V0.7) additionally proves ``exclude_pattern``:
- calls omitting ``exclude_pattern`` reproduce the pre-change bytes exactly
  (the fixed ``BASELINE_OUTPUT`` below was captured 2026-09-17 from the
  Stage 1 pre-implementation build);
- omitting vs. passing ``""`` are byte-identical;
- exclusion filters lines in BOTH count and page passes so ``total`` and
  ``files_affected`` are post-exclusion and paging stays contiguous;
- exclusion wins on overlap, composes with ``file_pattern`` and
  ``case_sensitive``, preserves context rendering around kept matches,
  echoes ``EXCLUDE`` only when set, and keeps 4000/16000/200 behavior.
"""

from __future__ import annotations

import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.tools.search import search_text

# Fixed pre-change byte-for-byte baseline for ``search_text`` captured via
# ``_capture_baseline.py`` (2026-09-17) from the Stage 1 pre-implementation
# working tree with the exact fixture in
# ``test_baseline_output_unchanged_without_exclude``. A call OMITTING
# ``exclude_pattern`` MUST reproduce these exact bytes; any rendering or
# summary drift fails that test.
BASELINE_OUTPUT: str = """[SUMMARY]
tool: mcquest_search
scope: path="src"
PATTERN: targetWord
PATH: src
total: 4
files_affected: 3
returned: 4
offset: 0
has_more: false
truncated: false
collection_complete: true
budget: 4000/16000
[EVIDENCE]

src/app.ts:1
  1: import { targetWord } from './lib';
  2: const keep = 'targetWord';
src/app.ts:2
  1: import { targetWord } from './lib';
  2: const keep = 'targetWord';
  3: const skipMe = 1;
src/lib.ts:1
  1: export const targetWord = 'x';
src/other.py:1
  1: targetWord = 42
[END]"""


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


def locations(output: str) -> list[tuple[str, int]]:
    """``(relative, line)`` pairs from the snippet-header lines."""
    body = output.partition("[EVIDENCE]")[2]
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(r"^(\S+?):(\d+)$", body, re.M)
    ]


def context_numbers(output: str) -> list[int]:
    """Line numbers rendered in snippet context lines."""
    body = output.partition("[EVIDENCE]")[2]
    return [int(n) for n in re.findall(r"^  (\d+):", body, re.M)]
def test_summary_first_with_echo_fields_and_trailer(write_file) -> None:
    write_file("src/app.ts", "const targetName = 1;\n")
    write_file("src/lib.ts", "const other = 2;\n")

    out = search_text(pattern="targetName", path="src")

    assert out.startswith("[SUMMARY]\n")
    s = summary_of(out)
    assert s["tool"] == "mcquest_search"
    assert s["scope"] == 'path="src"'
    assert s["PATTERN"] == "targetName"
    assert s["PATH"] == "src"
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert s["returned"] == "1"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert "[EVIDENCE]" in out
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("src/app.ts", 1)]


def test_snippet_show_match_line_plus_context(write_file) -> None:
    write_file("src/app.ts", "a\nb\ntargetName\nc\n")

    out = search_text(pattern="targetName", path="src")

    assert "src/app.ts:3" in out
    assert context_numbers(out) == [2, 3, 4]


def test_default_max_results_is_50(write_file) -> None:
    write_file("src/app.ts", "targetName\n" * 80)

    out = search_text(pattern="targetName", path="src", context_lines=0)

    s = summary_of(out)
    assert s["total"] == "80"
    assert s["returned"] == "50"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "50"
    assert len(locations(out)) == 50


def test_max_results_hard_cap_is_500_with_16000_budget(write_file) -> None:
    write_file("src/app.ts", "a\n" * 600)

    out = search_text(pattern="a", path="src", context_lines=0, max_results=10**6)

    s = summary_of(out)
    assert s["total"] == "600"
    assert s["returned"] == "500"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "500"
    assert s["budget"] == "16000/16000"
    assert len(locations(out)) == 500
    # Explicitly asking for the cap yields the identical page.
    assert search_text(
        pattern="a", path="src", context_lines=0, max_results=500
    ) == out


def test_order_deterministic_sorted_by_path_then_line(write_file) -> None:
    write_file("src/z.ts", "targetName\n")
    write_file("src/a.ts", "targetName\nx\ntargetName\n")

    first = search_text(pattern="targetName", path="src")
    second = search_text(pattern="targetName", path="src")

    assert first == second
    assert locations(first) == [
        ("src/a.ts", 1),
        ("src/a.ts", 3),
        ("src/z.ts", 1),
    ]


def test_context_lines_capped_at_code_limit_3(write_file) -> None:
    lines = [f"line {i}" if i != 5 else "line 5 targetName" for i in range(1, 12)]
    write_file("src/app.ts", "\n".join(lines) + "\n")

    out = search_text(pattern="targetName", path="src", context_lines=99)

    assert context_numbers(out) == list(range(2, 9))


def test_context_lines_coerced_up_from_negative(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    out = search_text(pattern="targetName", path="src", context_lines=-5)

    assert context_numbers(out) == [1]


def test_offset_negative_rejected(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        search_text(pattern="targetName", path="src", offset=-1)


def test_paging_by_offset_contiguous_no_gaps(write_file) -> None:
    write_file("src/app.ts", "targetName\n" * 12)

    p1 = search_text(
        pattern="targetName", path="src", context_lines=0, max_results=5, offset=0
    )
    p2 = search_text(
        pattern="targetName", path="src", context_lines=0, max_results=5, offset=5
    )
    p3 = search_text(
        pattern="targetName", path="src", context_lines=0, max_results=5, offset=10
    )

    assert [summary_of(p)["next_offset"] for p in (p1, p2)] == ["5", "10"]
    assert summary_of(p3)["has_more"] == "false"
    assert "next_offset" not in summary_of(p3)
    assert locations(p1) + locations(p2) + locations(p3) == [
        ("src/app.ts", n) for n in range(1, 13)
    ]


def test_default_budget_4000_expanded_16000(write_file) -> None:
    write_file("src/app.ts", ("x" * 150 + " targetName\n") * 60)

    default = search_text(pattern="targetName", path="src")
    assert len(default) <= 4000
    assert summary_of(default)["budget"] == "4000/16000"
    assert "[OUTPUT TRUNCATED" in default

    expanded = search_text(pattern="targetName", path="src", max_results=500)
    assert 4000 < len(expanded) <= 16000
    assert summary_of(expanded)["budget"] == "16000/16000"
    assert "[OUTPUT TRUNCATED" in expanded


def test_lines_clipped_at_200_chars(write_file) -> None:
    long_line = "y" * 300 + " targetName"
    write_file("src/app.ts", long_line + "\n")

    out = search_text(pattern="targetName", path="src")

    assert max(len(line) for line in out.splitlines()) <= 200


def test_2mb_file_skip_guard(repo, write_file) -> None:
    write_file("src/small.ts", "targetName\n")
    big_rel = write_file("src/big.ts", "targetName\n")
    big_abs = os.path.join(repo, big_rel.replace("/", os.sep))
    with open(big_abs, "r+b") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")

    out = search_text(pattern="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "1"
    assert locations(out) == [("src/small.ts", 1)]
# --- Stage 1: exclude_pattern (additive, backward-compatible) -------------


def test_baseline_output_unchanged_without_exclude(write_file) -> None:
    """Byte-for-byte fixture: omitting exclude_pattern == pre-change bytes."""
    write_file(
        "src/app.ts",
        "import { targetWord } from './lib';\n"
        "const keep = 'targetWord';\n"
        "const skipMe = 1;\n",
    )
    write_file("src/lib.ts", "export const targetWord = 'x';\n")
    write_file("src/other.py", "targetWord = 42\n")

    out = search_text(pattern="targetWord", path="src")

    assert out == BASELINE_OUTPUT
    assert len(out) == 503


def test_omitted_and_empty_exclude_identical(write_file) -> None:
    """Omitting exclude_pattern and passing '' produce byte-identical output."""
    write_file("src/app.ts", "targetWord\n")

    omitted = search_text(pattern="targetWord", path="src")
    explicit_empty = search_text(pattern="targetWord", path="src", exclude_pattern="")

    assert omitted == explicit_empty
    assert "EXCLUDE" not in omitted
    assert "EXCLUDE" not in explicit_empty


def test_exclude_pattern_returns_only_non_excluded(write_file) -> None:
    write_file(
        "src/app.ts",
        "first targetWord\n"
        "skipMe targetWord\n"
        "third targetWord\n",
    )

    out = search_text(pattern="targetWord", path="src", exclude_pattern="^skipMe")

    s = summary_of(out)
    assert s["total"] == "2"
    assert s["files_affected"] == "1"
    assert locations(out) == [("src/app.ts", 1), ("src/app.ts", 3)]


def test_exclude_pattern_wins_on_overlap(write_file) -> None:
    """A line matching both pattern and exclude_pattern is excluded."""
    write_file("src/app.ts", "targetWord shared\nplain other\n")

    out = search_text(pattern="targetWord", path="src", exclude_pattern="shared")

    s = summary_of(out)
    assert s["total"] == "0"
    assert s["files_affected"] == "0"
    assert locations(out) == []


def test_exclude_pattern_zero_total_truthful_page(write_file) -> None:
    write_file("src/app.ts", "targetWord\n")

    out = search_text(
        pattern="targetWord", path="src", exclude_pattern="targetWord"
    )

    s = summary_of(out)
    assert s["total"] == "0"
    assert s["returned"] == "0"
    assert s["has_more"] == "false"
    assert "next_offset" not in s
    assert out.rstrip().endswith("[END]")
def test_exclude_pattern_paging_contiguous(write_file) -> None:
    # 12 lines: every 3rd line is "targetWord", rest "skipMe targetWord" →
    # matches (after exclusion) at lines 1, 4, 7, 10 → total 4.
    write_file(
        "src/app.ts",
        "".join(
            "targetWord\n" if i % 3 == 1 else "skipMe targetWord\n"
            for i in range(1, 13)
        ),
    )

    p1 = search_text(
        pattern="targetWord",
        path="src",
        context_lines=0,
        max_results=2,
        offset=0,
        exclude_pattern="^skipMe",
    )
    p2 = search_text(
        pattern="targetWord",
        path="src",
        context_lines=0,
        max_results=2,
        offset=2,
        exclude_pattern="^skipMe",
    )

    assert summary_of(p1)["total"] == "4"
    assert summary_of(p1)["next_offset"] == "2"
    assert summary_of(p2)["has_more"] == "false"
    assert "next_offset" not in summary_of(p2)
    assert locations(p1) + locations(p2) == [
        ("src/app.ts", 1),
        ("src/app.ts", 4),
        ("src/app.ts", 7),
        ("src/app.ts", 10),
    ]


def test_exclude_pattern_composes_with_file_pattern(write_file) -> None:
    write_file("src/a.ts", "targetWord\n")
    write_file("src/b.ts", "targetWord bOnly\n")
    write_file("src/c.txt", "targetWord\n")

    out = search_text(
        pattern="targetWord",
        path="src",
        file_pattern="*.ts",
        exclude_pattern="bOnly",
    )

    # c.txt is out by glob; b.ts's matching line is out by exclude; only
    # a.ts line 1 survives.
    s = summary_of(out)
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert locations(out) == [("src/a.ts", 1)]


def test_exclude_pattern_honors_case_sensitive(write_file) -> None:
    write_file("src/app.ts", "targetWord\nTARGETWORD\n")

    # Default case-insensitive exclude: both lines match both regexes → 0.
    out_ci = search_text(pattern="targetWord", path="src", exclude_pattern="TARGETWORD")
    assert summary_of(out_ci)["total"] == "0"

    # case_sensitive=True: pattern only matches "targetWord"; exclude only
    # matches "TARGETWORD" → the lowercase line survives.
    out_cs = search_text(
        pattern="targetWord",
        path="src",
        case_sensitive=True,
        exclude_pattern="TARGETWORD",
    )
    assert summary_of(out_cs)["total"] == "1"
    assert locations(out_cs) == [("src/app.ts", 1)]


def test_exclude_pattern_invalid_regex_raises_value_error(write_file) -> None:
    write_file("src/app.ts", "x\n")

    with pytest.raises(ValueError, match="Invalid exclude_pattern regex"):
        search_text(pattern="x", path="src", exclude_pattern="[")


def test_exclude_pattern_context_unchanged_around_kept_match(write_file) -> None:
    # The excluded line is not a match, so the kept match's context window
    # (lines 1..3) must be rendered exactly as before (unchanged context).
    write_file("src/app.ts", "a\ntargetWord\nskipMe\nc\n")

    out = search_text(pattern="targetWord", path="src", exclude_pattern="^skipMe")

    assert locations(out) == [("src/app.ts", 2)]
    assert context_numbers(out) == [1, 2, 3]


def test_exclude_pattern_echoed_in_summary_only_when_set(write_file) -> None:
    write_file("src/app.ts", "targetWord\n")

    without = search_text(pattern="targetWord", path="src")
    assert "EXCLUDE" not in without

    with_excl = search_text(pattern="targetWord", path="src", exclude_pattern="skipMe")
    assert "EXCLUDE: skipMe" in with_excl


def test_exclude_pattern_default_budget_still_applies(write_file) -> None:
    write_file("src/app.ts", ("x" * 150 + " targetWord\n") * 60)

    out = search_text(pattern="targetWord", path="src", exclude_pattern="unusedMatch")

    assert len(out) <= 4000
    assert summary_of(out)["budget"] == "4000/16000"
    assert summary_of(out)["total"] == "60"
    assert "[OUTPUT TRUNCATED" in out