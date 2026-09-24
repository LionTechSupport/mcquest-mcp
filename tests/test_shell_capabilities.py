"""P2 capability-registry tests (contract §19; architecture §7.7; decisions A12, S5).

The headline guarantees under test: ``EXPECTED_TOOLS`` (the pinned
registration list) remains the single authority, the registry adds intent
metadata only, drift is impossible in either direction, PLANNED rows are never
presented as registered or executable, and ordering/rendering is deterministic.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from mcquest_mcp.server import mcp
from mcquest_mcp.shell import capabilities as registry

from test_registration import EXPECTED_TOOLS


P2_TOOLS = (
    "mcquest_shell_capabilities",
    "mcquest_shell_context",
    "mcquest_shell_environment",
    "mcquest_shell_terminal",
)

PLANNED_TOOLS = (
    "mcquest_shell_history",
    "mcquest_shell_next",
    "mcquest_shell_observe",
    "mcquest_shell_plan",
    "mcquest_shell_prepare",
    "mcquest_shell_validate",
)


def _live_tool_names() -> list[str]:
    return sorted(tool.name for tool in asyncio.run(mcp.list_tools()))


def test_registry_names_equal_expected_tools_both_directions() -> None:
    # A12 drift test 1: an orphan registry row and an unregistered tool both fail.
    names = registry.capability_names()
    assert names == tuple(EXPECTED_TOOLS)
    assert set(names) == set(EXPECTED_TOOLS)


def test_registry_equals_live_server_listing() -> None:
    # A12 drift test 2: registry == the tools actually exposed by the server.
    assert sorted(registry.capability_names()) == _live_tool_names()


def test_registry_totals_match_the_phase_plan() -> None:
    implemented, planned = registry.capability_totals()
    assert (implemented, planned) == (28, 6)
    assert len(registry.CAPABILITIES) == 28
    assert len(registry.PLANNED_CAPABILITIES) == 6


def test_registry_order_is_deterministic_and_sorted() -> None:
    # A12 drift test 3: deterministic order.
    names = registry.capability_names()
    assert names == tuple(sorted(names))
    assert names == registry.capability_names()  # repeated call is stable


def test_families_distinguish_v08_and_v09_capabilities() -> None:
    repo_rows = [
        row
        for row in registry.CAPABILITIES
        if row.family is registry.CapabilityFamily.REPOSITORY_INTELLIGENCE
    ]
    shell_rows = [
        row
        for row in registry.CAPABILITIES
        if row.family is registry.CapabilityFamily.SHELL_INTELLIGENCE
    ]
    assert len(repo_rows) == 24
    assert len(shell_rows) == 4
    assert set(row.name for row in shell_rows) == set(P2_TOOLS)


def test_the_four_p2_tools_are_implemented_shell_capabilities() -> None:
    by_name = {row.name: row for row in registry.CAPABILITIES}
    for name in P2_TOOLS:
        row = by_name[name]
        assert row.status is registry.CapabilityStatus.IMPLEMENTED
        assert row.phase == "P2"
        assert row.read_only is True
        assert row.purpose.strip()
        assert row.execution in registry.EXECUTION_VOCABULARY
    # Only the probe-running tools report probe execution (A3 allowlist only).
    assert by_name["mcquest_shell_environment"].execution == (
        registry.EXECUTION_FIXED_ARGV_PROBES
    )
    assert by_name["mcquest_shell_context"].execution == (
        registry.EXECUTION_FIXED_ARGV_PROBES
    )
    assert by_name["mcquest_shell_terminal"].execution == registry.EXECUTION_NONE
    assert by_name["mcquest_shell_capabilities"].execution == registry.EXECUTION_NONE


def test_capability_rows_never_carry_confidence_or_ttl() -> None:
    fields = {field.name for field in dataclasses.fields(registry.Capability)}
    assert "confidence" not in fields
    assert "ttl" not in fields
    assert "risk" not in fields
    assert fields == {
        "name",
        "purpose",
        "family",
        "phase",
        "status",
        "read_only",
        "execution",
        "scope",
        "intent_tags",
        "prerequisites",
        "mutation_cost",
    }


def test_every_intent_tag_comes_from_the_frozen_vocabulary() -> None:
    for row in registry.CAPABILITIES + registry.PLANNED_CAPABILITIES:
        assert row.intent_tags, row.name
        for tag in row.intent_tags:
            assert tag in registry.INTENT_TAG_VOCABULARY, (row.name, tag)


def test_vocabulary_exposes_operation_and_capability_classes() -> None:
    assert "SEARCH_REGEX" in registry.INTENT_TAG_VOCABULARY  # contract §13 taxonomy
    assert "CAPABILITY_READ" in registry.INTENT_TAG_VOCABULARY
    assert registry.INTENT_TAG_VOCABULARY == frozenset(
        registry.OPERATION_CLASSES + registry.CAPABILITY_CLASSES
    )


def test_row_field_discipline() -> None:
    for row in registry.CAPABILITIES + registry.PLANNED_CAPABILITIES:
        assert row.scope in registry.SCOPE_VOCABULARY, row.name
        assert row.execution in registry.EXECUTION_VOCABULARY, row.name
        assert row.read_only is True, row.name
        assert row.purpose.strip(), row.name
        assert row.mutation_cost is None, row.name  # read-only: no mutation cost
        assert isinstance(row.prerequisites, tuple)


def test_planned_capabilities_are_never_registered_or_advertised() -> None:
    planned = set(registry.planned_capability_names())
    assert planned == set(PLANNED_TOOLS)
    assert planned.isdisjoint(set(EXPECTED_TOOLS))  # never in the pinned authority
    assert planned.isdisjoint(set(_live_tool_names()))  # never exposed by the server
    assert planned.isdisjoint(set(registry.capability_names()))  # never "implemented"


def test_planned_rows_are_marked_planned_with_their_phase() -> None:
    by_name = {row.name: row for row in registry.PLANNED_CAPABILITIES}
    assert by_name["mcquest_shell_validate"].phase == "P4"
    assert by_name["mcquest_shell_observe"].phase == "P4"
    for name in PLANNED_TOOLS:
        assert by_name[name].status is registry.CapabilityStatus.PLANNED
        assert by_name[name].read_only is True
        assert by_name[name].mutation_cost is None


def test_paging_is_deterministic_and_bounded() -> None:
    first = registry.capability_page()
    second = registry.capability_page()
    assert first == second
    assert (first.total, first.returned, first.offset) == (34, 10, 0)
    assert first.has_more is True
    assert first.next_offset == 10


def test_paging_reaches_every_row_exactly_once() -> None:
    seen: list[str] = []
    offset = 0
    while True:
        page = registry.capability_page(offset=offset)
        seen.extend(
            line.split(" | ")[0][2:]
            for _heading, lines in page.sections
            for line in lines
            if line.startswith("- ")
        )
        if not page.has_more:
            break
        offset = page.next_offset
    expected = [
        row.name
        for row in registry.CAPABILITIES
        if row.family is registry.CapabilityFamily.REPOSITORY_INTELLIGENCE
    ] + [
        row.name
        for row in registry.CAPABILITIES
        if row.family is registry.CapabilityFamily.SHELL_INTELLIGENCE
    ] + [row.name for row in registry.PLANNED_CAPABILITIES]
    assert seen == expected
    assert len(set(seen)) == 34


def test_paging_rejects_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        registry.capability_page(offset=-1)
    with pytest.raises(ValueError):
        registry.capability_page(max_results=0)
    with pytest.raises(ValueError):
        registry.capability_page(max_results=registry.CAPABILITY_MAX_RESULTS + 1)
    with pytest.raises(ValueError):
        registry.capability_page(offset=True)  # bool is not a valid offset


def test_rendered_sections_label_implemented_and_planned_distinctly() -> None:
    page = registry.capability_page(offset=0, max_results=registry.CAPABILITY_MAX_RESULTS)
    headings = [heading for heading, _lines in page.sections]
    assert headings and all("IMPLEMENTED" in heading for heading in headings)
    for _heading, lines in page.sections:
        for line in lines:
            if line.startswith("- "):
                assert "status=IMPLEMENTED" in line
                assert "status=PLANNED" not in line

    planned_page = registry.capability_page(offset=28, max_results=10)
    headings = [heading for heading, _lines in planned_page.sections]
    assert headings and all("PLANNED" in heading for heading in headings)
    assert "NOT EXECUTABLE" in headings[0]
    for _heading, lines in planned_page.sections:
        for line in lines:
            if line.startswith("- "):
                assert "status=PLANNED" in line
                assert "status=IMPLEMENTED" not in line


def test_registry_rows_do_not_duplicate_registration_authority() -> None:
    """The registry must never become a second hand-maintained surface."""
    assert not hasattr(registry, "EXPECTED_TOOLS")
    assert registry.capability_names() == tuple(EXPECTED_TOOLS)
