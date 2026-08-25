"""Shared fixtures for the mcquest-mcp regression suite.

The package resolves its project root once, at import time, from the
``MCQUEST_PROJECT_ROOT`` environment variable.  Tests therefore pin that
variable to a fresh temporary directory before any ``mcquest_mcp`` module is
imported in the test process.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest


TEST_ROOT = tempfile.mkdtemp(prefix="mcquest_mcp_test_")
os.environ["MCQUEST_PROJECT_ROOT"] = TEST_ROOT
atexit.register(lambda: shutil.rmtree(TEST_ROOT, ignore_errors=True))


@pytest.fixture(autouse=True)
def _clean_test_root() -> None:
    """Give every test a pristine temporary project root."""
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
    Path(TEST_ROOT).mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def repo() -> str:
    """Return the temporary project root used as ``MCQUEST_PROJECT_ROOT``."""
    return TEST_ROOT


@pytest.fixture
def write_file(repo: str):
    """Write a project-relative file and return its relative POSIX path."""

    def _write(relative_path: str, content: str) -> str:
        full = os.path.join(repo, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(content)
        return os.path.relpath(full, repo).replace(os.sep, "/")

    return _write