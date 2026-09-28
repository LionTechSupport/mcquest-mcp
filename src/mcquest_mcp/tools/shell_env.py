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
from ..shell import observe, planner, validate
from ..shell.facts import VALUE_UNKNOWN, Fact, Scope, Source
from ..shell.redundancy import ChangeReason
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


def shell_validate(
    *,
    command: str,
    mode: str = "validate",
    client_cwd: str = "",
    client_shell: str = "",
    client_shell_version: str = "",
    client_session: str = "",
    client_process_id: str = "",
    repository_root: str = "",
    changed_reasons: str = "",
) -> str:
    """Full deterministic validation report; ``lint`` is a mode, not a tool."""
    store = environment.get_store()
    identity = _identity(
        client_session=client_session,
        client_process_id=client_process_id,
        client_cwd=client_cwd,
        client_shell=client_shell,
        client_shell_version=client_shell_version,
    )
    facts = environment.client_terminal_facts(
        store, identity, observed_at=environment.observed_now()
    )
    cwd_fact = next(
        (fact for fact in facts if fact.observation == "terminal.cwd"), None
    )
    reasons = tuple(
        ChangeReason(item.strip())
        for item in changed_reasons.split(",")
        if item.strip()
    )
    report = validate.validate_command(
        command,
        store,
        mode=mode,
        shell=client_shell or None,
        shell_version=client_shell_version or None,
        client_cwd=cwd_fact,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
        repository_root=repository_root or None,
        changed_reasons=reasons,
    )
    counts = report.counts
    fields: dict[str, object] = {
        "mode": report.mode,
        "verdict": report.summary_verdict,
        "ERROR": counts["ERROR"],
        "WARNING": counts["WARNING"],
        "INFO": counts["INFO"],
        "PASS": counts["PASS"],
        "sections": len(report.sections),
        "operation": report.operation.value,
        "duplicate": "true" if report.duplicate else "false",
        "analysis_only": "true",
        "read_only": "true",
    }
    body: list[str] = []
    for section in report.sections:
        body.append(f"{section.name}: {section.verdict.value}")
        for finding in section.findings:
            location = (
                f" @{finding.position}" if finding.position is not None else ""
            )
            body.append(
                f"  - {finding.verdict.value} {finding.code}{location}: "
                f"{finding.message}"
            )
        body.append("")
    text = (
        summary_block("mcquest_shell_validate", fields)
        + "\n\n"
        + "\n".join(body)
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)


def shell_observe(
    *,
    kind: str = "observation",
    name: str = "",
    value: str = "",
    scope: str = "",
    subject: str = "",
    source: str = "",
    recorded_at_source: str = "CLIENT",
    operation: str = "",
    invalidate_event: str = "",
    command_text: str = "",
    client_session: str = "",
    client_process_id: str = "",
) -> str:
    """Record observations/evidence and apply invalidation (decision A14)."""
    store = environment.get_store()
    fields: dict[str, object] = {"read_only": "true"}
    body: list[str] = []
    if invalidate_event.strip():
        bumped = observe.invalidate(
            store, invalidate_event.strip(), subject=subject
        )
        for key_scope, key_subject in bumped:
            body.append(
                f"invalidated {key_scope.value}/{key_subject or '*'}: revision bumped"
            )
        fields["invalidation_event"] = invalidate_event.strip()
        fields["invalidated"] = len(bumped)
    else:
        if kind.strip() == observe.IngestKind.COMMAND.value:
            result = observe.record_command_observation(
                store,
                text=command_text or value,
                operation=operation,
                client_session=client_session,
                client_process_id=client_process_id,
            )
        else:
            result = observe.record_observation(
                store,
                name=name,
                value=value,
                scope=Scope(scope.strip().upper()),
                source=source or Source.CLIENT_DECLARED.value,
                recorded_at_source=recorded_at_source,
                subject=subject,
                operation=operation,
                client_session=client_session,
                client_process_id=client_process_id,
            )
        fields["status"] = result.status.value
        fields["kind"] = result.kind.value
        body.append(f"{result.name}: {result.status.value} — {result.detail}")
        if result.observation_id:
            fields["observation_id"] = result.observation_id
        if result.scope is not None:
            fields["scope"] = result.scope.value
        if result.source is not None:
            fields["source"] = result.source.value
        if result.trust is not None:
            fields["trust"] = result.trust.value
        if result.freshness is not None:
            fields["freshness"] = result.freshness.value
    text = (
        summary_block("mcquest_shell_observe", fields)
        + "\n\n"
        + "\n".join(body)
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)


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


