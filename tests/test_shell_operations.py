"""P3 deterministic semantic-operation classification tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.operations import (
    MAX_INPUT_CHARS,
    OPERATION_CLASSES,
    Operation,
    classify_operation,
    is_mutation_bearing,
    normalize_operation,
)


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("Read README.md", Operation.READ_FILE),
        ("Check quiz.loading in en/si/ta JSON files", Operation.READ_JSON),
        ("Find the exact literal loading in src", Operation.SEARCH_LITERAL),
        ("Search source files with regex ^export", Operation.SEARCH_REGEX),
        ("List files under src recursively", Operation.ENUMERATE_FILES),
        ("Check whether src/app.ts exists", Operation.CHECK_PATH),
        ("Check git status and the current branch", Operation.CHECK_GIT_STATE),
        ("Check git config core.autocrlf", Operation.CHECK_CONFIG),
        ("Measure EOL for Docs/V0.8", Operation.MEASURE_EOL),
        ("Run node scripts/build.js", Operation.RUN_NODE),
        ("Run python scripts/check.py", Operation.RUN_PYTHON),
        ("Run pytest tests", Operation.RUN_TEST),
        ("Build the frontend with npm run build", Operation.BUILD),
        ("Install dependencies with npm install", Operation.INSTALL),
        ("Edit src/app.ts and write the new content", Operation.EDIT),
        # V1.1 owner-approved READ_SQLITE (see Docs/V1.1 Gate 0/Gate 1).
        ("Read rows from the quizzes table in data.db", Operation.READ_SQLITE),
        ("SELECT name FROM _collections in the SQLite database", Operation.READ_SQLITE),
        ("Read data.db as plain text", Operation.READ_FILE),
    ],
)
def test_all_frozen_operations_are_reachable(intent: str, expected: Operation) -> None:
    assert classify_operation(intent) is expected


def test_operation_vocabulary_is_exactly_frozen() -> None:
    # V1.0 froze 15 classes; V1.1 adds exactly one owner-approved class
    # (READ_SQLITE) and nothing else may change without explicit approval.
    assert set(OPERATION_CLASSES) == {
        "READ_FILE", "READ_JSON", "READ_SQLITE", "SEARCH_LITERAL", "SEARCH_REGEX",
        "ENUMERATE_FILES", "CHECK_PATH", "CHECK_GIT_STATE", "CHECK_CONFIG",
        "MEASURE_EOL", "RUN_NODE", "RUN_PYTHON", "RUN_TEST", "BUILD",
        "INSTALL", "EDIT",
    }
    assert len(OPERATION_CLASSES) == 16


def test_structured_json_beats_literal_or_plain_read() -> None:
    assert classify_operation("Get-Content locale.json | ConvertFrom-Json") is Operation.READ_JSON
    assert classify_operation("Read locale.json as text") is Operation.READ_FILE


def test_search_forms_are_distinguished_deterministically() -> None:
    assert classify_operation("Select-String -SimpleMatch loading app.ts") is Operation.SEARCH_LITERAL
    assert classify_operation("Select-String -Pattern '^export' app.ts") is Operation.SEARCH_REGEX
    assert classify_operation('findstr /c:"loading" locale.json') is Operation.SEARCH_LITERAL


def test_git_config_is_not_misclassified_as_git_state() -> None:
    assert classify_operation("git config --get core.autocrlf") is Operation.CHECK_CONFIG
    assert classify_operation("git status --short") is Operation.CHECK_GIT_STATE


def test_unknown_and_empty_intent_remain_unknown() -> None:
    assert classify_operation("make the workspace feel nicer") is Operation.UNKNOWN
    assert classify_operation("") is Operation.UNKNOWN
    assert classify_operation("   ") is Operation.UNKNOWN


def test_operation_normalization_is_exact_not_alias_based() -> None:
    assert normalize_operation("  read_json  ") is Operation.READ_JSON
    assert normalize_operation("READ FILE") is Operation.UNKNOWN
    assert normalize_operation("list") is Operation.UNKNOWN


def test_edit_and_install_are_the_only_mutation_bearing_classes() -> None:
    assert is_mutation_bearing(Operation.EDIT)
    assert is_mutation_bearing(Operation.INSTALL)
    assert all(
        not is_mutation_bearing(operation)
        for operation in Operation
        if operation not in {Operation.EDIT, Operation.INSTALL, Operation.UNKNOWN}
    )


def test_classification_is_repeatable_and_bounded() -> None:
    intent = "Check quiz.loading in JSON locale files"
    assert classify_operation(intent) == classify_operation(intent)
    with pytest.raises(ValueError, match="maximum"):
        classify_operation("x" * (MAX_INPUT_CHARS + 1))
