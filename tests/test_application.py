import io
import json
from pathlib import Path

import pytest

from tests.conftest import DEFAULT_SETTINGS, EXAMPLES_DIRECTORY, FileWriter
from zlog.application import (
    ExtractionApplication,
    ExtractionRequest,
    StandardStreams,
)
from zlog.cli_rules import PendingCliRule
from zlog.config import Settings
from zlog.errors import ConfigurationError, InputError, SpecError
from zlog.options import BindingSection, FormulaEscaping
from zlog.plugins import PluginRegistry

EXAMPLE_CSV = """\
path,run,run_index,epoch,samples,warnings,event,loss,acc
{log},adam,1,,,,start,,
{log},adam,1,1,,,epoch,0.90,0.50
{log},adam,1,1,100,,progress,,
{log},adam,1,2,100,,epoch,0.70,0.61
{log},adam,1,2,100,lr-high,warning,,
{log},adam,1,2,250,lr-high,progress,,
{log},adam,1,2,250,lr-high|nan-loss,warning,,
{log},sgd,2,,,,start,,
{log},sgd,2,1,,,epoch,1.20,0.40
"""


def pending_rule(pattern: str, *records: str) -> PendingCliRule:
    rule = PendingCliRule(pattern)
    for record in records:
        rule.add_binding(BindingSection.RECORD, record)
    return rule


def run_application(
    request: ExtractionRequest, stdin: bytes = b""
) -> tuple[str, StandardStreams]:
    stdout = io.BytesIO()
    streams = StandardStreams(io.BytesIO(stdin), stdout)
    ExtractionApplication(request, PluginRegistry(), streams).run()
    return stdout.getvalue().decode("utf-8"), streams


def make_request(
    spec_file: Path | None = None,
    cli_rules: tuple[PendingCliRule, ...] = (),
    inputs: tuple[str, ...] = (),
    output_file: Path | None = None,
    settings: Settings = DEFAULT_SETTINGS,
) -> ExtractionRequest:
    return ExtractionRequest(
        spec_file, cli_rules, inputs, output_file, settings
    )


def test_golden_example() -> None:
    log = str(EXAMPLES_DIRECTORY / "train.log")

    output, _ = run_application(
        make_request(
            EXAMPLES_DIRECTORY / "train.yaml",
            inputs=(log,),
            settings=Settings(concat_separator="|"),
        )
    )

    assert output == EXAMPLE_CSV.format(log=log)


def test_cli_rules_follow_spec_rules(write_file: FileWriter) -> None:
    spec = write_file(
        "spec.yaml", "matches: [{pattern: 'a=(\\d)', record: {a: 1}}]"
    )

    output, _ = run_application(
        make_request(
            spec,
            cli_rules=(pending_rule(r"(\w)=(\d)", "key", "value"),),
        ),
        stdin=b"a=1\nb=2\n",
    )

    assert output.splitlines() == ["path,a,key,value", "-,1,,", "-,,b,2"]


def test_stdin_is_the_default_input_and_json_is_available() -> None:
    output, streams = run_application(
        make_request(
            cli_rules=(pending_rule(r"x=(\d)", "x"),),
            inputs=("-",),
            settings=Settings(output_format="json", stdin_path="<stdin>"),
        ),
        stdin=b"x=1\nnope\n",
    )

    assert json.loads(output) == [{"path": "<stdin>", "x": "1"}]
    assert not streams.stdin.closed


def test_output_file_is_written(write_file: FileWriter, tmp_path: Path) -> None:
    log = write_file("a.log", "x==1\n")
    target = tmp_path / "out.csv"

    output, _ = run_application(
        make_request(
            cli_rules=(pending_rule(r"x=(.*)", "x"),),
            inputs=(str(log),),
            output_file=target,
            settings=Settings(formula_escaping=FormulaEscaping.QUOTE),
        )
    )

    assert output == ""
    assert target.read_text(encoding="utf-8") == f"path,x\n{log},'=1\n"


def test_missing_rules_are_rejected() -> None:
    with pytest.raises(SpecError, match="no match rules"):
        run_application(make_request())


def test_unknown_format_fails_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"

    with pytest.raises(ConfigurationError, match="unknown output format"):
        run_application(
            make_request(
                cli_rules=(pending_rule("x", "x=0"),),
                output_file=target,
                settings=Settings(output_format="xml"),
            )
        )

    assert not target.exists()


def test_missing_inputs_fail_before_writing(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"

    with pytest.raises(InputError, match="does not exist"):
        run_application(
            make_request(
                cli_rules=(pending_rule("x", "x=0"),),
                inputs=(str(tmp_path / "absent.log"),),
                output_file=target,
            )
        )

    assert not target.exists()
