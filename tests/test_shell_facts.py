"""P1 state tests: the approved fact vocabulary (contract §6–§9; decisions A2, A5, S1–S3).

Behaviour tests only. They assert the approved contract — exact enum membership,
provenance retention, absence of numeric confidence / wall-clock TTL fields,
corroboration semantics — never incidental implementation structure.
"""

from __future__ import annotations

import dataclasses

import pytest

from mcquest_mcp.shell.facts import (
    EVIDENCE_CLIENT_DECLARED,
    VALUE_UNKNOWN,
    CostClass,
    Fact,
    Freshness,
    Observation,
    Scope,
    Source,
    Trust,
    corroborate,
    default_freshness,
    observation_id,
)

OBSERVED_AT = "2026-01-01T00:00:00Z"


def make_fact(**overrides: object) -> Fact:
    """Build a valid SERVER_OBSERVED repository fact; callers override single fields."""
    base: dict[str, object] = {
        "observation": "git.autocrlf",
        "value": True,
        "scope": Scope.REPOSITORY,
        "freshness": Freshness.SESSION,
        "observed_at": OBSERVED_AT,
        "source": Source.SERVER_OBSERVED,
        "trust": Trust.TRUSTED,
        "evidence": "git config core.autocrlf",
        "subject": "core.autocrlf",
    }
    base.update(overrides)
    return Fact(**base)  # type: ignore[arg-type]


def test_source_vocabulary_is_exactly_the_approved_three() -> None:
    assert {m.value for m in Source} == {"SERVER_OBSERVED", "CLIENT_DECLARED", "UNKNOWN"}


def test_trust_vocabulary_is_exactly_the_approved_four() -> None:
    assert {m.value for m in Trust} == {"trusted", "corroborated", "untrusted", "unknown"}
    assert Trust.UNTRUSTED == "untrusted"  # str-mixin equality for rendering paths


def test_scope_vocabulary_is_the_approved_six() -> None:
    assert {m.value for m in Scope} == {
        "REPOSITORY",
        "WORKTREE",
        "FILE",
        "SESSION",
        "PROCESS",
        "EPHEMERAL",
    }


def test_freshness_vocabulary_is_the_approved_five() -> None:
    assert {m.value for m in Freshness} == {"STATIC", "SESSION", "WORKTREE", "PROCESS", "EPHEMERAL"}


