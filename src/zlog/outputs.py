import io
import logging
import os
import secrets
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import BinaryIO, Final, Protocol, TextIO

LOGGER = logging.getLogger(__name__)

TEMPORARY_NAME_BYTES = 4
TEMPORARY_SUFFIX = ".tmp"
EXCLUSIVE_CREATE_MODE: Final = "x"


class OutputTarget(Protocol):
    def open(self) -> AbstractContextManager[TextIO]: ...


class StandardOutputTarget:
    def __init__(self, stream: BinaryIO, encoding: str) -> None:
        self._stream = stream
        self._encoding = encoding

    @contextmanager
    def open(self) -> Generator[TextIO, None, None]:
        wrapper = io.TextIOWrapper(
            self._stream, encoding=self._encoding, newline=""
        )
        try:
            yield wrapper
        finally:
            wrapper.flush()
            wrapper.detach()


class AtomicFileTarget:
    def __init__(self, path: Path, encoding: str) -> None:
        self._path = path
        self._encoding = encoding

    @contextmanager
    def open(self) -> Generator[TextIO, None, None]:
        temporary = self._path.with_name(
            f".{self._path.name}."
            f"{secrets.token_hex(TEMPORARY_NAME_BYTES)}{TEMPORARY_SUFFIX}"
        )
        stream = temporary.open(
            EXCLUSIVE_CREATE_MODE, encoding=self._encoding, newline=""
        )
        LOGGER.debug("writing output to temporary file %s", temporary)
        try:
            with stream:
                yield stream
        except BaseException:
            temporary.unlink(missing_ok=True)
            LOGGER.debug("discarded temporary file %s", temporary)
            raise
        else:
            os.replace(temporary, self._path)
            LOGGER.info("wrote %s", self._path)
