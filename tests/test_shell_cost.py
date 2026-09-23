"""P1 state tests: the qualitative cost vocabulary (contract §21; proposal §23 examples).

Deterministic mapping only — no numeric scores, no runtime measurement, no command
analysis (that arrives with the analyzers in a later phase).
"""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.cost import (
    COST_EXAMPLES,
    COST_ORDER,
    CostClass,
    example_cost,
    is_costlier,
)

ALL_CLASSES = (CostClass.TRIVIAL, CostClass.LOW, CostClass.MEDIUM, CostClass.HIGH, CostClass.VERY_HIGH)


def test_cost_order_is_the_approved_vocabulary_in_severity_order() -> None:
    assert COST_ORDER == ALL_CLASSES
    assert {m.value for m in CostClass} == {"TRIVIAL", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"}


def test_cost_examples_cover_every_class() -> None:
    assert set(COST_EXAMPLES) == set(CostClass)
    assert all(examples for examples in COST_EXAMPLES.values())


def test_every_published_example_maps_back_to_its_class() -> None:
    for cost_class, examples in COST_EXAMPLES.items():
        for example in examples:
            assert example_cost(example) is cost_class


def test_unknown_example_is_reported_as_none_never_guessed() -> None:
    assert example_cost("recursive crawlers across the whole monorepo") is None
    assert example_cost("") is None


def test_is_costlier_is_a_deterministic_pairwise_matrix() -> None:
    # TRIVIAL < LOW < MEDIUM < HIGH < VERY_HIGH — every ordered pair, every time.
    for index_left, left in enumerate(ALL_CLASSES):
        for index_right, right in enumerate(ALL_CLASSES):
            expected = index_left > index_right
            for _ in range(3):
                assert is_costlier(left, right) is expected
            if left is right:
                assert is_costlier(left, right) is False


def test_is_costlier_rejects_non_cost_values_including_plain_strings() -> None:
    with pytest.raises(ValueError):
        is_costlier("LOW", "HIGH")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        is_costlier(CostClass.LOW, 3)  # type: ignore[arg-type]


def test_cost_model_is_qualitative_only_no_numeric_scores() -> None:
    assert all(isinstance(member.value, str) for member in CostClass)
    assert not hasattr(is_costlier, "score")
    import mcquest_mcp.shell.cost as cost_module

    for name in ("score", "points", "weight", "numeric_cost"):
        assert not hasattr(cost_module, name)
    for example_lookup in (example_cost,):
        for example in ("git status", "Get-Location"):
            assert isinstance(example_lookup(example), (CostClass, type(None)))