# --- P5 adapters: plan / prepare / history / next ---------------------------
# These are thin like every other adapter in this module: normalize declared
# inputs, call the P5 planner, render through the shared formatting layer. They
# execute nothing and mutate nothing; `planner.EXECUTION_NOT_PERMITTED` is
# rendered in every plan so a recommendation can never read as authorization.


def _evidence_line(item: planner.EvidenceItem) -> str:
    return (
        f"- {item.observation}: {item.state.value} | {item.source.value}/"
        f"{item.trust.value} | {item.scope.value}/{item.freshness.value} | "
        f"ev: {item.detail}"
    )


def _step_line(step: planner.PlanStep) -> str:
    capability = f" -> {step.capability}" if step.capability else ""
    return (
        f"{step.order}. [{step.ladder.value}]{capability} {step.action} "
        f"(operation {step.operation.value})"
    )


def _plan_sections(plan: planner.Plan) -> list[str]:
    body: list[str] = []
    body.append(f"operation: {plan.operation.value}")
    body.append(f"status: {plan.status.value}")
    body.append("")
    body.append("evidence:")
    if plan.evidence:
        for item in plan.evidence:
            body.append(_evidence_line(item))
    else:
        body.append("  - no required evidence for this operation class")
    body.append("")
    body.append("required observations:")
    if plan.required_observations:
        for requirement in plan.required_observations:
            body.append(
                f"- {requirement.observation} ({requirement.scope.value}) via "
                f"{requirement.capability}: {requirement.reason}"
            )
    else:
        body.append("  - none")
    body.append("")
    body.append("plan (recommendation, not execution):")
    if plan.steps:
        for step in plan.steps:
            body.append(_step_line(step))
    else:
        body.append("  - no step is justified for this intent")
    body.append("")
    body.append("blockers:")
    for blocker in plan.blockers:
        body.append(f"- {blocker}")
    if not plan.blockers:
        body.append("  - none")
    body.append("")
    body.append("validation requirements:")
    for note in plan.validation_context:
        body.append(f"- {note}")
    body.append("")
    body.append(f"note: {planner.EXECUTION_NOT_PERMITTED}")
    return body


def shell_plan(
    intent: str,
    client_session: str = "",
    client_process_id: str = "",
) -> str:
    """Classify an intent and emit a bounded, deterministic plan (never executed)."""
    store = environment.get_store()
    plan = planner.build_plan(
        intent, store,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
    )
    known = sum(
        1 for item in plan.evidence if item.state is planner.EvidenceState.KNOWN
    )
    fields: dict[str, object] = {
        "operation": plan.operation.value,
        "status": plan.status.value,
        "steps": len(plan.steps),
        "known_evidence": known,
        "required_observations": len(plan.required_observations),
        "blockers": len(plan.blockers),
        "execution_permitted": "false",
        "read_only": "true",
    }
    text = (
        summary_block("mcquest_shell_plan", fields)
        + "\n\n"
        + "\n".join(_plan_sections(plan))
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)


