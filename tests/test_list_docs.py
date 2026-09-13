"""Phase C focused tests for ``mcquest_list_docs``.

Proves the v0.5 discovery contract for Markdown discovery
(``Docs/V0.5/04-V0.5-TEST-PLAN.md`` I/J/K/M/V):

- summary-first shape including aggregate doc-type breakdown;
- default page of 100 under the 4000-char presentation budget;
- absolute 16,000-char ceiling (serialized allowance included);
- explicit ``offset`` pagination only; deterministic ordering;
- 304-doc fixture totals; markdown-only filtering and singleton returns;
- traversal rejection and missing-path behavior.
"""

from __future__ import annotations

import json
import os

import pytest

from mcquest_mcp.tools.docs import list_docs

from conftest import repo, write_file  # noqa: F401  (fixtures)


# --- fixtures ----------------------------------------------------------


def _make_tree(root: str, spec: dict[str, str]) -> None:
    for relative, content in spec.items():
        full = os.path.join(root, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)


@pytest.fixture
def many_docs(repo: str) -> None:
    """250 markdown docs across two dirs plus root-level docs."""
    spec: dict[str, str] = {}
    for i in range(120):
        spec[f"docs/phase_{i:03d}/01-IMPLEMENTATION.md"] = "# impl\n"
    for i in range(120):
        spec[f"docs/audits/{i:03d}-AUDIT.md"] = "# audit\n"
    for i in range(10):
        spec[f"docs/readme_{i:03d}.md"] = "# readme\n"
    _make_tree(repo, spec)


@pytest.fixture
def doc_forest(repo: str) -> None:
    """304 docs plus a non-markdown file and an ignored-dir doc."""
    spec: dict[str, str] = {}
    for i in range(304):
        spec[f"docs/doc_{i:04d}.md"] = "# doc\n"
    spec["docs/notes.txt"] = "ignored\n"
    spec["node_modules/pkg/dep.md"] = "ignored\n"
    _make_tree(repo, spec)


def _serialized_len(text: str) -> int:
    return len(json.dumps({"content": [{"type": "text", "text": text}]}))


def _parse_summary(output: str) -> dict[str, str]:
    lines = output.splitlines()
    assert lines[0] == "[SUMMARY]", lines[:1]
    summary: dict[str, str] = {}
    for line in lines[1:]:
        if line == "[EVIDENCE]":
            break
        key, _, value = line.partition(": ")
        summary[key] = value
    return summary


def _evidence_paths(output: str) -> list[str]:
    lines = output.splitlines()
    try:
        start = lines.index("[EVIDENCE]") + 1
    except ValueError:
        return []
    end = len(lines)
    if "[END]" in lines[start:]:
        end = start + lines[start:].index("[END]")
    return [line for line in lines[start:end] if line.strip()]
# --- summary shape -----------------------------------------------------


def test_summary_first_block(many_docs) -> None:
    output = list_docs(path="docs")
    assert output.startswith("[SUMMARY]\n")
    summary = _parse_summary(output)
    assert summary["tool"] == "mcquest_list_docs"
    assert summary["scope"] == 'path="docs"'
    assert summary["ROOT"] == "docs"
    assert summary["PATTERN"] == "*.md"
    assert summary["total"] == "250"
    assert summary["returned"] == "100"
    assert summary["offset"] == "0"
    assert summary["next_offset"] == "100"
    assert summary["has_more"] == "true"
    assert summary["truncated"] == "false"
    assert summary["collection_complete"] == "true"
    assert summary["budget"].startswith("4000/")


def test_doc_type_aggregate_metadata(many_docs) -> None:
    output = list_docs(path="docs")
    summary = _parse_summary(output)
    aggregate = summary.get("aggregate", "")
    assert "IMPLEMENTATION=120" in aggregate
    assert "AUDIT=120" in aggregate
    assert "OTHER=10" in aggregate


