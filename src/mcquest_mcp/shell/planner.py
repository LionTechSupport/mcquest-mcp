"""Planning / preparation / history / next-step orchestration (P5).

Contract §13 (semantic operations + preference ladder), §14 (recommend-only),
§19 (capability routing), §20 (redundancy), §22 (differentiated next action),
and decisions A5 (no wall-clock TTL), A12 (registry is metadata only), A13
(recommend, never enforce), A14 (single state model).

This module **consumes** the approved foundations; it never rebuilds them:

- evidence state comes from the P1 ``ObservationStore`` and its single
  ``reuse_check`` decision, so "stale" and "invalidated" mean exactly what
  contract §12 means and no second fact/observation/store model exists;
- identity binding, scope, freshness, source and trust are the P1 enums;
- the operation vocabulary is the frozen contract §13 ``Operation`` enum from
  ``operations.py`` — no new class, no new operation category, and never a
  ``DELETE``/``EXECUTE``/``COMMAND``/``SHELL`` member;
- routing reads the P2 ``capabilities`` registry, whose registration authority
  remains ``EXPECTED_TOOLS`` (A12); a routed name is a recommendation, never an
  invocation (contract §19 rule 4);
- blind-retry prevention reuses the P3 ``redundancy`` n0-n3 ladder.

Deliberately absent — these are approved decisions, not omissions:

- **no execution path**: no subprocess, no process spawn, no shell. A plan is a
  recommendation; Cline remains the execution authority (contract §14 rule 4).
  ``execution_permitted`` is a constant ``False`` on every result;
- no mutation, no autonomous repair, no enforcement or denial;
- no numeric confidence and no numeric risk (contract §7 rule 4);
- no wall-clock TTL (A5): ``observed_at`` is never read or rendered, so output
  is byte-identical across runs and ``time``/``datetime`` are never imported;
- no fabricated facts: anything not established stays UNKNOWN (contract §18
  rule 4) and is reported as an explicit required observation instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import capabilities as registry
from .facts import (
    BINDING_PROCESS_SCOPES,
    BINDING_SESSION_SCOPES,
    Fact,
    Freshness,
    Scope,
    Source,
    Trust,
)
from .operations import Operation, classify_operation, is_mutation_bearing
from .redundancy import ChangeReason, analyze_redundancy
from .store import ObservationStore

# Bounds. P5 never grows an input into a scan: every entry point is bounded and
# every rendered list is capped here, so no plan can become unbounded work.
MAX_INPUT_CHARS = 16_384
MAX_REQUIRED_EVIDENCE = 12
MAX_PLAN_STEPS = 8
MAX_HISTORY_ROWS = 50
MAX_HISTORY_LIMIT = 50

# Contract §14. V0.9 analyses, observes, plans, validates and recommends. It
# never executes, and a plan is never execution authorization.
EXECUTION_NOT_PERMITTED = (
    "read-only and recommend-only (§14): nothing is executed here, a plan is not "
    "authorization, and Cline remains the execution authority"
)
VALIDATION_REQUIRED = (
    "Any command text must be validated with mcquest_shell_validate before the "
    "client executes it; validation is analysis, not authorization."
)
NO_BLIND_RETRY = (
    "A repeat is justified only when something relevant changed (contract §22); "
    "otherwise the next action must differ from the previous one."
)
METHOD_HISTORY = (
    "history is read from the single in-memory ObservationStore/CommandHistory; "
    "nothing is persisted, and a server restart yields unknown (decision A4/S3)"
)


class EvidenceState(str, Enum):
    """Why an observation may or may not be reused. Not a confidence scale."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"
    INSUFFICIENT = "INSUFFICIENT"

    def __str__(self) -> str:
        return str(self.value)


class PlanLadder(str, Enum):
    """The contract §13 preference ladder, in its frozen order."""

    EXISTING_EVIDENCE = "existing evidence"
    EXISTING_CAPABILITY = "existing MCQuest capability"
    STRUCTURED_TOOL = "structured tool operation"
    TARGETED_SHELL = "targeted shell operation"
    BROAD_SCAN = "broader scan"

    def __str__(self) -> str:
        return str(self.value)


