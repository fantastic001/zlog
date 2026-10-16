from pathlib import Path

import pytest

from tests.conftest import RunTreeBuilder
from zlog.discovery import (
    GroupLabelParser,
    RunDirectoryScanner,
    StdinRunSource,
)
from zlog.errors import InputError


def test_scans_groups_and_sorted_iterations(
    build_run_tree: RunTreeBuilder,
) -> None:
    root = build_run_tree(
        {"adam-small-v2": {10: "", 2: ""}, "sgd-large": {0: ""}}
    )
    (root / "adam-small-v2" / "notes.out").write_text("")
    (root / "adam-small-v2" / "3.log").write_text("")
    (root / "stray.out").write_text("")

    runs = RunDirectoryScanner(["optimizer", "size"], "-", ".out").scan(root)

    assert [run.key for run in runs] == [
        (("optimizer", "adam"), ("size", "small")),
        (("optimizer", "sgd"), ("size", "large")),
    ]
    assert [source.iteration for source in runs[0].sources] == [2, 10]


def test_skips_directories_with_too_few_labels(
    build_run_tree: RunTreeBuilder,
) -> None:
    root = build_run_tree({"adam": {0: ""}})

    assert RunDirectoryScanner(["a", "b"], "-", ".out").scan(root) == []


def test_no_directory_groups_yields_empty_keys(
    build_run_tree: RunTreeBuilder,
) -> None:
    root = build_run_tree({"all": {0: ""}})

    runs = RunDirectoryScanner([], "-", ".out").scan(root)

    assert [run.key for run in runs] == [()]


def test_missing_input_directory_raises(tmp_path: Path) -> None:
    scanner = RunDirectoryScanner(["a"], "-", ".out")

    with pytest.raises(InputError):
        scanner.scan(tmp_path / "missing")


def test_unreadable_run_directory_raises(
    build_run_tree: RunTreeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_run_tree({"adam": {0: ""}})
    original_iterdir = Path.iterdir

    def failing_iterdir(path: Path):  # type: ignore[no-untyped-def]
        if path.name == "adam":
            raise PermissionError("denied")
        else:
            return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", failing_iterdir)

    with pytest.raises(InputError, match="denied"):
        RunDirectoryScanner(["a"], "-", ".out").scan(root)


@pytest.mark.parametrize(("separator", "extension"), [("", ".out"), ("-", "")])
def test_rejects_empty_separator_or_extension(
    separator: str, extension: str
) -> None:
    with pytest.raises(ValueError):
        RunDirectoryScanner(["a"], separator, extension)


def test_stdin_run_source_builds_single_run_from_labels() -> None:
    parser = GroupLabelParser(["optimizer", "size"], "-")

    runs = StdinRunSource(parser, "adam-small").list_runs()

    assert [run.key for run in runs] == [
        (("optimizer", "adam"), ("size", "small"))
    ]
    assert [source.iteration for source in runs[0].sources] == [0]


def test_stdin_run_source_without_directory_groups_needs_no_labels() -> None:
    runs = StdinRunSource(GroupLabelParser([], "-"), "").list_runs()

    assert [run.key for run in runs] == [()]


@pytest.mark.parametrize("labels", ["", "adam"])
def test_stdin_run_source_rejects_missing_labels(labels: str) -> None:
    parser = GroupLabelParser(["optimizer", "size"], "-")

    with pytest.raises(InputError, match="--stdin-labels"):
        StdinRunSource(parser, labels).list_runs()
