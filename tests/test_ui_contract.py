"""V0.8 regression: ``mcquest_ui_contract_audit`` lexical prop-contract audit.

Binding contract: ``Docs/V0.8/01-V0.8-CONTRACT.md`` sections 2.0/2.2/3/4
(DEC-027 path/error table; DEC-018 fixed category enum and sort key;
DEC-022 all-sites refinement; DEC-023 fully-available-definition rule;
DEC-031 ``mismatched_usage``/``signature_drift`` severity mapping;
DEC-016/DEC-022 full-scan two-pass completeness; DEC-028 budgets and
continuation) and ``Docs/V0.8/04-V0.8-TEST-PLAN.md`` sections 2.3/2.4/2.5/
2.7/2.8. Fixtures are temporary files written under the per-test project
root (conftest), so no assertion depends on live repository contents.

Everything asserted here is lexical: exact-text/token comparisons with no
parser, no symbol resolution, and no semantic inference (DEC-015/DEC-018).
``risk`` is never emitted (DEC-025) and no consistency row type exists
(DEC-024).
"""

from __future__ import annotations

import asyncio
import os
import re

import pytest

from mcquest_mcp.config import MAX_FILE_BYTES
from mcquest_mcp.server import mcp
from mcquest_mcp.tools.ui_contract import ui_contract_audit

ROW_HEAD = re.compile(
    r"^(?P<rel>.+):(?P<line>\d+): (?P<name>[A-Za-z_$][\w$]*) (?P<category>[a-z_]+) "
    r"\[severity: (?P<severity>\w+) \(heuristic\); "
    r"confidence: (?P<confidence>\w+) \(heuristic\)\]$"
)
ISSUE_LINE = re.compile(r"^    issue: (?P<issue>.*)$")
EVIDENCE_LINE = re.compile(r"^    evidence: (?P<evidence>.*)$")

FIXED_CATEGORIES = {
    "missing_prop",
    "stale_prop",
    "mismatched_usage",
    "signature_drift",
    "unverifiable",
}
FIXED_SEVERITIES = {"info", "warning", "critical"}
FIXED_CONFIDENCES = {"low", "medium", "high"}


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


def rows_of(output: str) -> list[dict[str, str]]:
    """Parse one page of issue rows into per-row field dictionaries."""
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in output.partition("[EVIDENCE]")[2].splitlines():
        head = ROW_HEAD.match(raw)
        if head:
            current = {
                "rel": head["rel"],
                "line": head["line"],
                "name": head["name"],
                "category": head["category"],
                "severity": head["severity"],
                "confidence": head["confidence"],
            }
            rows.append(current)
            continue
        if current is None:
            continue
        issue = ISSUE_LINE.match(raw)
        if issue:
            current["issue"] = issue["issue"]
            continue
        evidence = EVIDENCE_LINE.match(raw)
        if evidence:
            current["evidence"] = evidence["evidence"]
    return rows


def signatures(output: str) -> list[tuple[str, int, str, str, str, str]]:
    """Return ``(rel, line, name, category, severity, confidence)`` tuples."""
    return [
        (
            row["rel"],
            int(row["line"]),
            row["name"],
            row["category"],
            row["severity"],
            row["confidence"],
        )
        for row in rows_of(output)
    ]


# --- shared phenotype fixture (contract section 2.2) -------------------------

# One finding of every category, anchored deterministically. ``List`` and
# ``Panel`` exercise a complete, fully evaluable all-sites omission
# (critical); ``Badge`` has no in-scope definition (mismatched_usage);
# ``Widget`` has only a spread call site (never critical, DEC-022).
FIXTURE = {
    "src/a_def.tsx": (
        "export function List({ items, footer }) {\n"
        "  return null;\n"
        "}\n"
    ),
    "src/b_call.tsx": "const first = <List items={[1]} />;\n",
    "src/c_def.tsx": "const Panel = ({ title, count }) => null;\n",
    "src/d_call.tsx": (
        'const p1 = <Panel title="x" extra="e" />;\n'
        'const p2 = <Panel title="y" />;\n'
    ),
    "src/e_mismatch.tsx": (
        'const x = <Badge kind="a" />;\n'
        'const y = <Badge label="b" />;\n'
    ),
    "src/f_def.tsx": (
        "export function Widget({ size }) {\n"
        "  return null;\n"
        "}\n"
    ),
    "src/g_spread.tsx": "const s = <Widget {...rest} />;\n",
}