LADDER_ORDER: tuple[PlanLadder, ...] = (
    PlanLadder.EXISTING_EVIDENCE,
    PlanLadder.EXISTING_CAPABILITY,
    PlanLadder.STRUCTURED_TOOL,
    PlanLadder.TARGETED_SHELL,
    PlanLadder.BROAD_SCAN,
)


class PlanStatus(str, Enum):
    """Whether a bounded recommendation could be produced at all."""

    READY = "READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    # Used by history_view when the store holds no records at all: unavailable
    # history is reported explicitly, never filled in (decision A4/S3).
    INSUFFICIENT = "INSUFFICIENT"
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:
        return str(self.value)


class PrepareStatus(str, Enum):
    """Preparation outcome; a guess is never presented as a preparation."""

    PREPARED = "PREPARED"
    INSUFFICIENT_PREREQUISITES = "INSUFFICIENT_PREREQUISITES"
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:
        return str(self.value)


class NextAction(str, Enum):
    """The next useful step. Never a loop, never an execution."""

    OBSERVE = "OBSERVE"
    ROUTE = "ROUTE"
    VALIDATE = "VALIDATE"
    DIFFERENTIATE = "DIFFERENTIATE"
    STOP = "STOP"

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True)
class EvidenceItem:
    """One consulted observation and the single P1 reuse decision behind it."""

    observation: str
    scope: Scope
    state: EvidenceState
    source: Source
    trust: Trust
    freshness: Freshness
    detail: str


@dataclass(frozen=True)
class EvidenceRequirement:
    """One observation the operation needs, and who establishes it."""

    observation: str
    scope: Scope
    capability: str
    reason: str


@dataclass(frozen=True)
class PlanStep:
    """One bounded step on the contract §13 ladder."""

    order: int
    ladder: PlanLadder
    action: str
    operation: Operation
    capability: str | None
    rationale: str
    evidence_basis: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    """A recommendation, never an authorization (contract §14)."""

    intent: str
    operation: Operation
    status: PlanStatus
    evidence: tuple[EvidenceItem, ...]
    required_observations: tuple[EvidenceRequirement, ...]
    steps: tuple[PlanStep, ...]
    blockers: tuple[str, ...]
    validation_context: tuple[str, ...]
    execution_permitted: bool = False


@dataclass(frozen=True)
class Preparation:
    """A bounded, non-executing preparation of a requested task."""

    status: PrepareStatus
    intent: str
    operation: Operation
    plan: Plan
    missing_prerequisites: tuple[EvidenceRequirement, ...]
    prepared_text: str
    validation_context: tuple[str, ...]
    execution_permitted: bool = False


@dataclass(frozen=True)
class HistoryRow:
    """One history record with its established scope/provenance labels."""

    record_id: str
    kind: str
    scope: str
    freshness: str
    source: str
    trust: str
    state: EvidenceState
    binding: str
    detail: str


@dataclass(frozen=True)
class HistoryView:
    """A deterministic page over the existing in-memory store."""

    status: PlanStatus
    rows: tuple[HistoryRow, ...]
    total: int
    returned: int
    offset: int
    has_more: bool
    next_offset: int | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class NextStep:
    """The next useful observation or planning step — not an execution."""

    intent: str
    operation: Operation
    action: NextAction
    step: PlanStep | None
    plan: Plan
    detail: str
    changed_conditions: tuple[str, ...]
    method_line: str
    execution_permitted: bool = False


