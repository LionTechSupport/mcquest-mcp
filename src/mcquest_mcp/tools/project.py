from __future__ import annotations

from pathlib import Path

from ..config import IGNORED_DIRECTORIES
from ..formatting import truncate
from ..security import project_root


def project_info() -> str:
    """
    Return a compact deterministic overview of the MCQuest project.
    """

    root = project_root()

    important_files = [
        "frontend/package.json",
        "frontend/vite.config.ts",
        "frontend/tailwind.config.js",
        "frontend/capacitor.config.ts",
        "frontend/index.html",
        "frontend/src/App.tsx",
        "frontend/src/components/UnifiedLayout.tsx",
        "frontend/src/styles/globals.css",
    ]

    existing = []

    for relative in important_files:
        path = root / relative

        if path.exists():
            existing.append(relative)

    top_level = []

    try:
        for item in sorted(root.iterdir()):
            if item.name in IGNORED_DIRECTORIES:
                continue

            suffix = "/" if item.is_dir() else ""

            top_level.append(
                item.name + suffix
            )
    except OSError:
        pass

    return truncate(
        "MCQUEST PROJECT\n"
        "================\n"
        f"ROOT: {root}\n\n"
        "TOP-LEVEL:\n"
        + "\n".join(
            f"- {item}"
            for item in top_level
        )
        + "\n\nIMPORTANT FILES:\n"
        + "\n".join(
            f"- {item}"
            for item in existing
        )
    )