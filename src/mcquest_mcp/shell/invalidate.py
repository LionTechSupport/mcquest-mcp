"""Event → scope invalidation with monotonic per-scope/subject revisions (contract §12; architecture §5.3).

**Invalidate rather than guess.** Every event with a known effect bumps the
revision counters of exactly its mapped scopes/subjects; a reusable fact turns
stale the moment an applicable event lands, with no wall-clock involved
(decision A5).

Mappings follow the approved architecture §5.3 table plus the contract §12
event list. Three events needed mappings the tables left implicit; each is
flagged ``interpretation`` below and recorded in ``05-V0.9-STATE.md``:

- ENVIRONMENT_CHANGE (mandated by the P1 authorization): env vars are
  "shell variables, process-local state" (contract §10) → PROCESS refined by
  the variable name, plus EPHEMERAL output that may depend on them;
- CONFIGURATION_CHANGE: "corresponding observed facts" (contract §12) →
  REPOSITORY, FILE and SESSION refined by the config key — wholesale for
  those scopes when no key is supplied, never WORKTREE;
- REPOSITORY_WORKTREE_CHANGE (mandated by the P1 authorization): both named
  scopes wholesale; FILE changes arrive through the file events.

Subject-refinement never *narrows* inherently broad events: a supplied
subject is ignored for wholesale targets, and a canonical target always
bumps its fixed subject regardless of any supplied subject.
"""

from __future__ import annotations

from enum import Enum

from .facts import (
    SUBJECT_CWD,
    SUBJECT_CONSOLE_CODEPAGE,
    Scope,
    require_enum,
    require_optional_str,
)
from .store import ObservationStore


class InvalidationEvent(str, Enum):
    """Approved invalidation events (contract §12 + the mandated P1 list)."""

    SET_LOCATION = "set_location"
    FILE_MODIFIED = "file_modified"
    FILE_CREATED_DELETED = "file_created_deleted"
    GIT_CHECKOUT = "git_checkout"
    GIT_RESET = "git_reset"
    GIT_PULL = "git_pull"
    BRANCH_SWITCH = "branch_switch"
    DEPENDENCY_INSTALL = "dependency_install"
    ENVIRONMENT_CHANGE = "environment_change"
    CONFIGURATION_CHANGE = "configuration_change"
    CONSOLE_CODEPAGE_CHANGE = "console_codepage_change"
    PROCESS_RESTART = "process_restart"
    TERMINAL_RESTART = "terminal_restart"
    SERVER_RESTART = "server_restart"
    REPOSITORY_WORKTREE_CHANGE = "repository_worktree_change"

    def __str__(self) -> str:
        return str(self.value)


# Subject handling per target: "all" bumps every known key in the scope;
# "refine" bumps only the event's supplied subject (falling back to the whole
# scope when none is supplied); "canonical" always bumps the fixed subject in
# the third slot — the event's subject is irrelevant there.
_ALL = "all"
_REFINE = "refine"
_CANONICAL = "canonical"

EventTarget = tuple[Scope, str, str | None]

EVENT_TARGETS: dict[InvalidationEvent, tuple[EventTarget, ...]] = {
    # CWD change touches the cwd slot only — shell version etc. survive.
    InvalidationEvent.SET_LOCATION: ((Scope.PROCESS, _CANONICAL, SUBJECT_CWD),),
    # A modified file: its FILE slot + worktree content/search evidence (§5.3).
    InvalidationEvent.FILE_MODIFIED: (
        (Scope.FILE, _REFINE, None),
        (Scope.WORKTREE, _ALL, None),
    ),
    InvalidationEvent.FILE_CREATED_DELETED: (
        (Scope.FILE, _REFINE, None),
        (Scope.WORKTREE, _ALL, None),
    ),
    # Git moves rewrite worktree observations, not repository identity/config.
    InvalidationEvent.GIT_CHECKOUT: ((Scope.WORKTREE, _ALL, None),),
    InvalidationEvent.GIT_RESET: ((Scope.WORKTREE, _ALL, None),),
    InvalidationEvent.GIT_PULL: ((Scope.WORKTREE, _ALL, None),),
    InvalidationEvent.BRANCH_SWITCH: ((Scope.WORKTREE, _ALL, None),),
    # Installed executables/packages are session-scoped discoveries (§5.3).
    InvalidationEvent.DEPENDENCY_INSTALL: ((Scope.SESSION, _ALL, None),),
    # interpretation: env vars are process-local state (§10); output may depend on them.
    InvalidationEvent.ENVIRONMENT_CHANGE: (
        (Scope.PROCESS, _REFINE, None),
        (Scope.EPHEMERAL, _ALL, None),
    ),
    # interpretation: "corresponding observed facts" (§12) refined by config key.
    InvalidationEvent.CONFIGURATION_CHANGE: (
        (Scope.REPOSITORY, _REFINE, None),
        (Scope.FILE, _REFINE, None),
        (Scope.SESSION, _REFINE, None),
    ),
    # The code-page slot only; rendering-dependent (EPHEMERAL) output goes stale.
    InvalidationEvent.CONSOLE_CODEPAGE_CHANGE: (
        (Scope.PROCESS, _CANONICAL, SUBJECT_CONSOLE_CODEPAGE),
        (Scope.EPHEMERAL, _ALL, None),
    ),
    InvalidationEvent.PROCESS_RESTART: ((Scope.PROCESS, _ALL, None),),
    InvalidationEvent.TERMINAL_RESTART: (
        (Scope.SESSION, _ALL, None),
        (Scope.PROCESS, _ALL, None),
    ),
    InvalidationEvent.SERVER_RESTART: (
        (Scope.SESSION, _ALL, None),
        (Scope.PROCESS, _ALL, None),
    ),
    # interpretation: both named scopes wholesale; FILE changes arrive via file events.
    InvalidationEvent.REPOSITORY_WORKTREE_CHANGE: (
        (Scope.REPOSITORY, _ALL, None),
        (Scope.WORKTREE, _ALL, None),
    ),
}


def apply_invalidation(
    store: ObservationStore,
    event: InvalidationEvent,
    *,
    subject: str | None = None,
) -> tuple[tuple[Scope, str], ...]:
    """Apply ``event`` to ``store``; return every bumped key, sorted deterministically.

    ``subject`` narrows ``refine`` targets (the changed path, variable name or
    config key). It never affects ``canonical`` targets and never narrows
    wholesale targets — a checkout is broad by nature. An event with no known
    targets raises; unknown events are never mapped by guesswork.
    """
    if not isinstance(event, InvalidationEvent):
        raise TypeError(f"event must be InvalidationEvent, got {type(event).__name__}")
    require_enum(event, InvalidationEvent, "event")
    require_optional_str(subject, "subject")
    bumped: set[tuple[Scope, str]] = set()
    for scope, mode, canonical_subject in EVENT_TARGETS[event]:
        if mode == _CANONICAL:
            bumped.update(store.invalidate_scope(scope, canonical_subject))
        elif mode == _REFINE and subject:
            bumped.update(store.invalidate_scope(scope, subject))
        else:  # _ALL, or _REFINE with no supplied subject
            bumped.update(store.invalidate_scope(scope))
    return tuple(sorted(bumped, key=lambda key: (key[0].value, key[1])))