EXPECTED_FIXTURE_ROWS = [
    ("src/a_def.tsx", 1, "List", "signature_drift", "warning", "high"),
    ("src/b_call.tsx", 1, "List", "missing_prop", "critical", "high"),
    ("src/c_def.tsx", 1, "Panel", "signature_drift", "warning", "high"),
    ("src/d_call.tsx", 1, "Panel", "stale_prop", "warning", "high"),
    ("src/d_call.tsx", 1, "Panel", "missing_prop", "critical", "high"),
    ("src/d_call.tsx", 2, "Panel", "missing_prop", "critical", "high"),
    ("src/e_mismatch.tsx", 1, "Badge", "mismatched_usage", "warning", "medium"),
    ("src/g_spread.tsx", 1, "Widget", "unverifiable", "info", "low"),
]

# The seven files holding definition/call evidence of the components that
# produced findings (files_affected is computed from the finding evidence,
# not from every scanned file).
FIXTURE_AFFECTED_FILES = 7


def write_fixture(write_file) -> None:
    for relative, content in FIXTURE.items():
        write_file(relative, content)


# --- categories, severity, confidence (contract section 2.2 / section 4) ----


def test_phenotype_rows_summary_ordering_and_evidence(write_file) -> None:
    write_fixture(write_file)

    out = ui_contract_audit(path="src")

    s = summary_of(out)
    assert s["tool"] == "mcquest_ui_contract_audit"
    assert s["scope"] == 'path="src"'
    assert s["PATH"] == "src"
    assert s["component_pattern"] == "*"
    assert s["include_callers"] == "true"
    assert s["max_results"] == "50"
    assert s["total"] == str(len(EXPECTED_FIXTURE_ROWS))
    assert s["files_affected"] == str(FIXTURE_AFFECTED_FILES)
    assert s["returned"] == str(len(EXPECTED_FIXTURE_ROWS))
    assert s["offset"] == "0"
    assert s["has_more"] == "false"
    assert s["truncated"] == "false"
    assert s["collection_complete"] == "true"
    assert s["budget"] == "4000/16000"
    assert "next_offset" not in s
    assert out.rstrip().endswith("[END]")

    # Exact deterministic ordering by (relative_path ASC, line ASC)
    # (DEC-018 / test plan section 2.3).
    assert signatures(out) == EXPECTED_FIXTURE_ROWS


def test_every_category_and_evidence_row_is_present(write_file) -> None:
    write_fixture(write_file)

    rows = rows_of(ui_contract_audit(path="src"))

    # The fixed enum (DEC-018) is fully exercised by this fixture.
    assert {row["category"] for row in rows} == FIXED_CATEGORIES

    # DEC-017: every emitted severity/confidence label carries its required
    # supporting evidence row, and every row explains its issue.
    for row in rows:
        assert row["severity"] in FIXED_SEVERITIES
        assert row["confidence"] in FIXED_CONFIDENCES
        assert row.get("issue", "").strip()
        assert row.get("evidence", "").strip()
        assert ":" in row["evidence"]

    by_category = {row["category"]: row for row in rows}
    # stale_prop evidence names both the call site and the definition.
    assert "call site src/d_call.tsx:1" in by_category["stale_prop"]["evidence"]
    assert "definition src/c_def.tsx:1" in by_category["stale_prop"]["evidence"]
    # missing_prop evidence names the definition that declares the prop (there
    # is one missing_prop row per omitting call site, so select by component).
    list_missing = next(
        row
        for row in rows
        if row["category"] == "missing_prop" and row["name"] == "List"
    )
    assert "definition src/a_def.tsx:1" in list_missing["evidence"]
    # unverifiable evidence names the unevaluable call site and definition.
    assert "call site src/g_spread.tsx:1" in by_category["unverifiable"]["evidence"]
    # mismatched_usage evidence lists the disagreeing call sites.
    assert "src/e_mismatch.tsx:1" in by_category["mismatched_usage"]["evidence"]
    assert "src/e_mismatch.tsx:2" in by_category["mismatched_usage"]["evidence"]
    # signature_drift evidence names the differing call sites.
    assert "differing call sites" in by_category["signature_drift"]["evidence"]


