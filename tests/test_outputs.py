import io
from pathlib import Path

import pytest

from zlog.outputs import AtomicFileTarget, StandardOutputTarget


def test_standard_output_encodes_and_keeps_the_buffer_open() -> None:
    buffer = io.BytesIO()

    with StandardOutputTarget(buffer, "utf-8").open() as stream:
        stream.write("é\n")

    assert buffer.getvalue() == "é\n".encode()
    assert not buffer.closed


def test_atomic_file_is_written_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"

    with AtomicFileTarget(target, "utf-8").open() as stream:
        stream.write("a\n")
        assert not target.exists()

    assert target.read_text(encoding="utf-8") == "a\n"
    assert [path.name for path in tmp_path.iterdir()] == ["out.csv"]


def test_atomic_file_keeps_the_old_content_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    target.write_text("old\n", encoding="utf-8")

    with (
        pytest.raises(RuntimeError, match="boom"),
        AtomicFileTarget(target, "utf-8").open() as stream,
    ):
        stream.write("partial")
        raise RuntimeError("boom")

    assert target.read_text(encoding="utf-8") == "old\n"
    assert [path.name for path in tmp_path.iterdir()] == ["out.csv"]
