"""Thin P2 MCP adapters for the four V0.9 shell tools (architecture §8).

Business/state logic lives in ``shell/environment.py`` and
``shell/capabilities.py``; this module only validates declared inputs, calls
the corresponding shell component, and renders through ``formatting.py``
(``summary_block`` + ``truncate``: budgets 4000 default / 16000 absolute /
200-char line clip). Every adapter is READ ONLY: no I/O beyond the approved
fixed-argv probes performed inside ``shell/environment.py``, and no mutation
of any kind.

Client-declared inputs follow decision A2's declared-input set
(``client_session``, ``client_process_id``, ``client_cwd``, ``client_shell``)
plus the contract §5 client-declared shell version
(``client_shell_version``). An empty string always means "not declared".
"""

from __future__ import annotations

from ..config import NORMAL_OUTPUT_CHARS
from ..formatting import summary_block, truncate
from ..shell import environment
from ..shell import capabilities as registry
from ..shell.facts import VALUE_UNKNOWN, Fact
from ..shell.terminal import TerminalIdentity


def _identity(
    *,
    client_session: str,
    client_process_id: str,
    client_cwd: str,
    client_shell: str,
    client_shell_version: str,
) -> TerminalIdentity:
    return environment.normalize_identity(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )


def _fact_line(fact: Fact) -> str:
    value = fact.value if fact.value is not None else VALUE_UNKNOWN
    return (
        f"- {fact.observation}: {value} | {fact.source}/{fact.trust} "
        f"| {fact.scope}/{fact.freshness} | ev: {fact.evidence}"
    )


def _render_report(
    tool: str, fields: dict[str, object], sections: tuple
) -> str:
    """Summary-first render of (heading, facts, notes) sections within budget."""
    body: list[str] = []
    for heading, facts, notes in sections:
        body.append(heading)
        for fact in facts:
            body.append(_fact_line(fact))
        for note in notes:
            body.append(f"note: {note}")
        body.append("")
    text = summary_block(tool, fields) + "\n\n" + "\n".join(body) + "\n[END]"
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)


def shell_environment(
    *,
    client_session: str = "",
    client_process_id: str = "",
    client_cwd: str = "",
    client_shell: str = "",
    client_shell_version: str = "",
) -> str:
    """Environment Contract with source/trust labels (read-only, bounded probes)."""
    store = environment.get_store()
    identity = _identity(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )
    sections = environment.build_environment_report(
        store, identity, observed_at=environment.observed_now()
    )
    facts = environment.report_facts(sections)
    unknowns = environment.report_unknown_count(sections)
    cwd_unknown = any(
        fact.observation == "terminal.cwd" and fact.value == VALUE_UNKNOWN
        for fact in facts
    )
    fields: dict[str, object] = {
        "facts": len(facts),
        "unknowns": unknowns,
        "degraded": "true" if cwd_unknown else "false",
        "probes": "fixed-argv read-only",
        "read_only": "true",
    }
    return _render_report("mcquest_shell_environment", fields, sections)


def shell_terminal(
    *,
    client_session: str = "",
    client_process_id: str = "",
    client_cwd: str = "",
    client_shell: str = "",
    client_shell_version: str = "",
) -> str:
    """Terminal/session/process identity: server vs client, never conflated."""
    store = environment.get_store()
    identity = _identity(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )
    sections = environment.build_terminal_report(
        store, identity, observed_at=environment.observed_now()
    )
    facts = environment.report_facts(sections)
    fields: dict[str, object] = {
        "facts": len(facts),
        "unknowns": environment.report_unknown_count(sections),
        "read_only": "true",
    }
    return _render_report("mcquest_shell_terminal", fields, sections)


def shell_context(
    *,
    client_session: str = "",
    client_process_id: str = "",
    client_cwd: str = "",
    client_shell: str = "",
    client_shell_version: str = "",
) -> str:
    """Compact shell-intelligence context assembled from P1 + P2 state."""
    store = environment.get_store()
    identity = _identity(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )
    sections = environment.build_context_report(
        store, identity, observed_at=environment.observed_now()
    )
    fields: dict[str, object] = {
        "sections": len(sections),
        "unknowns": environment.report_unknown_count(sections),
        "read_only": "true",
    }
    return _render_report("mcquest_shell_context", fields, sections)


def shell_capabilities(offset: int = 0, max_results: int = 10) -> str:
    """Capability registry with intent metadata; EXPECTED_TOOLS stays authoritative."""
    page = registry.capability_page(offset=offset, max_results=max_results)
    implemented, planned = registry.capability_totals()
    fields: dict[str, object] = {
        "implemented": implemented,
        "planned": planned,
        "authority": "EXPECTED_TOOLS",
        "total": page.total,
        "returned": page.returned,
        "offset": page.offset,
        "collection_complete": "true",
        "truncated": "false",
        "budget": f"{NORMAL_OUTPUT_CHARS}/{NORMAL_OUTPUT_CHARS}",
        "read_only": "true",
    }
    if page.has_more:
        fields["has_more"] = "true"
        fields["next_offset"] = page.next_offset
    else:
        fields["has_more"] = "false"
    body: list[str] = []
    for heading, lines in page.sections:
        body.append(heading)
        body.extend(lines)
        body.append("")
    text = (
        summary_block("mcquest_shell_capabilities", fields)
        + "\n\n"
        + "\n".join(body)
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)