def test_definition_and_call_sites_resolve_across_files(write_file) -> None:
    # The definition lives in a_def.tsx, the call site in b_call.tsx: the
    # in-scope contract is the whole scanned scope, not a single file.
    write_file(
        "src/a_def.tsx",
        "export function List({ items, footer }) {\n  return null;\n}\n",
    )
    write_file("src/b_call.tsx", "const first = <List items={[1]} />;\n")

    out = ui_contract_audit(path="src")

    assert signatures(out) == [
        ("src/a_def.tsx", 1, "List", "signature_drift", "warning", "high"),
        ("src/b_call.tsx", 1, "List", "missing_prop", "critical", "high"),
    ]
    missing = next(row for row in rows_of(out) if row["category"] == "missing_prop")
    assert "definition src/a_def.tsx:1" in missing["evidence"]


def test_complete_all_sites_omission_is_critical(write_file) -> None:
    # Every in-scope call site is accounted for, fully evaluable, and omits
    # the prop -> critical (DEC-022).
    write_file("src/a_def.tsx", "export function Same({ a, b }) { return null; }\n")
    write_file(
        "src/b_call.tsx",
        "const s1 = <Same a={1} />;\nconst s2 = <Same a={2} />;\n",
    )

    out = ui_contract_audit(path="src")

    # One row per call site: rows are per-location evidence and are never
    # collapsed into a single aggregate row.
    assert signatures(out) == [
        ("src/a_def.tsx", 1, "Same", "signature_drift", "warning", "high"),
        ("src/b_call.tsx", 1, "Same", "missing_prop", "critical", "high"),
        ("src/b_call.tsx", 2, "Same", "missing_prop", "critical", "high"),
    ]
    critical = [row for row in rows_of(out) if row["severity"] == "critical"]
    assert all("all in-scope call sites omit it" in row["issue"] for row in critical)


def test_partial_omission_is_never_critical(write_file) -> None:
    # One call site omits the prop while another supplies it -> warning, and
    # the issue text must not claim an all-sites omission (DEC-022).
    write_file(
        "src/a_def.tsx",
        "export function Msg({ tone, text }) {\n  return null;\n}\n",
    )
    write_file(
        "src/b_call.tsx",
        'const m1 = <Msg tone="a" text="b" />;\nconst m2 = <Msg tone="a" />;\n',
    )

    out = ui_contract_audit(path="src")

    assert signatures(out) == [
        ("src/a_def.tsx", 1, "Msg", "signature_drift", "warning", "high"),
        ("src/b_call.tsx", 2, "Msg", "missing_prop", "warning", "high"),
    ]
    missing = [row for row in rows_of(out) if row["category"] == "missing_prop"]
    assert len(missing) == 1
    assert "all in-scope call sites omit it" not in missing[0]["issue"]


def test_unevaluable_call_site_downgrades_severity_and_confidence(write_file) -> None:
    # A spread call site cannot be accounted for, so an omission that could
    # otherwise become an all-sites claim is warning/medium, never critical
    # (DEC-022), and the unevaluable site is reported as unverifiable.
    write_file(
        "src/a_def.tsx",
        "export function Tabs({ active, items }) {\n  return null;\n}\n",
    )
    write_file(
        "src/b_call.tsx",
        "const t1 = <Tabs items={[1]} />;\nconst t2 = <Tabs {...rest} />;\n",
    )

    out = ui_contract_audit(path="src")

    assert signatures(out) == [
        ("src/a_def.tsx", 1, "Tabs", "signature_drift", "warning", "high"),
        ("src/b_call.tsx", 1, "Tabs", "missing_prop", "warning", "medium"),
        ("src/b_call.tsx", 2, "Tabs", "unverifiable", "info", "low"),
    ]
    assert all(row["severity"] != "critical" for row in rows_of(out))


