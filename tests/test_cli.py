"""Regression: ``--project`` CLI bootstrap and project-root selection.

The console script points at ``mcquest_mcp.cli:main``. These tests pin the
selected-root behavior without launching a long-running stdio server: they
exercise the resolution rule (``--project`` > ``MCQUEST_PROJECT_ROOT`` > fail)
and verify that ``main`` establishes ``MCQUEST_PROJECT_ROOT`` before the server
is imported.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

from mcquest_mcp import cli


def test_explicit_project_becomes_the_root(tmp_path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    selected = cli.resolve_project_root(str(project_dir), None)
    assert selected == project_dir.resolve()
    assert selected.is_absolute()


def test_environment_variable_selected_when_no_project(tmp_path) -> None:
    project_dir = tmp_path / "env-repo"
    project_dir.mkdir()
    selected = cli.resolve_project_root(None, str(project_dir))
    assert selected == project_dir.resolve()


def test_dash_project_overrides_environment_variable(tmp_path) -> None:
    env_dir = tmp_path / "env-repo"
    flag_dir = tmp_path / "flag-repo"
    env_dir.mkdir()
    flag_dir.mkdir()
    selected = cli.resolve_project_root(str(flag_dir), str(env_dir))
    assert selected == flag_dir.resolve()
    assert selected != env_dir.resolve()


def test_relative_project_resolved_to_absolute(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    selected = cli.resolve_project_root("relative-repo", None)
    assert selected.is_absolute()
    assert selected.name == "relative-repo"


def test_missing_configuration_fails_loudly(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="project root"):
        cli.resolve_project_root(None, None)


def _stub_server(monkeypatch) -> dict:
    """Replace ``mcquest_mcp.server`` with a record-only stub and return a recorder."""
    recorded: dict[str, bool] = {"ran": False}
    fake_mcp = types.SimpleNamespace(run=lambda: recorded.update(ran=True))
    fake_module = types.ModuleType("mcquest_mcp.server")
    fake_module.mcp = fake_mcp
    monkeypatch.setitem(sys.modules, "mcquest_mcp.server", fake_module)
    return recorded


def test_main_sets_root_from_project_and_runs(monkeypatch, tmp_path) -> None:
    project_dir = tmp_path / "repo"
    project_dir.mkdir()
    recorded = _stub_server(monkeypatch)
    monkeypatch.setenv("MCQUEST_PROJECT_ROOT", "C:\\ignored\\env")
    monkeypatch.setattr("sys.argv", ["mcquest-mcp", "--project", str(project_dir)])

    cli.main()

    assert recorded["ran"] is True
    assert os.environ["MCQUEST_PROJECT_ROOT"] == str(project_dir.resolve())


def test_main_uses_environment_when_no_project(monkeypatch, tmp_path) -> None:
    env_dir = tmp_path / "env-repo"
    env_dir.mkdir()
    recorded = _stub_server(monkeypatch)
    monkeypatch.setenv("MCQUEST_PROJECT_ROOT", str(env_dir))
    monkeypatch.setattr("sys.argv", ["mcquest-mcp"])

    cli.main()

    assert recorded["ran"] is True
    assert os.environ["MCQUEST_PROJECT_ROOT"] == str(env_dir.resolve())


def test_main_fails_when_no_configuration(monkeypatch) -> None:
    _stub_server(monkeypatch)
    monkeypatch.delenv("MCQUEST_PROJECT_ROOT", raising=False)
    monkeypatch.setattr("sys.argv", ["mcquest-mcp"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2