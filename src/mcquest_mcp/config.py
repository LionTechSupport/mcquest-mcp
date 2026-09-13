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

# Phase C discovery bounds (see Docs/V0.5/02-V0.5-IMPLEMENTATION-PLAN.md
# Phase C): default page size and absolute per-page hard cap for the
# list_files / list_docs / find_files discovery tools.
DISCOVERY_DEFAULT_RESULTS = 100
DISCOVERY_MAX_RESULTS = 300

# Phase D search/evidence bounds (see Docs/V0.5/05-V0.5-DECISIONS.md
# D016 + approved Phase D plan): default page size for the search tools
# and the approved per-match context hard caps (code 3 / docs 5, Q5).
SEARCH_DEFAULT_RESULTS = 50
SEARCH_CONTEXT_CAP_CODE = 3
SEARCH_CONTEXT_CAP_DOCS = 5

# v0.5 output budgets (see Docs/V0.5/01-V0.5-CONTRACT.md binding
# clarifications and Docs/V0.5/05-V0.5-DECISIONS.md D001/D002/D007):
# - MAX_OUTPUT_CHARS  : ABSOLUTE response ceiling, never exceeded.
# - NORMAL_OUTPUT_CHARS: target presentation budget for a default call.
# - LINE_CLIP_CHARS   : every emitted line is clipped to this length.
MAX_OUTPUT_CHARS = 16_000
NORMAL_OUTPUT_CHARS = 4_000
LINE_CLIP_CHARS = 200