# --- evidence requirements (contract §13/§6, grounded in real names) ---------
# A frozen, explicit table: for each frozen operation class, the observations a
# plan needs before it can be READY, and the existing capability that
# establishes each one. Names are the P2 ``environment``/``terminal`` identifiers
# so the planner joins the real store rather than inventing fact names. Nothing
# here creates a new operation, scope, or capability.
_REQUIRED_EVIDENCE: dict[Operation, tuple[EvidenceRequirement, ...]] = {
    Operation.CHECK_GIT_STATE: (
        EvidenceRequirement(
            "environment.git_toplevel", Scope.REPOSITORY, "mcquest_shell_environment",
            "git state is only meaningful relative to an established repository root",
        ),
    ),
    Operation.CHECK_CONFIG: (
        EvidenceRequirement(
            "environment.which.git", Scope.SESSION, "mcquest_shell_environment",
            "a git configuration probe is only meaningful when git is on PATH",
        ),
    ),
    Operation.RUN_NODE: (
        EvidenceRequirement(
            "environment.which.node", Scope.SESSION, "mcquest_shell_environment",
            "node availability is a SESSION discovery, not an assumption",
        ),
    ),
    Operation.RUN_PYTHON: (
        EvidenceRequirement(
            "environment.which.node", Scope.SESSION, "mcquest_shell_environment",
            "the runtime probe establishes interpreter presence before planning",
        ),
    ),
    Operation.READ_FILE: (
        EvidenceRequirement(
            "terminal.cwd", Scope.PROCESS, "mcquest_shell_terminal",
            "a relative path is resolved against the client CWD, never the server's",
        ),
    ),
    Operation.READ_JSON: (
        EvidenceRequirement(
            "terminal.cwd", Scope.PROCESS, "mcquest_shell_terminal",
            "a relative path is resolved against the client CWD, never the server's",
        ),
    ),
    Operation.READ_SQLITE: (
        EvidenceRequirement(
            "environment.project_root", Scope.SESSION, "mcquest_shell_environment",
            "sqlite scope must be anchored to a known project root",
        ),
    ),
    Operation.SEARCH_LITERAL: (
        EvidenceRequirement(
            "environment.project_root", Scope.SESSION, "mcquest_shell_environment",
            "search scope must be anchored to a known project root",
        ),
    ),
    Operation.SEARCH_REGEX: (
        EvidenceRequirement(
            "environment.project_root", Scope.SESSION, "mcquest_shell_environment",
            "search scope must be anchored to a known project root",
        ),
    ),
    Operation.ENUMERATE_FILES: (
        EvidenceRequirement(
            "environment.project_root", Scope.SESSION, "mcquest_shell_environment",
            "enumeration scope must be anchored to a known project root",
        ),
    ),
    Operation.CHECK_PATH: (
        EvidenceRequirement(
            "terminal.cwd", Scope.PROCESS, "mcquest_shell_terminal",
            "a relative path is resolved against the client CWD, never the server's",
        ),
    ),
    Operation.MEASURE_EOL: (
        EvidenceRequirement(
            "terminal.cwd", Scope.PROCESS, "mcquest_shell_terminal",
            "a relative path is resolved against the client CWD, never the server's",
        ),
    ),
}

# The shell-intelligence capability that most directly serves each frozen
# operation, used only when the P3 classifier already produced a class. It never
# widens the operation vocabulary and never names a planned/unregistered tool.
_OPERATION_TOOL: dict[Operation, str] = {
    Operation.READ_FILE: "mcquest_read_file",
    Operation.READ_JSON: "mcquest_locale_inspect",
    Operation.READ_SQLITE: "mcquest_sqlite_read",
    Operation.SEARCH_LITERAL: "mcquest_search",
    Operation.SEARCH_REGEX: "mcquest_search",
    Operation.ENUMERATE_FILES: "mcquest_list_files",
    Operation.CHECK_PATH: "mcquest_find_files",
    Operation.CHECK_GIT_STATE: "mcquest_git_context",
    Operation.CHECK_CONFIG: "mcquest_shell_environment",
    Operation.MEASURE_EOL: "mcquest_read_file",
}

# Operations no read-only MCQuest capability serves. For these the planner can
# only recommend a targeted shell operation, and it must say so rather than
# route to a capability that would not answer the intent (contract §19 rule 5).
_SHELL_ONLY_OPERATIONS: frozenset[Operation] = frozenset(
    {
        Operation.RUN_NODE, Operation.RUN_PYTHON, Operation.RUN_TEST,
        Operation.BUILD, Operation.INSTALL, Operation.EDIT,
    }
)