def test_stale_prop_requires_a_fully_available_definition(write_file) -> None:
    # Exactly one definition site with a lexically enumerable prop set is a
    # "fully available" definition -> stale_prop warning (DEC-023).
    write_file(
        "src/a_def.tsx",
        "export function Panel({ title, count }) {\n  return null;\n}\n",
    )
    write_file("src/b_call.tsx", 'const p1 = <Panel title="x" extra="e" />;\n')

    out = ui_contract_audit(path="src")

    assert signatures(out) == [
        ("src/a_def.tsx", 1, "Panel", "signature_drift", "warning", "high"),
        ("src/b_call.tsx", 1, "Panel", "stale_prop", "warning", "high"),
        # ``count`` is declared and omitted by every in-scope call site, so the
        # all-sites rule legitimately also reports it (critical).
        ("src/b_call.tsx", 1, "Panel", "missing_prop", "critical", "high"),
    ]
    stale = next(row for row in rows_of(out) if row["category"] == "stale_prop")
    assert 'prop "extra"' in stale["issue"]


def test_ambiguous_and_non_enumerable_definitions_are_unverifiable(write_file) -> None:
    # Duplicated definition sites and non-enumerable declared prop sets must
    # never produce a verified stale_prop/missing_prop (DEC-023): only
    # unverifiable rows, always info/low and never critical.
    write_file(
        "src/dups.tsx",
        "function Dup({ a }) { return null; }\n"
        "const Dup = ({ b }) => null;\n"
        "const d1 = <Dup a={1} />;\n",
    )
    write_file(
        "src/ids.tsx",
        "function Wrapper(props) { return null; }\n"
        'const w1 = <Wrapper title="t" />;\n'
        "const w2 = <Wrapper {...rest} />;\n",
    )
    write_file(
        "src/klass.tsx",
        "class Legacy extends Base {}\n"
        "const l1 = <Legacy x={1} />;\n",
    )

    out = ui_contract_audit(path="src")

    assert signatures(out) == [
        ("src/dups.tsx", 1, "Dup", "unverifiable", "info", "low"),
        ("src/ids.tsx", 1, "Wrapper", "unverifiable", "info", "low"),
        ("src/ids.tsx", 2, "Wrapper", "unverifiable", "info", "low"),
        ("src/ids.tsx", 3, "Wrapper", "unverifiable", "info", "low"),
        ("src/klass.tsx", 1, "Legacy", "unverifiable", "info", "low"),
        ("src/klass.tsx", 2, "Legacy", "unverifiable", "info", "low"),
    ]
    for row in rows_of(out):
        assert row["category"] == "unverifiable"
        assert row["severity"] == "info"
        assert row["confidence"] == "low"
    # The ambiguous definition sites are both named in the evidence.
    dup = rows_of(out)[0]
    assert "src/dups.tsx:1" in dup["evidence"]
    assert "src/dups.tsx:2" in dup["evidence"]


def test_literal_object_call_sites_are_evaluable(write_file) -> None:
    # ``Name({...})`` object-literal call sites are recognised alongside JSX
    # tags and feed the same evidence rules.
    write_file(
        "src/a_def.tsx",
        "export function Box({ width, height }) { return null; }\n",
    )
    write_file(
        "src/b_call.tsx",
        "const b1 = Box({ width: 1 });\nconst b2 = Box({ width: 2 });\n",
    )

    out = ui_contract_audit(path="src")

    assert signatures(out) == [
        ("src/a_def.tsx", 1, "Box", "signature_drift", "warning", "high"),
        ("src/b_call.tsx", 1, "Box", "missing_prop", "critical", "high"),
        ("src/b_call.tsx", 2, "Box", "missing_prop", "critical", "high"),
    ]


# --- include_callers and generic type syntax (contract section 2.2) ---------


def test_include_callers_false_keeps_definition_anchored_rows(write_file) -> None:
    write_fixture(write_file)

    out = ui_contract_audit(path="src", include_callers=False)

    s = summary_of(out)
    assert s["include_callers"] == "false"
    assert s["total"] == "2"
    assert s["files_affected"] == "4"
    assert s["collection_complete"] == "true"
    # Definition-anchored signature_drift is governed by its own evidence rule
    # and is NOT suppressed merely because call-site rows are excluded.
    assert signatures(out) == [
        ("src/a_def.tsx", 1, "List", "signature_drift", "warning", "high"),
        ("src/c_def.tsx", 1, "Panel", "signature_drift", "warning", "high"),
    ]
    # No call-site-anchored row is reported in this mode.
    anchored = {row["rel"] for row in rows_of(out)}
    assert anchored == {"src/a_def.tsx", "src/c_def.tsx"}


