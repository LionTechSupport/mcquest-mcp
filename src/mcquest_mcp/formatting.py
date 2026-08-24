from __future__ import annotations

from .config import MAX_OUTPUT_CHARS


def truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text

    return (
        text[:limit]
        + "\n\n"
        + f"[OUTPUT TRUNCATED: {len(text) - limit:,} characters omitted]"
    )


def numbered_lines(
    text: str,
    start_line: int = 1,
    end_line: int | None = None,
) -> str:
    lines = text.splitlines()

    start_index = max(start_line - 1, 0)

    if end_line is None:
        selected = lines[start_index:]
    else:
        selected = lines[start_index:end_line]

    output = []

    for index, line in enumerate(
        selected,
        start=start_index + 1,
    ):
        output.append(f"{index:6}: {line}")

    return truncate("\n".join(output))