"""Shared V0.9 state vocabulary (contract §6–§9; decisions A2, A5).

Dependency-free foundation for every ``shell`` component. It defines exactly
the approved enumerations, the ``Fact`` provenance record, the deterministic
``Observation`` wrapper, corroboration, and the freshness defaults.

Deliberately absent — these are approved decisions, not omissions:

- no numeric confidence field: reliability is expressed only through source +
  trust + freshness (contract §7 rule 4);
- no wall-clock expiry: ``observed_at`` is UTC ISO-8601 provenance that never
  triggers automatic invalidation (decision A5).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum


class Source(str, Enum):
    """Where a fact came from — exactly three, frozen (contract §6)."""

    SERVER_OBSERVED = "SERVER_OBSERVED"
    CLIENT_DECLARED = "CLIENT_DECLARED"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return str(self.value)


class Trust(str, Enum):
    """Exactly four authority levels; none may be invented (contract §7)."""

    TRUSTED = "trusted"
    CORROBORATED = "corroborated"
    UNTRUSTED = "untrusted"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return str(self.value)


class Scope(str, Enum):
    """Observation scopes (contract §10); FILE anchors path evidence (A14)."""

    REPOSITORY = "REPOSITORY"
    WORKTREE = "WORKTREE"
    FILE = "FILE"
    SESSION = "SESSION"
    PROCESS = "PROCESS"
    EPHEMERAL = "EPHEMERAL"

    def __str__(self) -> str:
        return str(self.value)


class Freshness(str, Enum):
    """Semantic freshness classes — never time-based (contract §11, A5)."""

    STATIC = "STATIC"
    SESSION = "SESSION"
    WORKTREE = "WORKTREE"
    PROCESS = "PROCESS"
    EPHEMERAL = "EPHEMERAL"

    def __str__(self) -> str:
        return str(self.value)


class CostClass(str, Enum):
    """Qualitative cost vocabulary (contract §21; VERY_HIGH = "VERY HIGH")."""

    TRIVIAL = "TRIVIAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

    def __str__(self) -> str:
        return str(self.value)


# Canonical sentinel values (contract §6/§7, §18 rule 4).
VALUE_UNKNOWN = "unknown"
EVIDENCE_CLIENT_DECLARED = "declared by client; not verified"
EVIDENCE_UNOBSERVED = "no declaration and no observation"

# Canonical subjects shared between terminal.py and invalidate.py.
SUBJECT_CWD = "cwd"
SUBJECT_CONSOLE_CODEPAGE = "console_codepage"

# Identity-bound scopes (contract §10): SESSION binds the session;
# PROCESS/EPHEMERAL bind session AND process. The repository family
# (REPOSITORY/WORKTREE/FILE) stays reusable across terminals until an
# invalidation event says otherwise.
BINDING_SESSION_SCOPES = frozenset({Scope.SESSION})
BINDING_PROCESS_SCOPES = frozenset({Scope.PROCESS, Scope.EPHEMERAL})

# Documented scope → default freshness pairing (contract §11 examples; the §9
# example pairs FILE scope with WORKTREE freshness). Callers may override per
# fact — e.g. git.autocrlf is REPOSITORY scope with SESSION freshness.
DEFAULT_FRESHNESS: dict[Scope, Freshness] = {
    Scope.REPOSITORY: Freshness.STATIC,
    Scope.WORKTREE: Freshness.WORKTREE,
    Scope.FILE: Freshness.WORKTREE,
    Scope.SESSION: Freshness.SESSION,
    Scope.PROCESS: Freshness.PROCESS,
    Scope.EPHEMERAL: Freshness.EPHEMERAL,
}


def require_enum(value: object, enum_type: type, label: str) -> None:
    """Raise TypeError unless ``value`` is an instance of ``enum_type``."""
    if not isinstance(value, enum_type):
        name = getattr(enum_type, "__name__", str(enum_type))
        raise TypeError(f"{label} must be {name}, got {type(value).__name__}")


def require_non_empty_str(value: object, label: str) -> None:
    """Raise unless ``value`` is a non-empty string."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be str, got {type(value).__name__}")
    if not value:
        raise ValueError(f"{label} must not be empty")


def require_optional_str(value: object, label: str) -> None:
    """Raise unless ``value`` is ``None`` or a string."""
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{label} must be str or None, got {type(value).__name__}")


