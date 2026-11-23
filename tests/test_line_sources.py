import io
import os
import stat
from pathlib import Path
from typing import TextIO, cast
from unittest.mock import Mock

import pytest

from tests.conftest import FileWriter
from zlog.errors import InputError
from zlog.line_sources import (
    BoundedLineReader,
    FileLineSource,
    SourceLine,
    StdinLineSource,
    TextDecoding,
)

UTF8 = TextDecoding("utf-8", "replace")


def read_lines(text: str, max_line_length: int = 100) -> list[SourceLine]:
    reader = BoundedLineReader(io.StringIO(text), "test", max_line_length)
    return list(reader.lines())


def test_lines_are_numbered_and_stripped() -> None:
    assert read_lines("a\n\nb") == [
        SourceLine(1, "a"),
        SourceLine(2, ""),
        SourceLine(3, "b"),
    ]
    assert read_lines("") == []


def test_line_length_limit_is_inclusive() -> None:
    assert read_lines("abcde\nabcde", max_line_length=5) == [
        SourceLine(1, "abcde"),
        SourceLine(2, "abcde"),
    ]


@pytest.mark.parametrize("text", ["abcdef\n", "abcdef", "ok\nabcdefgh\n"])
def test_longer_lines_fail(text: str) -> None:
    with pytest.raises(InputError, match="longer than max_line_length=5"):
        read_lines(text, max_line_length=5)


def test_reader_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        BoundedLineReader(io.StringIO(""), "test", 0)


def test_read_failures_become_input_errors() -> None:
    stream = Mock(spec=io.StringIO)
    stream.readline.side_effect = OSError("disk gone")
    reader = BoundedLineReader(cast(TextIO, stream), "test", 10)

    with pytest.raises(InputError, match="test:1: cannot read: disk gone"):
        list(reader.lines())


def test_file_source_uses_universal_newlines(tmp_path: Path) -> None:
    path = tmp_path / "log.txt"
    path.write_bytes(b"a\r\nb\rc\nd\xff\n")
    source = FileLineSource(path, UTF8)

    with source.open() as stream:
        lines = [
            line.text for line in BoundedLineReader(stream, "t", 9).lines()
        ]

    assert source.path == str(path)
    assert lines == ["a", "b", "c", "d\ufffd"]


def test_strict_decoding_fails_with_location(tmp_path: Path) -> None:
    path = tmp_path / "log.txt"
    path.write_bytes(b"ok\n\xff\n")
    source = FileLineSource(path, TextDecoding("utf-8", "strict"))

    with (
        source.open() as stream,
        pytest.raises(InputError, match="invalid utf-8 at or after line 1"),
    ):
        list(BoundedLineReader(stream, source.path, 9).lines())


def test_ensure_readable(write_file: FileWriter, tmp_path: Path) -> None:
    FileLineSource(write_file("ok.log", "x"), UTF8).ensure_readable()

    with pytest.raises(InputError, match="does not exist"):
        FileLineSource(tmp_path / "absent.log", UTF8).ensure_readable()
    with pytest.raises(InputError, match="is a directory"):
        FileLineSource(tmp_path, UTF8).ensure_readable()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read anything")
def test_unreadable_input_is_rejected(write_file: FileWriter) -> None:
    path = write_file("secret.log", "x")
    path.chmod(0)
    try:
        with pytest.raises(InputError, match="not readable"):
            FileLineSource(path, UTF8).ensure_readable()
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_open_failure_becomes_input_error(tmp_path: Path) -> None:
    source = FileLineSource(tmp_path / "absent.log", UTF8)

    with pytest.raises(InputError, match="cannot open"), source.open():
        pass


def test_stdin_source_leaves_the_stream_open() -> None:
    stream = io.BytesIO(b"one\ntwo\n")
    source = StdinLineSource(stream, "-", UTF8)
    source.ensure_readable()

    with source.open() as text:
        lines = [line.text for line in BoundedLineReader(text, "-", 9).lines()]

    assert source.path == "-"
    assert lines == ["one", "two"]
    assert not stream.closed
