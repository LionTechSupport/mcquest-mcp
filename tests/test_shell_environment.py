"""P2 environment tests: Environment Contract + approved fixed-argv probes.

Covers test-plan §5 (E1-E9) plus the authorization's probe-safety contract:
fixed argv, ``shell=False``, timeout bound, explicit UTF-8 decoding with
replacement, ``check=False``, failure -> UNKNOWN, no stale evidence after a
failure, provenance labels, and P1 observation reuse (no wall-clock TTL).
All probes are mocked — no test executes a real subprocess.
"""

from __future__ import annotations

import platform
import subprocess

import pytest

from mcquest_mcp.security import project_root
from mcquest_mcp.shell import environment
from mcquest_mcp.shell.facts import (
    VALUE_UNKNOWN,
    Freshness,
    Scope,
    Source,
    Trust,
)
from mcquest_mcp.shell.invalidate import InvalidationEvent, apply_invalidation
from mcquest_mcp.shell.store import ObservationStore
from mcquest_mcp.shell.terminal import SERVER_SUBJECT, resolve


@pytest.fixture(autouse=True)
def _clean_store() -> None:
    """No state may leak between tests (S11/S3 restart semantics)."""
    environment.reset_store()
    yield
    environment.reset_store()


APPROVED_ARGVS = (
    environment.GIT_VERSION_ARGV,
    environment.GIT_TOPLEVEL_ARGV,
    environment.NODE_VERSION_ARGV,
    environment.PWSH_VERSION_ARGV,
    environment.POWERSHELL_VERSION_ARGV,
)

DEFAULT_PATHS = {
    "git": "C:/Tools/git/cmd/git.exe",
    "node": "C:/Tools/nodejs/node.exe",
    "pwsh": "C:/Tools/pwsh/pwsh.exe",
    "powershell": "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
}

DEFAULT_RESPONSES = {
    environment.GIT_VERSION_ARGV: (b"git version 2.49.0\r\n", 0),
    environment.GIT_TOPLEVEL_ARGV: (b"D:/repo\r\n", 0),
    environment.NODE_VERSION_ARGV: (b"v22.14.0\n", 0),
    environment.PWSH_VERSION_ARGV: (b"7.6.2\n", 0),
    environment.POWERSHELL_VERSION_ARGV: (b"5.1.26100.9444\r\n", 0),
}


class _FakeCompleted:
    def __init__(self, stdout: bytes, returncode: int) -> None:
        self.stdout = stdout
        self.returncode = returncode


