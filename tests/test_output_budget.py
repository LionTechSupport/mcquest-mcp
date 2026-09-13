"""Phase A focused tests: v0.5 OutputBudget infrastructure.

Proves the binding v0.5 contract invariants
(``Docs/V0.5/04-V0.5-TEST-PLAN.md`` sections D, E, F, G, H and the atomic /
serialized aspects of V):

- D. 16,000-char absolute ceiling (raw and ``json.dumps`` serialized);
- E. 4,000-char normal presentation budget;
- F. 200-char per-line clipping;
- G. atomic item cutoff (never a partial item);
- H. summary / header survives truncation;
- plus public ``truncate()`` marker compatibility, ``numbered_lines()``
  prefix preservation and clip, and the contract's serialized response model.
"""

from __future__ import annotations

import json

from mcquest_mcp import config
from mcquest_mcp.formatting import (
    OutputBudget,
    numbered_lines,
    summary_block,
    truncate,
)

NORMAL = 4_000
CEILING = 16_000
CLIP = 200
# The serialized wrapper adds a few hundred characters of JSON overhead; the
# test plan allows a ~500-char tolerance over the raw ceiling.
SERIALIZED_ALLOWANCE = 500


def serialized_len(text: str) -> int:
    """Length of the contract's serialized response model (test plan D)."""
    return len(json.dumps({"content": [{"type": "text", "text": text}]}))


# --- A1 constants -----------------------------------------------------

def test_budget_constants() -> None:
    assert config.NORMAL_OUTPUT_CHARS == NORMAL
    assert config.MAX_OUTPUT_CHARS == CEILING
    assert config.LINE_CLIP_CHARS == CLIP


def test_budget_defaults() -> None:
    budget = OutputBudget()
    assert budget.normal == NORMAL
    assert budget.ceiling == CEILING
    assert budget.clip == CLIP


# --- D. 16,000-char absolute ceiling -----------------------------------

def test_truncate_large_input_stays_below_ceiling() -> None:
    out = truncate("x" * 100_000)
    assert len(out) <= CEILING


def test_truncate_pathological_many_long_lines() -> None:
    out = truncate("\n".join(["y" * 5_000] * 1_000))
    assert len(out) <= CEILING


def test_truncate_under_ceiling_returns_text_unchanged() -> None:
    text = "line one\nline two"
    assert truncate(text) == text


def test_truncate_empty() -> None:
    assert truncate("") == ""


def test_budget_emit_fits_exactly_at_ceiling() -> None:
    budget = OutputBudget(ceiling=10)
    assert budget.emit("a" * 10) is True
    assert budget.used == 10
    assert budget.truncated is False


def test_budget_emit_crosses_boundary_by_one_character() -> None:
    budget = OutputBudget(ceiling=10)
    assert budget.emit("a" * 10) is True
    assert budget.emit("b") is False  # 11 > 10: rejected whole
    assert budget.truncated is True
    assert budget.omitted == 1
    assert "b" not in budget.finalize()


# --- E. 4,000-char normal budget --------------------------------------

def test_normal_budget_is_target_not_ceiling() -> None:
    # The normal budget is the default per-tool presentation target; the
    # ceiling is the enforceable bound. A budget tracks both.
    budget = OutputBudget(normal=NORMAL, ceiling=CEILING)
    assert budget.normal == NORMAL
    budget.emit("v" * NORMAL)  # exactly the normal budget
    assert budget.used == NORMAL
    assert budget.truncated is False
    # The normal budget is a target, not a cap: content may exceed it up to
    # the absolute ceiling (e.g. an explicitly ranged read in a later phase).
    assert budget.emit("more") is True
    assert budget.used == NORMAL + 4
    out = budget.finalize()
    assert len(out) == NORMAL + 5  # used + the single join newline
# --- F. 200-char per-line clip -----------------------------------------

def test_clip_20k_single_line_in_truncate() -> None:
    out = truncate("z" * 20_000)
    assert len(out.splitlines()[0]) <= CLIP
    assert "OUTPUT TRUNCATED" in out
    assert len(out) <= 400


def test_clip_many_long_lines() -> None:
    out = truncate("\n".join(["z" * 5_000] * 20))
    for line in out.splitlines():
        assert len(line) <= CLIP


def test_clip_uses_ellipsis_and_keeps_200() -> None:
    out = truncate("x" * 220)
    first = out.splitlines()[0]
    assert first == "x" * 199 + "…"
    assert len(first) == 200


def test_clip_short_lines_unchanged() -> None:
    out = truncate("short\nlines\nstay")
    assert out == "short\nlines\nstay"


# --- G. atomic item cutoff -----------------------------------------------

