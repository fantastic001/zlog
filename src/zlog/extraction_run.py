import logging
from collections.abc import Sequence
from types import MappingProxyType

from zlog.context_state import ContextState
from zlog.errors import ExtractionError, InvalidValueError
from zlog.hooks import ExtractedRow, HookDispatcher, RunSummary
from zlog.line_processing import LineProcessor, MatchedLine
from zlog.line_sources import BoundedLineReader, LineSource, SourceLine
from zlog.rules import ColumnLayout
from zlog.writers import RowWriter

LOGGER = logging.getLogger(__name__)


class RunStatistics:
    def __init__(self, rule_count: int) -> None:
        self._inputs_read = 0
        self._lines_read = 0
        self._matches_per_rule = [0] * rule_count

    def count_input(self) -> None:
        self._inputs_read += 1

    def count_line(self) -> None:
        self._lines_read += 1

    def count_match(self, rule_index: int) -> None:
        self._matches_per_rule[rule_index] += 1

    def summary(self) -> RunSummary:
        return RunSummary(
            inputs_read=self._inputs_read,
            lines_read=self._lines_read,
            rows_written=sum(self._matches_per_rule),
            matches_per_rule=tuple(self._matches_per_rule),
        )


class RowSink:
    def __init__(
        self, layout: ColumnLayout, writer: RowWriter, hooks: HookDispatcher
    ) -> None:
        self._layout = layout
        self._writer = writer
        self._hooks = hooks

    def start(self) -> None:
        self._writer.write_header(self._layout.header)

    def emit(self, path: str, line_number: int, matched: MatchedLine) -> None:
        values = self._layout.arrange(path, matched.context, matched.record)
        self._writer.write_row(values)
        if self._hooks.has_row_listeners:
            self._notify_row_listeners(path, line_number, matched, values)
        else:
            LOGGER.debug("no row listeners for %s:%d", path, line_number)

    def finish(self) -> None:
        self._writer.finish()

    def _notify_row_listeners(
        self,
        path: str,
        line_number: int,
        matched: MatchedLine,
        values: Sequence[str | None],
    ) -> None:
        row_values = dict(zip(self._layout.header, values, strict=True))
        self._hooks.on_row(
            ExtractedRow(
                path,
                line_number,
                matched.rule_index,
                MappingProxyType(row_values),
            )
        )


class ExtractionRunner:
    def __init__(
        self,
        processor: LineProcessor,
        state: ContextState,
        sink: RowSink,
        max_line_length: int,
        rule_count: int,
    ) -> None:
        self._processor = processor
        self._state = state
        self._sink = sink
        self._max_line_length = max_line_length
        self._statistics = RunStatistics(rule_count)

    def run(self, sources: Sequence[LineSource]) -> RunSummary:
        self._sink.start()
        for source in sources:
            self._extract_source(source)
        self._sink.finish()
        summary = self._statistics.summary()
        LOGGER.info("run summary: %s", summary)
        return summary

    def _extract_source(self, source: LineSource) -> None:
        LOGGER.info("reading %s", source.path)
        self._state.clear()
        self._statistics.count_input()
        with source.open() as stream:
            reader = BoundedLineReader(
                stream, source.path, self._max_line_length
            )
            for line in reader.lines():
                self._process_line(source.path, line)

    def _process_line(self, path: str, line: SourceLine) -> None:
        self._statistics.count_line()
        match self._process_or_locate_error(path, line):
            case MatchedLine() as matched:
                self._statistics.count_match(matched.rule_index)
                self._sink.emit(path, line.number, matched)
            case None:
                LOGGER.debug("%s:%d produced no row", path, line.number)

    def _process_or_locate_error(
        self, path: str, line: SourceLine
    ) -> MatchedLine | None:
        try:
            return self._processor.process(line.text)
        except InvalidValueError as error:
            raise ExtractionError(f"{path}:{line.number}: {error}") from error