def test_jsx_generic_argument_is_not_mistaken_for_a_call(write_file) -> None:
    # The immediately-nested generic form ``<Name<...`` is a type-parameter
    # application, not JSX usage: it must not create a call site. If it were
    # misparsed, ``cols``/``rows`` would fabricate stale_prop findings.
    write_file(
        "src/gen.tsx",
        "export function Grid({ cols }) { return null; }\n"
        "const g = <Grid<number> cols={2} rows={3} />;\n",
    )

    out = ui_contract_audit(path="src")

    assert signatures(out) == []
    assert summary_of(out)["total"] == "0"


def test_type_argument_usage_is_not_a_component_call(write_file) -> None:
    # A type argument (``Array<Chip>``, ``Box<Wrap>``) is a type position, not
    # a call: it must not be enumerated as a relevant call site. Counting it
    # fabricates findings from evidence that is not a call at all, which
    # DEC-022 forbids ("A merely unobserved call site is never reported as a
    # verified missing-prop violation" / absence of evidence is never proof of
    # a defect) -- see the defect report accompanying this phase.
    write_file(
        "src/a_type.tsx",
        "export function Chip({ label }) { return null; }\n"
        "const items: Array<Chip> = [];\n"
        'const ok = <Chip label="x" />;\n',
    )
    write_file(
        "src/b_type.tsx",
        "export function Wrap({ a }) { return null; }\n"
        "const w: Box<Wrap> = null;\n",
    )

    out = ui_contract_audit(path="src")

    # The only real call site (``<Chip label="x" />``) passes every declared
    # prop, so no finding is supportable anywhere in this scope.
    assert signatures(out) == []


def test_keyword_adjacent_jsx_is_still_a_call_site(write_file) -> None:
    # The type-argument guard keys on a ``<`` glued to a preceding identifier,
    # so a genuine JSX element written directly after a JavaScript keyword
    # (``return<Keyword ... />``) must still be recognised as a real call site
    # and must NOT be skipped as a type-argument reference. The four
    # type-argument forms below must contribute no call site at all, so any
    # zero-prop site leaking from them would fabricate ``missing_prop``.
    write_file(
        "src/keyword.tsx",
        "export function Keyword({ label }) { return null; }\n"
        "const t: Array<Keyword> = [];\n"
        "const u: React.FC<Keyword> = null;\n"
        "const v = useMemo<Keyword>(() => null, []);\n"
        "const n: Array<Array<Keyword>> = [];\n"
        "export function Orphan({ title }) { return null; }\n"
        "const o: Box<Orphan> = null;\n"
        'function render() { return<Keyword label="x" mystery="1" />; }\n',
    )

    out = ui_contract_audit(path="src")

    s = summary_of(out)
    assert s["total"] == "2"
    assert s["files_affected"] == "1"
    assert s["collection_complete"] == "true"

    # The keyword-adjacent element is the component's only call site, and it is
    # evaluated lexically: ``mystery`` is passed but not declared (stale_prop),
    # and the declared ``label`` IS passed, so no missing_prop follows.
    assert signatures(out) == [
        ("src/keyword.tsx", 1, "Keyword", "signature_drift", "warning", "high"),
        ("src/keyword.tsx", 8, "Keyword", "stale_prop", "warning", "high"),
    ]
    rows = rows_of(out)
    stale = next(row for row in rows if row["category"] == "stale_prop")
    assert "call site src/keyword.tsx:8" in stale["evidence"]
    # Its prop keys were parsed from the JSX tag (a misclassified
    # type-argument reference would carry no keys and never reach this rule).
    assert "passes: label, mystery" in stale["evidence"]

    # No false, type-reference-driven findings: no zero-prop call site was
    # invented, and the drift row is explained by the real element alone --
    # the four type-argument lines contributed no call site.
    assert "missing_prop" not in out
    drift = next(row for row in rows if row["category"] == "signature_drift")
    assert "differing call sites: src/keyword.tsx:8" in drift["evidence"]
    assert "Orphan" not in out  # type-argument-only reference: no findings
    assert "critical" not in out
    for type_argument_line in ("src/keyword.tsx:2", "src/keyword.tsx:3",
                               "src/keyword.tsx:4", "src/keyword.tsx:5",
                               "src/keyword.tsx:7"):
        assert type_argument_line not in out