def test_no_automatic_page_2_and_explicit_offset(many_docs) -> None:
    first = list_docs(path="docs")
    first_paths = _evidence_paths(first)
    assert len(first_paths) == 100
    summary = _parse_summary(first)
    assert summary["has_more"] == "true"
    assert summary["next_offset"] == "100"
    assert first_paths == sorted(first_paths)

    second = list_docs(path="docs", offset=100)
    second_paths = _evidence_paths(second)
    assert second_paths and not set(first_paths) & set(second_paths)
    summary2 = _parse_summary(second)
    assert summary2["offset"] == "100"
    assert summary2["next_offset"] == "200"


def test_full_walk_covers_every_doc_exactly_once(many_docs) -> None:
    seen: list[str] = []
    offset = 0
    for _ in range(10):
        output = list_docs(path="docs", offset=offset)
        summary = _parse_summary(output)
        seen.extend(_evidence_paths(output))
        if summary["has_more"] != "true":
            break
        offset = int(summary["next_offset"])
    assert len(seen) == 250
    assert len(set(seen)) == 250
    assert seen == sorted(seen)


def test_deterministic_repeated_calls(many_docs) -> None:
    assert list_docs(path="docs") == list_docs(path="docs")
    assert list_docs(path="docs", offset=50) == list_docs(path="docs", offset=50)
# --- budget ------------------------------------------------------------


def test_default_page_within_4000_chars(many_docs) -> None:
    output = list_docs(path="docs")
    assert len(output) <= 4_000
    assert _serialized_len(output) <= 4_500


def test_explicit_page_within_ceiling(doc_forest) -> None:
    output = list_docs(path="docs", max_results=10_000)
    assert len(output) <= 16_000
    assert _serialized_len(output) <= 16_500


def test_hard_cap_300(doc_forest) -> None:
    output = list_docs(path="docs", max_results=10_000)
    summary = _parse_summary(output)
    assert summary["total"] == "304"
    assert summary["returned"] == "300"
    assert summary["offset"] == "0"


def test_offset_beyond_total_is_empty(many_docs) -> None:
    output = list_docs(path="docs", offset=5_000)
    summary = _parse_summary(output)
    assert summary["returned"] == "0"
    assert summary["has_more"] == "false"
    assert _evidence_paths(output) == []


def test_offset_negative_rejected(many_docs) -> None:
    with pytest.raises(ValueError, match="offset"):
        list_docs(path="docs", offset=-1)


def test_traversal_rejected(repo) -> None:
    with pytest.raises(ValueError, match="escapes"):
        list_docs(path="..")


def test_missing_path_raises(repo) -> None:
    with pytest.raises(FileNotFoundError):
        list_docs(path="does-not-exist")


# --- filters and security ----------------------------------------------


def test_markdown_only_and_ignored_dir_excluded(doc_forest) -> None:
    output = list_docs(path="docs")
    summary = _parse_summary(output)
    assert summary["total"] == "304"
    assert _evidence_paths(output)
    assert all(p.startswith("docs/doc_") for p in _evidence_paths(output))


def test_pattern_filter(repo) -> None:
    _make_tree(
        repo,
        {
            "docs/a.md": "# a\n",
            "docs/b.MD": "# b\n",
            "docs/c.txt": "c\n",
        },
    )
    output = list_docs(path="docs", pattern="*.md")
    summary = _parse_summary(output)
    assert summary["total"] == "2"
    assert _evidence_paths(output) == ["docs/a.md", "docs/b.MD"]


def test_single_markdown_file_root_returns_path(write_file) -> None:
    relative = write_file("docs/one.md", "# one\n")
    assert list_docs(path=relative) == relative


def test_non_markdown_file_root_rejected(write_file) -> None:
    relative = write_file("docs/one.txt", "x\n")
    with pytest.raises(ValueError, match="Not a Markdown"):
        list_docs(path=relative)


# --- legacy compatibility ----------------------------------------------


def test_legacy_count_substring_preserved(write_file) -> None:
    write_file("docs/one.md", "# one\n")
    output = list_docs(path="docs")
    assert "COUNT: 1" in output
    assert "docs/one.md" in output
