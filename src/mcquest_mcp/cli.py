"""CLI entry point for ``mcquest-mcp``.

The console script is wired to :func:`main`. It parses ``--project`` *before*
the MCP server is imported so the selected project root is established as the
``MCQUEST_PROJECT_ROOT`` environment variable while the server package is still
free of root-importing modules. Only after the root is decided does ``main``
lazily import :mod:`mcquest_mcp.server` (which freezes
``config.DEFAULT_PROJECT_ROOT`` at import time from that variable).

Selected project root precedence:

    --project           (highest)
    MCQUEST_PROJECT_ROOT
    no configuration    -> startup fails loudly
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def resolve_project_root(explicit: str | None, env_value: str | None) -> Path:
    """Return the configured project root as an absolute, normalized path.

    ``explicit`` (from ``--project``) takes precedence over ``env_value`` from
    the ``MCQUEST_PROJECT_ROOT`` environment variable. If neither is supplied a
    :class:`RuntimeError` is raised so the caller can fail startup loudly.
    """
    raw = explicit if explicit else env_value
    if not raw:
        raise RuntimeError(
            "No project root configured. Pass --project <PATH> to select the "
            "repository to inspect, or set the MCQUEST_PROJECT_ROOT environment "
            "variable."
        )
    return Path(raw).expanduser().resolve()


def main() -> None:
    """Start the read-only MCP server confined to the selected project root."""
    parser = argparse.ArgumentParser(
        prog="mcquest-mcp",
        description=(
            "Read-only MCP server confined to a single project root. The root is "
            "selected by --project (absolute or relative) or the "
            "MCQUEST_PROJECT_ROOT environment variable; --project takes precedence."
        ),
    )
    parser.add_argument(
        "--project",
        metavar="PATH",
        help=(
            "Absolute or relative path to the project root the read-only tools "
            "are confined to. Overrides MCQUEST_PROJECT_ROOT."
        ),
    )
    args = parser.parse_args()

    try:
        root = resolve_project_root(
            args.project,
            os.environ.get("MCQUEST_PROJECT_ROOT"),
        )
    except RuntimeError as exc:
        parser.error(str(exc))

    # Establish the root before importing the server: config.DEFAULT_PROJECT_ROOT
    # is frozen from MCQUEST_PROJECT_ROOT when mcquest_mcp.server is imported.
    os.environ["MCQUEST_PROJECT_ROOT"] = str(root)

    # Lazy import keeps the root-importing server out of the entry-point call
    # chain until the project root has been decided above.
    from mcquest_mcp.server import mcp  # noqa: PLC0415

    mcp.run()


if __name__ == "__main__":
    main()