# --- pagination, completeness, and budgets (contract sections 2.3/3) --------


def test_explicit_pagination_and_continuation(write_file) -> None:
    write_fixture(write_file)

    first = ui_contract_audit(path="src", max_results=3)
    s1 = summary_of(first)
    assert s1["total"] == "8"
    assert s1["returned"] == "3"
    assert s1["offset"] == "0"
    assert s1["has_more"] == "true"
    assert s1["next_offset"] == "3"
    assert s1["budget"] == "4000/16000"
    assert signatures(first) == EXPECTED_FIXTURE_ROWS[:3]

    second = ui_contract_audit(path="src", max_results=3, offset=3)
    s2 = summary_of(second)
    assert s2["total"] == "8"
    assert s2["returned"] == "3"
    assert s2["offset"] == "3"
    assert s2["has_more"] == "true"
    assert s2["next_offset"] == "6"
    assert signatures(second) == EXPECTED_FIXTURE_ROWS[3:6]

    third = ui_contract_audit(path="src", max_results=3, offset=6)
    s3 = summary_of(third)
    assert s3["returned"] == "2"
    assert s3["has_more"] == "false"
    assert "next_offset" not in s3
    assert signatures(third) == EXPECTED_FIXTURE_ROWS[6:]

    # The pages reconstruct the full page-1 ordering with no duplicates and no
    # gaps (deterministic continuation).
    assert (
        signatures(first) + signatures(second) + signatures(third)
        == EXPECTED_FIXTURE_ROWS
    )


def test_offset_at_and_beyond_the_total_is_an_empty_page(write_file) -> None:
    write_fixture(write_file)

    at_end = ui_contract_audit(path="src", offset=8)
    assert summary_of(at_end)["returned"] == "0"
    assert summary_of(at_end)["has_more"] == "false"
    assert summary_of(at_end)["total"] == "8"
    assert signatures(at_end) == []

    past_end = ui_contract_audit(path="src", offset=100)
    s = summary_of(past_end)
    assert s["returned"] == "0"
    assert s["has_more"] == "false"
    assert s["total"] == "8"
    assert s["collection_complete"] == "true"
    assert past_end.rstrip().endswith("[END]")


def test_component_pattern_filters_scanned_files(write_file) -> None:
    write_file(
        "src/keep_a.tsx",
        "export function K({ alpha, beta }) { return null; }\n"
        "const k1 = <K alpha={1} />;\n",
    )
    write_file(
        "src/skip_b.tsx",
        "export function S({ alpha, beta }) { return null; }\n"
        "const s1 = <S alpha={1} />;\n",
    )

    out = ui_contract_audit(path="src", component_pattern="*_a.tsx")

    assert summary_of(out)["component_pattern"] == "*_a.tsx"
    assert {row["rel"] for row in rows_of(out)} == {"src/keep_a.tsx"}
    assert summary_of(out)["files_affected"] == "1"


# --- budgets, truncation, atomic emission (DEC-028 / P014) ------------------


def dense_source(count: int = 200) -> str:
    """``count`` components, each producing one signature_drift + one missing_prop."""
    lines: list[str] = []
    for index in range(count):
        lines.append(
            f"export function C{index:03d}({{ alpha, beta }}) {{ return null; }}"
        )
        lines.append(f"const k{index:03d} = <C{index:03d} alpha={{1}} />;")
    return "\n".join(lines) + "\n"


