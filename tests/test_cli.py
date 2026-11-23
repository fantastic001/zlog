import io
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import EXAMPLES_DIRECTORY, FileWriter
from zlog.application import StandardStreams
from zlog.cli import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    build_plugin_registry,
    execute_request,
    exit_code_for,
    main,
    parse_request,
)
from zlog.errors import (
    ConfigurationError,
    ExtractionError,
    InputError,
    SpecError,
)
from zlog.options import FeatureState

PLUGINS_OFF = {"ZLOG_PLUGINS": "off"}


def run_cli(argv: list[str], stdin: bytes = b"") -> tuple[int, str]:
    request = parse_request(argv, PLUGINS_OFF)
    stdout = io.BytesIO()
    code = execute_request(request, StandardStreams(io.BytesIO(stdin), stdout))
    return code, stdout.getvalue().decode("utf-8")


def test_example_through_the_command_line() -> None:
    code, output = run_cli(
        [
            "-s",
            str(EXAMPLES_DIRECTORY / "train.yaml"),
            str(EXAMPLES_DIRECTORY / "train.log"),
            "--concat-separator",
            "|",
            "--format",
            "jsonl",
        ]
    )

    assert code == EXIT_SUCCESS
    assert len(output.splitlines()) == 9
    assert '"warnings": "lr-high|nan-loss"' in output


def test_cli_settings_override_environment() -> None:
    request = parse_request(
        ["-p", "x", "--csv-delimiter", ";", "--encoding", "latin-1"]
        + ["--formula-escaping", "tab", "--log-level", "info"],
        {"ZLOG_CSV_DELIMITER": "\t"},
    )

    assert request.settings.csv_delimiter == ";"
    assert request.settings.file_encoding == "latin-1"
    assert request.settings.formula_escaping.value == "tab"
    assert request.settings.log_level == "INFO"
    assert len(request.cli_rules) == 1
    assert request.spec_file is None


@pytest.mark.parametrize(
    ("argv", "stdin", "expected_code"),
    [
        (["-p", "a(b)", "-r", "v=3"], b"", EXIT_USAGE_ERROR),
        (["-p", "a"], b"", EXIT_SUCCESS),
        (["-p", "n=(\\w+)", "-c", "+n"], b"n=1\nn=x\n", EXIT_FAILURE),
        (["-p", "a", "-r", "v=0", "absent.log"], b"", EXIT_FAILURE),
        (["-p", "a", "--format", "xml"], b"", EXIT_USAGE_ERROR),
    ],
)
def test_exit_codes(
    argv: list[str], stdin: bytes, expected_code: int, tmp_path: Path
) -> None:
    code, _ = run_cli(
        [str(tmp_path / arg) if arg.endswith(".log") else arg for arg in argv],
        stdin,
    )

    assert code == expected_code


def test_errors_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    code, output = run_cli(["-p", "n=(\\w+)", "-c", "+n"], b"n=1\nn=x\n")

    assert code == EXIT_FAILURE
    assert output == "path,n\n-,1\n"
    assert "-:2: context variable 'n'" in caplog.text


def test_usage_errors_exit_with_two() -> None:
    with pytest.raises(SystemExit) as raised:
        parse_request(["-c", "x"], {})

    assert raised.value.code == EXIT_USAGE_ERROR


def test_main_reports_configuration_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ZLOG_DECIMAL_PRECISION", "0")

    assert main(["-p", "x"]) == EXIT_USAGE_ERROR
    assert "decimal_precision must lie between" in capsys.readouterr().err


def test_main_writes_an_output_file(
    monkeypatch: pytest.MonkeyPatch, write_file: FileWriter, tmp_path: Path
) -> None:
    monkeypatch.setenv("ZLOG_PLUGINS", "off")
    log = write_file("a.log", "v=1\n")
    target = tmp_path / "out.csv"

    code = main(["-p", "v=(\\d)", "-r", "v", str(log), "-o", str(target)])

    assert code == EXIT_SUCCESS
    assert target.read_text(encoding="utf-8") == f"path,v\n{log},1\n"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigurationError("x"), EXIT_USAGE_ERROR),
        (SpecError("x"), EXIT_USAGE_ERROR),
        (InputError("x"), EXIT_FAILURE),
        (ExtractionError("x"), EXIT_FAILURE),
        (OSError("x"), EXIT_FAILURE),
        (ValueError("x"), EXIT_FAILURE),
    ],
)
def test_exit_code_for(error: Exception, expected: int) -> None:
    assert exit_code_for(error) == expected


@pytest.mark.parametrize("state", [FeatureState.ENABLED, FeatureState.DISABLED])
def test_build_plugin_registry(state: FeatureState) -> None:
    assert build_plugin_registry(state).hooks == ()


def test_module_entry_point_prints_version() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "zlog", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == EXIT_SUCCESS
    assert completed.stdout.startswith("zlog ")
