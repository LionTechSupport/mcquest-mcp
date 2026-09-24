"""Environment Contract assembly and the approved fixed-argv probes (P2).

Contract §5 (Environment Contract) and §15 (probe boundary); architecture §5.4;
decisions A2, A3, A5, A8, S1, S2. This is the only V0.9 module that runs the
approved read-only observation probes (architecture §3).

Closed probe allowlist:

- project root   ``--project`` / ``MCQUEST_PROJECT_ROOT`` via the existing
                 ``security.project_root()`` convention (no process);
- platform       Python stdlib only (``platform``);
- presence       ``shutil.which(name)`` (never executes the discovered tool);
- git facts      ``git --version``, ``git rev-parse --show-toplevel``;
- node version   ``node --version``;
- PowerShell 7+  ``pwsh -Version`` — documented print-and-exit probe, no
                 ``-Command``;
- Windows PowerShell 5.1
                 the EXACT fixed literal ``powershell.exe -NoProfile
                 -NonInteractive -Command $PSVersionTable.PSVersion.ToString()``
                 — authorized by the P2 hybrid ruling as a fixed server-side
                 observation probe. This is the ONLY place in V0.9 that may pass
                 ``-Command``, and only ever with that literal: never arbitrary
                 or user-supplied command text, never a dynamically built
                 command, never a generic PowerShell execution facility.

Probe safety (contract §15 rules; authorization §7/§18): argv is an explicit
list of literal strings, ``shell=False``, no shell string interpolation, no
``cmd`` wrapper, timeout ≤ 10 s, stdout bounded then decoded explicitly as
UTF-8 with ``errors="replace"``, ``check=False``, working directory is the
project root, and any failure (missing executable, timeout, nonzero exit, no
output) yields ``UNKNOWN`` — never a fabricated or stale value.

Server-lifetime shared state: the single ``ObservationStore`` used by the P2
adapters lives here (``get_store()`` / ``reset_store()``). Validity is the P1
reuse rule (scope + identity + revision); there is no wall-clock TTL (A5).
Rendered tool output carries no clock-dependent content (contract §16 rule 6);
``observed_at`` stays provenance inside the store.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from ..security import project_root
from .facts import (
    VALUE_UNKNOWN,
    Fact,
    Freshness,
    Scope,
    Source,
    Trust,
    corroborate,
)
from .store import ObservationStore
from .terminal import (
    SERVER_SUBJECT,
    TERMINAL_FIELDS,
    TerminalIdentity,
    declare,
    resolve,
)

# --- probe contract constants (contract §15) --------------------------------

PROBE_TIMEOUT_SECONDS = 10  # contract §15 rule 3: timeout <= 10 s
MAX_PROBE_OUTPUT_CHARS = 4096  # bounded probe stdout

# Fixed argv lists — the closed allowlist. Never assembled from client text.
GIT_VERSION_ARGV: tuple[str, ...] = ("git", "--version")
GIT_TOPLEVEL_ARGV: tuple[str, ...] = ("git", "rev-parse", "--show-toplevel")
NODE_VERSION_ARGV: tuple[str, ...] = ("node", "--version")
PWSH_VERSION_ARGV: tuple[str, ...] = ("pwsh", "-Version")
POWERSHELL_VERSION_ARGV: tuple[str, ...] = (
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "$PSVersionTable.PSVersion.ToString()",
)

VERSION_PROBES: dict[str, tuple[str, ...]] = {
    "git": GIT_VERSION_ARGV,
    "node": NODE_VERSION_ARGV,
    "pwsh": PWSH_VERSION_ARGV,
    "powershell": POWERSHELL_VERSION_ARGV,
}

# Executables observed for presence via shutil.which (presence only).
EXECUTABLE_NAMES: tuple[str, ...] = ("git", "node", "pwsh", "powershell")

# --- observation names (deterministic) --------------------------------------

OBS_PROJECT_ROOT = "environment.project_root"
OBS_OS_FAMILY = "environment.os_family"
OBS_OS_VERSION = "environment.os_version"
OBS_PYTHON_VERSION = "environment.python_version"
OBS_GIT_TOPLEVEL = "environment.git_toplevel"
OBS_BASELINE_POWERSHELL = "environment.baseline.powershell"
OBS_BASELINE_PWSH = "environment.baseline.pwsh"


def obs_which(name: str) -> str:
    return f"environment.which.{name}"


def obs_version(name: str) -> str:
    return f"environment.version.{name}"


# Stable render order for client terminal fields (subset of terminal.py's set).
ENVIRONMENT_CLIENT_FIELDS: tuple[str, ...] = (
    "terminal.session_id",
    "terminal.process_id",
    "terminal.shell",
    "terminal.shell_version",
    "terminal.cwd",
)

# Canonical directives (decision S1; test-plan E1/T5).
DIRECTIVE_EXPLICIT_PATH = (
    "CWD unknown/untrusted: use explicit repository paths; never infer the "
    "client terminal CWD from the MCP server process."
)
DIRECTIVE_MULTI_TERMINAL = (
    "Facts from another terminal/process are never current for this one; "
    "identity-scoped observations are not promoted across sessions/processes."
)
NOTE_MACHINE_BASELINE = (
    "Shell versions above are machine capability (SERVER_OBSERVED, subject="
    f"{SERVER_SUBJECT}) - never the client's terminal shell."
)
NOTE_PROBE_CONTRACT = (
    "Probes: fixed argv lists, shell=False, timeout<=10s, UTF-8 errors=replace, "
    "check=False, cwd=project root; failure yields UNKNOWN; no client text is "
    "ever interpolated."
)

# A frozen baseline vocabulary (decision A8): only these tags exist.
BASELINE_PS51 = "ps5.1"
BASELINE_PS7 = "ps7"
BASELINE_UNKNOWN = "unknown"


# --- server-lifetime shared store (single shared state, decision A4) --------

_STORE = ObservationStore()


def get_store() -> ObservationStore:
    """The server-lifetime shared observation store."""
    return _STORE


def reset_store() -> None:
    """Drop all shared state — restart semantics (decision S3) and test isolation."""
    _STORE.reset()


def observed_now() -> str:
    """UTC ISO-8601 provenance timestamp (contract §9; never rendered, A5)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- probe runner ------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one fixed-argv probe; failure is explicit, never fabricated."""

    argv: tuple[str, ...]
    ok: bool
    stdout: str
    returncode: int | None
    error: str | None


def run_probe(argv: Sequence[str], *, cwd: str | Path) -> ProbeResult:
    """Run one approved fixed-argv, read-only probe (contract §15).

    Guarantees: explicit list argv (never a shell string), ``shell=False``,
    ``check=False``, timeout ≤ ``PROBE_TIMEOUT_SECONDS``, bounded stdout
    decoded explicitly as UTF-8 with ``errors="replace"``, and working
    directory pinned to ``cwd``. Never raises: every failure mode becomes a
    non-ok ``ProbeResult`` whose affected fact must render as ``UNKNOWN``.
    """
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a sequence of strings, not a string")
    materialized = tuple(argv)
    if not materialized:
        raise ValueError("argv must not be empty")
    for index, item in enumerate(materialized):
        if not isinstance(item, str) or not item:
            raise ValueError(f"argv[{index}] must be a non-empty string")

    try:
        completed = subprocess.run(
            list(materialized),
            shell=False,
            cwd=str(cwd),
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(materialized, False, "", None, "timeout")
    except OSError as exc:
        # Includes "executable missing" — becomes UNKNOWN, never false.
        return ProbeResult(
            materialized, False, "", None, f"os-error:{type(exc).__name__}"
        )

    raw = completed.stdout or b""
    if isinstance(raw, (bytes, bytearray)):
        bounded = bytes(raw)[:MAX_PROBE_OUTPUT_CHARS]
        text = bounded.decode("utf-8", errors="replace")
    else:  # defensive: a mocked runner may already return text
        text = str(raw)[:MAX_PROBE_OUTPUT_CHARS]

    returncode = completed.returncode
    if returncode == 0:
        return ProbeResult(materialized, True, text, 0, None)
    return ProbeResult(materialized, False, text, returncode, f"exit-{returncode}")


# --- fact construction -------------------------------------------------------


def _server_fact(
    observation: str,
    value: object,
    *,
    scope: Scope,
    freshness: Freshness,
    evidence: str,
    subject: str | None = SERVER_SUBJECT,
    repository: str | None = None,
) -> Fact:
    return Fact(
        observation=observation,
        value=value,
        scope=scope,
        freshness=freshness,
        observed_at=observed_now(),
        source=Source.SERVER_OBSERVED,
        trust=Trust.TRUSTED,
        evidence=evidence,
        subject=subject,
        repository=repository,
    )


def _unknown_fact(
    observation: str,
    *,
    scope: Scope,
    freshness: Freshness,
    evidence: str,
    subject: str | None = SERVER_SUBJECT,
    repository: str | None = None,
) -> Fact:
    """Probe-failure / absence representation (contract §15 rule 4; §18 rule 4)."""
    return Fact(
        observation=observation,
        value=VALUE_UNKNOWN,
        scope=scope,
        freshness=freshness,
        observed_at=observed_now(),
        source=Source.UNKNOWN,
        trust=Trust.UNTRUSTED,
        evidence=evidence,
        subject=subject,
        repository=repository,
    )


def _reuse_or_compute(
    store: ObservationStore,
    observation: str,
    scope: Scope,
    subject: str | None,
    compute: Callable[[], Fact],
) -> Fact:
    """Reuse a stored fact when P1 reuse allows; otherwise compute and record.

    Reuse requires scope match, identity match (repository-family facts carry
    no terminal identity) and an unchanged revision — never a clock (A5).
    """
    candidate = store.lookup(observation, scope, subject)
    if candidate is not None and store.reuse_check(
        candidate, scope=scope, terminal_session=None, process_id=None
    ):
        return candidate
    return store.record(compute())


# --- PowerShell baseline derivation (decision A8) ---------------------------


def powershell_baseline(version: str) -> str:
    """Map an OBSERVED PowerShell version string to a frozen A8 baseline tag.

    ``5.1.x`` -> ``ps5.1``; major ``>= 7`` -> ``ps7``; anything else (6.x,
    unparseable, empty) -> ``unknown``. Deterministic and never optimistic:
    unknown stays unknown.
    """
    if not isinstance(version, str):
        return BASELINE_UNKNOWN
    parts = version.strip().split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else -1
    except (ValueError, IndexError):
        return BASELINE_UNKNOWN
    if major == 5 and minor == 1:
        return BASELINE_PS51
    if major >= 7:
        return BASELINE_PS7
    return BASELINE_UNKNOWN


def _which_fact(store: ObservationStore, name: str) -> Fact:
    observation = obs_which(name)

    def compute() -> Fact:
        found = shutil.which(name)
        if found is None:
            return _unknown_fact(
                observation,
                scope=Scope.SESSION,
                freshness=Freshness.SESSION,
                evidence=f"shutil.which({name!r}): no match on PATH",
            )
        return _server_fact(
            observation,
            found,
            scope=Scope.SESSION,
            freshness=Freshness.SESSION,
            evidence=f"shutil.which({name!r})",
        )

    return _reuse_or_compute(store, observation, Scope.SESSION, SERVER_SUBJECT, compute)


def _version_fact(store: ObservationStore, name: str, root: Path) -> Fact:
    observation = obs_version(name)

    def compute() -> Fact:
        if shutil.which(name) is None:
            return _unknown_fact(
                observation,
                scope=Scope.SESSION,
                freshness=Freshness.SESSION,
                evidence=f"{name} not on PATH; version probe not run",
            )
        result = run_probe(VERSION_PROBES[name], cwd=root)
        if not result.ok:
            return _unknown_fact(
                observation,
                scope=Scope.SESSION,
                freshness=Freshness.SESSION,
                evidence=f"probe failed ({result.error}); UNKNOWN",
            )
        value = result.stdout.strip()
        if not value:
            return _unknown_fact(
                observation,
                scope=Scope.SESSION,
                freshness=Freshness.SESSION,
                evidence="probe produced no output; UNKNOWN",
            )
        return _server_fact(
            observation,
            value,
            scope=Scope.SESSION,
            freshness=Freshness.SESSION,
            evidence=f"{' '.join(result.argv)} (fixed argv)",
        )

    return _reuse_or_compute(store, observation, Scope.SESSION, SERVER_SUBJECT, compute)


def _baseline_fact(
    store: ObservationStore, observation: str, version_fact: Fact
) -> Fact:
    """Derive an A8 baseline tag only from a successful version observation."""

    def compute() -> Fact:
        if (
            version_fact.value == VALUE_UNKNOWN
            or version_fact.source is not Source.SERVER_OBSERVED
        ):
            return _unknown_fact(
                observation,
                scope=Scope.SESSION,
                freshness=Freshness.SESSION,
                evidence=f"{version_fact.observation} is unknown; baseline not derived",
            )
        tag = powershell_baseline(str(version_fact.value))
        if tag == BASELINE_UNKNOWN:
            return _unknown_fact(
                observation,
                scope=Scope.SESSION,
                freshness=Freshness.SESSION,
                evidence=f"baseline not classifiable from {version_fact.observation}",
            )
        return _server_fact(
            observation,
            tag,
            scope=Scope.SESSION,
            freshness=Freshness.SESSION,
            evidence=f"derived from {version_fact.observation}",
        )

    return _reuse_or_compute(store, observation, Scope.SESSION, SERVER_SUBJECT, compute)


def _project_root_fact(store: ObservationStore, root: Path) -> Fact:
    def compute() -> Fact:
        return _server_fact(
            OBS_PROJECT_ROOT,
            str(root),
            scope=Scope.REPOSITORY,
            freshness=Freshness.STATIC,
            evidence="--project / MCQUEST_PROJECT_ROOT (config)",
            subject=None,
        )

    return _reuse_or_compute(store, OBS_PROJECT_ROOT, Scope.REPOSITORY, None, compute)


def _stdlib_fact(
    store: ObservationStore,
    observation: str,
    value_provider: Callable[[], str],
    evidence: str,
) -> Fact:
    def compute() -> Fact:
        return _server_fact(
            observation,
            value_provider(),
            scope=Scope.SESSION,
            freshness=Freshness.STATIC,
            evidence=evidence,
        )

    return _reuse_or_compute(store, observation, Scope.SESSION, SERVER_SUBJECT, compute)


def _git_toplevel_fact(store: ObservationStore, root: Path) -> Fact:
    observation = OBS_GIT_TOPLEVEL

    def compute() -> Fact:
        if shutil.which("git") is None:
            return _unknown_fact(
                observation,
                scope=Scope.REPOSITORY,
                freshness=Freshness.STATIC,
                evidence="git not on PATH; repository probe not run",
                subject=None,
                repository=str(root),
            )
        result = run_probe(GIT_TOPLEVEL_ARGV, cwd=root)
        if not result.ok:
            return _unknown_fact(
                observation,
                scope=Scope.REPOSITORY,
                freshness=Freshness.STATIC,
                evidence=f"rev-parse --show-toplevel failed ({result.error}); UNKNOWN",
                subject=None,
                repository=str(root),
            )
        value = result.stdout.strip()
        if not value:
            return _unknown_fact(
                observation,
                scope=Scope.REPOSITORY,
                freshness=Freshness.STATIC,
                evidence="rev-parse --show-toplevel produced no output; UNKNOWN",
                subject=None,
                repository=str(root),
            )
        return _server_fact(
            observation,
            value,
            scope=Scope.REPOSITORY,
            freshness=Freshness.STATIC,
            evidence="git rev-parse --show-toplevel (fixed argv)",
            subject=None,
            repository=str(root),
        )

    return _reuse_or_compute(store, observation, Scope.REPOSITORY, None, compute)


def collect_environment(store: ObservationStore) -> tuple[Fact, ...]:
    """Assemble every environment fact through reuse-or-probe, in stable order."""
    root = project_root()
    facts: list[Fact] = [
        _project_root_fact(store, root),
        _stdlib_fact(store, OBS_OS_FAMILY, platform.system, "platform.system() stdlib"),
        _stdlib_fact(store, OBS_OS_VERSION, platform.version, "platform.version() stdlib"),
        _stdlib_fact(
            store, OBS_PYTHON_VERSION, platform.python_version,
            "platform.python_version() stdlib",
        ),
    ]
    for name in EXECUTABLE_NAMES:
        facts.append(_which_fact(store, name))
    versions: dict[str, Fact] = {}
    for name in EXECUTABLE_NAMES:
        versions[name] = _version_fact(store, name, root)
        facts.append(versions[name])
    facts.append(
        _baseline_fact(store, OBS_BASELINE_POWERSHELL, versions["powershell"])
    )
    facts.append(_baseline_fact(store, OBS_BASELINE_PWSH, versions["pwsh"]))
    facts.append(_git_toplevel_fact(store, root))
    return tuple(facts)


# --- server process identity (decision S2) ----------------------------------


def server_process_facts(store: ObservationStore) -> tuple[Fact, ...]:
    """The MCP server's own process facts, always under the ``mcp_server`` subject.

    These are never served as the client's terminal state (contract §6 rule 2;
    decision S2) and are rendered only inside an explicitly labeled section.
    """

    def cwd_fact() -> Fact:
        return _server_fact(
            "terminal.cwd",
            str(os.getcwd()),
            scope=Scope.PROCESS,
            freshness=Freshness.PROCESS,
            evidence=f"server os.getcwd(); subject={SERVER_SUBJECT}",
        )

    def pid_fact() -> Fact:
        return _server_fact(
            "terminal.process_id",
            str(os.getpid()),
            scope=Scope.PROCESS,
            freshness=Freshness.PROCESS,
            evidence=f"server os.getpid(); subject={SERVER_SUBJECT}",
        )

    cwd = _reuse_or_compute(store, "terminal.cwd", Scope.PROCESS, SERVER_SUBJECT, cwd_fact)
    pid = _reuse_or_compute(
        store, "terminal.process_id", Scope.PROCESS, SERVER_SUBJECT, pid_fact
    )
    return (cwd, pid)


# --- client terminal declaration and resolution ------------------------------


def normalize_identity(
    *,
    client_session: str | None = None,
    client_process_id: str | None = None,
    client_cwd: str | None = None,
    client_shell: str | None = None,
    client_shell_version: str | None = None,
) -> TerminalIdentity:
    """Normalize declared inputs: strip, empty -> None (never guessed)."""

    def clean(raw: str | None) -> str | None:
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise TypeError("client declaration inputs must be strings")
        stripped = raw.strip()
        return stripped or None

    return TerminalIdentity(
        session_id=clean(client_session),
        process_id=clean(client_process_id),
        cwd=clean(client_cwd),
        shell=clean(client_shell),
        shell_version=clean(client_shell_version),
    )


def _cwd_inside_project(cwd: str) -> bool:
    """True only for an absolute declared CWD that resolves inside the known root."""
    try:
        candidate = Path(cwd)
        if not candidate.is_absolute():
            return False  # a relative client CWD has no trustworthy anchor (E3)
        root = Path(project_root())
        return candidate.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def declare_client_terminal(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[Fact, ...]:
    """Record declared client facts, corroborate an in-root CWD, return current state.

    Corroboration upgrades trust only, never source (contract §7 rule 1), and
    only when the declared absolute path resolves inside the known project
    root; anything else stays ``untrusted`` (test-plan E2/E3).
    """
    declare(store, identity, observed_at=observed_at)
    if identity.cwd is not None and _cwd_inside_project(identity.cwd):
        current = resolve(
            store,
            "terminal.cwd",
            terminal_session=identity.session_id,
            process_id=identity.process_id,
            observed_at=observed_at,
        )
        if (
            current.source is Source.CLIENT_DECLARED
            and current.trust is Trust.UNTRUSTED
        ):
            store.record(
                corroborate(current, evidence="inside the known root")
            )
    return client_terminal_facts(store, identity, observed_at=observed_at)


def client_terminal_facts(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[Fact, ...]:
    """Resolve the contract §5 environment-relevant fields for ONE identity."""
    return tuple(
        resolve(
            store,
            observation,
            terminal_session=identity.session_id,
            process_id=identity.process_id,
            observed_at=observed_at,
        )
        for observation in ENVIRONMENT_CLIENT_FIELDS
    )


def client_terminal_all_facts(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[Fact, ...]:
    """All six contract §8 terminal fields, including console code page."""
    return tuple(
        resolve(
            store,
            observation,
            terminal_session=identity.session_id,
            process_id=identity.process_id,
            observed_at=observed_at,
        )
        for observation in TERMINAL_FIELDS
    )


def cwd_directive(cwd_fact: Fact) -> str | None:
    """Decision S1 degraded-mode directive; None once a trusted CWD exists."""
    if cwd_fact.value == VALUE_UNKNOWN or cwd_fact.trust is Trust.UNTRUSTED:
        return DIRECTIVE_EXPLICIT_PATH
    return None


# --- report assembly ---------------------------------------------------------

# (heading, facts, notes) — rendered by the thin adapter through formatting.py.
ReportSection = tuple[str, tuple[Fact, ...], tuple[str, ...]]


def _select(facts: tuple[Fact, ...], names: Sequence[str]) -> tuple[Fact, ...]:
    by_name = {fact.observation: fact for fact in facts}
    return tuple(by_name[name] for name in names if name in by_name)


def build_environment_report(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[ReportSection, ...]:
    """Environment Contract sections (contract §5) with source/trust labels."""
    env = collect_environment(store)
    client = declare_client_terminal(store, identity, observed_at=observed_at)
    server = server_process_facts(store)
    client_cwd = next(f for f in client if f.observation == "terminal.cwd")
    directive = cwd_directive(client_cwd)

    sections: list[ReportSection] = [
        ("PROJECT ROOT", _select(env, (OBS_PROJECT_ROOT,)), ()),
        (
            "OS / PYTHON (stdlib)",
            _select(env, (OBS_OS_FAMILY, OBS_OS_VERSION, OBS_PYTHON_VERSION)),
            (),
        ),
        (
            "EXECUTABLES ON PATH (shutil.which - presence only)",
            _select(env, tuple(obs_which(n) for n in EXECUTABLE_NAMES)),
            (),
        ),
        (
            "VERSIONS & BASELINES (fixed-argv probes - machine capability)",
            _select(
                env,
                tuple(obs_version(n) for n in EXECUTABLE_NAMES)
                + (OBS_BASELINE_POWERSHELL, OBS_BASELINE_PWSH),
            ),
            (NOTE_MACHINE_BASELINE,),
        ),
        ("GIT REPOSITORY", _select(env, (OBS_GIT_TOPLEVEL,)), ()),
        (
            f"SERVER PROCESS (subject={SERVER_SUBJECT} - not the client terminal)",
            server,
            (),
        ),
        (
            "CLIENT TERMINAL (declared inputs only)",
            client,
            (directive,) if directive else (),
        ),
        ("PROBE CONTRACT", (), (NOTE_PROBE_CONTRACT,)),
    ]
    return tuple(sections)


def build_terminal_report(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[ReportSection, ...]:
    """Terminal identity report: server vs client, never conflated (contract §8)."""
    declare_client_terminal(store, identity, observed_at=observed_at)
    client_all = client_terminal_all_facts(store, identity, observed_at=observed_at)
    server = server_process_facts(store)
    client_cwd = next(f for f in client_all if f.observation == "terminal.cwd")
    directive = cwd_directive(client_cwd)
    notes = [DIRECTIVE_MULTI_TERMINAL]
    if directive:
        notes.append(directive)
    return (
        (
            f"SERVER PROCESS (subject={SERVER_SUBJECT} - never the client terminal)",
            server,
            (),
        ),
        (
            "CLIENT TERMINAL (CLIENT_DECLARED only; unknown when not declared)",
            client_all,
            (),
        ),
        ("SCOPE / DIRECTIVES", (), tuple(notes)),
    )


def build_context_report(
    store: ObservationStore,
    identity: TerminalIdentity,
    *,
    observed_at: str,
) -> tuple[ReportSection, ...]:
    """Compact shell-intelligence context (contract §5) assembled from P1 + P2 state.

    Distinguishes repository, worktree, server process, client terminal and
    environment, then reports freshness/trust counts, every explicit unknown,
    and the standing directives. No confidence score, no completeness claim,
    no wall-clock content.
    """
    env = collect_environment(store)
    client = declare_client_terminal(store, identity, observed_at=observed_at)
    server = server_process_facts(store)

    repository = _select(env, (OBS_PROJECT_ROOT, OBS_GIT_TOPLEVEL))
    condensed_env = _select(
        env,
        (
            OBS_OS_FAMILY,
            OBS_OS_VERSION,
            OBS_PYTHON_VERSION,
            obs_version("git"),
            obs_version("node"),
            obs_version("pwsh"),
            obs_version("powershell"),
            OBS_BASELINE_POWERSHELL,
            OBS_BASELINE_PWSH,
        ),
    )
    all_facts = repository + server + client + condensed_env
    unknowns = tuple(
        fact
        for fact in all_facts
        if fact.value == VALUE_UNKNOWN or fact.source is Source.UNKNOWN
    )

    trust_counts: dict[str, int] = {trust.value: 0 for trust in Trust}
    freshness_counts: dict[str, int] = {fresh.value: 0 for fresh in Freshness}
    for fact in all_facts:
        trust_counts[fact.trust.value] += 1
        freshness_counts[fact.freshness.value] += 1
    trust_note = "trust: " + " ".join(
        f"{key}={trust_counts[key]}"
        for key in ("trusted", "corroborated", "untrusted", "unknown")
    )
    freshness_note = "freshness: " + " ".join(
        f"{key}={freshness_counts[key]}"
        for key in ("STATIC", "SESSION", "WORKTREE", "PROCESS", "EPHEMERAL")
    )

    client_cwd = next(f for f in client if f.observation == "terminal.cwd")
    directive = cwd_directive(client_cwd)
    directives = [DIRECTIVE_MULTI_TERMINAL]
    if directive:
        directives.append(directive)

    return (
        ("REPOSITORY", repository, ()),
        (
            "WORKTREE",
            (),
            (
                "worktree: unknown - no WORKTREE-scoped observation exists in P2 "
                "(git status is not probed by this phase)",
            ),
        ),
        (
            f"SERVER PROCESS (subject={SERVER_SUBJECT} - not the client terminal)",
            server,
            (),
        ),
        (
            "CLIENT TERMINAL (declared inputs only; unknown when not declared)",
            client,
            (),
        ),
        ("ENVIRONMENT (machine capability - never the client's shell)", condensed_env, ()),
        ("FRESHNESS / TRUST", (), (trust_note, freshness_note)),
        ("UNKNOWNS", unknowns, ()),
        ("DIRECTIVES", (), tuple(directives)),
    )


def report_facts(sections: Sequence[ReportSection]) -> tuple[Fact, ...]:
    """Every fact across ``sections`` in section order (deterministic)."""
    return tuple(fact for _heading, facts, _notes in sections for fact in facts)


def report_unknown_count(sections: Sequence[ReportSection]) -> int:
    """Number of rendered facts whose value is unknown."""
    return sum(
        1
        for fact in report_facts(sections)
        if fact.value == VALUE_UNKNOWN or fact.source is Source.UNKNOWN
    )
