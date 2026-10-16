import logging
import re
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from zlog.domain import PatternSpec
from zlog.errors import ExtractionError
from zlog.options import MatchPolicy
from zlog.regex_macros import RegexMacroExpander

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompiledPattern:
    regex: re.Pattern[str]
    names: tuple[str, ...]


def compile_patterns(
    patterns: Sequence[PatternSpec], expander: RegexMacroExpander
) -> tuple[CompiledPattern, ...]:
    compiled = tuple(
        CompiledPattern(expander.compile(pattern.regex), pattern.names)
        for pattern in patterns
    )
    for pattern in compiled:
        if pattern.regex.groups >= len(pattern.names):
            LOGGER.debug("compiled pattern %s", pattern.regex.pattern)
        else:
            LOGGER.warning(
                "pattern %r has %d groups for %d names; extra names unused",
                pattern.regex.pattern,
                pattern.regex.groups,
                len(pattern.names),
            )
    return compiled


Match = re.Match[str]
MatchSelector = Callable[[Iterator[Match]], Match | None]


def select_last_match(matches: Iterator[Match]) -> Match | None:
    latest = deque(matches, maxlen=1)
    return latest.pop() if latest else None


MATCH_SELECTORS: Mapping[MatchPolicy, MatchSelector] = MappingProxyType(
    {
        MatchPolicy.FIRST: lambda matches: next(matches, None),
        MatchPolicy.LAST: select_last_match,
    }
)


SegmentValues = list[dict[str, str]]


class ValueExtractor(Protocol):
    def extract(self, source: Path) -> SegmentValues: ...


class IterationSplitter(Protocol):
    def split(self, lines: Sequence[str]) -> list[list[str]]: ...


class WholeFileSplitter:
    def split(self, lines: Sequence[str]) -> list[list[str]]:
        return [list(lines)]


class SeparatorLineSplitter:
    def __init__(self, separator: re.Pattern[str]) -> None:
        self._separator = separator

    def split(self, lines: Sequence[str]) -> list[list[str]]:
        segments: list[list[str]] = [[]]
        for line in lines:
            if self._separator.search(line) is None:
                segments[-1].append(line)
            else:
                segments.append([])
        non_blank_segments = [
            segment for segment in segments if self._has_content(segment)
        ]
        LOGGER.debug(
            "split %d lines into %d segments",
            len(lines),
            len(non_blank_segments),
        )
        return non_blank_segments

    @staticmethod
    def _has_content(segment: Sequence[str]) -> bool:
        return any(line.strip() for line in segment)


def build_iteration_splitter(
    separator: re.Pattern[str] | None,
) -> IterationSplitter:
    match separator:
        case None:
            return WholeFileSplitter()
        case re.Pattern():
            LOGGER.debug("splitting iterations on %s", separator.pattern)
            return SeparatorLineSplitter(separator)


class TextValueExtractor:
    def __init__(
        self,
        patterns: Sequence[CompiledPattern],
        match_policy: MatchPolicy,
    ) -> None:
        self._patterns = tuple(patterns)
        self._select_match = MATCH_SELECTORS[match_policy]

    def extract_from_text(self, text: str) -> dict[str, str]:
        return self.extract_from_lines(text.splitlines())

    def extract_from_lines(self, lines: Sequence[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        for pattern in self._patterns:
            values.update(self._extract_pattern_values(pattern, lines))
        return values

    def _extract_pattern_values(
        self, pattern: CompiledPattern, lines: Sequence[str]
    ) -> dict[str, str]:
        matches = (
            found
            for found in map(pattern.regex.search, lines)
            if found is not None
        )
        selected = self._select_match(matches)
        if selected is not None:
            return {
                name: value
                for name, value in zip(
                    pattern.names, selected.groups(), strict=False
                )
                if value is not None
            }
        else:
            return {}


class SegmentedTextExtractor:
    def __init__(
        self,
        splitter: IterationSplitter,
        line_extractor: TextValueExtractor,
    ) -> None:
        self._splitter = splitter
        self._line_extractor = line_extractor

    def extract_segments(self, text: str) -> SegmentValues:
        return [
            self._line_extractor.extract_from_lines(segment)
            for segment in self._splitter.split(text.splitlines())
        ]


class FileValueExtractor:
    def __init__(
        self,
        text_extractor: SegmentedTextExtractor,
        encoding: str,
        max_file_bytes: int,
    ) -> None:
        if max_file_bytes > 0:
            self._text_extractor = text_extractor
            self._encoding = encoding
            self._max_file_bytes = max_file_bytes
        else:
            raise ValueError("max_file_bytes must be positive")

    def extract(self, source: Path) -> SegmentValues:
        LOGGER.debug("extracting values from %s", source)
        text = self._read_bounded_text(source)
        segments = self._text_extractor.extract_segments(text)
        LOGGER.debug("extracted %s from %s", segments, source)
        return segments

    def _read_bounded_text(self, source: Path) -> str:
        try:
            size = source.stat().st_size
            if size <= self._max_file_bytes:
                return source.read_text(
                    encoding=self._encoding, errors="replace"
                )
            else:
                raise ExtractionError(
                    f"{source} has {size} bytes, "
                    f"limit is {self._max_file_bytes}"
                )
        except OSError as error:
            raise ExtractionError(f"cannot read {source}: {error}") from error
