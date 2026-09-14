"""V0.6 Phase 1 (E1 carry-forward): ``pattern_audit`` summary-first bounded model.

Verifies the approved Phase 1 scope:

- summary-first default response (``[SUMMARY]`` block + ``[CATEGORY COUNTS]``
  table, up to 2 sample matches per category) under the 4,000-char normal
  presentation budget;
- additive ``category`` parameter (single category expansion, enum-validated,
  bounded by the 16,000-char ceiling);
- legacy ``categories`` selector preserved (comma-separated subset / 'all');
- truncation / continuation metadata truthfulness (has_more, truncated,
  collection_complete, budget; line clipping at 200 chars);
- deterministic output, read-only behavior and ignored-path boundaries.
"""

from __future__ import annotations

import asyncio

import pytest

from mcquest_mcp.config import MAX_OUTPUT_CHARS, NORMAL_OUTPUT_CHARS
from mcquest_mcp.formatting import LINE_CLIP_CHARS
from mcquest_mcp.security import resolve_project_path
from mcquest_mcp.server import mcp
from mcquest_mcp.tools.audit import (
    AUDIT_CATEGORIES,
    DEFAULT_SAMPLES_PER_CATEGORY,
    pattern_audit,
)

LONG = (
    "w-screen fixed sticky overflow-x-auto overflow-x:auto whitespace-nowrap "
    "min-w-[500px] -mx-4 translate-x-3 right-[-5px] w-[400px] sticky"
)


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


def counts_block(output: str) -> list[list[str]]:
    """Return the ``[CATEGORY COUNTS]`` rows as ``[name, count]`` pairs."""
    head = output.partition("[CATEGORY COUNTS]")[2]
    rows: list[str] = []
    for line in head.splitlines():
        if line.startswith("## ") or line.startswith("["):
            break
        if ": " in line:
            rows.append(line)
    return [[part.strip() for part in row.split(": ")] for row in rows]


def sample_names(blocks: dict[str, list[str]]) -> list[str]:
    """Ordered category names with at least one sample line."""
    return [name for name in AUDIT_CATEGORIES if blocks.get(name)]


@pytest.fixture
def dirty_repo(write_file) -> None:
    """Source files matching every audit category."""
    body = "import x from 'react';\nconst a = '" + LONG + " targetWord';\n" + (
        "const z = '" + LONG + "';\n"
    ) * 200
    write_file("src/c.tsx", body)
    for i in range(5):
        write_file(f"src/extra{i}.tsx", "const b = '" + LONG + "';\n")


@pytest.fixture
def small_repo(write_file) -> None:
    """Small single-file repo so a category expansion fits the 16k ceiling."""
    write_file(
        "small/a.tsx",
        ("const z = '" + LONG + "';\n") * 40,
    )


def test_default_is_summary_first_with_counts_and_bounded_samples(dirty_repo) -> None:
    out = pattern_audit(path="src")
    assert out.startswith("[SUMMARY]\n")

    s = summary_of(out)
    assert s["tool"] == "mcquest_pattern_audit"
    assert s["category_count"] == "11"
    assert s["matches"] == str(11 * 100)  # each category capped at 100
    assert s["budget"] == f"{NORMAL_OUTPUT_CHARS}/{MAX_OUTPUT_CHARS}"
    assert s["collection_complete"] == "true"

    names = [row[0] for row in counts_block(out)]
    assert names == list(AUDIT_CATEGORIES)

    # Bounded samples: at most DEFAULT_SAMPLES_PER_CATEGORY lines per category,
    # and the default never dumps the full 100-match collection.
    blocks = sample_blocks(out)
    for name in AUDIT_CATEGORIES:
        assert len(blocks.get(name, [])) <= DEFAULT_SAMPLES_PER_CATEGORY, name
    assert sum(len(v) for v in blocks.values()) < 100


def test_default_respects_presentation_budget(write_file) -> None:
    # Depth + long lines to pressure the normal budget; never exceeds it.
    write_file(
        "long/dir/with/a/deep/nesting/path/f.tsx",
        "const x = '" + "z" * 200 + " " + LONG + "';\n" * 60,
    )
    out = pattern_audit(path=".")
    assert len(out) <= NORMAL_OUTPUT_CHARS
    s = summary_of(out)
    if s["truncated"] == "true":
        assert "[OUTPUT TRUNCATED" in out
    else:
        assert out.rstrip().endswith("[END]")


