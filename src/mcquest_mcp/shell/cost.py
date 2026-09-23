"""Qualitative cost model (contract §21; proposal §23 examples; decision DEC-041).

Deterministic vocabulary and pairwise ordering only — no numeric scores, no
runtime measurement, no command analysis (the analyzers arrive in a later
phase).

Mutation cost (contract §21: "plus a separate mutation cost for state-changing
operations") is represented as its own field using this same vocabulary — see
``CommandRecord.mutation`` in store.py — rather than a second invented scale.
"""

from __future__ import annotations

from .facts import CostClass

__all__ = ["CostClass", "COST_ORDER", "COST_EXAMPLES", "is_costlier", "example_cost"]

# Severity order, weakest → strongest (the contract §21 listing order).
COST_ORDER: tuple[CostClass, ...] = (
    CostClass.TRIVIAL,
    CostClass.LOW,
    CostClass.MEDIUM,
    CostClass.HIGH,
    CostClass.VERY_HIGH,
)

# The proposal §23 worked examples, anchoring the vocabulary. Classifying
# *actual* commands is the analyzers' job in a later phase — this table never
# inspects command text.
COST_EXAMPLES: dict[CostClass, tuple[str, ...]] = {
    CostClass.TRIVIAL: ("observation lookup", "Get-Location", "Test-Path"),
    CostClass.LOW: (
        "targeted file read",
        "structured JSON read",
        "single-file literal search",
        "git status",
    ),
    CostClass.MEDIUM: ("bounded enumeration", "multiple targeted reads"),
    CostClass.HIGH: ("recursive scans", "broad Select-String", "custom Python crawlers"),
    CostClass.VERY_HIGH: ("repeated full scans", "overlapping crawlers"),
}


def is_costlier(left: CostClass, right: CostClass) -> bool:
    """True when ``left`` ranks strictly above ``right`` in ``COST_ORDER``.

    Deterministic and qualitative: no numeric score is produced or stored.
    """
    for label, item in (("left", left), ("right", right)):
        if not isinstance(item, CostClass):
            raise ValueError(f"{label} must be a CostClass, got {type(item).__name__}")
    return COST_ORDER.index(left) > COST_ORDER.index(right)


def example_cost(example: str) -> CostClass | None:
    """Exact lookup of a published example; ``None`` when not listed.

    Bounded on purpose: an unrecognised phrase stays UNKNOWN and is never
    assigned a guessed class (contract §18 rule 4).
    """
    for cost_class in COST_ORDER:
        if example in COST_EXAMPLES[cost_class]:
            return cost_class
    return None