def default_freshness(scope: Scope) -> Freshness:
    """Default freshness class for ``scope`` (contract §11)."""
    require_enum(scope, Scope, "scope")
    return DEFAULT_FRESHNESS[scope]


@dataclass(frozen=True)
class Fact:
    """One observation with the provenance contract §9 requires.

    Field order follows the contract: the eight required fields come first,
    then the optional context fields, then the store-managed ``revision``
    (contract §12: invalidated by explicit events, never by a clock).
    """

    observation: str
    value: object
    scope: Scope
    freshness: Freshness
    observed_at: str
    source: Source
    trust: Trust
    evidence: str
    subject: str | None = None
    repository: str | None = None
    file: str | None = None
    operation: str | None = None
    terminal_session: str | None = None
    process_id: str | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        require_non_empty_str(self.observation, "observation")
        require_enum(self.scope, Scope, "scope")
        require_enum(self.freshness, Freshness, "freshness")
        require_non_empty_str(self.observed_at, "observed_at")
        require_enum(self.source, Source, "source")
        require_enum(self.trust, Trust, "trust")
        require_non_empty_str(self.evidence, "evidence")
        require_optional_str(self.subject, "subject")
        require_optional_str(self.repository, "repository")
        require_optional_str(self.file, "file")
        require_optional_str(self.operation, "operation")
        require_optional_str(self.terminal_session, "terminal_session")
        require_optional_str(self.process_id, "process_id")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise TypeError(f"revision must be int, got {type(self.revision).__name__}")
        if self.revision < 0:
            raise ValueError("revision must not be negative")
        # Binding rule: a *declared* fact on an identity-bound scope must carry
        # that identity, so it can never be served to another terminal/process.
        # UNKNOWN-source facts describe the absence of a declaration and carry
        # no identity requirement (contract §6 rule 4, decision S1).
        if self.source is Source.CLIENT_DECLARED:
            if self.scope in BINDING_SESSION_SCOPES and self.terminal_session is None:
                raise ValueError(
                    "CLIENT_DECLARED SESSION facts require terminal_session (contract §8)"
                )
            if self.scope in BINDING_PROCESS_SCOPES and (
                self.terminal_session is None or self.process_id is None
            ):
                raise ValueError(
                    "CLIENT_DECLARED PROCESS/EPHEMERAL facts require terminal_session "
                    "and process_id (contract §8)"
                )


def observation_id(fact: Fact) -> str:
    """Deterministic identity string for ``fact``.

    Identity is scope + subject + session/process — never time (contract §9
    rule 1): the same identity yields the same id in any store, on any run.
    """
    parts = (
        fact.observation,
        fact.scope.value,
        fact.subject or "",
        fact.terminal_session or "",
        fact.process_id or "",
    )
    digest = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"obs-{digest[:12]}"


def corroborate(fact: Fact, *, evidence: str | None = None) -> Fact:
    """Upgrade a client-declared fact's trust to ``corroborated``.

    Corroboration changes trust only — never source (contract §7 rule 1) —
    and the original provenance phrase must remain present (contract §17
    rule 2). Only CLIENT_DECLARED facts may be corroborated.
    """
    if fact.source is not Source.CLIENT_DECLARED:
        raise ValueError("only CLIENT_DECLARED facts may be corroborated (contract §7 rule 1)")
    if evidence is None:
        new_evidence = fact.evidence
    else:
        require_non_empty_str(evidence, "evidence")
        new_evidence = f"{fact.evidence}; {evidence}"
    return replace(fact, trust=Trust.CORROBORATED, evidence=new_evidence)


_OBSERVATION_ORIGINS = frozenset({"tool", "terminal_session"})


@dataclass(frozen=True)
class Observation:
    """A ``Fact`` plus its deterministic id and origin (architecture §5.1)."""

    fact: Fact
    observation_id: str
    origin: str

    @classmethod
    def wrap(cls, fact: Fact, *, origin: str) -> "Observation":
        """Wrap ``fact``; ``origin`` is exactly ``tool`` or ``terminal_session``."""
        if origin not in _OBSERVATION_ORIGINS:
            allowed = ", ".join(sorted(_OBSERVATION_ORIGINS))
            raise ValueError(f"origin must be one of: {allowed}")
        return cls(fact=fact, observation_id=observation_id(fact), origin=origin)

