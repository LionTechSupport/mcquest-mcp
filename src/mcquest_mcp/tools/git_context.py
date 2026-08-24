"""READ-ONLY Git context tool for MCQuest MCP."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..formatting import truncate
from ..security import project_root


def git_context(
    max_commits: int = 10,
    max_changes: int = 50,
) -> str:
    """Return read-only Git investigation information.

    Provides: current branch, working-tree status, recent commits,
    changed files, relevant commit info.

    DOES NOT perform commits, adds, resets, checkouts, merges,
    rebases, pushes, or pulls.
    """
    root = project_root()

    if not (root / ".git").exists():
        return "GIT CONTEXT: No Git repository found at project root."

    parts: list[str] = []
    parts.append("GIT CONTEXT (READ-ONLY)")
    parts.append("=" * 40)

    # Current branch
    branch = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    parts.append(f"BRANCH: {branch}")

    # Working tree status
    status = _git(root, ["status", "--porcelain"])
    if status:
        status_lines = status.splitlines()
        parts.append(f"UNCOMMITTED CHANGES: {len(status_lines)} file(s)")
        for line in status_lines[:max_changes]:
            parts.append(f"  {line}")
        if len(status_lines) > max_changes:
            parts.append(
                f"  ... and {len(status_lines) - max_changes} more changes"
            )
    else:
        parts.append("UNCOMMITTED CHANGES: (clean)")

    # Recent commits
    max_commits = min(max(max_commits, 1), 50)
    log = _git(
        root,
        [
            "log",
            f"--max-count={max_commits}",
            "--oneline",
            "--no-decorate",
        ],
    )
    parts.append(f"\nRECENT COMMITS (last {max_commits}):")
    for line in log.splitlines():
        parts.append(f"  {line}")

    # Recently changed files
    changed = _git(
        root,
        ["diff", "--name-only", "HEAD~5", "HEAD"],
    )
    if changed and "unknown revision" not in changed.lower():
        changed_files = changed.splitlines()
        parts.append("\nCHANGED FILES (last 5 commits):")
        for f in changed_files[:max_changes]:
            parts.append(f"  {f}")
        if len(changed_files) > max_changes:
            parts.append(
                f"  ... and {len(changed_files) - max_changes} more files"
            )

    parts.append(
        "\n---\nNOTE: Read-only Git inspection. No mutations performed."
    )
    return truncate("\n".join(parts))


def _git(root: Path, args: list[str]) -> str:
    """Run a read-only git command and return stdout as text."""
    try:
        result = subprocess.run(
            ["git", "--no-pager"] + args,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return ""