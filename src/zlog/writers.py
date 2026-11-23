import csv
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Protocol, TextIO

from zlog.config import Settings
from zlog.options import FormulaEscaping

LOGGER = logging.getLogger(__name__)

ROW_TERMINATOR = "\n"
FORMULA_TRIGGER_CHARACTERS = tuple("=+-@\t\r\n＝＋－＠")
FORMULA_ESCAPE_PREFIXES: Mapping[FormulaEscaping, str] = MappingProxyType(
    {FormulaEscaping.QUOTE: "'", FormulaEscaping.TAB: "\t"}
)

RowValues = Sequence[str | None]


class RowWriter(Protocol):
    def write_header(self, columns: Sequence[str]) -> None: ...

    def write_row(self, values: RowValues) -> None: ...

    def finish(self) -> None: ...


class CsvRowWriter:
    def __init__(self, stream: TextIO, delimiter: str) -> None:
        self._writer = csv.writer(
            stream, delimiter=delimiter, lineterminator=ROW_TERMINATOR
        )

    def write_header(self, columns: Sequence[str]) -> None:
        self._writer.writerow(columns)

    def write_row(self, values: RowValues) -> None:
        self._writer.writerow(values)

    def finish(self) -> None:
        LOGGER.debug("csv output complete")


class JsonLinesRowWriter:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._columns: tuple[str, ...] = ()

    def write_header(self, columns: Sequence[str]) -> None:
        self._columns = tuple(columns)

    def write_row(self, values: RowValues) -> None:
        self._stream.write(encode_json_row(self._columns, values))
        self._stream.write(ROW_TERMINATOR)

    def finish(self) -> None:
        LOGGER.debug("json lines output complete")


class JsonArrayRowWriter:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._columns: tuple[str, ...] = ()
        self._row_count = 0

    def write_header(self, columns: Sequence[str]) -> None:
        self._columns = tuple(columns)

    def write_row(self, values: RowValues) -> None:
        self._stream.write(self._delimiter_before_row())
        self._stream.write(encode_json_row(self._columns, values))
        self._row_count += 1

    def finish(self) -> None:
        if self._row_count > 0:
            self._stream.write(f"{ROW_TERMINATOR}]{ROW_TERMINATOR}")
        else:
            self._stream.write(f"[]{ROW_TERMINATOR}")

    def _delimiter_before_row(self) -> str:
        if self._row_count > 0:
            return f",{ROW_TERMINATOR}"
        else:
            return f"[{ROW_TERMINATOR}"


def encode_json_row(columns: Sequence[str], values: RowValues) -> str:
    assert len(columns) == len(values), "row must match the header"
    return json.dumps(dict(zip(columns, values, strict=True)))


class FormulaEscapingWriter:
    def __init__(self, inner: RowWriter, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix

    def write_header(self, columns: Sequence[str]) -> None:
        self._inner.write_header(columns)

    def write_row(self, values: RowValues) -> None:
        self._inner.write_row(tuple(map(self._escape_formula, values)))

    def finish(self) -> None:
        self._inner.finish()

    def _escape_formula(self, value: str | None) -> str | None:
        match value:
            case str() if value.startswith(FORMULA_TRIGGER_CHARACTERS):
                return self._prefix + value
            case _:
                return value


def apply_formula_escaping(
    writer: RowWriter, escaping: FormulaEscaping
) -> RowWriter:
    match escaping:
        case FormulaEscaping.OFF:
            return writer
        case FormulaEscaping.QUOTE | FormulaEscaping.TAB:
            LOGGER.info("escaping formulas with %s", escaping.value)
            return FormulaEscapingWriter(
                writer, FORMULA_ESCAPE_PREFIXES[escaping]
            )


RowWriterFactory = Callable[[TextIO, Settings], RowWriter]

BUILTIN_OUTPUT_FORMATS: Mapping[str, RowWriterFactory] = MappingProxyType(
    {
        "csv": lambda stream, settings: CsvRowWriter(
            stream, settings.csv_delimiter
        ),
        "json": lambda stream, settings: JsonArrayRowWriter(stream),
        "jsonl": lambda stream, settings: JsonLinesRowWriter(stream),
    }
)