def _compact_plan(plan: planner.Plan) -> list[str]:
    """A short plan digest for the next/prepare adapters.

    ``shell_plan`` renders the full ladder; ``prepare`` and ``next`` report one
    decision and must not re-dump every step, so they render this bounded digest
    instead of the whole plan (contract §16 output bounds).
    """
    body = [
        f"operation: {plan.operation.value}",
        f"status: {plan.status.value}",
    ]
    if plan.evidence:
        summary = ", ".join(
            f"{item.observation}={item.state.value}" for item in plan.evidence
        )
        body.append(f"evidence: {summary}")
    if plan.required_observations:
        body.append(
            "missing: "
            + ", ".join(
                f"{item.observation} ({item.scope.value})"
                for item in plan.required_observations
            )
        )
    for blocker in plan.blockers:
        body.append(f"blocker: {blocker}")
    body.append(f"note: {planner.EXECUTION_NOT_PERMITTED}")
    return body


def shell_prepare(
    intent: str,
    client_session: str = "",
    client_process_id: str = "",
) -> str:
    """Prepare a requested task as text only; never execute, write, or install."""
    store = environment.get_store()
    preparation = planner.prepare_request(
        intent, store,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
    )
    body = [preparation.prepared_text, ""]
    body.extend(_compact_plan(preparation.plan))
    fields: dict[str, object] = {
        "operation": preparation.operation.value,
        "status": preparation.status.value,
        "missing_prerequisites": len(preparation.missing_prerequisites),
        "executed": "false",
        "execution_permitted": "false",
        "read_only": "true",
    }
    text = (
        summary_block("mcquest_shell_prepare", fields)
        + "\n\n"
        + "\n".join(body)
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)


def shell_history(
    offset: int = 0,
    limit: int = 10,
    client_session: str = "",
    client_process_id: str = "",
) -> str:
    """Page the existing in-memory command/observation history deterministically."""
    store = environment.get_store()
    view = planner.history_view(
        store,
        offset=offset,
        limit=limit,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
    )
    fields: dict[str, object] = {
        "status": view.status.value,
        "total": view.total,
        "returned": view.returned,
        "offset": view.offset,
        "has_more": "true" if view.has_more else "false",
        "persistence": "in-memory only",
        "read_only": "true",
    }
    if view.has_more:
        fields["next_offset"] = view.next_offset
    body: list[str] = []
    for row in view.rows:
        body.append(
            f"- {row.record_id} [{row.kind}] {row.state.value} | "
            f"{row.source}/{row.trust} | {row.scope}/{row.freshness} | "
            f"binding={row.binding} | ev: {row.detail}"
        )
    if not view.rows:
        body.append("  - no history record available in this server process")
    for note in view.notes:
        body.append(f"note: {note}")
    body.append(f"note: {planner.EXECUTION_NOT_PERMITTED}")
    text = (
        summary_block("mcquest_shell_history", fields)
        + "\n\n"
        + "\n".join(body)
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)


def shell_next(
    intent: str,
    last_command: str = "",
    changed_reasons: str = "",
    repository_root: str = "",
    client_session: str = "",
    client_process_id: str = "",
) -> str:
    """Recommend the next useful observation/planning step; never execute it."""
    store = environment.get_store()
    reasons = tuple(
        ChangeReason(item.strip())
        for item in changed_reasons.split(",")
        if item.strip()
    )
    step = planner.next_step(
        intent, store,
        terminal_session=client_session or None,
        process_id=client_process_id or None,
        changed_reasons=reasons,
        last_command=last_command,
        repository_root=repository_root or None,
    )
    fields: dict[str, object] = {
        "action": step.action.value,
        "operation": step.operation.value,
        "changed_conditions": len(step.changed_conditions),
        "executed": "false",
        "execution_permitted": "false",
        "read_only": "true",
    }
    body = [f"action: {step.action.value}", f"detail: {step.detail}", ""]
    body.extend(_compact_plan(step.plan))
    body.append(f"method: {step.method_line}")
    text = (
        summary_block("mcquest_shell_next", fields)
        + "\n\n"
        + "\n".join(body)
        + "\n[END]"
    )
    return truncate(text, limit=NORMAL_OUTPUT_CHARS)
