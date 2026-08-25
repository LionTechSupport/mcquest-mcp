from __future__ import annotations

import os
from pathlib import Path


def _default_project_root() -> Path:
    """Return the configured project root or fail loudly if none is set.

    ``MCQUEST_PROJECT_ROOT`` is the only source of truth for the root here; the
    value is established by the ``mcquest-mcp --project`` bootstrap *before* this
    module is imported. A machine-specific fallback is intentionally avoided so an
    unconfigured server never silently serves the wrong repository.
    """
    raw = os.environ.get("MCQUEST_PROJECT_ROOT")
    if not raw:
        raise RuntimeError(
            "No project root configured. Pass --project <PATH> when launching "
            "mcquest-mcp, or set the MCQUEST_PROJECT_ROOT environment variable "
            "to the repository the read-only tools are confined to."
        )
    return Path(raw).resolve()


DEFAULT_PROJECT_ROOT = _default_project_root()


# Directories that should never be exposed through the read-only tools.
IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
}


# Binary / generated files that are not useful for source auditing.
IGNORED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp3",
    ".mp4",
    ".mov",
}


MAX_FILE_BYTES = 2_000_000
MAX_SEARCH_RESULTS = 500
MAX_OUTPUT_CHARS = 80_000