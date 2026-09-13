"""Phase D regression: ``mcquest_find_usages`` summary-first, paged.

``find_usages`` scans TypeScript-family sources only (.ts/.tsx/.js/.jsx) for
whole-word symbol references, emitting the canonical ``[SUMMARY]`` block +
one explicit page of ``path:line: reference`` lines ordered by
``(relative_path ASC, line ASC)`` (D008/D009/D016). Phase D added the missing
2MB file-size skip guard (audit finding G7).
"""

from __future__ import annotations

import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.tools.imports import find_usages


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
    """``(relative, line)`` pairs from ``path:line: reference`` lines."""
    body = output.partition("[EVIDENCE]")[2]
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(r"^([^\s:]+?):(\d+): ", body, re.M)
    ]


def test_summary_first_with_echo_fields(write_file) -> None:
    write_file("src/a.ts", "const targetName = 1;\n")
    write_file("src/b.js", "targetName(2);\n")

    out = find_usages(symbol="targetName", path="src")

    s = summary_of(out)
    assert s["tool"] == "mcquest_find_usages"
    assert s["scope"] == 'path="src"'
    assert s["SYMBOL"] == "targetName"
    assert s["PATH"] == "src"
    assert s["total"] == "2"
    assert s["files_affected"] == "2"
    assert s["returned"] == "2"
    assert s["budget"] == "4000/16000"
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("src/a.ts", 1), ("src/b.js", 1)]


def test_word_boundary_matching(write_file) -> None:
    write_file(
        "src/app.ts",
        "const targetName = 1;\n"
        "const myTargetName = 2;\n"
        "const targetNameExtra = 3;\n"
        "targetName();\n",
    )

    out = find_usages(symbol="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "2"
    assert locations(out) == [("src/app.ts", 1), ("src/app.ts", 4)]


def test_only_typescript_family_sources_are_scanned(write_file) -> None:
    write_file("src/a.ts", "targetName\n")
    write_file("src/b.js", "targetName\n")
    write_file("src/c.py", "targetName\n")
    write_file("src/d.txt", "targetName\n")

    out = find_usages(symbol="targetName", path="src")

    assert summary_of(out)["total"] == "2"
    assert locations(out) == [("src/a.ts", 1), ("src/b.js", 1)]


def test_file_pattern_restricts_scan(write_file) -> None:
    write_file("src/a.ts", "targetName\n")
    write_file("src/b.js", "targetName\n")

    out = find_usages(symbol="targetName", path="src", file_pattern="*.js")

    assert summary_of(out)["total"] == "1"
    assert locations(out) == [("src/b.js", 1)]


def test_default_max_results_is_50(write_file) -> None:
    write_file("src/app.ts", "targetName\n" * 80)

    out = find_usages(symbol="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "80"
    assert s["returned"] == "50"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "50"
    assert len(locations(out)) == 50


def test_offset_negative_rejected(write_file) -> None:
    write_file("src/app.ts", "targetName\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        find_usages(symbol="targetName", path="src", offset=-1)


def test_2mb_file_skip_guard(repo, write_file) -> None:
    write_file("src/small.ts", "targetName\n")
    big_rel = write_file("src/big.ts", "targetName\n")
    big_abs = os.path.join(repo, big_rel.replace("/", os.sep))
    with open(big_abs, "r+b") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")

    out = find_usages(symbol="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "1"
    assert locations(out) == [("src/small.ts", 1)]