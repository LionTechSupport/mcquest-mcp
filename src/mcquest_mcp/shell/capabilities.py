"""Capability registry with intent metadata (contract §19; architecture §7.7).

Decisions A12 and S5 govern this module: ``EXPECTED_TOOLS`` (the pinned list in
``tests/test_registration.py``) remains the SINGLE authority for which MCP
tools exist. This registry adds intent metadata only — it never registers a
tool, never replaces the registration test, and is protected by the three A12
drift tests:

1. exact set equality, both directions, between ``CAPABILITIES`` and
   ``EXPECTED_TOOLS`` (an orphan row and an unregistered tool both fail);
2. live-server equality — ``CAPABILITIES`` == the tools actually exposed by
   ``mcp.list_tools()``;
3. field/tag discipline — every intent tag comes from the frozen
   ``INTENT_TAG_VOCABULARY`` (the contract §13 operation taxonomy plus the
   capability classes), every purpose is non-empty, execution lies in a frozen
   vocabulary, and registry order is deterministic (sorted by name).

Rows are split by family so V0.8 repository intelligence and V0.9 shell
intelligence stay distinguishable, and ``PLANNED_CAPABILITIES`` keeps future
P4/P5 tools visible WITHOUT ever presenting them as implemented, registered,
or executable. No numeric confidence exists anywhere (contract §7 rule 4);
``mutation_cost=None`` records that no state-changing operation is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .facts import CostClass


class CapabilityStatus(str, Enum):
    """IMPLEMENTED = registered today; PLANNED = never advertised as existing."""

    IMPLEMENTED = "IMPLEMENTED"
    PLANNED = "PLANNED"

    def __str__(self) -> str:
        return str(self.value)


class CapabilityFamily(str, Enum):
    """V0.8 repository intelligence vs V0.9 shell intelligence (A12 rows)."""

    REPOSITORY_INTELLIGENCE = "V0.8_REPOSITORY_INTELLIGENCE"
    SHELL_INTELLIGENCE = "V0.9_SHELL_INTELLIGENCE"

    def __str__(self) -> str:
        return str(self.value)


# Frozen execution vocabulary: whether running the capability ever spawns an
# approved fixed-argv observation probe. Nothing else may appear.
EXECUTION_NONE = "none"
EXECUTION_FIXED_ARGV_PROBES = "approved_fixed_argv_probes"
EXECUTION_VOCABULARY = frozenset({EXECUTION_NONE, EXECUTION_FIXED_ARGV_PROBES})

# Frozen scope vocabulary for capability rows.
SCOPE_VOCABULARY = frozenset(
    {"repository", "environment", "terminal", "context", "capability", "command"}
)

# Frozen operation taxonomy (contract §13) — the operation classes.
OPERATION_CLASSES: tuple[str, ...] = (
    "READ_FILE",
    "READ_JSON",
    "READ_SQLITE",
    "SEARCH_LITERAL",
    "SEARCH_REGEX",
    "ENUMERATE_FILES",
    "CHECK_PATH",
    "CHECK_GIT_STATE",
    "CHECK_CONFIG",
    "MEASURE_EOL",
    "RUN_NODE",
    "RUN_PYTHON",
    "RUN_TEST",
    "BUILD",
    "INSTALL",
    "EDIT",
)

# Frozen capability classes (routing intent tags; A12 tag vocabulary).
CAPABILITY_CLASSES: tuple[str, ...] = (
    "PROJECT_OVERVIEW",
    "FILE_DISCOVERY",
    "FILE_READ",
    "SOURCE_SEARCH",
    "DOC_SEARCH",
    "EVIDENCE_SEARCH",
    "REFERENCE_READ",
    "STRING_INVENTORY",
    "LOCALE_READ",
    "SQLITE_READ",
    "COMPONENT_INVENTORY",
    "PATTERN_AUDIT",
    "DIAGNOSTICS",
    "PHASE_READ",
    "GIT_READ",
    "UI_TEXT_READ",
    "UI_CONTRACT_READ",
    "DOC_GAP_READ",
    "CHANGE_IMPACT_READ",
    "ENVIRONMENT_READ",
    "TERMINAL_READ",
    "CONTEXT_READ",
    "CAPABILITY_READ",
    "COMMAND_VALIDATE",
    "OBSERVATION_INGEST",
    "COMMAND_PLAN",
    "COMMAND_PREPARE",
    "HISTORY_READ",
    "NEXT_ACTION",
)

INTENT_TAG_VOCABULARY = frozenset(OPERATION_CLASSES + CAPABILITY_CLASSES)


@dataclass(frozen=True)
class Capability:
    """One registry row: intent metadata ONLY (A12); never a registration."""

    name: str
    purpose: str
    family: CapabilityFamily
    phase: str
    status: CapabilityStatus
    read_only: bool
    execution: str
    scope: str
    intent_tags: tuple[str, ...]
    prerequisites: tuple[str, ...]
    mutation_cost: CostClass | None


def _row(
    name: str,
    purpose: str,
    *,
    family: CapabilityFamily,
    phase: str,
    status: CapabilityStatus,
    execution: str,
    scope: str,
    intent_tags: tuple[str, ...],
    prerequisites: tuple[str, ...] = (),
) -> Capability:
    return Capability(
        name=name,
        purpose=purpose,
        family=family,
        phase=phase,
        status=status,
        read_only=True,
        execution=execution,
        scope=scope,
        intent_tags=intent_tags,
        prerequisites=prerequisites,
        mutation_cost=None,
    )


_REPO = CapabilityFamily.REPOSITORY_INTELLIGENCE
_SHELL = CapabilityFamily.SHELL_INTELLIGENCE
_IMPL = CapabilityStatus.IMPLEMENTED
_PLAN = CapabilityStatus.PLANNED
_NP = EXECUTION_NONE
_FP = EXECUTION_FIXED_ARGV_PROBES
_ROOT_REQUIRED = ("project root configured via --project / MCQUEST_PROJECT_ROOT",)

# --- V0.8 repository-intelligence capabilities (24 registered tools) --------

_CAPABILITIES_V08: tuple[Capability, ...] = (
    _row(
        "mcquest_compare_phase",
        "Compare documentation sets between two phases (evidence-neutral)",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("PHASE_READ",),
    ),
    _row(
        "mcquest_component_inventory",
        "Inventory lexical React component candidates in JS/TS sources",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("COMPONENT_INVENTORY",),
    ),
    _row(
        "mcquest_diagnostics",
        "TypeScript/TSX/JS/JSX parser diagnostics with bounded context",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_FP,
        scope="repository", intent_tags=("DIAGNOSTICS",),
    ),
    _row(
        "mcquest_doc_gap_audit",
        "Lexical documentation-gap audit for stale references",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("DOC_GAP_READ",),
    ),
    _row(
        "mcquest_feature_impact_audit",
        "Lexical change-impact evidence for a target across code/docs/locales",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("CHANGE_IMPACT_READ",),
    ),
    _row(
        "mcquest_find_evidence",
        "Cross-search code, documentation, and phase evidence in one call",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("EVIDENCE_SEARCH",),
    ),
    _row(
        "mcquest_find_files",
        "Locate project files by case-insensitive filename substring",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("FILE_DISCOVERY",),
    ),
    _row(
        "mcquest_find_imports",
        "Find ES module imports that reference a target module/component",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("REFERENCE_READ",),
    ),
    _row(
        "mcquest_find_strings",
        "Enumerate quoted string literals in JS/TS/JSX/TSX sources",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("STRING_INVENTORY",),
    ),
    _row(
        "mcquest_find_ui_text",
        "Inventory quoted literals as lexical UI-text candidates",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("UI_TEXT_READ",),
    ),
    _row(
        "mcquest_find_usages",
        "Find word-boundary identifier usages (lexical matches only)",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("REFERENCE_READ",),
    ),
    _row(
        "mcquest_git_context",
        "Read-only Git branch/status/commits/changes overview",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_FP,
        scope="repository", intent_tags=("GIT_READ", "CHECK_GIT_STATE"),
    ),

    _row(
        "mcquest_list_docs",
        "List Markdown documentation files, paged and glob-filtered",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("FILE_DISCOVERY", "DOC_SEARCH"),
    ),
    _row(
        "mcquest_list_files",
        "Recursively list project files with glob pattern filtering",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("FILE_DISCOVERY", "ENUMERATE_FILES"),
    ),
    _row(
        "mcquest_locale_inspect",
        "Inspect JSON locale files for structure, duplicates, and key diffs",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("LOCALE_READ", "READ_JSON"),
    ),
    _row(
        "mcquest_pattern_audit",
        "Audit responsive/layout CSS patterns as bounded evidence",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("PATTERN_AUDIT",),
    ),
    _row(
        "mcquest_phase_context",
        "Locate phase/stage documentation by free-text query or phase id",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("PHASE_READ",),
    ),
    _row(
        "mcquest_project_context",
        "Compact high-level understanding of the selected project",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("PROJECT_OVERVIEW",),
    ),
    _row(
        "mcquest_project_info",
        "Compact overview of the selected project structure",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("PROJECT_OVERVIEW",),
    ),
    _row(
        "mcquest_read_doc",
        "Read bounded Markdown documentation windows with line numbers",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("FILE_READ", "DOC_SEARCH"),
    ),
    _row(
        "mcquest_read_file",
        "Read bounded source-file windows with exact line numbers",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("FILE_READ",),
    ),
    _row(
        "mcquest_search",
        "Regex search over source files, paged with context snippets",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("SOURCE_SEARCH", "SEARCH_REGEX"),
    ),
    _row(
        "mcquest_search_docs",
        "Regex/text search across Markdown documentation (preferred)",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("DOC_SEARCH", "SEARCH_REGEX"),
    ),
    _row(
        "mcquest_ui_contract_audit",
        "Lexical component prop-contract audit for drift detection",
        family=_REPO, phase="V0.8", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("UI_CONTRACT_READ",),
    ),
    _row(
        "mcquest_sqlite_read",
        "Read structured rows from a project-local SQLite database (read-only SELECT)",
        family=_REPO, phase="V1.1", status=_IMPL, execution=_NP,
        scope="repository", intent_tags=("SQLITE_READ", "READ_SQLITE"),
        prerequisites=_ROOT_REQUIRED,
    ),
)

# --- V0.9 shell-intelligence capabilities registered by P2 ------------------

_CAPABILITIES_V09: tuple[Capability, ...] = (
    _row(
        "mcquest_shell_capabilities",
        "Expose the capability registry with intent metadata (A12)",
        family=_SHELL, phase="P2", status=_IMPL, execution=_NP,
        scope="capability", intent_tags=("CAPABILITY_READ",),
    ),
    _row(
        "mcquest_shell_context",
        "Compact shell-intelligence context: repository, worktree, server, "
        "client terminal, environment, unknowns",
        family=_SHELL, phase="P2", status=_IMPL, execution=_FP,
        scope="context", intent_tags=("CONTEXT_READ",),
        prerequisites=_ROOT_REQUIRED,
    ),
    _row(
        "mcquest_shell_environment",
        "Environment Contract with source/trust labels via approved probes",
        family=_SHELL, phase="P2", status=_IMPL, execution=_FP,
        scope="environment", intent_tags=("ENVIRONMENT_READ", "CHECK_CONFIG"),
        prerequisites=_ROOT_REQUIRED,
    ),
    _row(
        "mcquest_shell_observe",
        "Record declared observations/evidence and invalidate affected scopes",
        family=_SHELL, phase="P4", status=_IMPL, execution=_NP,
        scope="context", intent_tags=("OBSERVATION_INGEST",),
    ),
    _row(
        "mcquest_shell_terminal",
        "Terminal/session/process identity: server (mcp_server) vs client, "
        "unknown when undeclared",
        family=_SHELL, phase="P2", status=_IMPL, execution=_NP,
        scope="terminal", intent_tags=("TERMINAL_READ",),
    ),
    _row(
        "mcquest_shell_validate",
        "Full deterministic command validation report (incl. lint mode)",
        family=_SHELL, phase="P4", status=_IMPL, execution=_NP,
        scope="command", intent_tags=("COMMAND_VALIDATE",),
    ),
    # --- P5 (decision A11, phase 3 of 3): planner, preparation, history, next ---
    _row(
        "mcquest_shell_plan",
        "Classify intent, build a bounded plan, route to existing capabilities",
        family=_SHELL, phase="P5", status=_IMPL, execution=_NP,
        scope="command", intent_tags=("COMMAND_PLAN",),
    ),
    _row(
        "mcquest_shell_prepare",
        "Emit prepared command text, always labeled not executed",
        family=_SHELL, phase="P5", status=_IMPL, execution=_NP,
        scope="command", intent_tags=("COMMAND_PREPARE",),
    ),
    _row(
        "mcquest_shell_history",
        "Page command/observation history with n0-n3 duplicate context",
        family=_SHELL, phase="P5", status=_IMPL, execution=_NP,
        scope="command", intent_tags=("HISTORY_READ",),
    ),
    _row(
        "mcquest_shell_next",
        "Differentiated next action after a failure (never a blind retry)",
        family=_SHELL, phase="P5", status=_IMPL, execution=_NP,
        scope="command", intent_tags=("NEXT_ACTION",),
    ),
)

# --- PLANNED capabilities (P6+) — NOT registered, NOT implemented -------------
# P4 and P5 both moved their rows into IMPLEMENTED at their own phase gate, so
# the approved ten-tool surface is now fully registered and this tuple is empty.
# It is retained deliberately: the invariant "PLANNED is disjoint from LIVE and
# never advertised as implemented" (A12) must remain testable, and a future
# phase must add its rows here rather than inventing a second registry.
PLANNED_CAPABILITIES: tuple[Capability, ...] = ()

# The implemented registry: 24 V0.8 + 4 V0.9 (P2), sorted by name so order is
# deterministic and matches the EXPECTED_TOOLS ordering (A12 test 3).
CAPABILITIES: tuple[Capability, ...] = tuple(
    sorted(_CAPABILITIES_V08 + _CAPABILITIES_V09, key=lambda row: row.name)
)


def capability_names() -> tuple[str, ...]:
    """Names of IMPLEMENTED capabilities, sorted — compared with EXPECTED_TOOLS."""
    return tuple(row.name for row in CAPABILITIES)


def planned_capability_names() -> tuple[str, ...]:
    """Names of PLANNED capabilities — must never appear in any registration."""
    return tuple(row.name for row in PLANNED_CAPABILITIES)


def capability_totals() -> tuple[int, int]:
    """(implemented, planned) row counts."""
    return (len(CAPABILITIES), len(PLANNED_CAPABILITIES))


# --- deterministic paging/rendering (consumed by tools/shell_env.py) --------

CAPABILITY_MAX_RESULTS = 10  # hard cap: 3-line rows fit the 4000 default budget
CAPABILITY_ROW_LINES = 3


@dataclass(frozen=True)
class CapabilityPage:
    """One deterministic page of registry rows plus paging metadata."""

    sections: tuple[tuple[str, tuple[str, ...]], ...]
    total: int
    returned: int
    offset: int
    has_more: bool
    next_offset: int | None


def _capability_lines(row: Capability) -> tuple[str, str, str]:
    prereq = "; ".join(row.prerequisites) if row.prerequisites else "none"
    intent = ", ".join(row.intent_tags)
    line_one = (
        f"- {row.name} | status={row.status.value} phase={row.phase} "
        f"family={row.family.value} ro={'true' if row.read_only else 'false'} "
        f"execution={row.execution}"
    )
    line_two = f"  purpose: {row.purpose}"
    line_three = (
        f"  scope={row.scope} intent=[{intent}] "
        f"mutation={'none' if row.mutation_cost is None else row.mutation_cost.value} "
        f"prereq={prereq}"
    )
    return line_one, line_two, line_three


def _heading(group: str) -> str:
    if group == "v08":
        total = sum(1 for row in CAPABILITIES if row.family is _REPO)
        return f"IMPLEMENTED - V0.8 REPOSITORY INTELLIGENCE ({total} registered; read-only)"
    if group == "v09":
        total = sum(1 for row in CAPABILITIES if row.family is _SHELL)
        return f"IMPLEMENTED - V0.9 SHELL INTELLIGENCE (P2+P4+P5: {total} registered; read-only)"
    return (
        "PLANNED - NOT REGISTERED / NOT IMPLEMENTED / NOT EXECUTABLE "
        f"({len(PLANNED_CAPABILITIES)})"
    )


def capability_page(
    offset: int = 0, max_results: int = CAPABILITY_MAX_RESULTS
) -> CapabilityPage:
    """Deterministic paged view over implemented rows then planned rows.

    Implemented rows always precede planned rows; planned rows keep their
    ``PLANNED`` status and dedicated heading so they can never read as
    registered. ``total`` counts the whole registry (implemented + planned).
    """
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be an int >= 0")
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or max_results < 1
        or max_results > CAPABILITY_MAX_RESULTS
    ):
        raise ValueError(
            f"max_results must be an int between 1 and {CAPABILITY_MAX_RESULTS}"
        )

    ordered: list[tuple[str, Capability]] = []
    ordered.extend(("v08", row) for row in CAPABILITIES if row.family is _REPO)
    ordered.extend(("v09", row) for row in CAPABILITIES if row.family is _SHELL)
    ordered.extend(("plan", row) for row in PLANNED_CAPABILITIES)
    total = len(ordered)

    page = ordered[offset : offset + max_results]
    sections: list[tuple[str, tuple[str, ...]]] = []
    current_group: str | None = None
    buffer: list[str] = []
    for group, row in page:
        if group != current_group:
            if current_group is not None:
                sections.append((_heading(current_group), tuple(buffer)))
            current_group = group
            buffer = []
        buffer.extend(_capability_lines(row))
    if current_group is not None:
        sections.append((_heading(current_group), tuple(buffer)))

    returned = len(page)
    next_offset = offset + returned if offset + returned < total else None
    return CapabilityPage(
        sections=tuple(sections),
        total=total,
        returned=returned,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
    )
