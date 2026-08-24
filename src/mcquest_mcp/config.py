from __future__ import annotations

import os
from pathlib import Path


DEFAULT_PROJECT_ROOT = Path(
    os.environ.get(
        "MCQUEST_PROJECT_ROOT",
        r"D:\App Development\Education_app\MCQuest",
    )
).resolve()


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