def install_probe_mock(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict | None = None,
    paths: dict | None = None,
    *,
    fail_argv: dict | None = None,
) -> list:
    """Patch shutil.which + subprocess.run; return the recorded call list.

    ``responses`` maps argv tuple -> (stdout, returncode) or a list of such
    pairs consumed in order (the last entry repeats). ``fail_argv`` maps argv
    tuple -> exception to raise.
    """
    responses = DEFAULT_RESPONSES if responses is None else responses
    paths = DEFAULT_PATHS if paths is None else paths
    fail_argv = fail_argv or {}
    cursors: dict = {}
    calls: list = []

    def fake_which(name: str):
        return paths.get(name)

    def fake_run(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        key = tuple(argv)
        if key in fail_argv:
            raise fail_argv[key]
        if key not in responses:
            raise AssertionError(f"unexpected probe argv: {argv!r}")
        entry = responses[key]
        if isinstance(entry, list):
            index = cursors.get(key, 0)
            entry = entry[min(index, len(entry) - 1)]
            cursors[key] = index + 1
        stdout, returncode = entry
        return _FakeCompleted(stdout, returncode)

    monkeypatch.setattr(environment.shutil, "which", fake_which)
    monkeypatch.setattr(environment.subprocess, "run", fake_run)
    return calls


def _fact(store: ObservationStore, observation: str, scope: Scope, subject):
    fact = store.lookup(observation, scope, subject)
    assert fact is not None, f"missing fact {observation}"
    return fact


def test_project_root_fact_uses_config_convention(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(store, environment.OBS_PROJECT_ROOT, Scope.REPOSITORY, None)
    assert fact.value == str(project_root())
    assert fact.source is Source.SERVER_OBSERVED
    assert fact.trust is Trust.TRUSTED
    assert fact.scope is Scope.REPOSITORY
    assert fact.freshness is Freshness.STATIC
    assert "MCQUEST_PROJECT_ROOT" in fact.evidence


def test_os_and_python_facts_come_from_stdlib(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    os_family = _fact(store, environment.OBS_OS_FAMILY, Scope.SESSION, SERVER_SUBJECT)
    python = _fact(
        store, environment.OBS_PYTHON_VERSION, Scope.SESSION, SERVER_SUBJECT
    )
    assert os_family.value == platform.system()
    assert python.value == platform.python_version()
    assert "stdlib" in os_family.evidence
    assert "stdlib" in python.evidence


def test_executable_presence_facts_match_declared_paths(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    for name, path in DEFAULT_PATHS.items():
        fact = _fact(store, environment.obs_which(name), Scope.SESSION, SERVER_SUBJECT)
        assert fact.value == path
        assert fact.source is Source.SERVER_OBSERVED
        assert "shutil.which" in fact.evidence


def test_missing_executable_is_unknown_and_never_probed(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch, paths=dict(DEFAULT_PATHS, pwsh=None))
    store = environment.get_store()
    environment.collect_environment(store)
    presence = _fact(store, environment.obs_which("pwsh"), Scope.SESSION, SERVER_SUBJECT)
    version = _fact(store, environment.obs_version("pwsh"), Scope.SESSION, SERVER_SUBJECT)
    for fact in (presence, version):
        assert fact.value == VALUE_UNKNOWN
        assert fact.source is Source.UNKNOWN
        assert fact.trust is Trust.UNTRUSTED
    assert "shutil.which('pwsh'): no match" in presence.evidence
    assert "not on PATH" in version.evidence
    assert list(environment.PWSH_VERSION_ARGV) not in calls


def test_node_probe_uses_fixed_argv_and_reports_version(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert fact.value == "v22.14.0"
    assert fact.source is Source.SERVER_OBSERVED
    assert fact.trust is Trust.TRUSTED
    assert environment.NODE_VERSION_ARGV == ("node", "--version")
    assert any(argv == list(environment.NODE_VERSION_ARGV) for argv, _ in calls)


def test_git_probes_version_and_repository_toplevel(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    version = _fact(store, environment.obs_version("git"), Scope.SESSION, SERVER_SUBJECT)
    toplevel = _fact(store, environment.OBS_GIT_TOPLEVEL, Scope.REPOSITORY, None)
    assert version.value.startswith("git version")
    assert toplevel.value == "D:/repo"
    assert toplevel.source is Source.SERVER_OBSERVED
    assert toplevel.trust is Trust.TRUSTED
    assert toplevel.repository == str(project_root())


def test_git_toplevel_failure_is_unknown_without_losing_version(monkeypatch) -> None:
    install_probe_mock(
        monkeypatch,
        responses={
            **DEFAULT_RESPONSES,
            environment.GIT_TOPLEVEL_ARGV: (b"", 128),
        },
    )
    store = environment.get_store()
    environment.collect_environment(store)
    version = _fact(store, environment.obs_version("git"), Scope.SESSION, SERVER_SUBJECT)
    toplevel = _fact(store, environment.OBS_GIT_TOPLEVEL, Scope.REPOSITORY, None)
    assert version.source is Source.SERVER_OBSERVED  # independent probe survives
    assert toplevel.value == VALUE_UNKNOWN
    assert toplevel.source is Source.UNKNOWN
    assert "exit-128" in toplevel.evidence


def test_powershell51_probe_uses_authorized_fixed_literal(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    assert environment.POWERSHELL_VERSION_ARGV == (
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$PSVersionTable.PSVersion.ToString()",
    )
    matching = [argv for argv, _ in calls if argv[0] == "powershell.exe"]
    assert matching == [list(environment.POWERSHELL_VERSION_ARGV)]
    fact = _fact(
        store, environment.obs_version("powershell"), Scope.SESSION, SERVER_SUBJECT
    )
    assert fact.value == "5.1.26100.9444"


def test_pwsh_probe_uses_version_flag_without_command(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch)
    environment.collect_environment(environment.get_store())
    matching = [argv for argv, _ in calls if argv[0] == "pwsh"]
    assert matching == [["pwsh", "-Version"]]
    assert "-Command" not in matching[0]


def test_only_the_powershell51_probe_may_contain_command(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    environment.collect_environment(environment.get_store())
    for argv in APPROVED_ARGVS:
        if argv is environment.POWERSHELL_VERSION_ARGV:
            assert "-Command" in argv
        else:
            assert "-Command" not in argv


def test_probe_discipline_shell_false_timeout_check_and_cwd(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch)
    environment.collect_environment(environment.get_store())
    assert calls, "expected at least one probe call"
    for argv, kwargs in calls:
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        assert tuple(argv) in APPROVED_ARGVS
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= environment.PROBE_TIMEOUT_SECONDS <= 10
        assert kwargs["check"] is False
        assert kwargs["cwd"] == str(project_root())
        assert kwargs["capture_output"] is True
        assert "cmd" != argv[0]


def test_nonzero_exit_yields_unknown(monkeypatch) -> None:
    install_probe_mock(
        monkeypatch,
        responses={**DEFAULT_RESPONSES, environment.NODE_VERSION_ARGV: (b"", 1)},
    )
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert fact.value == VALUE_UNKNOWN
    assert fact.source is Source.UNKNOWN
    assert "exit-1" in fact.evidence


def test_timeout_yields_unknown(monkeypatch) -> None:
    install_probe_mock(
        monkeypatch,
        fail_argv={
            environment.NODE_VERSION_ARGV: subprocess.TimeoutExpired(
                list(environment.NODE_VERSION_ARGV), environment.PROBE_TIMEOUT_SECONDS
            )
        },
    )
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert fact.value == VALUE_UNKNOWN
    assert fact.source is Source.UNKNOWN
    assert "timeout" in fact.evidence


def test_invalid_utf8_is_decoded_with_visible_replacement(monkeypatch) -> None:
    install_probe_mock(
        monkeypatch,
        responses={
            **DEFAULT_RESPONSES,
            environment.NODE_VERSION_ARGV: (b"v9\xff\xfe.0.0\n", 0),
        },
    )
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert "�" in fact.value  # errors="replace" — visible, never silent
    assert fact.value.startswith("v9")


def test_probe_output_is_bounded(monkeypatch) -> None:
    install_probe_mock(
        monkeypatch,
        responses={
            **DEFAULT_RESPONSES,
            environment.NODE_VERSION_ARGV: (b"x" * 100_000, 0),
        },
    )
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert len(fact.value) <= environment.MAX_PROBE_OUTPUT_CHARS


def test_failed_probe_leaves_no_stale_evidence(monkeypatch) -> None:
    calls = install_probe_mock(
        monkeypatch,
        responses={
            **DEFAULT_RESPONSES,
            environment.NODE_VERSION_ARGV: [
                (b"v1.0.0\n", 0),  # first observation succeeds
                (b"", 3),  # after invalidation the probe fails
            ],
        },
    )
    store = environment.get_store()
    environment.collect_environment(store)
    before = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert before.value == "v1.0.0"
    apply_invalidation(store, InvalidationEvent.DEPENDENCY_INSTALL)
    environment.collect_environment(store)
    after = _fact(store, environment.obs_version("node"), Scope.SESSION, SERVER_SUBJECT)
    assert after.value == VALUE_UNKNOWN  # never the retained v1.0.0
    assert after.source is Source.UNKNOWN
    node_calls = [a for a, _ in calls if a == list(environment.NODE_VERSION_ARGV)]
    assert len(node_calls) == 2


def test_observation_reuse_prevents_reprobe(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    first = len(calls)
    assert first == 5  # git version, git toplevel, node, pwsh, powershell
    environment.collect_environment(store)
    assert len(calls) == first  # reused — observe once (contract §12/§20)


def test_invalidation_forces_a_fresh_probe(monkeypatch) -> None:
    calls = install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    first = len(calls)
    apply_invalidation(store, InvalidationEvent.DEPENDENCY_INSTALL)
    environment.collect_environment(store)
    assert len(calls) > first


def test_failed_probe_result_is_recorded_and_reused(monkeypatch) -> None:
    calls = install_probe_mock(
        monkeypatch,
        responses={**DEFAULT_RESPONSES, environment.NODE_VERSION_ARGV: (b"", 9)},
    )
    store = environment.get_store()
    environment.collect_environment(store)
    environment.collect_environment(store)
    node_calls = [a for a, _ in calls if a == list(environment.NODE_VERSION_ARGV)]
    assert len(node_calls) == 1  # the UNKNOWN result is cached, not re-attempted


def test_powershell_baseline_derivation_is_deterministic() -> None:
    assert environment.powershell_baseline("5.1.26100.9444") == "ps5.1"
    assert environment.powershell_baseline("7.6.2") == "ps7"
    assert environment.powershell_baseline("6.2.7") == "unknown"
    assert environment.powershell_baseline("") == "unknown"
    assert environment.powershell_baseline("garbage") == "unknown"


def test_baseline_facts_derive_only_from_successful_versions(monkeypatch) -> None:
    install_probe_mock(monkeypatch)  # pwsh responds 7.6.2; powershell 5.1.x
    store = environment.get_store()
    environment.collect_environment(store)
    ps51 = _fact(
        store, environment.OBS_BASELINE_POWERSHELL, Scope.SESSION, SERVER_SUBJECT
    )
    pwsh = _fact(store, environment.OBS_BASELINE_PWSH, Scope.SESSION, SERVER_SUBJECT)
    assert ps51.value == "ps5.1"
    assert ps51.source is Source.SERVER_OBSERVED
    assert pwsh.value == "ps7"


def test_baseline_is_unknown_when_version_is_unknown(monkeypatch) -> None:
    install_probe_mock(monkeypatch, paths=dict(DEFAULT_PATHS, powershell=None))
    store = environment.get_store()
    environment.collect_environment(store)
    fact = _fact(
        store, environment.OBS_BASELINE_POWERSHELL, Scope.SESSION, SERVER_SUBJECT
    )
    assert fact.value == VALUE_UNKNOWN
    assert fact.source is Source.UNKNOWN
    assert "baseline not derived" in fact.evidence


def test_shell_baselines_are_machine_capability_never_client_shell(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    environment.collect_environment(store)
    machine = _fact(
        store, environment.obs_version("powershell"), Scope.SESSION, SERVER_SUBJECT
    )
    assert machine.subject == SERVER_SUBJECT  # labeled machine capability (E5)
    client_shell = resolve(store, "terminal.shell", observed_at="2026-01-01T00:00:00Z")
    assert client_shell.value == VALUE_UNKNOWN  # machine facts never leak (E5)


def test_server_process_facts_never_served_as_client_state(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    server_cwd, server_pid = environment.server_process_facts(store)
    assert server_cwd.subject == SERVER_SUBJECT
    assert server_pid.subject == SERVER_SUBJECT
    assert server_cwd.source is Source.SERVER_OBSERVED
    served = resolve(store, "terminal.cwd", observed_at="2026-01-01T00:00:00Z")
    assert served.value == VALUE_UNKNOWN  # mcp_server fact is never served (E6)
    assert served.subject != SERVER_SUBJECT


def test_degraded_cold_start_reports_unknown_cwd_with_directive(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    identity = environment.normalize_identity()
    sections = environment.build_environment_report(
        store, identity, observed_at=environment.observed_now()
    )
    facts = environment.report_facts(sections)
    client_cwd = [
        f
        for f in facts
        if f.observation == "terminal.cwd" and f.subject != SERVER_SUBJECT
    ]
    assert client_cwd and client_cwd[0].value == VALUE_UNKNOWN
    assert client_cwd[0].source is Source.UNKNOWN
    assert client_cwd[0].trust is Trust.UNTRUSTED
    notes = [note for _h, _f, ns in sections for note in ns]
    assert environment.DIRECTIVE_EXPLICIT_PATH in notes  # E1: not a hard failure


def test_declared_cwd_is_client_declared_and_corroborated_inside_root(
    monkeypatch,
) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    identity = environment.normalize_identity(
        client_session="A",
        client_process_id="1",
        client_cwd=str(project_root()),
    )
    facts = environment.declare_client_terminal(
        store, identity, observed_at=environment.observed_now()
    )
    cwd = next(f for f in facts if f.observation == "terminal.cwd")
    assert cwd.source is Source.CLIENT_DECLARED  # E2: corroboration never re-labels
    assert cwd.trust is Trust.CORROBORATED  # E3: inside the known root


def test_declared_cwd_outside_root_stays_untrusted(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    identity = environment.normalize_identity(
        client_session="A",
        client_process_id="1",
        client_cwd="C:\\elsewhere\\not-the-repo",
    )
    facts = environment.declare_client_terminal(
        store, identity, observed_at=environment.observed_now()
    )
    cwd = next(f for f in facts if f.observation == "terminal.cwd")
    assert cwd.source is Source.CLIENT_DECLARED
    assert cwd.trust is Trust.UNTRUSTED  # E3: outside stays untrusted


def test_relative_declared_cwd_is_never_corroborated(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    store = environment.get_store()
    identity = environment.normalize_identity(
        client_session="A", client_process_id="1", client_cwd="subdir"
    )
    facts = environment.declare_client_terminal(
        store, identity, observed_at=environment.observed_now()
    )
    cwd = next(f for f in facts if f.observation == "terminal.cwd")
    assert cwd.trust is Trust.UNTRUSTED  # no anchor — the server CWD is not assumed


def test_identity_normalization_strips_and_maps_empty_to_none() -> None:
    identity = environment.normalize_identity(
        client_session="  A  ",
        client_process_id="",
        client_cwd="   ",
        client_shell="PowerShell",
    )
    assert identity.session_id == "A"
    assert identity.process_id is None
    assert identity.cwd is None
    assert identity.shell == "PowerShell"
    assert identity.shell_version is None


def test_collect_environment_runs_no_subprocess_when_nothing_is_on_path(
    monkeypatch,
) -> None:
    calls = install_probe_mock(monkeypatch, paths={})
    store = environment.get_store()
    facts = environment.collect_environment(store)
    assert facts  # stdlib + which-derived unknowns still assemble
    assert calls == []  # presence gate: no probe for a missing executable


def test_run_probe_rejects_degenerate_argv(monkeypatch) -> None:
    install_probe_mock(monkeypatch)
    with pytest.raises(TypeError):
        environment.run_probe("node --version", cwd=project_root())
    with pytest.raises(ValueError):
        environment.run_probe((), cwd=project_root())
    with pytest.raises(ValueError):
        environment.run_probe(("",), cwd=project_root())
