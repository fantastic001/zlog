import json
from pathlib import Path

import pytest

from tests.conftest import RunTreeBuilder
from zlog.cli import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    build_plugin_registry,
    main,
)
from zlog.options import FeatureState

RUN_TREE = {
    "adam-small": {
        index: f"accuracy: {value}\nloss={value * 10}\n"
        for index, value in enumerate([0.1, 0.2, 0.3])
    },
    "sgd-small": {
        index: f"accuracy: {value}\n"
        for index, value in enumerate([0.7, 0.8, 0.9])
    },
    "rms-small": {0: "accuracy: 0.5\n"},
}


@pytest.fixture
def input_dir(build_run_tree: RunTreeBuilder) -> Path:
    return build_run_tree(RUN_TREE)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZLOG_PLUGINS", "off")


def test_markdown_report(
    spec_file: Path, input_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(spec_file), str(input_dir), "--verbose"])

    captured = capsys.readouterr()
    assert exit_code == EXIT_SUCCESS
    assert "# Summary for all groups" in captured.out
    assert "0.200000 +- 0.081650 (N=3)" in captured.out
    assert "# Comparing groups for pattern: accuracy" in captured.out
    assert "(adam, small) vs (sgd, small)" in captured.out
    assert "# Comparing groups for pattern: loss" in captured.out
    assert "Iteration: 0" in captured.err


def test_json_report_with_filter_and_output_file(
    spec_file: Path, input_dir: Path, tmp_path: Path
) -> None:
    output_file = tmp_path / "report.json"

    exit_code = main(
        [
            str(spec_file),
            str(input_dir),
            "--format",
            "json",
            "--same-distributions-only",
            "--output",
            str(output_file),
        ]
    )

    document = json.loads(output_file.read_text())
    assert exit_code == EXIT_SUCCESS
    assert document[0]["rows"][0]["accuracy"]["n"] == 3
    accuracy_rows = document[1]["rows"]
    assert all(row["same_distribution"] is True for row in accuracy_rows)
    assert len(accuracy_rows) == 1


def test_checkpoint_is_written_and_restart_accepted(
    spec_file: Path, input_dir: Path, tmp_path: Path
) -> None:
    checkpoint_file = tmp_path / "state.json"
    arguments = [str(spec_file), str(input_dir), "--format", "csv"]

    first = main([*arguments, "--checkpoint", str(checkpoint_file)])
    second = main(
        [*arguments, "--checkpoint", str(checkpoint_file), "--restart"]
    )

    assert (first, second) == (EXIT_SUCCESS, EXIT_SUCCESS)
    assert len(json.loads(checkpoint_file.read_text())["entries"]) == 7


def test_no_groups_reports_no_results(
    tmp_path: Path, input_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_file = tmp_path / "empty.yaml"
    spec_file.write_text("patterns: []\n")

    exit_code = main([str(spec_file), str(input_dir)])

    assert exit_code == EXIT_SUCCESS
    assert capsys.readouterr().out == "# No results to summarize.\n"


@pytest.mark.parametrize(
    "extra_arguments", [["--format", "xml"], ["--log-level", "chatty"]]
)
def test_usage_errors(
    spec_file: Path, input_dir: Path, extra_arguments: list[str]
) -> None:
    exit_code = main([str(spec_file), str(input_dir), *extra_arguments])

    assert exit_code == EXIT_USAGE_ERROR


def test_missing_spec_is_usage_error(tmp_path: Path, input_dir: Path) -> None:
    exit_code = main([str(tmp_path / "missing.yaml"), str(input_dir)])

    assert exit_code == EXIT_USAGE_ERROR


def test_unwritable_output_is_failure(
    spec_file: Path, input_dir: Path, tmp_path: Path
) -> None:
    output_file = tmp_path / "missing-directory" / "report.md"

    exit_code = main(
        [str(spec_file), str(input_dir), "--output", str(output_file)]
    )

    assert exit_code == EXIT_FAILURE


def test_plugin_registry_respects_feature_flag() -> None:
    enabled = build_plugin_registry(FeatureState.ENABLED)
    disabled = build_plugin_registry(FeatureState.DISABLED)

    assert enabled.hooks == disabled.hooks == ()
