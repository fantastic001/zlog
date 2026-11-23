import io
import json

import pytest

from zlog.config import Settings
from zlog.options import FormulaEscaping
from zlog.writers import (
    BUILTIN_OUTPUT_FORMATS,
    CsvRowWriter,
    FormulaEscapingWriter,
    JsonArrayRowWriter,
    JsonLinesRowWriter,
    RowWriter,
    apply_formula_escaping,
    encode_json_row,
)

HEADER = ("path", "a", "b")
ROWS = (("x.log", "1", None), ("x.log", 'say "hi", ok\nbye', "2"))


def write_all(writer: RowWriter) -> None:
    writer.write_header(HEADER)
    for row in ROWS:
        writer.write_row(row)
    writer.finish()


def test_csv_writer_quotes_and_leaves_missing_values_empty() -> None:
    stream = io.StringIO()

    write_all(CsvRowWriter(stream, ","))

    assert stream.getvalue() == (
        'path,a,b\nx.log,1,\nx.log,"say ""hi"", ok\nbye",2\n'
    )


def test_csv_writer_uses_the_delimiter() -> None:
    stream = io.StringIO()
    writer = CsvRowWriter(stream, "\t")

    writer.write_header(("a", "b"))

    assert stream.getvalue() == "a\tb\n"


def test_json_lines_writer_uses_null_for_missing_values() -> None:
    stream = io.StringIO()

    write_all(JsonLinesRowWriter(stream))

    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert rows[0] == {"path": "x.log", "a": "1", "b": None}
    assert rows[1]["a"] == 'say "hi", ok\nbye'


def test_json_array_writer() -> None:
    stream = io.StringIO()

    write_all(JsonArrayRowWriter(stream))

    assert json.loads(stream.getvalue()) == [
        dict(zip(HEADER, row, strict=True)) for row in ROWS
    ]


def test_json_array_writer_without_rows() -> None:
    stream = io.StringIO()
    writer = JsonArrayRowWriter(stream)
    writer.write_header(HEADER)

    writer.finish()

    assert stream.getvalue() == "[]\n"


def test_encode_json_row_requires_matching_lengths() -> None:
    with pytest.raises(AssertionError):
        encode_json_row(("a",), ("1", "2"))


@pytest.mark.parametrize(
    ("escaping", "expected"),
    [(FormulaEscaping.QUOTE, "'"), (FormulaEscaping.TAB, "\t")],
)
def test_formula_escaping_prefixes_risky_cells(
    escaping: FormulaEscaping, expected: str
) -> None:
    stream = io.StringIO()
    writer = apply_formula_escaping(JsonLinesRowWriter(stream), escaping)
    risky = ("=1+1", "+1", "-0.5", "@SUM(A1)", "\uff1dX", "\tx", "\rx")
    columns = tuple(f"c{index}" for index in range(len(risky) + 2))

    writer.write_header(columns)
    writer.write_row((*risky, "0.5", None))
    writer.finish()

    assert isinstance(writer, FormulaEscapingWriter)
    assert list(json.loads(stream.getvalue()).values()) == [
        *(expected + value for value in risky),
        "0.5",
        None,
    ]


def test_formula_escaping_escapes_every_value() -> None:
    stream = io.StringIO()
    writer = apply_formula_escaping(
        CsvRowWriter(stream, ","), FormulaEscaping.QUOTE
    )

    writer.write_header(("a", "b", "c"))
    writer.write_row(("=1", "-2", "3"))

    assert stream.getvalue() == "a,b,c\n'=1,'-2,3\n"


def test_formula_escaping_off_returns_the_writer() -> None:
    writer = CsvRowWriter(io.StringIO(), ",")

    assert apply_formula_escaping(writer, FormulaEscaping.OFF) is writer


@pytest.mark.parametrize(
    ("name", "writer_type"),
    [
        ("csv", CsvRowWriter),
        ("json", JsonArrayRowWriter),
        ("jsonl", JsonLinesRowWriter),
    ],
)
def test_builtin_output_formats(name: str, writer_type: type) -> None:
    writer = BUILTIN_OUTPUT_FORMATS[name](io.StringIO(), Settings())

    assert isinstance(writer, writer_type)
