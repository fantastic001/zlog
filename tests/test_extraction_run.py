import io
from pathlib import Path

import pytest

from tests.conftest import FileWriter, compile_spec, parse_yaml_spec
from zlog.context_state import ContextState
from zlog.errors import ExtractionError
from zlog.extraction_run import ExtractionRunner, RowSink, RunStatistics
from zlog.hooks import ExtractedRow, HookDispatcher, RunSummary
from zlog.line_processing import LineProcessor
from zlog.line_sources import FileLineSource, LineSource, TextDecoding
from zlog.rules import derive_column_layout
from zlog.writers import CsvRowWriter

SPEC_TEXT = """
matches:
  - {pattern: 'run (\\w+)', context: {run: 1, +runs: {value: 1}}}
  - {pattern: 'n=(\\w+)', context: {+total: 1}, record: {n: 1}}
"""
UTF8 = TextDecoding("utf-8", "strict")


class RowCollector:
    def __init__(self) -> None:
        self.rows: list[ExtractedRow] = []

    def on_row(self, row: ExtractedRow) -> None:
        self.rows.append(row)


def run_files(
    sources: list[LineSource], hooks: tuple[object, ...] = ()
) -> tuple[str, RunSummary]:
    spec = parse_yaml_spec(SPEC_TEXT)
    rules = compile_spec(spec)
    state = ContextState()
    stream = io.StringIO()
    sink = RowSink(
        derive_column_layout(spec, "path"),
        CsvRowWriter(stream, ","),
        HookDispatcher(hooks),
    )
    runner = ExtractionRunner(
        LineProcessor(rules, state), state, sink, 100, len(rules)
    )
    summary = runner.run(sources)
    return stream.getvalue(), summary


def file_sources(*paths: Path) -> list[LineSource]:
    return [FileLineSource(path, UTF8) for path in paths]


def test_rows_carry_path_and_context_is_cleared_per_file(
    write_file: FileWriter,
) -> None:
    first = write_file("a.log", "run x\nn=1\nn=2\n")
    second = write_file("b.log", "n=5\nrun y\n")

    output, summary = run_files(file_sources(first, second))

    assert output.splitlines() == [
        "path,run,runs,total,n",
        f"{first},x,1,,",
        f"{first},x,1,1,1",
        f"{first},x,1,3,2",
        f"{second},,,5,5",
        f"{second},y,1,5,",
    ]
    assert summary == RunSummary(2, 5, 5, (2, 3))


def test_lemma_file_independence(write_file: FileWriter) -> None:
    first = write_file("a.log", "run x\nn=1\nskip\nn=2\n")
    second = write_file("b.log", "n=7\nrun y\nn=1\n")

    together, _ = run_files(file_sources(first, second))
    alone_first, _ = run_files(file_sources(first))
    alone_second, _ = run_files(file_sources(second))

    header, *first_rows = alone_first.splitlines()
    _, *second_rows = alone_second.splitlines()
    assert together.splitlines() == [header, *first_rows, *second_rows]


def test_row_hooks_receive_located_rows(write_file: FileWriter) -> None:
    log = write_file("a.log", "skip\nn=4\n")
    collector = RowCollector()

    run_files(file_sources(log), (collector,))

    assert collector.rows == [
        ExtractedRow(
            str(log),
            2,
            1,
            {
                "path": str(log),
                "run": None,
                "runs": None,
                "total": "4",
                "n": "4",
            },
        )
    ]


def test_invalid_values_are_reported_with_location(
    write_file: FileWriter,
) -> None:
    log = write_file("a.log", "n=1\nn=oops\n")

    with pytest.raises(ExtractionError, match=r"a\.log:2: context variable"):
        run_files(file_sources(log))


def test_statistics_summary() -> None:
    statistics = RunStatistics(2)
    statistics.count_input()
    statistics.count_line()
    statistics.count_line()
    statistics.count_match(1)

    assert statistics.summary() == RunSummary(1, 2, 1, (0, 1))