def test_deterministic_repeated_default(dirty_repo) -> None:
    assert pattern_audit(path="src") == pattern_audit(path="src")


def sample_blocks(output: str) -> dict[str, list[str]]:
    """Parse each ``## <category>`` sample block from the evidence body."""
    body = output.partition("[EVIDENCE]")[2]
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            blocks.setdefault(current, [])
        elif line.startswith("["):
            continue
        elif current is not None and line.strip():
            blocks[current].append(line)
    return blocks


def test_category_expansion_lists_matches(small_repo) -> None:
    out = pattern_audit(path="small", category="nowrap")
    s = summary_of(out)
    assert s["CATEGORY"] == "nowrap"
    assert s["category_count"] == "1"
    assert s["budget"] == f"{MAX_OUTPUT_CHARS}/{MAX_OUTPUT_CHARS}"
    blocks = sample_blocks(out)
    assert list(blocks.keys()) == ["nowrap"]
    # Explicit expansion lists the collected matches (not the summary subset).
    assert len(blocks["nowrap"]) == 40
    assert len(blocks["nowrap"]) > DEFAULT_SAMPLES_PER_CATEGORY
    assert s["matches"] == "40"
    assert s["has_more"] == "false"  # every collected match was emitted
    assert out.rstrip().endswith("[END]")


def test_category_parameter_overrides_categories(small_repo) -> None:
    out = pattern_audit(
        path="small", categories="nowrap", category="sticky-position"
    )
    s = summary_of(out)
    assert s["CATEGORY"] == "sticky-position"
    assert list(sample_blocks(out).keys()) == ["sticky-position"]


def test_category_expansion_within_ceiling(write_file) -> None:
    write_file("big/long.tsx", "const x = '" + LONG + "';\n" * 500)
    out = pattern_audit(
        path="big",
        category="nowrap",
        max_results_per_category=500,
    )
    assert len(out) <= MAX_OUTPUT_CHARS
    s = summary_of(out)
    if s["truncated"] == "true":
        assert "[OUTPUT TRUNCATED" in out


def test_unknown_category_rejected(dirty_repo) -> None:
    with pytest.raises(ValueError, match="Unknown category"):
        pattern_audit(path="src", category="bogus")


def test_legacy_categories_selector_and_validation(dirty_repo) -> None:
    out = pattern_audit(path="src", categories="nowrap,sticky-position")
    names = [row[0] for row in counts_block(out)]
    assert names == ["nowrap", "sticky-position"]

    with pytest.raises(ValueError, match="Unknown categories"):
        pattern_audit(path="src", categories="bogus,sticky-position")


def test_no_matches_renders_counts_only(write_file) -> None:
    write_file("empty/src.tsx", "const x = 1;\n")
    out = pattern_audit(path="empty")
    s = summary_of(out)
    assert s["category_count"] == "11"
    assert s["matches"] == "0"
    assert s["has_more"] == "false"
    assert out.rstrip().endswith("[END]")
    assert "[OUTPUT TRUNCATED" not in out


def test_clip_applied_to_oversized_lines(write_file) -> None:
    write_file(
        "src/huge.tsx",
        "const x = '" + "z" * 500 + " whitespace-nowrap\n",
    )
    out = pattern_audit(path="src", category="nowrap")
    for line in out.splitlines():
        assert len(line) <= LINE_CLIP_CHARS + 1, line


def test_ignored_and_traversal_boundaries(write_file) -> None:
    write_file("node_modules/skip.tsx", "w-screen\n")
    write_file("src/ok.tsx", "w-screen\n")
    assert "node_modules" not in pattern_audit(path=".")

    with pytest.raises(ValueError, match="escapes"):
        resolve_project_path("../outside")


def test_registered_schema_adds_category_parameter() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_pattern_audit")
    props = tool.input_schema["properties"]
    assert "category" in props
    assert tool.input_schema.get("required", []) == []
    # Existing parameters preserved (additive-only change).
    for param in ("path", "categories", "max_results_per_category"):
        assert param in props
    assert "summary counts + samples" in props["categories"]["description"]