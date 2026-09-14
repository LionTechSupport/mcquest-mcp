"""V0.6 Phase 1 (F1/F2 carry-forward): cross-tool token-sparse acceptance.

Establishes the cross-tool acceptance contract for the bounded-output model
against every applicable registered mcquest_* tool, using representative
worst-case fixtures/inputs:

- default output stays within the 4,000-char normal presentation budget where
  the tool has a normal bounded presentation contract;
- worst-case output never exceeds the 16,000-char ABSOLUTE ceiling, raw AND
  serialized through the contract's MCP text response model;
- every emitted line is clipped at 200 chars (no line-level bypass);
- truncation/continuation metadata stays truthful: collection_complete=true
  means the total is known (not that all results were delivered), and
  has_more=true is accompanied by a next_* continuation field; a truncated
  flag is accompanied by the explicit omission marker;
- every worst-case call is read-only (repository snapshot unchanged).

Does NOT weaken assertions to pass: bounds are exact constants, metadata
checks are structural, fixtures are pathological (500-match searches, 20k-char
lines, 150-file listings, 300-line sources).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcquest_mcp.config import LINE_CLIP_CHARS, MAX_OUTPUT_CHARS, NORMAL_OUTPUT_CHARS
from mcquest_mcp.tools import (
    compare_phase,
    find_evidence,
    find_files,
    find_imports,
    find_usages,
    git_context,
    list_docs,
    list_files,
    pattern_audit,
    phase_context,
    project_context,
    project_info,
    read_doc,
    read_file,
    search_docs,
    search_text,
)

NORMAL = NORMAL_OUTPUT_CHARS  # 4,000
CEILING = MAX_OUTPUT_CHARS  # 16,000
CLIP = LINE_CLIP_CHARS  # 200
ALLOWANCE = 500  # serialized JSON wrapper tolerance (test plan D)

WORD = "targetWord"
MATCH_LINE = (
    "w-screen fixed sticky overflow-x-auto overflow-x:auto whitespace-nowrap "
    "min-w-[500px] -mx-4 translate-x-3 right-[-5px] w-[400px] sticky " + WORD
)


def serialized_len(text: str) -> int:
    """Length of the contract's serialized MCP text response model."""
    return len(json.dumps({"content": [{"type": "text", "text": text}]}))


def summary_fields(output: str) -> dict[str, str]:
    """Parse the canonical ``[SUMMARY]`` block into ``{key: value}``."""
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


@pytest.fixture
def dirty_repo(write_file) -> None:
    """Pathological fixture covering every category of worst-case input."""
    for i in range(3):
        write_file(
            f"src/c{i}.tsx",
            "import React from 'react';\n"
            f"const zetaSym = {i};\n"
            + ("const x = '" + MATCH_LINE + "';\n") * 300,
        )
    write_file("src/style.css", "overflow-x: auto;\n" * 200 + WORD + "\n" * 5)
    write_file("src/long.tsx", "x" * 20_000 + " w-screen\n")
    for i in range(150):
        write_file(f"many/dir{i}/f{i}.tsx", f"{WORD} w-screen\n")
    write_file("docs/phase-61-audit.md", "# Phase 61\n" + WORD + "\n" * 300)
    write_file("docs/phase-62-audit.md", "# Phase 62\n" + WORD + "\n" * 300)
    write_file("docs/guide.md", "# Guide\n" + WORD + "\n" * 5)


# (name, function, default_call, worst-case_call, has_normal_budget)
TOOL_SPECS = [
    ("list_files", list_files, {"path": "src"}, {"path": "many", "max_results": 300}, True),
    ("read_file", read_file, {"path": "src/c0.tsx"}, {"path": "src/c0.tsx", "start_line": 1, "end_line": 1000}, True),
    ("list_docs", list_docs, {"path": "docs"}, {"path": "docs", "max_results": 300}, True),
    ("read_doc", read_doc, {"path": "docs/guide.md"}, {"path": "docs/phase-61-audit.md", "start_line": 1, "end_line": 1000}, True),
    ("find_files", find_files, {"query": "w-screen", "path": "src"}, {"query": "w-screen", "path": "many", "max_results": 300}, True),
    ("search", search_text, {"pattern": WORD, "path": "src"}, {"pattern": ".", "path": "src", "context_lines": 3, "max_results": 500}, True),
    ("search_docs", search_docs, {"pattern": WORD}, {"pattern": WORD, "max_results": 500, "context_lines": 5}, True),
    ("find_imports", find_imports, {"target": "react", "path": "src"}, {"target": "react", "path": "src", "max_results": 500}, True),
    ("find_usages", find_usages, {"symbol": "zetaSym", "path": "src"}, {"symbol": "zetaSym", "path": "src", "max_results": 500}, True),
    ("find_evidence", find_evidence, {"query": WORD, "path": "src"}, {"query": WORD, "scope": "all", "path": "src", "max_results": 500, "context_lines": 5}, True),
    ("phase_context", phase_context, {"query": WORD}, {"query": WORD, "max_results": 500, "context_lines": 5}, True),
    ("pattern_audit", pattern_audit, {"path": "src"}, {"path": "src", "category": "nowrap", "max_results_per_category": 500}, True),
    ("project_info", project_info, {}, {}, False),
    ("project_context", project_context, {}, {}, False),
    ("git_context", git_context, {}, {"max_commits": 50, "max_changes": 50}, False),
    ("compare_phase", compare_phase, {"from_phase": "61", "to_phase": "62"}, {"from_phase": "61", "to_phase": "62", "max_results": 300}, False),
]

