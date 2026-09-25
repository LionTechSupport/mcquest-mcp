"""P3 A9 n0-n3 redundancy primitive tests."""

from __future__ import annotations

import pytest

from mcquest_mcp.shell.redundancy import (
    MAX_INPUT_CHARS,
    ChangeReason,
    analyze_redundancy,
    normalize_command,
)
from mcquest_mcp.shell.store import ObservationStore


def test_n0_only_trims_outer_whitespace() -> None:
    assert normalize_command("  Get-Content   a.txt  ")[0] == "Get-Content   a.txt"


def test_n1_collapses_whitespace_and_folds_ascii_case_only() -> None:
    forms = normalize_command("  GET-content\tA  ")
    assert forms[1] == "get-content a"
    assert normalize_command("CAFÉ")[1] != normalize_command("café")[1]


def test_n2_unifies_only_safe_quote_spans() -> None:
    assert normalize_command("Write-Output 'abc'")[2] == normalize_command(
        'Write-Output "abc"'
    )[2]
    assert normalize_command("Write-Output '$name'")[2] != normalize_command(
        'Write-Output "$name"'
    )[2]
    unsafe = [
        "Write-Output 'a`b'",
        'Write-Output "a`b"',
        "Write-Output 'it''s'",
        'Write-Output "say ""hi"""',
        "Write-Output 'has\"quote'",
        'Write-Output "has\'quote"',
    ]
    for command in unsafe:
        assert normalize_command(command)[2] == normalize_command(command)[1]


def test_n3_normalizes_path_separators_and_drive_case() -> None:
    left = normalize_command(r"Get-Content C:\\Repo\\src\\a.txt")[3]
    right = normalize_command("Get-Content c:/repo/src/a.txt")[3]
    assert left == right
    assert left == "get-content c:/repo/src/a.txt"


def test_n3_collapses_duplicate_path_separators() -> None:
    assert normalize_command("Get-Content C:/repo//src///a.txt")[3] == normalize_command(
        r"Get-Content C:\repo\src\a.txt"
    )[3]


def test_n3_does_not_rewrite_url_separators() -> None:
    assert normalize_command("Get-Content https://example.test/a")[3] == (
        "get-content https://example.test/a"
    )


def test_repo_root_prefix_is_removed_only_with_matching_known_root() -> None:
    command = r"Set-Location 'D:\\Repo'; git status"
    assert normalize_command(command, repository_root=None)[3] != normalize_command(
        command, repository_root=r"D:\Repo"
    )[3]
    assert normalize_command(command, repository_root=r"D:\Repo")[3] == "git status"


def test_cd_prefix_is_allowed_but_only_one_prefix_is_removed() -> None:
    command = r"cd D:\Repo; Set-Location D:\Repo; git status"
    assert normalize_command(command, repository_root=r"D:\Repo")[3] == (
        "set-location d:/repo; git status"
    )


@pytest.mark.parametrize(
    "left,right",
    [
        ("ls src", "Get-ChildItem src"),
        ("Get-ChildItem -Recurse src", "Get-ChildItem -r src"),
        ("Get-Item a,b", "Get-Item b,a"),
        ("Write-Output 'a'", 'Write-Output "a" | Out-String'),
    ],
)
def test_excluded_equivalences_remain_nonduplicates_at_n3(
    left: str, right: str
) -> None:
    assert normalize_command(left)[3] != normalize_command(right)[3]


def test_redundancy_uses_existing_store_and_returns_exact_level() -> None:
    store = ObservationStore()
    record = store.record_command("Get-Content  README.md")
    result = analyze_redundancy(
        " get-CONTENT   readme.md ",
        store,
        terminal_session=None,
        process_id=None,
    )
    assert result.duplicate is True
    assert result.level == "n1"
    assert result.command_id == record.command_id
    assert len(store.commands()) == 1


def test_repository_root_prefix_participates_in_redundancy_comparison() -> None:
    store = ObservationStore()
    record = store.record_command("git status")
    result = analyze_redundancy(
        r"Set-Location D:\Repo; git status",
        store,
        repository_root=r"D:\Repo",
    )
    assert result.duplicate is True
    assert result.level == "n3"
    assert result.command_id == record.command_id


def test_process_scoped_history_is_not_reused_without_matching_identity() -> None:
    store = ObservationStore()
    store.record_command("git status", terminal_session="a", process_id="1")
    result = analyze_redundancy(
        "git status", store, terminal_session="b", process_id="2"
    )
    assert result.duplicate is False
    assert result.message == "no duplicate found (levels n0–n3 checked)"


def test_explicit_relevant_change_justifies_a_repeat_without_hiding_duplicate() -> None:
    store = ObservationStore()
    store.record_command("git status")
    result = analyze_redundancy(
        "git status", store, changed_reasons=(ChangeReason.WORKTREE,)
    )
    assert result.duplicate is True
    assert result.justified is True
    assert ChangeReason.WORKTREE.value in result.justification


def test_redundancy_is_deterministic_and_bounded() -> None:
    assert normalize_command(" A  B ") == normalize_command(" A  B ")
    with pytest.raises(ValueError, match="maximum"):
        normalize_command("x" * (MAX_INPUT_CHARS + 1))


def test_negative_result_discloses_n0_through_n3_and_exclusions() -> None:
    result = analyze_redundancy("Get-Location", ObservationStore())
    assert "levels n0–n3 checked" in result.method_line
    assert "similarity" in result.method_line
    assert "aliases" in result.method_line
