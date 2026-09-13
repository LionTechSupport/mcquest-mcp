"""Phase C focused tests for ``mcquest_list_files``.

Proves the v0.5 discovery contract (see ``Docs/V0.5/04-V0.5-TEST-PLAN.md``
I/J/K/M/V and ``Docs/V0.5/05-V0.5-DECISIONS.md`` D008/D009):

- summary-first shape (total, COUNT, returned, offset, next_offset,
  has_more, truncated, collection_complete, budget, aggregate);
- default page of 100 under the 4000-char presentation budget;
- absolute 16,000-char ceiling (inclusive of serialization allowance);
- explicit ``offset`` pagination only (never an automatic page 2);
- deterministic ordering and exact no-gap/no-overlap page walks;
- honest totals + always-true collection_complete (full counting pass);
- 300-result hard cap; 601-file fixture totals; legacy ``COUNT:`` line;
- filter behavior (pattern, ignored dirs/extensions, path scoping),
  traversal rejection, byte-identical repeated calls.
"""

from __future__ import annotations

import json
import os

import pytest

from mcquest_mcp.tools.files import list_files

from conftest import repo, write_file  # noqa: F401  (fixtures)


# --- fixtures ----------------------------------------------------------


def _make_tree(root: str, spec: dict[str, str]) -> None:
    """Create a file tree from ``{relative_path: content}`` under ``root``."""
    for relative, content in spec.items():
        full = os.path.join(root, relative)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)


@pytest.fixture
def many_files(repo: str) -> None:
    """250 files across two top-level dirs plus root-level files."""
    spec: dict[str, str] = {}
    for i in range(120):
        spec[f"src/file_{i:03d}.ts"] = "x\n"
    for i in range(120):
        spec[f"tests/test_{i:03d}.py"] = "x\n"
    for i in range(10):
        spec[f"root_{i:03d}.txt"] = "x\n"
    _make_tree(repo, spec)


@pytest.fixture
def big_tree(repo: str) -> None:
    """601 source files (the V.601-file fixture)."""
    spec: dict[str, str] = {}
    for i in range(601):
        spec[f"src/file_{i:04d}.ts"] = "x\n"
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
# --- pagination --------------------------------------------------------


def test_default_page_has_no_automatic_page_2(many_files) -> None:
    output = list_files(path=".")
    paths = _evidence_paths(output)
    assert len(paths) == 100
    assert "src/file_000.ts" in paths
    # The 101st result (first of page 2) must not appear automatically.
    summary = _parse_summary(output)
    assert summary["has_more"] == "true"
    assert summary["next_offset"] == "100"
    ordered = sorted(paths)
    assert paths == ordered  # deterministic (relative_path ASC)


def test_page_2_requires_explicit_offset(many_files) -> None:
    first = list_files(path=".")
    first_paths = _evidence_paths(first)
    second = list_files(path=".", offset=100)
    second_paths = _evidence_paths(second)
    assert second_paths and not set(first_paths) & set(second_paths)
    summary = _parse_summary(second)
    assert summary["offset"] == "100"
    assert summary["next_offset"] == "200"
    assert summary["has_more"] == "true"


def test_next_offset_walk_covers_everything_exactly_once(many_files) -> None:
    seen: list[str] = []
    offset = 0
    for _ in range(10):
        output = list_files(path=".", offset=offset)
        summary = _parse_summary(output)
        seen.extend(_evidence_paths(output))
        if summary["has_more"] != "true":
            break
        offset = int(summary["next_offset"])
    assert len(seen) == 250
    assert len(set(seen)) == 250  # no gaps, no overlaps
    assert seen == sorted(seen)


def test_offset_beyond_total_is_empty_not_error(many_files) -> None:
    output = list_files(path=".", offset=1_000)
    summary = _parse_summary(output)
    assert summary["returned"] == "0"
    assert summary["has_more"] == "false"
    assert _evidence_paths(output) == []


def test_offset_negative_rejected(many_files) -> None:
    with pytest.raises(ValueError, match="offset"):
        list_files(path=".", offset=-1)


def test_deterministic_ordering_repeated_calls(many_files) -> None:
    assert list_files(path=".") == list_files(path=".")
    assert list_files(path=".", offset=100) == list_files(path=".", offset=100)


# --- total honesty -----------------------------------------------------


def test_total_is_full_count_not_page_size(big_tree) -> None:
    output = list_files(path=".", max_results=50)
    summary = _parse_summary(output)
    assert summary["total"] == "601"
    assert summary["returned"] == "50"
    assert summary["collection_complete"] == "true"