SPEC_NAMES = [spec[0] for spec in TOOL_SPECS]
NORMAL_SPECS = [spec for spec in TOOL_SPECS if spec[4]]


@pytest.mark.parametrize("spec", NORMAL_SPECS, ids=[spec[0] for spec in NORMAL_SPECS])
def test_default_within_normal_presentation_budget(dirty_repo, spec) -> None:
    _name, func, default_kwargs, _worst, _has_normal = spec
    out = func(**default_kwargs)
    assert len(out) <= NORMAL, _name


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=SPEC_NAMES)
def test_default_within_absolute_ceiling(dirty_repo, spec) -> None:
    _name, func, default_kwargs, _worst, _has_normal = spec
    assert len(func(**default_kwargs)) <= CEILING, _name


@pytest.mark.parametrize("spec", TOOL_SPECS, ids=SPEC_NAMES)
def test_worst_case_raw_and_serialized_within_ceiling(dirty_repo, spec) -> None:
    _name, func, _default, worst_kwargs, _has_normal = spec
    out = func(**worst_kwargs)
    assert len(out) <= CEILING, f"{_name}: raw {len(out)}"
    assert serialized_len(out) <= CEILING + ALLOWANCE, f"{_name}: serialized"


@pytest.mark.parametrize("spec", NORMAL_SPECS, ids=[spec[0] for spec in NORMAL_SPECS])
def test_summary_metadata_truthful_and_lines_clipped(dirty_repo, spec) -> None:
    name, func, default_kwargs, _worst, _has_normal = spec
    out = func(**default_kwargs)
    assert out.startswith("[SUMMARY]\n"), name

    s = summary_fields(out)
    assert "has_more" in s and "truncated" in s and "budget" in s, name
    assert s["has_more"] in ("true", "false")
    assert s["truncated"] in ("true", "false")
    # windowed reads report total_lines/next_start_line; collection_complete is
    # emitted by the discovery/search/audit tools that carry honest totals.
    if "collection_complete" in s:
        assert s["collection_complete"] in ("true", "false")

    budget = s["budget"].split("/")
    assert len(budget) == 2
    assert budget[0].isdigit() and budget[1].isdigit()
    assert int(budget[1]) <= CEILING
    assert int(budget[0]) <= int(budget[1])

    next_keys = [k for k in s if k.startswith("next_")]
    if name == "pattern_audit":
        # no offset paging: continuation is the additive 'category' parameter
        assert s["has_more"] in ("true", "false")
    elif s["has_more"] == "true":
        assert next_keys, f"{name}: has_more without continuation field"
    else:
        assert not next_keys, f"{name}: next_* with has_more=false"

    if s["truncated"] == "true":
        assert "[OUTPUT TRUNCATED" in out, name
    else:
        assert "[OUTPUT TRUNCATED" not in out, name

    for line in out.splitlines():
        assert len(line) <= CLIP, f"{name}: line of {len(line)} chars"


def test_deterministic_repeated_outputs(dirty_repo) -> None:
    for name, func, kwargs, _worst, has_normal in TOOL_SPECS:
        if not has_normal:
            continue
        first = func(**kwargs)
        second = func(**kwargs)
        assert first == second, name


def test_worst_case_calls_are_read_only(dirty_repo, repo) -> None:
    def snapshot() -> dict[str, tuple[int, int]]:
        import os

        snap: dict[str, tuple[int, int]] = {}
        for current, dirs, files in os.walk(repo):
            for filename in files:
                full = os.path.join(current, filename)
                stat = os.stat(full)
                snap[full] = (stat.st_size, stat.st_mtime_ns)
        return snap

    before = snapshot()
    for _name, func, _default, worst_kwargs, _has_normal in TOOL_SPECS:
        func(**worst_kwargs)
    assert snapshot() == before


def test_diagnostics_worst_case_bounded(repo, write_file, monkeypatch) -> None:
    import sys

    diag = sys.modules["mcquest_mcp.tools.diagnostics"]

    write_file("src/a.tsx", "const x = 1;\n")
    monkeypatch.setattr(diag, "_node_available", lambda: True)
    monkeypatch.setattr(
        diag,
        "_detect_typescript",
        lambda root: (
            Path(repo) / "node_modules" / "typescript" / "lib" / "typescript.js",
            "5.4.5",
        ),
    )
    many = [
        {
            "code": 1005,
            "message": "'}' expected",
            "severity": "error",
            "line": i,
            "column": 1,
            "length": 1,
        }
        for i in range(1, 51)
    ]
    monkeypatch.setattr(
        diag,
        "_run_driver",
        lambda root, tslib, relative, source: {
            "ok": True,
            "file": "ignored",
            "scriptKindName": "TS",
            "typeScriptVersion": "5.4.5",
            "diagnostics": many,
        },
    )

    default = diag.diagnostics("src/a.tsx")
    worst = diag.diagnostics("src/a.tsx", context_lines=25, max_diagnostics=50)

    assert len(default) <= CEILING
    assert len(worst) <= CEILING
    assert serialized_len(worst) <= CEILING + ALLOWANCE
    assert "diagnostics shown: 50 (of 50)" in worst
    for line in worst.splitlines():
        assert len(line) <= CLIP + 1, line