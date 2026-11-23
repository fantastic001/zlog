import io
import logging
import os
from collections.abc import Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import BinaryIO, Protocol, TextIO

from zlog.errors import InputError

LOGGER = logging.getLogger(__name__)

LINE_TERMINATOR = "\n"
FIRST_LINE_NUMBER = 1


@dataclass(frozen=True)
class SourceLine:
    number: int
    text: str


@dataclass(frozen=True)
class TextDecoding:
    encoding: str
    errors: str


class LineSource(Protocol):
    @property
    def path(self) -> str: ...

    def ensure_readable(self) -> None: ...

    def open(self) -> AbstractContextManager[TextIO]: ...


class FileLineSource:
    def __init__(self, path: Path, decoding: TextDecoding) -> None:
        self._path = path
        self._decoding = decoding

    @property
    def path(self) -> str:
        return str(self._path)

    def ensure_readable(self) -> None:
        if not self._path.exists():
            raise InputError(f"input {self._path} does not exist")
        elif self._path.is_dir():
            raise InputError(f"input {self._path} is a directory")
        elif not os.access(self._path, os.R_OK):
            raise InputError(f"input {self._path} is not readable")
        else:
            LOGGER.debug("input %s is readable", self._path)

    @contextmanager
    def open(self) -> Generator[TextIO, None, None]:
        try:
            stream = self._path.open(
                encoding=self._decoding.encoding,
                errors=self._decoding.errors,
                newline=None,
            )
        except OSError as error:
            raise InputError(f"cannot open {self._path}: {error}") from error
        with stream:
            yield stream


class StdinLineSource:
    def __init__(
        self, stream: BinaryIO, path: str, decoding: TextDecoding
    ) -> None:
        self._stream = stream
        self._path = path
        self._decoding = decoding

    @property
    def path(self) -> str:
        return self._path

    def ensure_readable(self) -> None:
        LOGGER.debug("stdin needs no availability check")

    @contextmanager
    def open(self) -> Generator[TextIO, None, None]:
        wrapper = io.TextIOWrapper(
            self._stream,
            encoding=self._decoding.encoding,
            errors=self._decoding.errors,
            newline=None,
        )
        try:
            yield wrapper
        finally:
            wrapper.detach()


class BoundedLineReader:
    def __init__(
        self, stream: TextIO, source_path: str, max_line_length: int
    ) -> None:
        if max_line_length > 0:
            self._stream = stream
            self._source_path = source_path
            self._max_line_length = max_line_length
        else:
            raise ValueError("max_line_length must be positive")

    def lines(self) -> Iterator[SourceLine]:
        for number in count(FIRST_LINE_NUMBER):
            raw_line = self._read_raw_line(number)
            if raw_line:
                text = self._strip_terminator(raw_line, number)
                yield SourceLine(number, text)
            else:
                return

    def _read_raw_line(self, number: int) -> str:
        try:
            return self._stream.readline(self._max_line_length + 1)
        except UnicodeDecodeError as error:
            raise InputError(
                f"{self._source_path}: invalid {error.encoding} at or after "
                f"line {number}: {error.reason}"
            ) from error
        except OSError as error:
            raise InputError(
                f"{self._source_path}:{number}: cannot read: {error}"
            ) from error

    def _strip_terminator(self, raw_line: str, number: int) -> str:
        text = raw_line.removesuffix(LINE_TERMINATOR)
        if len(text) <= self._max_line_length:
            return text
        else:
            raise InputError(
                f"{self._source_path}:{number}: line is longer than "
                f"max_line_length={self._max_line_length}"
            )