def test_budgets_truncation_atomicity_and_honest_total(write_file) -> None:
    write_file("src/dense.tsx", dense_source())

    default = ui_contract_audit(path="src")
    assert len(default) <= 4000
    s = summary_of(default)
    assert s["budget"] == "4000/16000"
    # Full-scan two-pass honest total: the count is authoritative and does not
    # depend on how much fits in this page (DEC-016/P004).
    assert s["total"] == "400"
    assert s["collection_complete"] == "true"
    assert s["truncated"] == "true"
    assert s["has_more"] == "true"
    assert s["next_offset"] == s["returned"]
    assert "[OUTPUT TRUNCATED:" in default
    assert max(len(line) for line in default.splitlines()) <= 200

    # Atomic emission: whole rows only, never a split snippet.
    body = default.partition("[EVIDENCE]")[2]
    heads = sum(1 for line in body.splitlines() if ROW_HEAD.match(line))
    issues = sum(1 for line in body.splitlines() if ISSUE_LINE.match(line))
    evidence = sum(1 for line in body.splitlines() if EVIDENCE_LINE.match(line))
    assert heads > 0
    assert heads == issues == evidence

    # Expanded ceiling: more rows are delivered, the total stays honest.
    expanded = ui_contract_audit(path="src", max_results=500)
    assert len(expanded) <= 16000
    se = summary_of(expanded)
    assert se["budget"] == "16000/16000"
    assert se["total"] == s["total"]
    assert se["collection_complete"] == "true"
    assert max(len(line) for line in expanded.splitlines()) <= 200
    assert int(se["returned"]) > int(s["returned"])

    # Continuation past what the budget actually delivered.
    tail = ui_contract_audit(
        path="src", max_results=500, offset=int(se["next_offset"])
    )
    st = summary_of(tail)
    assert st["total"] == "400"
    assert st["offset"] == se["next_offset"]
    assert st["collection_complete"] == "true"
    # Deterministic continuation: the next page resumes at the first row not
    # delivered by the budget-cut page (in this fixture row N lives on source
    # line N, and the rows are ordered by (path, line)).
    assert signatures(tail)[0][1] == int(se["returned"]) + 1


def test_non_emittable_values_are_absent(write_file) -> None:
    write_fixture(write_file)

    out = ui_contract_audit(path="src")

    # risk semantics are deferred (DEC-025) and no consistency row type exists
    # (DEC-024): neither may appear in this tool's output.
    assert "risk" not in out
    assert "consistency" not in out.lower()
    for row in rows_of(out):
        assert row["category"] in FIXED_CATEGORIES
        assert row["severity"] in FIXED_SEVERITIES
        assert row["confidence"] in FIXED_CONFIDENCES


# --- path, file-type, and error behavior (contract section 2.0) -------------


def test_path_and_error_table(write_file) -> None:
    write_file("src/ok.tsx", "const s = 1;\n")
    write_file("src/notes.md", "# docs\n")
    write_file("src/script.py", "x = 1\n")
    write_file("src/style.css", ".a { color: red; }\n")
    write_file("src/data.json", "{}\n")
    write_file("node_modules/pkg.js", "const z = 1;\n")

    with pytest.raises(FileNotFoundError):
        ui_contract_audit(path="no/such/dir")
    with pytest.raises(ValueError, match="escapes"):
        ui_contract_audit(path="../outside")
    with pytest.raises(ValueError, match="ignored directory"):
        ui_contract_audit(path="node_modules")
    with pytest.raises(ValueError, match="ignored directory"):
        ui_contract_audit(path="node_modules/pkg.js")
    for relative in ("src/notes.md", "src/script.py", "src/style.css", "src/data.json"):
        with pytest.raises(ValueError, match="Unsupported file type"):
            ui_contract_audit(path=relative)


def test_empty_path_and_single_file_inputs(write_file) -> None:
    write_file(
        "src/a.tsx",
        "export function P({ a, b }) { return null; }\nconst p1 = <P a={1} />;\n",
    )

    root_scan = ui_contract_audit(path="")
    assert summary_of(root_scan)["PATH"] == "."

    single = write_file(
        "src/one.tsx",
        "export function Solo({ a }) { return null; }\nconst s1 = <Solo />;\n",
    )
    out = ui_contract_audit(path=single)
    assert signatures(out) == [
        ("src/one.tsx", 1, "Solo", "signature_drift", "warning", "high"),
        ("src/one.tsx", 2, "Solo", "missing_prop", "critical", "high"),
    ]


def test_zero_rows_mean_no_match_not_rejection(write_file) -> None:
    write_file("src/only.md", "# not code\n")
    write_file("src/plain.tsx", "const x = 1;\n")

    out = ui_contract_audit(path="src")

    s = summary_of(out)
    assert s["total"] == "0"
    assert s["returned"] == "0"
    assert s["files_affected"] == "0"
    assert s["collection_complete"] == "true"
    assert signatures(out) == []
    assert out.rstrip().endswith("[END]")


