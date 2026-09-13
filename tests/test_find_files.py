"""Phase C focused tests for ``mcquest_find_files``.

Proves the v0.5 discovery contract for filename search
(``Docs/V0.5/04-V0.5-TEST-PLAN.md`` I/J/K/M/V):

- summary-first shape (total, COUNT, returned, offset, next_offset,
  has_more, truncated, collection_complete, budget, aggregate);
- case-insensitive substring matching preserved;
- default page of 100 under the 4000-char presentation budget;
- absolute 16,000-char ceiling (serialized allowance included);
- explicit ``offset`` pagination only; deterministic ordering;
- honest totals + always-true collection_complete;
- traversal rejection and missing-path behavior.
"""

from __future__ import annotations

import json
import os

import pytest

from mcquest_mcp.tools.files import find_files

from conftest import repo, write_file  # noqa: F401  (fixtures)


# --- fixtures ----------------------------------------------------------


def _make_tree(root: str, spec: dict[str, str]) -> None:
    for relative, content in spec.items():
        full = os.path.join(root, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)


@pytest.fixture
def many_matches(repo: str) -> None:
    """240 files matching 'widget' across dirs, 10 not matching."""
    spec: dict[str, str] = {}
    for i in range(120):
        spec[f"src/widget_{i:03d}.ts"] = "x\n"
    for i in range(120):
        spec[f"tests/test_widget_{i:03d}.py"] = "x\n"
    for i in range(10):
        spec[f"other/plain_{i:03d}.txt"] = "x\n"
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


def test_summary_first_block(many_matches) -> None:
    output = find_files(query="widget")
    assert output.startswith("[SUMMARY]\n")
    summary = _parse_summary(output)
    assert summary["tool"] == "mcquest_find_files"
    assert summary["scope"] == 'path="."'
    assert summary["QUERY"] == "widget"
    assert summary["total"] == "240"
    assert summary["returned"] == "100"
    assert summary["offset"] == "0"
    assert summary["next_offset"] == "100"
    assert summary["has_more"] == "true"
    assert summary["truncated"] == "false"
    assert summary["collection_complete"] == "true"
    assert summary["budget"].startswith("4000/")


def test_case_insensitive_substring_match(many_matches) -> None:
    output = find_files(query="WIDGET")
    summary = _parse_summary(output)
    assert summary["total"] == "240"


def test_no_automatic_page_2_and_explicit_offset(many_matches) -> None:
    first = find_files(query="widget")
    first_paths = _evidence_paths(first)
    assert len(first_paths) == 100
    summary = _parse_summary(first)
    assert summary["has_more"] == "true"
    assert summary["next_offset"] == "100"
    assert first_paths == sorted(first_paths)

    second = find_files(query="widget", offset=100)
    second_paths = _evidence_paths(second)
    assert second_paths and not set(first_paths) & set(second_paths)
    summary2 = _parse_summary(second)
    assert summary2["offset"] == "100"
    assert summary2["next_offset"] == "200"


def test_full_walk_covers_every_match_exactly_once(many_matches) -> None:
    seen: list[str] = []
    offset = 0
    for _ in range(10):
        output = find_files(query="widget", offset=offset)
        summary = _parse_summary(output)
        seen.extend(_evidence_paths(output))
        if summary["has_more"] != "true":
            break
        offset = int(summary["next_offset"])
    assert len(seen) == 240
    assert len(set(seen)) == 240
    assert seen == sorted(seen)


def test_deterministic_repeated_calls(many_matches) -> None:
    assert find_files(query="widget") == find_files(query="widget")
    assert find_files(query="widget", offset=50) == find_files(
        query="widget", offset=50
    )


def test_aggregate_metadata_present(many_matches) -> None:
    output = find_files(query="widget")
    summary = _parse_summary(output)
    aggregate = summary.get("aggregate", "")
    assert "dirs: src=120, tests=120" in aggregate
    assert "exts: .py=120, .ts=120" in aggregate
# --- budget ------------------------------------------------------------


def test_default_page_within_4000_chars(many_matches) -> None:
    output = find_files(query="widget")
    assert len(output) <= 4_000
    assert _serialized_len(output) <= 4_500


def test_explicit_page_within_ceiling(repo) -> None:
    spec: dict[str, str] = {}
    for i in range(400):
        spec[f"src/w_{i:04d}.ts"] = "x\n"
    _make_tree(repo, spec)
    output = find_files(query="w_", max_results=10_000)
    assert len(output) <= 16_000
    assert _serialized_len(output) <= 16_500


def test_hard_cap_300(repo) -> None:
    spec: dict[str, str] = {}
    for i in range(400):
        spec[f"src/w_{i:04d}.ts"] = "x\n"
    _make_tree(repo, spec)
    output = find_files(query="w_", max_results=10_000)
    summary = _parse_summary(output)
    assert summary["total"] == "400"
    assert summary["returned"] == "300"


def test_offset_beyond_total_is_empty(many_matches) -> None:
    output = find_files(query="widget", offset=5_000)
    summary = _parse_summary(output)
    assert summary["returned"] == "0"
    assert summary["has_more"] == "false"
    assert _evidence_paths(output) == []


def test_offset_negative_rejected(many_matches) -> None:
    with pytest.raises(ValueError, match="offset"):
        find_files(query="widget", offset=-1)


def test_no_match_returns_empty_page(many_matches) -> None:
    output = find_files(query="zzz_nothing")
    summary = _parse_summary(output)
    assert summary["total"] == "0"
    assert summary["returned"] == "0"
    assert summary["has_more"] == "false"
    assert _evidence_paths(output) == []


# --- filters and security ----------------------------------------------


def test_ignored_extensions_excluded(repo) -> None:
    _make_tree(
        repo,
        {"src/a.ts": "x\n", "src/icon.png": "x\n", "src/b.ts": "x\n"},
    )
    output = find_files(query=".")
    summary = _parse_summary(output)
    assert summary["total"] == "2"
    assert _evidence_paths(output) == ["src/a.ts", "src/b.ts"]


def test_path_scoping(repo) -> None:
    _make_tree(
        repo,
        {"src/a.ts": "x\n", "tests/b.py": "x\n"},
    )
    output = find_files(query="a", path="src")
    summary = _parse_summary(output)
    assert summary["total"] == "1"
    assert _evidence_paths(output) == ["src/a.ts"]


def test_traversal_rejected(repo) -> None:
    with pytest.raises(ValueError, match="escapes"):
        find_files(query="a", path="..")


def test_missing_path_raises(repo) -> None:
    with pytest.raises(FileNotFoundError):
        find_files(query="a", path="does-not-exist")


# --- legacy compatibility ----------------------------------------------


def test_legacy_count_substring_preserved(write_file) -> None:
    write_file("src/a.ts", "x\n")
    output = find_files(query="a.ts")
    assert "COUNT: 1" in output
    assert "src/a.ts" in output
