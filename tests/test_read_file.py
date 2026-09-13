"""Phase B focused tests: mcquest_read_file windowed reads (v0.5).

Proves the approved Phase B read contract (``Docs/V0.5/04-V0.5-TEST-PLAN.md``
sections O, L, D, F, V):

- default read = at most a 250-line window <= 4,000 chars (normal budget);
- explicit range <= 1,000-line window and <= 16,000 chars (ceiling);
- continuation via next_start_line == rendered end_line + 1 (no gaps/overlaps);
- total_lines / has_more / truncated are truthful (truncated follows the
  Phase A OutputBudget definition: any dropped character, i.e. a 200-char
  line clip OR a budget cut);
- 200-char per-line clip; atomic cutoff; summary-first survives truncation;
- serialized MCP response bound; boundary files; numbering format preserved.
"""

from __future__ import annotations

import json
import re

from mcquest_mcp.tools.files import read_file

NORMAL = 4_000
CEILING = 16_000
CLIP = 200
SERIALIZED_ALLOWANCE = 500

NUMBERED_RE = re.compile(r"^ {0,5}\d+: ")
SUMMARY_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z_0-9]*): (.*)$")


def _body(output: str) -> str:
    return output[output.index("[EVIDENCE]") + len("[EVIDENCE]") :]


def _numbered(output: str) -> list[str]:
    return [line for line in _body(output).splitlines() if NUMBERED_RE.match(line)]


def _summary(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if line == "[EVIDENCE]":
            break
        match = SUMMARY_KEY_RE.match(line)
        if match:
            fields[match.group(1)] = match.group(2)
    return fields


def _serialized_len(text: str) -> int:
    return len(json.dumps({"content": [{"type": "text", "text": text}]}))
# --- default window -------------------------------------------------------

def test_default_window_is_at_most_250_lines(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 301)))
    out = read_file("f.txt")
    s = _summary(out)
    assert s["start_line"] == "1"
    assert s["end_line"] == "250"
    assert s["total_lines"] == "300"
    assert s["has_more"] == "true"
    assert s["next_start_line"] == "251"
    assert s["budget"] == "4000/16000"
    numbered = _numbered(out)
    assert len(numbered) == 250
    assert f"{250:6}: " in out
    assert f"{251:6}: " not in out


def test_default_read_stays_within_normal_budget(write_file) -> None:
    write_file("big.txt", "\n".join("x" * 40 for _ in range(5000)))
    out = read_file("big.txt")
    assert len(out) <= NORMAL
    assert "[OUTPUT TRUNCATED" in out


def test_has_more_false_at_end_of_file(write_file) -> None:
    write_file("tiny.txt", "a\nb")
    out = read_file("tiny.txt")
    s = _summary(out)
    assert s["end_line"] == "2"
    assert s["has_more"] == "false"
    assert "next_start_line" not in out


# --- total_lines ----------------------------------------------------------

def test_total_lines_is_truthful(write_file) -> None:
    write_file("empty.txt", "")
    write_file("one.txt", "solo")
    write_file("many.txt", "\n".join(f"l{i}" for i in range(1, 1001)))
    for name, expected in (
        ("empty.txt", "0"),
        ("one.txt", "1"),
        ("many.txt", "1000"),
    ):
        assert _summary(read_file(name))["total_lines"] == expected


# --- continuation ---------------------------------------------------------

def test_continuation_from_next_start_line(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 501)))
    page1 = read_file("f.txt")
    s1 = _summary(page1)
    assert s1["next_start_line"] == "251"

    page2 = read_file("f.txt", start_line=int(s1["next_start_line"]))
    s2 = _summary(page2)
    assert s2["start_line"] == "251"
    assert s2["end_line"] == "500"
    assert s2["has_more"] == "false"
    assert s2["budget"] == "16000/16000"
    assert f"{251:6}: " in page2
    assert f"{250:6}: " not in page2
# --- explicit range -------------------------------------------------------

def test_explicit_range_honored(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 5001)))
    out = read_file("f.txt", start_line=100, end_line=150)
    s = _summary(out)
    assert s["start_line"] == "100"
    assert s["end_line"] == "150"
    assert s["total_lines"] == "5000"
    assert s["has_more"] == "true"
    assert s["next_start_line"] == "151"
    assert len(_numbered(out)) == 51
    assert f"{100:6}: " in out
    assert f"{150:6}: " in out
    assert f"{99:6}: " not in out
    assert f"{151:6}: " not in out


def test_explicit_range_clamped_to_1000_lines(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 5001)))
    out = read_file("f.txt", start_line=100, end_line=5000)
    s = _summary(out)
    assert s["start_line"] == "100"
    assert s["end_line"] == "1099"
    assert s["has_more"] == "true"
    assert s["next_start_line"] == "1100"

    out2 = read_file("f.txt", start_line=1, end_line=5000)
    assert _summary(out2)["end_line"] == "1000"


def test_explicit_range_within_ceiling(write_file) -> None:
    write_file("big.txt", "\n".join("x" * 100 for _ in range(5000)))
    out = read_file("big.txt", start_line=1, end_line=5000)
    assert len(out) <= CEILING
    assert _serialized_len(out) <= CEILING + SERIALIZED_ALLOWANCE


# --- absolute ceiling -----------------------------------------------------

def test_absolute_ceiling_raw_and_serialized(write_file) -> None:
    write_file("big.txt", "\n".join("x" * 800 for _ in range(2000)))
    out = read_file("big.txt", start_line=1, end_line=2000)
    assert len(out) <= CEILING
    assert _serialized_len(out) <= CEILING + SERIALIZED_ALLOWANCE


