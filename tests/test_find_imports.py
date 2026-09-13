"""Phase D regression: ``mcquest_find_imports`` summary-first, paged.

``find_imports`` scans TypeScript-family sources only (.ts/.tsx/.js/.jsx)
for ES module imports referencing ``target``, emitting the canonical
``[SUMMARY]`` block + one explicit page of ``path:line: import`` lines
ordered by ``(relative_path ASC, line ASC)`` (D008/D009/D016). Phase D added
the missing 2MB file-size skip guard (audit finding G7).
"""

from __future__ import annotations

import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.tools.imports import find_imports


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
    """``(relative, line)`` pairs from ``path:line: import`` lines."""
    body = output.partition("[EVIDENCE]")[2]
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(r"^([^\s:]+?):(\d+): ", body, re.M)
    ]


def test_summary_first_with_echo_fields(write_file) -> None:
    write_file("src/a.ts", "import { Thing } from './lib/targetName';\n")
    write_file("src/b.js", "import targetName from 'targetName';\n")
    write_file("src/c.tsx", "const x = 'no import here';\n")

    out = find_imports(target="targetName", path="src")

    s = summary_of(out)
    assert s["tool"] == "mcquest_find_imports"
    assert s["scope"] == 'path="src"'
    assert s["TARGET"] == "targetName"
    assert s["PATH"] == "src"
    assert s["total"] == "2"
    assert s["files_affected"] == "2"
    assert s["returned"] == "2"
    assert s["budget"] == "4000/16000"
    assert out.rstrip().endswith("[END]")
    assert locations(out) == [("src/a.ts", 1), ("src/b.js", 1)]


def test_only_typescript_family_sources_are_scanned(write_file) -> None:
    write_file("src/a.ts", "import 'targetName';\n")
    write_file("src/b.js", "import 'targetName';\n")
    write_file("src/c.jsx", "import 'targetName';\n")
    write_file("src/d.tsx", "import 'targetName';\n")
    write_file("src/e.py", "import targetName\n")
    write_file("src/f.txt", "import 'targetName';\n")
    write_file("src/g.md", "import 'targetName';\n")

    out = find_imports(target="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "4"
    assert set(locations(out)) == {
        ("src/a.ts", 1),
        ("src/b.js", 1),
        ("src/c.jsx", 1),
        ("src/d.tsx", 1),
    }


def test_target_match_is_substring_of_module(write_file) -> None:
    write_file("src/a.ts", "import x from 'widgets/targetName-core';\n")
    write_file("src/b.ts", "import x from 'other';\n")

    out = find_imports(target="targetName", path="src")

    assert summary_of(out)["total"] == "1"
    assert locations(out) == [("src/a.ts", 1)]


def test_ordering_deterministic_sorted(write_file) -> None:
    write_file("src/z.ts", "import 'targetName';\n")
    write_file("src/a.ts", "import 'targetName';\nimport 'xx';\nimport 'targetName';\n")

    first = find_imports(target="targetName", path="src")
    second = find_imports(target="targetName", path="src")

    assert first == second
    assert locations(first) == [
        ("src/a.ts", 1),
        ("src/a.ts", 3),
        ("src/z.ts", 1),
    ]


def test_default_max_results_is_50(write_file) -> None:
    write_file("src/app.ts", "import 'targetName';\n" * 80)

    out = find_imports(target="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "80"
    assert s["returned"] == "50"
    assert s["has_more"] == "true"
    assert s["next_offset"] == "50"
    assert len(locations(out)) == 50


def test_offset_negative_rejected(write_file) -> None:
    write_file("src/app.ts", "import 'targetName';\n")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        find_imports(target="targetName", path="src", offset=-1)


def test_2mb_file_skip_guard(repo, write_file) -> None:
    write_file("src/small.ts", "import 'targetName';\n")
    big_rel = write_file("src/big.ts", "import 'targetName';\n")
    big_abs = os.path.join(repo, big_rel.replace("/", os.sep))
    with open(big_abs, "r+b") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")

    out = find_imports(target="targetName", path="src")

    s = summary_of(out)
    assert s["total"] == "1"
    assert locations(out) == [("src/small.ts", 1)]