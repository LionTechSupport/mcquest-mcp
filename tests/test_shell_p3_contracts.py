"""Cross-cutting P3 safety, registration, and phase-boundary tests."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from mcquest_mcp.server import mcp

from test_registration import EXPECTED_TOOLS

SHELL = Path(__file__).resolve().parent.parent / "src" / "mcquest_mcp" / "shell"
P3_MODULES = {
    "operations.py",
    "dialect.py",
    "native.py",
    "parse.py",
    "encoding.py",
    "hazards.py",
    "hygiene.py",
    "redundancy.py",
}
FUTURE_TOOLS = {
    "mcquest_shell_plan",
    "mcquest_shell_prepare",
    "mcquest_shell_validate",
    "mcquest_shell_observe",
    "mcquest_shell_history",
    "mcquest_shell_next",
}


def _p3_sources() -> list[Path]:
    return [SHELL / name for name in sorted(P3_MODULES)]


def test_exactly_the_eight_authorized_p3_modules_exist() -> None:
    assert {path.name for path in _p3_sources() if path.exists()} == P3_MODULES
    assert not (SHELL / "planner.py").exists()
    assert not (SHELL / "validate.py").exists()


def test_p3_keeps_the_registration_surface_at_exactly_28() -> None:
    names = sorted(tool.name for tool in asyncio.run(mcp.list_tools()))
    assert names == EXPECTED_TOOLS
    assert len(names) == 28
    assert set(names).isdisjoint(FUTURE_TOOLS)


def test_no_p3_tool_or_future_phase_tool_is_registered() -> None:
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert not any(name.startswith("mcquest_shell_analyze") for name in names)
    assert names.isdisjoint(FUTURE_TOOLS)


def test_p3_modules_have_no_process_network_or_clock_imports() -> None:
    forbidden_imports = {
        "subprocess", "socket", "requests", "urllib", "http", "time", "datetime"
    }
    for path in _p3_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] not in forbidden_imports
                    for alias in node.names
                ), path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_imports, path


def test_p3_modules_have_no_execution_or_mutation_calls() -> None:
    forbidden_calls = {
        "run", "Popen", "system", "popen", "write_text", "write_bytes",
        "unlink", "remove", "rename", "rmtree", "mkdir", "touch",
    }
    for path in _p3_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", "")
                )
                assert name not in forbidden_calls, (path.name, name)
                if isinstance(node.func, ast.Attribute):
                    assert not any(
                        keyword.arg == "shell" for keyword in node.keywords
                    ), path.name


def test_p3_does_not_duplicate_state_environment_or_registry_models() -> None:
    forbidden_classes = {
        "Fact", "Observation", "ObservationStore", "TerminalIdentity",
        "Capability", "EnvironmentContract",
    }
    for path in _p3_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        assert classes.isdisjoint(forbidden_classes), path.name


def test_p3_has_no_numeric_confidence_or_wall_clock_ttl_fields() -> None:
    forbidden_names = {"confidence", "ttl", "expires_at", "risk_score"}
    for path in _p3_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.attr if isinstance(node, ast.Attribute) else node.id
                assert name not in forbidden_names
            elif isinstance(node, ast.arg):
                assert node.arg not in forbidden_names


def test_p3_modules_do_not_import_planner_validator_or_registration_layers() -> None:
    forbidden_roots = {"planner", "validate", "server", "tools"}
    for path in _p3_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[-1] not in forbidden_roots, path.name


def test_p3_source_contains_no_future_tool_registration_names() -> None:
    for path in _p3_sources():
        text = path.read_text(encoding="utf-8")
        assert not any(tool in text for tool in FUTURE_TOOLS), path.name