def test_601_file_fixture_totals(big_tree) -> None:
    output = list_files(path=".")
    summary = _parse_summary(output)
    assert summary["total"] == "601"
    assert summary["COUNT"] == "100"
    assert summary["has_more"] == "true"
    assert len(_evidence_paths(output)) == 100


# --- filters / security ------------------------------------------------


def test_pattern_filter_scopes_results(repo) -> None:
    _make_tree(
        repo,
        {"src/a.py": "x\n", "src/b.ts": "x\n", "src/c.ts": "x\n"},
    )
    output = list_files(path="src", pattern="*.py")
    summary = _parse_summary(output)
    assert summary["total"] == "1"
    assert _evidence_paths(output) == ["src/a.py"]


def test_path_scoping(repo) -> None:
    _make_tree(
        repo,
        {"src/a.ts": "x\n", "tests/b.py": "x\n", "ROOT.txt": "x\n"},
    )
    output = list_files(path="src")
    summary = _parse_summary(output)
    assert summary["total"] == "1"
    assert _evidence_paths(output) == ["src/a.ts"]


def test_ignored_directories_and_extensions_excluded(repo) -> None:
    _make_tree(
        repo,
        {
            "src/a.ts": "x\n",
            "node_modules/pkg/b.ts": "x\n",
            "src/icon.png": "x\n",
        },
    )
    output = list_files(path=".")
    summary = _parse_summary(output)
    assert summary["total"] == "1"
    paths = _evidence_paths(output)
    assert paths == ["src/a.ts"]


def test_traversal_rejected(repo) -> None:
    with pytest.raises(ValueError, match="escapes"):
        list_files(path="..")


def test_missing_path_raises(repo) -> None:
    with pytest.raises(FileNotFoundError):
        list_files(path="does-not-exist")


# --- legacy compatibility ----------------------------------------------


def test_legacy_count_substring_preserved(write_file) -> None:
    write_file("src/a.ts", "x\n")
    output = list_files(path="src")
    assert "COUNT: 1" in output
    assert "src/a.ts" in output


def test_root_is_file_returns_single_path(write_file) -> None:
    relative = write_file("single.txt", "x\n")
    assert list_files(path=relative) == relative
# --- summary shape -----------------------------------------------------


def test_summary_first_block(many_files) -> None:
    output = list_files(path=".")
    assert output.startswith("[SUMMARY]\n")
    summary = _parse_summary(output)
    assert summary["tool"] == "mcquest_list_files"
    assert summary["scope"] == 'path="."'
    assert summary["total"] == "250"
    assert summary["returned"] == "100"
    assert summary["offset"] == "0"
    assert summary["next_offset"] == "100"
    assert summary["has_more"] == "true"
    assert summary["truncated"] == "false"
    assert summary["collection_complete"] == "true"
    assert summary["budget"].startswith("4000/")


def test_root_and_pattern_and_count_reported(many_files) -> None:
    output = list_files(path=".", pattern="*.ts")
    summary = _parse_summary(output)
    assert summary["ROOT"] == "."
    assert summary["PATTERN"] == "*.ts"
    assert summary["COUNT"] == "100"  # legacy label = returned page size
    assert summary["total"] == "120"
    assert summary["has_more"] == "true"


def test_aggregate_metadata_present_and_deterministic(many_files) -> None:
    output = list_files(path=".")
    summary = _parse_summary(output)
    aggregate = summary.get("aggregate", "")
    # Keys are sorted ASCII: "." < "src" < "tests"; extensions ".py" < ".ts" < ".txt".
    assert "dirs: .=10, src=120, tests=120" in aggregate
    assert "exts: .py=120, .ts=120, .txt=10" in aggregate
    assert list_files(path=".") == output  # byte-identical repeat


# --- budget ------------------------------------------------------------


def test_default_page_within_4000_chars(many_files) -> None:
    output = list_files(path=".")
    assert len(output) <= 4_000
    assert len(output) <= 4_100


def test_default_page_serialized_within_allowance(many_files) -> None:
    output = list_files(path=".")
    assert _serialized_len(output) <= 4_500


def test_explicit_page_never_exceeds_ceiling(big_tree) -> None:
    output = list_files(path=".", max_results=300)
    assert len(output) <= 16_000
    assert _serialized_len(output) <= 16_500


def test_hard_cap_300(big_tree) -> None:
    output = list_files(path=".", max_results=10_000)
    summary = _parse_summary(output)
    assert summary["returned"] == "300"
    assert summary["total"] == "601"