def test_atomic_cutoff_no_partial_item() -> None:
    budget = OutputBudget(ceiling=100)
    assert budget.emit("a" * 60) is True
    assert budget.emit("b" * 40) is True  # exactly fills the ceiling
    assert budget.emit("z" * 5) is False  # would cross: rejected whole
    out = budget.finalize()
    assert "z" not in out
    assert budget.truncated is True


def test_atomic_cutoff_in_numbered_lines() -> None:
    body = "\n".join("q" * 40 for _ in range(50))
    out = numbered_lines(body, limit=400)
    # The tail is a complete numbered line; it must never be a partial
    # fragment of a longer source line.
    for line in out.splitlines():
        if not line.startswith("[OUTPUT") and line.strip():
            assert line.endswith("q" * 40) or line.endswith("…")


def test_line_clip_via_budget_marks_truncated() -> None:
    budget = OutputBudget()
    budget.add_clipped_line("x" * 250)
    assert budget.truncated is True
    assert budget.omitted == 50


# --- truncated state ----------------------------------------------------

def test_truncated_false_when_nothing_dropped() -> None:
    budget = OutputBudget()
    budget.emit("hello")
    assert budget.truncated is False
    assert budget.finalize() == "hello"


def test_omitted_counts_rejected_items() -> None:
    budget = OutputBudget(ceiling=5)
    budget.emit("abcde")
    budget.emit("xy")
    assert budget.omitted == 2
# --- H. summary / header survives truncation -----------------------------

def test_header_survives_truncation() -> None:
    budget = OutputBudget(ceiling=400)
    header = summary_block(
        tool="mcquest_search",
        fields={"total": "57", "returned": "2", "has_more": "true"},
        scope='pattern="foo" path="src"',
    )
    budget.add_header(header)
    while budget.add_clipped_line("some evidence line"):
        pass
    out = budget.finalize()
    assert out.startswith("[SUMMARY]\n")
    assert "tool: mcquest_search" in out
    assert 'scope: pattern="foo" path="src"' in out
    assert "[EVIDENCE]" in out
    assert "OUTPUT TRUNCATED" in out
    assert len(out) <= 400


def test_header_then_body_order() -> None:
    budget = OutputBudget()
    budget.add_header("[SUMMARY]\ntotal: 1\n[EVIDENCE]")
    budget.add_clipped_line("row 1")
    budget.add_clipped_line("row 2")
    out = budget.finalize()
    assert out.index("[SUMMARY]") == 0
    assert out.index("[EVIDENCE]") < out.index("row 1")
    assert out.endswith("row 2")


def test_summary_block_shape() -> None:
    block = summary_block(
        tool="mcquest_search",
        fields={"returned": "20", "total": "57", "next_offset": "20"},
        scope='pattern="foo"',
    )
    assert block.startswith("[SUMMARY]")
    assert "tool: mcquest_search" in block
    assert 'scope: pattern="foo"' in block
    assert "returned: 20" in block
    assert block.endswith("[EVIDENCE]")


# --- truncate marker compatibility ---------------------------------------

def test_truncate_marker_present() -> None:
    out = truncate("x" * 200_000)
    assert "[OUTPUT TRUNCATED" in out


def test_truncate_marker_reports_omitted() -> None:
    out = truncate("q" * 500)
    assert "300 characters omitted" in out


# --- numbered_lines ------------------------------------------------------

def test_numbered_lines_prefix_preserved() -> None:
    out = numbered_lines("hello\nworld")
    assert "1: hello" in out
    assert "2: world" in out


def test_numbered_lines_custom_start_and_end() -> None:
    out = numbered_lines("a\nb\nc\nd\ne", start_line=2, end_line=4)
    assert "2: b" in out
    assert "3: c" in out
    assert "4: d" in out
    assert "5: e" not in out


def test_numbered_lines_clips_long_line() -> None:
    out = numbered_lines("a" * 20_000 + "\nshort")
    lines = out.splitlines()
    assert len(lines[0]) <= CLIP
    assert "short" in out


def test_numbered_lines_under_ceiling() -> None:
    out = numbered_lines("\n".join("x" * 100 for _ in range(400)))
    assert len(out) <= CEILING


# --- serialized response bound (test plan D) ------------------------------

def test_serialized_response_stays_bounded() -> None:
    worst = truncate("x" * 100_000)
    assert len(worst) <= CEILING
    assert serialized_len(worst) <= CEILING + SERIALIZED_ALLOWANCE


def test_serialized_model_is_text_block() -> None:
    out = truncate("x" * 100_000)
    payload = {"content": [{"type": "text", "text": out}]}
    assert payload["content"][0]["type"] == "text"
    assert len(json.dumps(payload)) <= CEILING + SERIALIZED_ALLOWANCE