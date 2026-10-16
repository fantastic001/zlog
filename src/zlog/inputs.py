from collections.abc import Sequence
from pathlib import Path
from typing import BinaryIO, Protocol

from zlog.config import Settings
from zlog.discovery import (
    DirectoryRunSource,
    GroupLabelParser,
    RunDirectoryScanner,
    RunSource,
    StdinRunSource,
)
from zlog.extraction import BoundedFileReader, BoundedStreamReader, TextReader
from zlog.options import FeatureState


class InputChannel(Protocol):
    @property
    def checkpointing(self) -> FeatureState: ...

    def create_run_source(
        self, directory_groups: Sequence[str]
    ) -> RunSource: ...

    def create_reader(self) -> TextReader: ...


class DirectoryInput:
    def __init__(self, input_dir: Path, settings: Settings) -> None:
        self._input_dir = input_dir
        self._settings = settings

    @property
    def checkpointing(self) -> FeatureState:
        return FeatureState.ENABLED

    def create_run_source(self, directory_groups: Sequence[str]) -> RunSource:
        scanner = RunDirectoryScanner(
            directory_groups,
            self._settings.group_separator,
            self._settings.output_extension,
        )
        return DirectoryRunSource(scanner, self._input_dir)

    def create_reader(self) -> TextReader:
        return BoundedFileReader(
            self._settings.file_encoding, self._settings.max_input_file_bytes
        )


class StdinInput:
    def __init__(
        self, stream: BinaryIO, labels: str, settings: Settings
    ) -> None:
        self._stream = stream
        self._labels = labels
        self._settings = settings

    @property
    def checkpointing(self) -> FeatureState:
        return FeatureState.DISABLED

    def create_run_source(self, directory_groups: Sequence[str]) -> RunSource:
        label_parser = GroupLabelParser(
            directory_groups, self._settings.group_separator
        )
        return StdinRunSource(label_parser, self._labels)

    def create_reader(self) -> TextReader:
        return BoundedStreamReader(
            self._stream,
            self._settings.file_encoding,
            self._settings.max_input_file_bytes,
        )
