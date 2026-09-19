"""V0.7 Phase 2 regression: ``mcquest_find_strings`` literal inventory.

Binding contract: ``Docs/V0.7/07-V0.7-PHASE2-PROPOSAL.md`` sections 7-11
(DEC-008). ``find_strings`` is a lexical literal-inventory primitive over
``.js``/``.jsx``/``.ts``/``.tsx``: summary-first, explicitly paged via
``search_block``, ``path:line:col: "value"`` evidence lines ordered by
``(relative_path ASC, line ASC, col ASC)``, two-pass honest ``total``
(``collection_complete=true`` always), template-literal segment rules,
escape handling, comment inclusion (lexical, not AST), ``min_length``
filtering, and the preserved V0.5/V0.6 output budgets / security
boundaries. Phase 3 (``mcquest_find_ui_strings``) is reserved only.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.server import mcp
from mcquest_mcp.tools.strings import find_strings


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


def evidence(output: str) -> list[tuple[str, int, int, str]]:
    """Parse ``relative:line:col: "value"`` evidence lines."""
    body = output.partition("[EVIDENCE]")[2]
    hits: list[tuple[str, int, int, str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        head, _, value = line.partition(': "')
        if not value.endswith('"'):
            continue
        rel_line, _, col_s = head.rpartition(":")
        rel, _, line_s = rel_line.rpartition(":")
        hits.append((rel, int(line_s), int(col_s), value[:-1]))
    return hits


def test_quoted_literals_with_exact_columns(write_file) -> None:
    write_file("src/a.tsx", "const s = 'a' + \"b\";\n")

    out = find_strings(path="src")

    s = summary_of(out)
    assert s["tool"] == "mcquest_find_strings"
    assert s["scope"] == 'path="src"'
    assert s["PATH"] == "src"
    assert s["total"] == "2"
    assert s["files_affected"] == "1"
    assert s["returned"] == "2"
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert out.rstrip().endswith("[END]")
    assert evidence(out) == [
        ("src/a.tsx", 1, 11, "a"),
        ("src/a.tsx", 1, 17, "b"),
    ]


def test_template_segments_interpolation_and_nested_literals(write_file) -> None:
    write_file("src/t.tsx", "const t = `a${\"b\"}c`;\n")
    write_file("src/n.tsx", "const s = `pre${`inner` + \"nest\"}post`;\n")

    out = find_strings(path="src")

    assert summary_of(out)["total"] == "7"
    assert evidence(out) == [
        ("src/n.tsx", 1, 11, "pre"),
        ("src/n.tsx", 1, 17, "inner"),
        ("src/n.tsx", 1, 27, "nest"),
        ("src/n.tsx", 1, 33, "post"),
        ("src/t.tsx", 1, 11, "a"),
        ("src/t.tsx", 1, 15, "b"),
        ("src/t.tsx", 1, 18, "c"),
    ]


def test_template_empty_segments_suppressed(write_file) -> None:
    write_file("src/t.tsx", "const t = `${x}${y}`;\nconst u = ``;\n")

    out = find_strings(path="src")

    assert summary_of(out)["total"] == "0"
    assert evidence(out) == []


def test_escaped_delimiters_do_not_terminate(write_file) -> None:
    write_file("src/e.js", "const a = 'it\\'s';\nconst b = \"say \\\"hi\\\"\";\n")
    write_file("src/f.ts", "const c = `a\\`b`;\n")

    out = find_strings(path="src")

    # Raw content without surrounding quotes; escape sequences kept verbatim.
    assert evidence(out) == [
        ("src/e.js", 1, 11, "it\\'s"),
        ("src/e.js", 2, 11, "say \\\"hi\\\""),
        ("src/f.ts", 1, 11, "a\\`b"),
    ]
def test_single_file_mode_and_unsupported_extension(write_file) -> None:
    write_file("src/a.ts", "const s = 'x';\n")
    write_file("src/b.ts", "const s = 'y';\n")

    out = find_strings(path="src/a.ts")

    s = summary_of(out)
    assert s["total"] == "1"
    assert s["files_affected"] == "1"
    assert evidence(out) == [("src/a.ts", 1, 11, "x")]

    write_file("note.md", "# 'not counted'\n")
    out_md = find_strings(path="note.md")
    assert summary_of(out_md)["total"] == "0"
    assert out_md.rstrip().endswith("[END]")


def test_file_pattern_filters_directory_scope(write_file) -> None:
    write_file("src/a.ts", "const s = 'aval';\n")
    write_file("src/b.tsx", "const s = 'bval';\n")
    write_file("src/c.js", "const s = 'cval';\n")

    out = find_strings(path="src", file_pattern="*.tsx")

    assert summary_of(out)["total"] == "1"
    assert evidence(out) == [("src/b.tsx", 1, 11, "bval")]


def test_ordering_by_path_then_line_then_col(write_file) -> None:
    write_file("src/b.ts", "const x = 'two' + 'one';\n")
    write_file("src/a.ts", "const y = 'AAA';\n")

    out = find_strings(path="src")

    assert evidence(out) == [
        ("src/a.ts", 1, 11, "AAA"),
        ("src/b.ts", 1, 11, "two"),
        ("src/b.ts", 1, 19, "one"),
    ]


def test_paging_contiguous_exactly_once_byte_identical(write_file) -> None:
    write_file(
        "src/p.ts",
        "\n".join(f"const s{i} = 'v{i}';" for i in range(5)) + "\n",
    )
    expected = [("src/p.ts", n, 12, f"v{n - 1}") for n in range(1, 6)]

    pages = [find_strings(path="src", max_results=2, offset=o) for o in (0, 2, 4)]

    for i, out in enumerate(pages):
        s = summary_of(out)
        assert s["total"] == "5"
        if i < 2:
            assert s["has_more"] == "true"
            assert s["next_offset"] == str((i + 1) * 2)
        else:
            assert s["has_more"] == "false"
            assert "next_offset" not in s

    combined = [hit for page in pages for hit in evidence(page)]
    assert combined == expected
    assert len(combined) == len(set(combined))
    assert len(combined) == 5

    assert find_strings(path="src", max_results=2, offset=0) == pages[0]
    assert find_strings(path="src") == find_strings(path="src")


def test_offset_beyond_total_returns_empty_truthful_page(write_file) -> None:
    write_file("src/a.ts", "const s = 'x';\n")

    out = find_strings(path="src", offset=10)

    s = summary_of(out)
    assert s["total"] == "1"
    assert s["returned"] == "0"
    assert s["has_more"] == "false"
    assert "next_offset" not in s
    assert evidence(out) == []
    assert out.rstrip().endswith("[END]")


def test_failure_behavior(write_file) -> None:
    write_file("src/a.ts", "const s = 'x';\n")

    with pytest.raises(FileNotFoundError):
        find_strings(path="src/missing.ts")

    with pytest.raises(ValueError):
        find_strings(path="../outside")

    with pytest.raises(ValueError, match="offset must be >= 0"):
        find_strings(path="src", offset=-1)


def test_scope_ignored_extensions_and_ignored_dirs(write_file, repo) -> None:
    write_file("src/small.ts", "const s = 'small';\n")
    big_rel = write_file("src/big.ts", "const s = 'big';\n")
    big_abs = os.path.join(repo, big_rel.replace("/", os.sep))
    with open(big_abs, "r+b") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")
    write_file("node_modules/pkg.ts", "const s = 'dep';\n")
    write_file("src/notme.py", "const s = 'py';\n")
    write_file("src/notme.md", "## 'md'\n")
    write_file("src/notme.txt", "'txt'\n")

    out = find_strings(path="src")
    assert summary_of(out)["total"] == "1"
    assert evidence(out) == [("src/small.ts", 1, 11, "small")]

    out_all = find_strings(path=".")
    assert "src/small.ts" in out_all
    assert "big.ts" not in out_all
    assert "node_modules" not in out_all
    assert "notme.py" not in out_all
    assert "notme.md" not in out_all


def test_single_file_inside_ignored_dir_rejected(write_file) -> None:
    write_file("node_modules/pkg.ts", "const s = 'dep';\n")

    with pytest.raises(ValueError):
        find_strings(path="node_modules/pkg.ts")


def test_binary_bytes_do_not_crash(repo, write_file) -> None:
    rel = write_file("src/bin.ts", "const s = 'o';\n")
    full = os.path.join(repo, rel.replace("/", os.sep))
    with open(full, "wb") as handle:
        handle.write(b"\xff\xfe'broken")

    out = find_strings(path="src")

    assert "[SUMMARY]" in out
    assert summary_of(out)["total"] == "0"
    assert out.rstrip().endswith("[END]")


def test_quoted_literals_inside_comments_may_be_returned(write_file) -> None:
    write_file("src/c.ts", "// todo: use 'label'\n/* block 'note' */\n")

    out = find_strings(path="src")

    # Lexical (not AST): quoted runs inside comments are reported as items.
    assert summary_of(out)["total"] == "2"
    assert evidence(out) == [
        ("src/c.ts", 1, 14, "label"),
        ("src/c.ts", 2, 10, "note"),
    ]


def test_read_only_leaves_files_unchanged(write_file, repo) -> None:
    write_file("src/a.ts", "const s = 'x';\n")

    def snapshot() -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for current, _dirs, files in os.walk(repo):
            for filename in files:
                full = os.path.join(current, filename)
                stat = os.stat(full)
                snap[full] = (stat.st_size, stat.st_mtime_ns)
        return snap

    before = snapshot()
    find_strings(path="src", max_results=500)
    find_strings(path=".", max_results=500)
    assert snapshot() == before


def test_registered_with_description_and_parameter_schema() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert "mcquest_find_strings" in names

    tool = next(t for t in tools if t.name == "mcquest_find_strings")
    desc = tool.description or ""
    assert desc.startswith("READ ONLY.")
    assert ".js, .jsx, .ts, .tsx" in desc
    assert "NOT a hardcoded-UI-string detector" in desc
    assert "collection_complete" in desc

    properties = tool.input_schema["properties"]
    for param in ("path", "file_pattern", "min_length", "max_results", "offset"):
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )

    assert properties["path"]["type"] == "string"
    assert properties["min_length"]["default"] == 1
    assert properties["max_results"]["default"] == 50
    assert properties["offset"]["default"] == 0
    assert tool.input_schema.get("required", []) == []


def test_default_budget_and_expanded_ceiling(write_file) -> None:
    # Long values so a default page cannot fit the 4,000-char budget and the
    # per-line 200-char clip engages (forcing truthful truncation).
    write_file(
        "src/dense.ts",
        "".join(
            f"const s = '{'x' * 180}{i:03d}';\n" for i in range(1000)
        ),
    )

    default = find_strings(path="src")
    assert len(default) <= 4000
    assert summary_of(default)["budget"] == "4000/16000"
    assert summary_of(default)["total"] == "1000"
    assert summary_of(default)["truncated"] == "true"
    assert "[OUTPUT TRUNCATED" in default

    expanded = find_strings(path="src", max_results=500)
    assert len(expanded) <= 16000
    assert summary_of(expanded)["budget"] == "16000/16000"
    assert summary_of(expanded)["max_results"] == "500"
    assert summary_of(expanded)["total"] == "1000"
    assert summary_of(expanded)["has_more"] == "true"
    assert int(summary_of(expanded)["returned"]) <= 500
    assert max(len(line) for line in expanded.splitlines()) <= 200


def test_min_length_filters_short_and_empty_literals(write_file) -> None:
    write_file("src/m.ts", "const a = '';\nconst b = 'x';\nconst c = 'hello';\n")

    out0 = find_strings(path="src", min_length=0)
    assert summary_of(out0)["total"] == "3"
    assert evidence(out0) == [
        ("src/m.ts", 1, 11, ""),
        ("src/m.ts", 2, 11, "x"),
        ("src/m.ts", 3, 11, "hello"),
    ]

    out1 = find_strings(path="src", min_length=1)
    assert summary_of(out1)["total"] == "2"
    assert evidence(out1) == [
        ("src/m.ts", 2, 11, "x"),
        ("src/m.ts", 3, 11, "hello"),
    ]

    out5 = find_strings(path="src", min_length=5)
    assert summary_of(out5)["total"] == "1"
    assert evidence(out5) == [("src/m.ts", 3, 11, "hello")]


def test_min_length_out_of_bounds_rejected(write_file) -> None:
    write_file("src/a.ts", "const s = 'x';\n")

    for bad in (-1, 101):
        with pytest.raises(ValueError, match="min_length"):
            find_strings(path="src", min_length=bad)

    find_strings(path="src", min_length=0)
    find_strings(path="src", min_length=100)