# --- line clipping --------------------------------------------------------

def test_long_single_line_clipped_to_200(write_file) -> None:
    write_file("long.txt", "z" * 20_000)
    out = read_file("long.txt")
    body_line = _numbered(out)[0]
    assert len(body_line) == CLIP
    assert body_line.endswith("\u2026")
    assert _summary(out)["truncated"] == "true"


# --- atomic cutoff --------------------------------------------------------

def test_atomic_cutoff_no_partial_items(write_file) -> None:
    lines = ["q" * 5000 for _ in range(300)]
    write_file("big.txt", "\n".join(lines))
    out = read_file("big.txt", start_line=1, end_line=300)
    expected = [f"{i:6}: {line}" for i, line in enumerate(lines, start=1)]
    expected = [line[:199] + "\u2026" if len(line) > 200 else line for line in expected]
    rendered = _numbered(out)
    assert rendered  # the page rendered at least one line
    assert rendered == expected[: len(rendered)]  # exact prefix, whole items
    assert len(rendered) < 300  # the ceiling cut the page


# --- truncated state ------------------------------------------------------

def test_truncated_state_is_truthful(write_file) -> None:
    write_file("ok.txt", "a\nb")
    assert _summary(read_file("ok.txt"))["truncated"] == "false"

    write_file("clip.txt", "p" * 20_000)
    assert _summary(read_file("clip.txt"))["truncated"] == "true"

    write_file("big.txt", "\n".join("w" * 60 for _ in range(5000)))
    assert _summary(read_file("big.txt"))["truncated"] == "true"

# --- boundary cases -------------------------------------------------------

def test_empty_file(write_file) -> None:
    write_file("empty.txt", "")
    out = read_file("empty.txt")
    s = _summary(out)
    assert s["start_line"] == "1"
    assert s["end_line"] == "0"
    assert s["total_lines"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert _numbered(out) == []


def test_one_line_file(write_file) -> None:
    write_file("one.txt", "only")
    s = _summary(read_file("one.txt"))
    assert s["end_line"] == "1"
    assert s["has_more"] == "false"


def test_start_equals_end(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 50)))
    out = read_file("f.txt", start_line=7, end_line=7)
    s = _summary(out)
    assert s["start_line"] == "7"
    assert s["end_line"] == "7"
    assert len(_numbered(out)) == 1


def test_end_line_beyond_eof_clamped(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 151)))
    s = _summary(read_file("f.txt", start_line=100, end_line=99_999))
    assert s["end_line"] == "150"
    assert s["has_more"] == "false"


def test_start_line_beyond_eof_empty_page(write_file) -> None:
    write_file("f.txt", "\n".join(f"l{i}" for i in range(1, 101)))
    out = read_file("f.txt", start_line=9_999)
    s = _summary(out)
    assert s["start_line"] == "9999"
    assert s["end_line"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert _numbered(out) == []


# --- serialized size / format compat -------------------------------------

def test_serialized_default_response_bounded(write_file) -> None:
    write_file("big.txt", "\n".join("w" * 60 for _ in range(5000)))
    out = read_file("big.txt")
    assert len(out) <= NORMAL
    assert _serialized_len(out) <= NORMAL + 200


def test_numbering_format_preserved(write_file) -> None:
    write_file("tiny.txt", "hello")
    out = read_file("tiny.txt")
    assert "     1: hello" in out
    assert out.endswith("[END]")

# --- summary-first --------------------------------------------------------

def test_summary_is_first_and_survives_truncation(write_file) -> None:
    write_file("big.txt", "\n".join("w" * 100 for _ in range(5000)))
    out = read_file("big.txt", start_line=1, end_line=5000)
    assert out.startswith("[SUMMARY]\n")
    assert out.index("[EVIDENCE]") < out.index("OUTPUT TRUNCATED")
    s = _summary(out)
    for key in (
        "tool",
        "scope",
        "start_line",
        "end_line",
        "total_lines",
        "has_more",
        "truncated",
        "budget",
    ):
        assert key in s, key
    assert s["tool"] == "mcquest_read_file"
    rendered = len(_numbered(out))
    assert int(s["end_line"]) - int(s["start_line"]) + 1 == rendered


def test_continuation_uses_ceiling_and_250_window(write_file) -> None:
    write_file("big.txt", "\n".join(f"line {i} " + "x" * 30 for i in range(1, 5001)))
    out = read_file("big.txt", start_line=2)
    s = _summary(out)
    assert s["start_line"] == "2"
    assert s["end_line"] == "251"
    assert s["has_more"] == "true"
    assert s["next_start_line"] == "252"
    assert s["budget"] == "16000/16000"
    assert len(out) <= CEILING


def test_full_walk_no_gaps_or_overlaps(write_file) -> None:
    write_file("big.txt", "\n".join(f"line {i} " + "x" * 30 for i in range(1, 5001)))
    out = read_file("big.txt")
    pages: list[tuple[int, int]] = []
    while True:
        s = _summary(out)
        pages.append((int(s["start_line"]), int(s["end_line"])))
        assert int(s["end_line"]) >= int(s["start_line"])  # never empty mid-walk
        if s["has_more"] == "false":
            break
        out = read_file("big.txt", start_line=int(s["next_start_line"]))

    assert pages[0][0] == 1
    assert pages[-1][1] == 5000
    for first, second in zip(pages, pages[1:]):
        assert second[0] == first[1] + 1, (first, second)
    assert sum(b - a + 1 for a, b in pages) == 5000