def test_cost_vocabulary_is_the_approved_five() -> None:
    assert {m.value for m in CostClass} == {"TRIVIAL", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"}


def test_enum_members_render_their_values_for_byte_deterministic_output() -> None:
    for enum_type in (Source, Trust, Scope, Freshness, CostClass):
        for member in enum_type:
            assert str(member) == member.value


def test_fact_retains_every_required_provenance_answer() -> None:
    fact = make_fact(
        terminal_session="abc123",
        process_id="18240",
        repository="D:\\DeveloperTools\\mcquest-mcp",
        file="package.json",
        operation="CHECK_CONFIG",
    )
    # what was observed / what value / who supplied it / where / when / how labelled
    # (contract §9 required fields, plus its optional context fields).
    assert fact.observation == "git.autocrlf"
    assert fact.value is True
    assert fact.source is Source.SERVER_OBSERVED
    assert fact.trust is Trust.TRUSTED
    assert fact.scope is Scope.REPOSITORY
    assert fact.freshness is Freshness.SESSION
    assert fact.terminal_session == "abc123"
    assert fact.process_id == "18240"
    assert fact.observed_at == OBSERVED_AT
    assert fact.evidence == "git config core.autocrlf"
    assert fact.repository == "D:\\DeveloperTools\\mcquest-mcp"
    assert fact.operation == "CHECK_CONFIG"


def test_fact_has_no_numeric_confidence_or_wall_clock_ttl_field() -> None:
    names = {f.name for f in dataclasses.fields(Fact)}
    assert names.isdisjoint(
        {"confidence", "score", "ttl", "expires_at", "expires", "valid_until", "valid_for"}
    )
    assert {
        "observation",
        "value",
        "scope",
        "freshness",
        "observed_at",
        "source",
        "trust",
        "evidence",
    } <= names


def test_fact_provenance_is_immutable() -> None:
    fact = make_fact()
    with pytest.raises(dataclasses.FrozenInstanceError):
        fact.evidence = "rewritten"  # type: ignore[misc]


def test_fact_rejects_non_enum_scope() -> None:
    with pytest.raises(TypeError):
        make_fact(scope="REPOSITORY")  # type: ignore[arg-type]


def test_fact_requires_non_empty_evidence_and_observed_at() -> None:
    with pytest.raises(ValueError):
        make_fact(evidence="")
    with pytest.raises(ValueError):
        make_fact(observed_at="")


def test_client_declared_process_fact_requires_declared_identity() -> None:
    # Missing either identity half must fail loudly: a PROCESS fact that could be
    # served to another process is exactly the promotion the contract forbids.
    with pytest.raises(ValueError):
        Fact(
            observation="terminal.cwd",
            value="D:\\DeveloperTools",
            scope=Scope.PROCESS,
            freshness=Freshness.PROCESS,
            observed_at=OBSERVED_AT,
            source=Source.CLIENT_DECLARED,
            trust=Trust.UNTRUSTED,
            evidence=EVIDENCE_CLIENT_DECLARED,
        )
    with pytest.raises(ValueError):
        Fact(
            observation="terminal.cwd",
            value="D:\\DeveloperTools",
            scope=Scope.PROCESS,
            freshness=Freshness.PROCESS,
            observed_at=OBSERVED_AT,
            source=Source.CLIENT_DECLARED,
            trust=Trust.UNTRUSTED,
            evidence=EVIDENCE_CLIENT_DECLARED,
            terminal_session="A",
            # process_id missing on purpose
        )


def test_client_declared_session_fact_requires_session() -> None:
    with pytest.raises(ValueError):
        Fact(
            observation="terminal.session_id",
            value="A",
            scope=Scope.SESSION,
            freshness=Freshness.SESSION,
            observed_at=OBSERVED_AT,
            source=Source.CLIENT_DECLARED,
            trust=Trust.UNTRUSTED,
            evidence=EVIDENCE_CLIENT_DECLARED,
        )


def test_unknown_process_fact_without_identity_is_constructible() -> None:
    # Degraded mode (decision S1): "nobody established it" carries no identity
    # and must still be representable — UNKNOWN is a valid, reportable answer.
    fact = make_fact(
        observation="terminal.cwd",
        value=VALUE_UNKNOWN,
        scope=Scope.PROCESS,
        freshness=Freshness.PROCESS,
        source=Source.UNKNOWN,
        trust=Trust.UNTRUSTED,
        subject="cwd",
        terminal_session=None,
        process_id=None,
        evidence="no declaration and no observation",
    )
    assert fact.source is Source.UNKNOWN
    assert fact.trust is Trust.UNTRUSTED


def test_corroboration_upgrades_trust_without_changing_source() -> None:
    declared = make_fact(
        observation="terminal.cwd",
        value="D:\\DeveloperTools\\mcquest-mcp",
        scope=Scope.PROCESS,
        freshness=Freshness.PROCESS,
        source=Source.CLIENT_DECLARED,
        trust=Trust.UNTRUSTED,
        evidence=EVIDENCE_CLIENT_DECLARED,
        subject="cwd",
        terminal_session="abc123",
        process_id="18240",
    )
    checked = corroborate(declared, evidence="path resolves inside the known root")
    assert checked.source is Source.CLIENT_DECLARED  # never re-labelled (contract §7 rule 1)
    assert checked.trust is Trust.CORROBORATED
    assert checked.evidence.startswith(EVIDENCE_CLIENT_DECLARED)
    assert "path resolves inside the known root" in checked.evidence
    assert declared.trust is Trust.UNTRUSTED  # frozen original untouched


def test_corroboration_without_new_evidence_keeps_provenance_text() -> None:
    declared = make_fact(
        source=Source.CLIENT_DECLARED,
        trust=Trust.UNTRUSTED,
        evidence=EVIDENCE_CLIENT_DECLARED,
    )
    checked = corroborate(declared)
    assert checked.evidence == EVIDENCE_CLIENT_DECLARED
    assert checked.trust is Trust.CORROBORATED


def test_corroboration_rejects_non_declared_sources() -> None:
    with pytest.raises(ValueError):
        corroborate(make_fact())  # SERVER_OBSERVED
    with pytest.raises(ValueError):
        corroborate(make_fact(source=Source.UNKNOWN, trust=Trust.UNKNOWN))


def test_default_freshness_mapping_is_deterministic() -> None:
    assert default_freshness(Scope.REPOSITORY) is Freshness.STATIC
    assert default_freshness(Scope.WORKTREE) is Freshness.WORKTREE
    assert default_freshness(Scope.FILE) is Freshness.WORKTREE
    assert default_freshness(Scope.SESSION) is Freshness.SESSION
    assert default_freshness(Scope.PROCESS) is Freshness.PROCESS
    assert default_freshness(Scope.EPHEMERAL) is Freshness.EPHEMERAL
    with pytest.raises(TypeError):
        default_freshness("REPOSITORY")  # type: ignore[arg-type]


def test_observation_id_is_deterministic_and_identity_based() -> None:
    first = make_fact()
    second = make_fact()
    other = make_fact(subject="remote.origin.url")
    assert observation_id(first) == observation_id(second)
    assert observation_id(first) != observation_id(other)
    assert observation_id(first).startswith("obs-")


def test_observation_wraps_fact_with_validated_origin() -> None:
    fact = make_fact()
    observation = Observation.wrap(fact, origin="tool")
    assert observation.fact is fact
    assert observation.observation_id == observation_id(fact)
    assert observation.origin == "tool"
    with pytest.raises(ValueError):
        Observation.wrap(fact, origin="somewhere")