def test_file_type_boundary_scans_only_code_extensions(write_file) -> None:
    def probe(name: str) -> str:
        return (
            f"export function {name}({{ alpha, beta }}) {{ return null; }}\n"
            f"const q1 = <{name} alpha={{1}} />;\n"
            f"const q2 = <{name} alpha={{2}} />;\n"
        )

    write_file("src/a.js", probe("JsProbe"))
    write_file("src/b.jsx", probe("JsxProbe"))
    write_file("src/c.ts", probe("TsProbe"))
    write_file("src/d.tsx", probe("TsxProbe"))
    # Out-of-boundary extensions must not be scanned at all (DEC-019), even
    # when they contain code-shaped content.
    write_file("src/skip.md", probe("MdProbe"))
    write_file("src/skip.markdown", probe("MarkdownProbe"))
    write_file("src/skip.py", probe("PyProbe"))
    write_file("src/skip.css", probe("CssProbe"))
    write_file("src/skip.json", probe("JsonProbe"))

    out = ui_contract_audit(path="src")

    assert summary_of(out)["files_affected"] == "4"
    assert summary_of(out)["total"] == "12"
    assert {row["rel"] for row in rows_of(out)} == {
        "src/a.js",
        "src/b.jsx",
        "src/c.ts",
        "src/d.tsx",
    }
    assert {row["name"] for row in rows_of(out)} == {
        "JsProbe",
        "JsxProbe",
        "TsProbe",
        "TsxProbe",
    }


def test_oversized_single_file_rejected(write_file) -> None:
    big = write_file("src/big.tsx", "y" * (MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="byte safety limit"):
        ui_contract_audit(path=big)


def test_negative_offset_rejected_and_max_results_clamped(write_file) -> None:
    write_fixture(write_file)

    with pytest.raises(ValueError, match="offset"):
        ui_contract_audit(path="src", offset=-1)

    clamped_low = ui_contract_audit(path="src", max_results=0)
    assert summary_of(clamped_low)["max_results"] == "1"
    assert summary_of(clamped_low)["returned"] == "1"

    clamped_high = ui_contract_audit(path="src", max_results=9999)
    assert summary_of(clamped_high)["max_results"] == "500"


def test_no_repository_mutation(write_file, repo) -> None:
    write_fixture(write_file)

    def snapshot() -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for base, _dirs, files in os.walk(repo):
            for name in files:
                full = os.path.join(base, name)
                stat = os.stat(full)
                snap[os.path.relpath(full, repo)] = (stat.st_size, stat.st_mtime_ns)
        return snap

    before = snapshot()
    ui_contract_audit(path="src")
    ui_contract_audit(path="src", max_results=500)
    ui_contract_audit(path="src", include_callers=False)
    assert snapshot() == before


# --- registration and discoverability (DEC-020) ------------------------------


def test_registered_with_description_and_schema_defaults() -> None:
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "mcquest_ui_contract_audit")
    desc = tool.description or ""

    assert desc.startswith("READ ONLY.")
    assert ".js/.jsx/.ts/.tsx" in desc
    assert (
        "missing_prop/stale_prop/mismatched_usage/signature_drift/unverifiable" in desc
    )
    assert "DEC-022" in desc and "DEC-023" in desc and "DEC-031" in desc
    assert "risk is never emitted" in desc
    assert "collection_complete=true means the authoritative total is known" in desc
    assert "does NOT mean every result was delivered" in desc

    properties = tool.input_schema["properties"]
    for param in (
        "path",
        "component_pattern",
        "include_callers",
        "max_results",
        "offset",
    ):
        description = properties[param].get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{param} missing a non-empty description"
        )
    assert properties["path"]["default"] == "."
    assert properties["component_pattern"]["default"] == "*"
    assert properties["include_callers"]["default"] is True
    assert properties["max_results"]["default"] == 50
    assert properties["offset"]["default"] == 0
    assert tool.input_schema.get("required", []) == []


def test_server_instructions_mention_the_tool() -> None:
    assert mcp.instructions is not None
    assert "mcquest_ui_contract_audit" in mcp.instructions