def _bounded(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be str, got {type(value).__name__}")
    if len(value) > MAX_INPUT_CHARS:
        raise ValueError(f"{label} exceeds the maximum of {MAX_INPUT_CHARS} characters")
    return value

    VALIDATE = "VALIDATE"
    DIFFERENTIATE = "DIFFERENTIATE"


# --- evidence assessment (single P1 reuse decision; no second state model) ---

def _binding_label(scope: Scope) -> str:
    """The contract §10 identity-binding label for a scope."""
    if scope in BINDING_PROCESS_SCOPES:
        return "session+process"
    if scope in BINDING_SESSION_SCOPES:
        return "session"
    return "none (repository family)"


def _assess(
    store: ObservationStore,
    requirement: EvidenceRequirement,
    *,
    terminal_session: str | None,
    process_id: str | None,
) -> EvidenceItem:
    """Classify one required observation using the store's own reuse decision.

    The four states map exactly onto contract §12:
    - KNOWN      present, identity matches, revision still current;
    - INVALIDATED present, but an explicit event bumped its revision;
    - STALE      present under this identity but only for a narrower scope than
                  the operation requires, so it cannot be served for this plan;
    - UNKNOWN    nobody established it (contract §18 rule 4 — never guessed).
    """
    fact = store.lookup(
        requirement.observation,
        requirement.scope,
        None,
        terminal_session=terminal_session,
        process_id=process_id,
    )
    if fact is None:
        return EvidenceItem(
            requirement.observation, requirement.scope, EvidenceState.UNKNOWN,
            Source.UNKNOWN, Trust.UNKNOWN, requirement.scope,
            "no observation recorded; UNKNOWN is preserved, never inferred",
        )
    reusable = store.reuse_check(
        fact,
        scope=requirement.scope,
        terminal_session=terminal_session,
        process_id=process_id,
    )
    if reusable:
        return EvidenceItem(
            fact.observation, fact.scope, EvidenceState.KNOWN,
            fact.source, fact.trust, fact.freshness,
            f"reusable at {fact.scope.value}/{fact.freshness.value} "
            f"(revision {fact.revision})",
        )
    current = store.revision_for(fact.scope, fact.subject)
    if fact.revision != current:
        return EvidenceItem(
            fact.observation, fact.scope, EvidenceState.INVALIDATED,
            fact.source, fact.trust, fact.freshness,
            f"an explicit invalidation event bumped the revision "
            f"({fact.revision} -> {current}); re-observation is required",
        )
    return EvidenceItem(
        fact.observation, fact.scope, EvidenceState.STALE,
        fact.source, fact.trust, fact.freshness,
        "recorded, but not reusable for this identity/scope; it is never "
        "promoted across sessions or processes (contract §8)",
    )


def assess_evidence(
    store: ObservationStore,
    operation: Operation,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
) -> tuple[EvidenceItem, ...]:
    """Deterministic, bounded evidence report for one frozen operation class."""
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    if not isinstance(operation, Operation):
        raise TypeError(f"operation must be Operation, got {type(operation).__name__}")
    return tuple(
        _assess(store, requirement, terminal_session=terminal_session, process_id=process_id)
        for requirement in _REQUIRED_EVIDENCE.get(operation, ())[:MAX_REQUIRED_EVIDENCE]
    )


# --- capability routing (contract §19; A12 metadata-only registry) -----------

def route_capability(operation: Operation, *, intent: str = "") -> str | None:
    """Name the existing capability that answers this operation, or ``None``.

    Routing consults the P2 registry only. A returned name is a recommendation
    the client may choose to call — V0.9 never invokes it (contract §19 rule 4),
    and it is never a planned/unregistered row.
    """
    if not isinstance(operation, Operation):
        raise TypeError(f"operation must be Operation, got {type(operation).__name__}")
    if operation is Operation.UNKNOWN:
        return None
    if operation in _SHELL_ONLY_OPERATIONS:
        # No read-only capability serves execution/build/install/edit; routing
        # to one would be a contract §19 rule 5 violation.
        return None
    return _OPERATION_TOOL.get(operation)


def _capability_exists(name: str) -> bool:
    """True only for a registered IMPLEMENTED capability row."""
    return name in registry.capability_names()


def _steps(
    operation: Operation,
    evidence: tuple[EvidenceItem, ...],
    required: tuple[EvidenceRequirement, ...],
    routed: str | None,
) -> tuple[PlanStep, ...]:
    """Compose the contract §13 ladder, highest-preference rung first.

    The order is the contract's preference order, not a display preference:
    existing evidence, then an existing capability, then a structured tool
    operation, then a targeted shell operation, and a broad scan only when
    nothing narrower is available.
    """
    steps: list[PlanStep] = []

    # 1. existing evidence
    known = tuple(item.observation for item in evidence if item.state is EvidenceState.KNOWN)
    if known:
        steps.append(PlanStep(
            order=len(steps) + 1,
            ladder=PlanLadder.EXISTING_EVIDENCE,
            action=f"reuse the existing observation(s): {', '.join(known)}",
            operation=operation,
            capability=None,
            rationale="contract §13 rung 1: existing evidence outranks every new interaction",
            evidence_basis=known,
        ))

    # 2. missing evidence, with the capability that establishes it
    for requirement in required[:MAX_PLAN_STEPS]:
        steps.append(PlanStep(
            order=len(steps) + 1,
            ladder=PlanLadder.EXISTING_CAPABILITY,
            action=f"establish {requirement.observation} "
                   f"({requirement.scope.value}) via {requirement.capability}",
            operation=operation,
            capability=requirement.capability,
            rationale=requirement.reason,
        ))

    # 3. existing capability
    if routed is not None and _capability_exists(routed):
        steps.append(PlanStep(
            order=len(steps) + 1,
            ladder=PlanLadder.EXISTING_CAPABILITY,
            action=f"route the intent to the existing capability {routed}",
            operation=operation,
            capability=routed,
            rationale=(
                "contract §19: an existing capability is preferred over recreating "
                "it through a shell command; this is a recommendation, not an "
                "invocation"
            ),
        ))
    elif operation in _SHELL_ONLY_OPERATIONS:
        steps.append(PlanStep(
            order=len(steps) + 1,
            ladder=PlanLadder.TARGETED_SHELL,
            action=f"no registered read-only capability serves {operation.value}; "
                   f"a targeted shell operation is the narrowest remaining option",
            operation=operation,
            capability=None,
            rationale=(
                "contract §19 rule 5 forbids routing to a capability that would not "
                "answer the intent; the server still never executes it"
            ),
        ))

    # 4. structured tool operation, then targeted shell / broad scan
    if routed is None and operation not in _SHELL_ONLY_OPERATIONS:
        steps.append(PlanStep(
            order=len(steps) + 1,
            ladder=PlanLadder.STRUCTURED_TOOL,
            action=f"use the structured tool operation {operation.value} rather "
                   f"than a text search over the same data",
            operation=operation,
            capability=None,
            rationale=(
                "contract §13: structured data is parsed and inspected, not grepped; "
                "repeated text search for a structured key is a contract violation"
            ),
        ))

    if operation in (Operation.SEARCH_LITERAL, Operation.SEARCH_REGEX,
                     Operation.ENUMERATE_FILES) and routed is None:
        steps.append(PlanStep(
            order=len(steps) + 1,
            ladder=PlanLadder.BROAD_SCAN,
            action=f"only if nothing narrower answers the intent, plan a bounded "
                   f"{operation.value} scan",
            operation=operation,
            capability=None,
            rationale="contract §13 rung 5: a broad scan is the last resort, never the first",
        ))

    return tuple(steps[:MAX_PLAN_STEPS])


# --- the planner ------------------------------------------------------------

def build_plan(
    intent: str,
    store: ObservationStore,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
) -> Plan:
    """Classify one intent and produce a bounded, deterministic recommendation.

    Read-only by construction: the planner reads the existing store, consults the
    existing registry, and returns a ``Plan``. It executes nothing, mutates
    nothing, and never invents a fact — anything unestablished is reported as a
    required observation (contract §13, §14, §18 rule 4).
    """
    text = _bounded(intent, label="intent").strip()
    if not text:
        raise ValueError("intent must not be empty")
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")

    operation = classify_operation(text)
    evidence = assess_evidence(
        store, operation,
        terminal_session=terminal_session, process_id=process_id,
    )
    required = tuple(
        requirement
        for requirement, item in zip(
            _REQUIRED_EVIDENCE.get(operation, ()), evidence
        )
        if item.state is not EvidenceState.KNOWN
    )
    blockers: list[str] = []
    if operation is Operation.UNKNOWN:
        blockers.append(
            "the intent could not be classified into a frozen operation class; "
            "UNKNOWN is preserved rather than guessed (contract §13, §18 rule 4)"
        )
    invalid = tuple(
        item.observation for item in evidence if item.state is EvidenceState.INVALIDATED
    )
    if invalid:
        blockers.append(
            "evidence invalidated by an explicit event and must be re-observed "
            "before use: " + ", ".join(invalid)
        )
    if is_mutation_bearing(operation):
        blockers.append(
            f"{operation.value} is mutation-bearing; V0.9 classifies and "
            "recommends it and never performs it (contract §14)"
        )

    routed = route_capability(operation, intent=text)
    steps = _steps(operation, evidence, required, routed)

    if operation is Operation.UNKNOWN:
        status = PlanStatus.BLOCKED
    elif required:
        status = PlanStatus.INSUFFICIENT_EVIDENCE
    else:
        status = PlanStatus.READY

    validation_context = [VALIDATION_REQUIRED]
    if status is not PlanStatus.READY:
        validation_context.append(
            "this plan is a recommendation with unmet prerequisites; it is not a "
            "validated command and confers no authorization"
        )
    return Plan(
        intent=text,
        operation=operation,
        status=status,
        evidence=evidence,
        required_observations=required,
        steps=steps,
        blockers=tuple(blockers),
        validation_context=tuple(validation_context),
        execution_permitted=False,
    )


# --- preparation (contract §14: emitted as text, never executed) ------------

PREPARED_LABEL = "PREPARED (TEXT ONLY) - NOT EXECUTED"
# Bounded so the rendered line stays inside the 200-char clip (D007).
MAX_MISSING_LISTED = 3


def _missing_summary(plan: Plan) -> str:
    """A bounded, deterministic digest of the unmet prerequisites."""
    names = [
        f"{item.observation} ({item.scope.value})" for item in plan.required_observations
    ]
    listed = ", ".join(names[:MAX_MISSING_LISTED])
    if len(names) > MAX_MISSING_LISTED:
        listed += f", +{len(names) - MAX_MISSING_LISTED} more"
    return listed


def prepare_request(
    intent: str,
    store: ObservationStore,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
) -> Preparation:
    """Normalize a task, resolve known facts, and describe what is missing.

    Preparation is non-executing: it records nothing, spawns nothing, and
    installs nothing. When the request cannot be safely or sufficiently
    prepared, it returns a deterministic BLOCKED / INSUFFICIENT result rather
    than guessing a command.
    """
    plan = build_plan(
        intent, store,
        terminal_session=terminal_session, process_id=process_id,
    )
    if plan.status is PlanStatus.BLOCKED:
        status = PrepareStatus.BLOCKED
    elif plan.status is PlanStatus.INSUFFICIENT_EVIDENCE:
        status = PrepareStatus.INSUFFICIENT_PREREQUISITES
    else:
        status = PrepareStatus.PREPARED

    if status is PrepareStatus.PREPARED:
        prepared_text = (
            f"{PREPARED_LABEL}: operation {plan.operation.value} is supported by the "
            f"evidence already recorded; validate any command text with "
            f"mcquest_shell_validate before Cline executes it."
        )
    else:
        prepared_text = (
            f"{PREPARED_LABEL}: incomplete for {plan.operation.value}; missing: "
            f"{_missing_summary(plan)}. No command is proposed, because proposing "
            f"one would be a guess."
        )

    return Preparation(
        status=status,
        intent=plan.intent,
        operation=plan.operation,
        plan=plan,
        missing_prerequisites=plan.required_observations,
        prepared_text=prepared_text,
        validation_context=plan.validation_context,
        execution_permitted=False,
    )



# --- history (reuses the P1 store; never a second persistence system) --------

def history_view(
    store: ObservationStore,
    *,
    offset: int = 0,
    limit: int = 10,
    terminal_session: str | None = None,
    process_id: str | None = None,
) -> HistoryView:
    """Page the existing command/observation history deterministically.

    This reads ``ObservationStore.commands()`` and ``ObservationStore.snapshot()``
    — the single P1 state model (contract §17 rule 3). It creates no second
    store, persists nothing, applies no wall-clock TTL, and reports provenance,
    trust, scope, freshness, identity binding, and the single P1 invalidation
    decision for every row. Unavailable or empty history is reported as
    INSUFFICIENT rather than filled in.
    """
    if not isinstance(store, ObservationStore):
        raise TypeError("store must be an existing ObservationStore")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be an int >= 0")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_HISTORY_LIMIT:
        raise ValueError(f"limit must be an int between 1 and {MAX_HISTORY_LIMIT}")

    notes: list[str] = [METHOD_HISTORY]

    # Command history — provenance contract §17 rule 3 requires the originating
    # text, normalization levels, cost, operation, and session/process.
    records = store.commands(
        terminal_session=terminal_session, process_id=process_id
    )
    command_rows = tuple(
        HistoryRow(
            record_id=record.command_id,
            kind="command",
            scope="EPHEMERAL" if record.operation is None else "EPHEMERAL",
            freshness="EPHEMERAL",
            source="SERVER_OBSERVED" if record.verdict else "UNKNOWN",
            trust="trusted" if record.verdict else "unknown",
            state=EvidenceState.KNOWN,
            binding="session+process" if record.process_id else "session",
            detail=(
                f"operation={record.operation or 'unclassified'} "
                f"cost={record.cost.value if record.cost else 'unknown'} "
                f"mutation={record.mutation.value if record.mutation else 'none'} "
                f"verdict={record.verdict or 'unrecorded'} "
                f"normalized={'|'.join(record.normalized) if record.normalized else 'none'} "
                f"session={record.terminal_session or 'undeclared'} "
                f"process={record.process_id or 'undeclared'}"
            ),
        )
        for record in records[:MAX_HISTORY_ROWS]
    )

    # Observation history — each row carries the single P1 reuse decision.
    observation_rows: list[HistoryRow] = []
    for fact in store.snapshot()[:MAX_HISTORY_ROWS]:
        if fact.terminal_session is not None and terminal_session is not None:
            if fact.terminal_session != terminal_session:
                continue
        if fact.process_id is not None and process_id is not None:
            if fact.process_id != process_id:
                continue
        reusable = store.reuse_check(
            fact,
            terminal_session=terminal_session,
            process_id=process_id,
        )
        if reusable:
            state = EvidenceState.KNOWN
            detail = f"reusable at revision {fact.revision}"
        else:
            current = store.revision_for(fact.scope, fact.subject)
            if fact.revision != current:
                state = EvidenceState.INVALIDATED
                detail = (
                    f"invalidated: revision {fact.revision} -> {current}; "
                    f"re-observation required"
                )
            else:
                state = EvidenceState.STALE
                detail = "recorded but not reusable for this identity (contract §8)"
        observation_rows.append(HistoryRow(
            record_id=f"{fact.scope.value}:{fact.observation}",
            kind="observation",
            scope=fact.scope.value,
            freshness=fact.freshness.value,
            source=fact.source.value,
            trust=fact.trust.value,
            state=state,
            binding=_binding_label(fact.scope),
            detail=detail,
        ))

    total = len(command_rows) + len(observation_rows)
    # One deterministic ordered sequence: commands (insertion order), then
    # observations (the store's own snapshot order). Paging never re-sorts.
    ordered = command_rows + tuple(observation_rows)
    page = ordered[offset : offset + limit]
    returned = len(page)
    next_offset = offset + returned if offset + returned < total else None

    if total == 0:
        status = PlanStatus.INSUFFICIENT
        notes.append(
            "history is empty in this server process; nothing is persisted across "
            "a restart and no history is inferred (decision A4/S3)"
        )
    else:
        status = PlanStatus.READY

    return HistoryView(
        status=status,
        rows=page,
        total=total,
        returned=returned,
        offset=offset,
        has_more=next_offset is not None,
        next_offset=next_offset,
        notes=tuple(notes),
    )


# --- next step (contract §22 differentiated recovery; no autonomous loop) ---

def next_step(
    intent: str,
    store: ObservationStore,
    *,
    terminal_session: str | None = None,
    process_id: str | None = None,
    changed_reasons: tuple[ChangeReason, ...] = (),
    last_command: str = "",
    repository_root: str | None = None,
) -> NextStep:
    """Determine the next useful observation/planning step — never execute it.

    Blind-retry prevention (contract §22): when the last command is a duplicate
    at some n0-n3 level and no relevant condition changed, repeating it is
    refused and a *different* next action is returned. A retry is permitted only
    when the caller names at least one changed condition. This is a single
    decision, not a loop: it never re-plans, never executes, and never mutates.
    """
    plan = build_plan(
        intent, store,
        terminal_session=terminal_session, process_id=process_id,
    )
    changed = tuple(reason.value for reason in changed_reasons)

    # Redundancy is evaluated only when the caller supplies a concrete command.
    duplicate = False
    duplicate_detail = ""
    if last_command.strip():
        result = analyze_redundancy(
            last_command,
            store,
            terminal_session=terminal_session,
            process_id=process_id,
            repository_root=repository_root,
            changed_reasons=changed_reasons,
        )
        duplicate = result.duplicate
        duplicate_detail = result.message

    # Choose the single next useful step from the plan's own ladder.
    if duplicate and not changed:
        action = NextAction.DIFFERENTIATE
        detail = (
            f"{duplicate_detail}; nothing relevant changed, so a blind repeat is "
            f"refused. {NO_BLIND_RETRY} Change state, scope, path, encoding "
            f"handling, dialect, or CWD, or choose a different action."
        )
        step = None
    elif plan.status is PlanStatus.BLOCKED:
        action = NextAction.STOP
        detail = (
            "the intent could not be classified into a frozen operation class; "
            "stop rather than guess (contract §13, §18 rule 4)"
        )
        step = None
    elif plan.required_observations:
        action = NextAction.OBSERVE
        first = plan.required_observations[0]
        detail = (
            f"observe {first.observation} at {first.scope.value} via "
            f"{first.capability} before planning further: {first.reason}"
        )
        step = next((s for s in plan.steps if s.capability == first.capability), None)
    elif plan.steps and plan.steps[-1].ladder is PlanLadder.EXISTING_CAPABILITY:
        action = NextAction.ROUTE
        step = plan.steps[-1]
        detail = (
            f"an existing capability answers this intent: "
            f"{step.capability}. This is a recommendation, never an invocation "
            f"(contract §19 rule 4)."
        )
    elif plan.steps:
        action = NextAction.VALIDATE
        step = plan.steps[0]
        detail = (
            f"evidence supports {plan.operation.value}; {VALIDATION_REQUIRED}"
        )
    else:
        action = NextAction.STOP
        step = None
        detail = (
            "no ladder step applies to this intent; no action is recommended "
            "and nothing is executed"
        )

    method = (
        "one decision from the §13 ladder + §20 n0-n3 redundancy ladder; "
        "never an autonomous loop; a repeat needs a changed condition (§22)"
    )
    return NextStep(
        intent=plan.intent,
        operation=plan.operation,
        action=action,
        step=step,
        plan=plan,
        detail=detail,
        changed_conditions=changed,
        method_line=method,
        execution_permitted=False,
    )
